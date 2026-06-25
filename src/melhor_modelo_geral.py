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

from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES

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

    feat_map = json.loads(best.get("feature_transform_map", "{}"))
    best_features = list(feat_map.keys())
    if not best_features:
        logger.warning("feature_transform_map vazio — usando ALL_FEATURES (%d)", len(ALL_FEATURES))
        best_features = ALL_FEATURES

    logger.info(
        "Melhor config: %s | rmse_otimizado=%.2f | tratamento=%s | n_features=%d",
        best["modelo"], best["rmse_otimizado"], best["tratamento"], len(best_features),
    )

    # ── 3. Carregar dados (train = treino, test = calibracao) ───────────
    train, test = carregar_dados(pasta_dados, mes_ref, cidade, cidade_nome=cidade_nome)
    X_train, y_train = train[best_features].copy(), train[target].values
    X_cal,   y_cal   = test[best_features].copy(),  test[target].values
    del train, test
    logger.info("Treino: %d | Calibracao: %d", len(X_train), len(X_cal))

    # ── 4. Reconstruir preprocessador ───────────────────────────────────
    scaler_cls = SCALER_MAP.get(best["scaler"], StandardScaler)
    imputer_str = best["imputer_num"] or "median"
    encoder_cls = ENCODER_MAP.get(best["encoder"])
    transform = best["transform"] if best["transform"] != "none" else None

    best_num_feats = [c for c in best_features if c in NUMERIC_FEATURES]
    best_cat_feats = [c for c in best_features if c in CATEGORICAL_FEATURES]

    pp = PreprocessadorFactory(
        numeric_features=best_num_feats,
        categorical_features=best_cat_feats,
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

    # ── 6. Treinar pipeline com dados de TREINO ─────────────────────────
    pipe = Pipeline([("preprocessador", pp), ("modelo", modelo)])
    pipe.fit(X_train, y_train)
    logger.info("Pipeline treinado com %d amostras", len(X_train))
    del X_train, y_train

    # ── 7. Preditor com intervalo conformal ──────────────────────────────
    from intervalo_predicao import PreditorComIntervalo
    preditor = PreditorComIntervalo(alpha=0.1)
    preditor.fit(pipe, X_cal, y_cal)
    del X_cal, y_cal

    # ── 8. Logar no MLflow ──────────────────────────────────────────────
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
        mlflow.set_tag("n_features", len(best_features))
        mlflow.set_tag("scaler", best["scaler"])
        mlflow.set_tag("imputer_num", best["imputer_num"])
        mlflow.set_tag("encoder", best["encoder"])
        mlflow.set_tag("transform", best["transform"])
        mlflow.set_tag("feature_transform_map", best.get("feature_transform_map", ""))
        mlflow.sklearn.log_model(pipe, f"{cidade}_modelo_geral_{mes_ref}")

    logger.info("Run salva: %s", run_name)

    # ── 9. Salvar modelo + preditor local ──────────────────────────────
    modelo_path = pasta_dados / f"{cidade}_modelo_geral_{mes_ref}.joblib"
    joblib.dump(pipe, modelo_path, compress=3)
    logger.info("Modelo salvo: %s", modelo_path.name)

    preditor_path = pasta_dados / f"{cidade}_preditor_intervalo_{mes_ref}.joblib"
    preditor.save(preditor_path)
    logger.info("Preditor com intervalo salvo: %s", preditor_path.name)

    # ── 9b. Remover modelos de meses anteriores ─────────────────────────
    for f in pasta_dados.glob(f"{cidade}_modelo_geral_*.joblib"):
        if f.name != modelo_path.name:
            f.unlink()
            logger.info("Modelo anterior removido: %s", f.name)
    for f in pasta_dados.glob(f"{cidade}_preditor_intervalo_*.joblib"):
        if f.name != preditor_path.name:
            f.unlink()
            logger.info("Preditor anterior removido: %s", f.name)

    # ── 10. Predicao com intervalo no imoveis_limpo ─────────────────────
    logger.info("Gerando predicoes com intervalo no dataset completo...")

    FONTES = ["zap", "vivareal", "chave_mao", "olx"]
    imoveis_path = pasta_dados / f"{cidade}_imoveis_limpo_{mes_ref}.parquet"
    if imoveis_path.exists():
        df_full = pd.read_parquet(imoveis_path)
        df_full["_fonte_origem"] = "combinado"
        logger.info("Combinado carregado: %d linhas", len(df_full))
    else:
        logger.info("Combinado não encontrado — carregando fontes individuais...")
        partes = []
        caminhos_fonte = {}
        for fonte in FONTES:
            pattern = f"{cidade}_imoveis_limpo_{fonte}_{mes_ref}.parquet"
            caminhos = list(pasta_dados.glob(pattern))
            if caminhos:
                caminho = caminhos[0]
                df = pd.read_parquet(caminho)
                df["_fonte_origem"] = fonte
                partes.append(df)
                caminhos_fonte[fonte] = caminho
                logger.info("  %s: %d registros", fonte, len(df))
        if not partes:
            raise FileNotFoundError(
                f"Nenhum arquivo de imóveis encontrado para {cidade}/{mes_ref}. "
                f"Execute os scripts de limpeza primeiro."
            )
        df_full = pd.concat(partes, ignore_index=True)
        logger.info("Total: %d registros (%d fontes)", len(df_full), len(partes))

    indices = CriandoIndicesIndividuais(cidade=cidade_nome, cache_dir=pasta_dados)
    df_full = indices.calcular_indices(imoveis_df=df_full)

    mask = (
        (df_full["metragem"] > 10)
        & (df_full["tipo_imovel"].isin(["casa", "apartamento"]))
        & (df_full["preco_por_m2"] >= 100)
    )
    df_filtrado = df_full[mask].copy()
    df_filtrado, _ = engenharia_features_completa(df_filtrado, df_filtrado.copy())

    # ── 10b. Salvar bairro_stats para o Streamlit ─────────────────────
    bairro_stats = df_filtrado.groupby('bairro').agg(
        metro_quadrado_bairro_mean=('preco_por_m2', 'mean'),
        metro_quadrado_bairro_median=('preco_por_m2', 'median'),
        valor_bairro_mean=('valor_imovel', 'mean'),
        lat_centroide=('lat', 'mean'),
        lng_centroide=('lng', 'mean'),
        count=('metragem', 'count'),
    ).fillna(0)

    bairro_stats['bairro_rank'] = (
        df_filtrado.groupby('bairro')['preco_por_m2'].median().rank()
    )

    score_cols = [c for c in df_filtrado.columns if c.startswith('score_')]
    for col in score_cols:
        bairro_stats[col] = df_filtrado.groupby('bairro')[col].mean()

    bairro_stats.index.name = 'bairro'

    stats_path = pasta_dados / f"{cidade}_bairro_stats_{mes_ref}.parquet"
    bairro_stats.to_parquet(stats_path)
    logger.info("Bairro stats salvo: %s (%d bairros)", stats_path.name, len(bairro_stats))

    X_pred = df_filtrado[best_features].copy()
    y_pred_full, y_lo, y_hi = preditor.predict(X_pred)

    pred_series = pd.Series(y_pred_full, index=df_filtrado.index, name="valor_predito")
    lo_series   = pd.Series(y_lo, index=df_filtrado.index, name="valor_predito_lo")
    hi_series   = pd.Series(y_hi, index=df_filtrado.index, name="valor_predito_hi")

    df_full = df_full.assign(
        valor_predito=pred_series,
        valor_predito_lo=lo_series,
        valor_predito_hi=hi_series,
        erro_absoluto=df_full[target] - pred_series,
        erro_percentual=((df_full[target] - pred_series) / df_full[target]) * 100,
    )

    if df_full["_fonte_origem"].eq("combinado").all():
        df_full.to_parquet(imoveis_path, index=False)
        logger.info(
            "Predicoes salvas em %s (%.0f com valor, %d sem filtro)",
            imoveis_path.name,
            df_full["valor_predito"].notna().sum(),
            df_full["valor_predito"].isna().sum(),
        )
    else:
        col_saida = [c for c in df_full.columns if c != "_fonte_origem"]
        for fonte in FONTES:
            mask = df_full["_fonte_origem"] == fonte
            if not mask.any():
                continue
            caminho_orig = caminhos_fonte[fonte]
            df_pred = df_full.loc[mask, col_saida]
            df_pred.to_parquet(caminho_orig, index=False)
            logger.info(
                "Predicoes %s: %s (%d registros, %.0f com valor)",
                fonte, caminho_orig.name, len(df_pred),
                df_pred["valor_predito"].notna().sum(),
            )

    # ── 12. Limpeza dos caches ──────────────────────────────────────────
    for nome in [
        f"{cidade}_train_{mes_ref}.parquet",
        f"{cidade}_test_{mes_ref}.parquet",
        #f"{cidade}_otimizados_melhores_incrementos_{mes_ref}.parquet",
        f"{cidade}_melhores_por_incremento_{mes_ref}.parquet",
        f"{cidade}_melhores_por_incremento_{mes_ref}.csv",
        f"{cidade}_otimizados_melhores_incrementos_{mes_ref}.csv",
    ]:
        p = pasta_dados / nome
        if p.exists():
            p.unlink()
            logger.info("Cache removido: %s", nome)

    logger.info("Concluido!")
    return pipe


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    warnings.filterwarnings("ignore")
    treinar_melhor_modelo_geral()
