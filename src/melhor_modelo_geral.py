from pathlib import Path
import json
import logging
import warnings
import os
from datetime import datetime

import pandas as pd
import numpy as np
import optuna
import joblib
from dotenv import load_dotenv
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
import mlflow
from datetime import datetime

from selecao_modelos_mlflow import (
    carregar_dados,
    SCALER_MAP,
    ENCODER_MAP,
    MODEL_KEY_MAP,
)
from preprocessador import PreprocessadorFactory
from otimizador_optuna import FactoryModelos
from mlflow_manager import MLflowManager
from criando_indices_individuais import CriandoIndicesIndividuais
from funcoes_engenharia_features import engenharia_features_completa


logger = logging.getLogger(__name__)

CATEGORICAL_FEATURES = [
    "tipo_imovel", "bairro", "novo_lancamento", "tem_elevador",
]

NUMERIC_FEATURES = [
    "metragem", "quartos", "banheiros", "vagas",
    "score_escola_privada", "score_escola_publica", "score_hospitais",
    "score_mercado", "score_farmacia", "score_parque",
    "score_seguranca", "score_educacao",
    "metro_quadrado_bairro_mean", "metro_quadrado_bairro_median",
    "valor_bairro_mean", "bairro_rank",
    "quartos_por_metro", "vagas_por_metro", "banheiros_por_quarto",
    "lat", "lng",
]

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

def treinar_melhor_modelo_geral(
    cidade=None,
    cidade_nome=None,
    mes_ref=None,
    pasta_dados=None,
    experimento=None,
):
    load_dotenv()

    cidade = cidade or os.getenv("CIDADE_PASTA")
    cidade_nome = cidade_nome or os.getenv("CIDADE_NOME", "Joinville, Santa Catarina, Brasil")
    mes_ref = mes_ref or os.getenv("MES_REF", datetime.now().strftime("%Y-%m"))
    pasta_dados = pasta_dados or Path(__file__).parent.parent / "dados" / cidade
    experimento = experimento or f"imoveis-{cidade}-valor"
    target = "valor_imovel"

    pasta_dados = Path(pasta_dados)

    logger.info("Cidade: %s | Mes: %s", cidade, mes_ref)

    # ── 1. Carregar resultados da otimização ────────────────────────────
    otim_path = pasta_dados / f"{cidade}_otimizados_melhores_incrementos_{mes_ref}.parquet"
    if not otim_path.exists():
        raise FileNotFoundError(
            f"Arquivo nao encontrado: {otim_path}. "
            "Execute joinville_otimizando_melhores_modelos.py primeiro."
        )

    df_otim = pd.read_parquet(otim_path)
    logger.info("Resultados carregados: %d linhas", len(df_otim))

    # ── 2. Melhor configuração (menor rmse_otimizado) ───────────────────
    best_idx = df_otim["rmse_otimizado"].idxmin()
    best = df_otim.loc[best_idx]

    logger.info(
        "Melhor config: %s | rmse_otimizado=%.2f | tratamento=%s | n_features=%.0f",
        best["modelo"], best["rmse_otimizado"], best["tratamento"], best["n_features"],
    )

    # ── 3. Carregar todos os dados e concatenar ─────────────────────────
    train, test = carregar_dados(pasta_dados, mes_ref, cidade)
    X = pd.concat([train[ALL_FEATURES], test[ALL_FEATURES]], ignore_index=True)
    y = pd.concat([train[target], test[target]], ignore_index=True).values
    del train, test

    # ── 4. Reconstruir preprocessador ───────────────────────────────────
    scaler_cls = SCALER_MAP.get(best["scaler"], StandardScaler)
    imputer_str = best["imputer_num"] or "median"
    encoder_cls = ENCODER_MAP.get(best["encoder"])
    transform = best["transform"] if best["transform"] != "none" else None

    pp = PreprocessadorFactory(
        numeric_features=NUMERIC_FEATURES,
        categorical_features=CATEGORICAL_FEATURES,
    ).criar(
        scaler=scaler_cls(),
        imputer_num=SimpleImputer(strategy=imputer_str),
        encoder=encoder_cls(),
        transform=transform,
    )

    # ── 5. Reconstruir modelo com best_params ───────────────────────────
    best_params = json.loads(best["best_params"])
    model_key = MODEL_KEY_MAP.get(best["modelo"], "")
    factory = getattr(FactoryModelos(), model_key, None)
    if not factory:
        raise ValueError(f"Modelo '{best['modelo']}' nao mapeado em MODEL_KEY_MAP")

    trial_fixo = optuna.trial.FixedTrial(best_params)
    modelo = factory(trial_fixo)

    # ── 6. Treinar pipeline com TODOS os dados ──────────────────────────
    pipe = Pipeline([("preprocessador", pp), ("modelo", modelo)])
    pipe.fit(X, y)
    logger.info("Modelo final treinado com %d amostras", len(X))
    del X, y

    # ── 7. Logar no MLflow ──────────────────────────────────────────────
    mgr = MLflowManager(nome_experimento=experimento)
    mgr.conectar()

    run_name = f"best_geral_{best['modelo']}_todas_feats"
    with mgr.run_session(
        run_name=run_name,
        tags={"categoria": "melhor_modelo_geral"},
    ):
        mlflow.log_params({f"best_{k}": str(v) for k, v in best_params.items()})
        mlflow.set_tag("modelo", best["modelo"])
        mlflow.set_tag("tratamento", best["tratamento"])
        mlflow.set_tag("n_features", len(ALL_FEATURES))
        mlflow.set_tag("scaler", best["scaler"])
        mlflow.set_tag("imputer_num", best["imputer_num"])
        mlflow.set_tag("encoder", best["encoder"])
        mlflow.set_tag("transform", best["transform"])
        mlflow.set_tag("feature_transform_map", best.get("feature_transform_map", ""))
        mlflow.sklearn.log_model(pipe, f"{cidade}_modelo_geral_{mes_ref}")

    logger.info("Run salva: %s", run_name)

    # ── 8. Salvar modelo local ──────────────────────────────────────────
    modelo_path = pasta_dados / f"{cidade}_modelo_geral_{mes_ref}.joblib"
    joblib.dump(pipe, modelo_path, compress=3)
    logger.info("Modelo salvo: %s", modelo_path.name)

    # ── 9. Remover modelos de meses anteriores ──────────────────────────
    for f in pasta_dados.glob(f"{cidade}_modelo_geral_*.joblib"):
        if f.name != modelo_path.name:
            f.unlink()
            logger.info("Modelo anterior removido: %s", f.name)

    # ── 10. Predicao no imoveis_limpo ───────────────────────────────────
    logger.info("Gerando predicoes no dataset completo...")

    imoveis_path = pasta_dados / f"{cidade}_imoveis_limpo_{mes_ref}.parquet"
    df_full = pd.read_parquet(imoveis_path)
    logger.info("Imoveis limpo carregado: %d linhas", len(df_full))

    indices = CriandoIndicesIndividuais(cidade=cidade_nome, cache_dir=pasta_dados)
    df_full = indices.calcular_indices(imoveis_df=df_full)

    mask = (
        (df_full["metragem"] > 10)
        & (df_full["tipo_imovel"].isin(["casa", "apartamento"]))
        & (df_full["preco_por_m2"] >= 100)
    )
    df_filtrado = df_full[mask].copy()
    df_filtrado, _ = engenharia_features_completa(df_filtrado, df_filtrado.copy())

    X_pred = df_filtrado[ALL_FEATURES].copy()
    y_pred_full = pipe.predict(X_pred)

    pred_series = pd.Series(y_pred_full, index=df_filtrado.index, name="valor_predito")

    df_full = df_full.assign(
        valor_predito=pred_series,
        #erro_absoluto=np.abs(df_full[target] - pred_series),
        #erro_percentual=np.abs(df_full[target] - pred_series) / df_full[target] * 100,
        erro_absoluto= df_full[target] - pred_series,
        erro_percentual=df_full[target] - pred_series / df_full[target] * 100,
        
    )

    df_full.to_parquet(imoveis_path, index=False)
    logger.info(
        "Predicoes salvas em %s (%.0f com valor, %d sem filtro)",
        imoveis_path.name,
        df_full["valor_predito"].notna().sum(),
        df_full["valor_predito"].isna().sum(),
    )

    # ── 11. Limpeza dos caches ──────────────────────────────────────────
    for nome in [
        f"{cidade}_train_{mes_ref}.parquet",
        f"{cidade}_test_{mes_ref}.parquet",
        f"{cidade}_otimizados_melhores_incrementos_{mes_ref}.parquet",
        f"{cidade}_melhores_por_incremento_{mes_ref}.parquet",
        f"{cidade}_melhores_por_incremento_{mes_ref}.csv",
        f"{cidade}_otimizados_melhores_incrementos_{mes_ref}.csv",
    ]:
        p = pasta_dados / nome
        if p.exists():
            p.unlink()
            logger.info("Cache removido: %s", nome)

    for f in pasta_dados.glob(f"pois_*.parquet"):
        f.unlink()
        logger.info("Cache POI removido: %s", f.name)

    logger.info("Concluido!")
    return pipe


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    warnings.filterwarnings("ignore")
    treinar_melhor_modelo_geral()
