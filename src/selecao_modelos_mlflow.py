import json
import logging
import os
import time
import pandas as pd
import numpy as np
import optuna
from tqdm import tqdm
from pathlib import Path
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import (
    StandardScaler, RobustScaler, MinMaxScaler,
    QuantileTransformer, PowerTransformer,
    OneHotEncoder, OrdinalEncoder,
)
from mlflow.tracking import MlflowClient

from sklearn.model_selection import train_test_split
from preprocessador import PreprocessadorFactory, Avaliador
from otimizador_optuna import OtimizadorOptuna, FactoryModelos
from criando_indices_individuais import CriandoIndicesIndividuais
from funcoes_engenharia_features import engenharia_features_completa


logger = logging.getLogger(__name__)

SCALER_MAP = {
    "StandardScaler": StandardScaler,
    "RobustScaler": RobustScaler,
    "MinMaxScaler": MinMaxScaler,
    "QuantileTransformer": lambda: QuantileTransformer(output_distribution="normal"),
    "PowerTransformer": PowerTransformer,
    "None": lambda: None,
}

ENCODER_MAP = {
    "OneHotEncoder": lambda: OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False),
    "OrdinalEncoder": lambda: OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
}

MODEL_KEY_MAP = {
    "RandomForest_opt": "random_forest",
    "RandomForest": "random_forest",
    "GradientBoosting_opt": "gradient_boosting",
    "GradientBoosting": "gradient_boosting",
    "Ridge_opt": "ridge",
    "Ridge": "ridge",
    "KNN_opt": "knn",
    "KNeighbors": "knn",
    "CatBoost_opt": "catboost",
    "CatBoost": "catboost",
    "Linear": "linear",
    "DecisionTree": "decision_tree",
}


def buscar_todos_runs(client, experiment_id):
    all_runs = []
    page_token = None
    while True:
        results = client.search_runs(
            experiment_ids=[experiment_id],
            max_results=5000,
            page_token=page_token,
        )
        all_runs.extend(results)
        if not results.token:
            break
        page_token = results.token
    return all_runs


def buscar_melhores_por_incremento(client, experiment_id, min_features=1, metrica="r2"):
    runs = buscar_todos_runs(client, experiment_id)
    rows = []
    for r in runs:
        if not r.data.metrics or metrica not in r.data.metrics:
            continue
        p, t, m = r.data.params, r.data.tags, r.data.metrics
        nf = int(t.get("n_features") or p.get("n_features", 0) or 0)
        if nf < min_features:
            continue
        eh_optuna = "_opt" in str(r.info.run_name or "")
        rows.append({
            "run_name": r.info.run_name or "",
            "modelo": t.get("modelo") or p.get("modelo", ""),
            "tratamento": t.get("tratamento") or p.get("tratamento", ""),
            "n_features": nf,
            "otimizacao": t.get("otimizacao") or ("optuna" if eh_optuna else "simples"),
            "transform": p.get("transform", "none"),
            "scaler": t.get("scaler", ""),
            "imputer_num": t.get("imputer_num", ""),
            "encoder": t.get("encoder", ""),
            "feature_history_columns": t.get("feature_history_columns", ""),
            "feature_history_num_columns": t.get("feature_history_num_columns", ""),
            "feature_history_run_name": t.get("feature_history_run_name", ""),
            "feature_transform_map": t.get("feature_transform_map", "{}"),
            "target_transformer": t.get("target_transformer", "none"),
            "r2": m.get("r2"),
            "rmse": m.get("rmse"),
            "mae": m.get("mae"),
            "mape": m.get("mape"),
            "mdape": m.get("mdape"),
            "rmsle": m.get("rmsle"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    direcao = "max" if metrica == "r2" else "min"
    idx = getattr(df.groupby("n_features")[metrica], f"idx{direcao}")()
    return df.loc[idx].sort_values("n_features").reset_index(drop=True)


def buscar_melhores_top_n(client, experiment_id, n=5, min_features=1, metrica="r2"):
    runs = buscar_todos_runs(client, experiment_id)
    rows = []
    for r in runs:
        if not r.data.metrics or metrica not in r.data.metrics:
            continue
        p, t, m = r.data.params, r.data.tags, r.data.metrics
        nf = int(t.get("n_features") or p.get("n_features", 0) or 0)
        if nf < min_features:
            continue
        eh_optuna = "_opt" in str(r.info.run_name or "")
        rows.append({
            "run_name": r.info.run_name or "",
            "modelo": t.get("modelo") or p.get("modelo", ""),
            "tratamento": t.get("tratamento") or p.get("tratamento", ""),
            "n_features": nf,
            "otimizacao": t.get("otimizacao") or ("optuna" if eh_optuna else "simples"),
            "transform": p.get("transform", "none"),
            "scaler": t.get("scaler", ""),
            "imputer_num": t.get("imputer_num", ""),
            "encoder": t.get("encoder", ""),
            "feature_history_columns": t.get("feature_history_columns", ""),
            "feature_history_num_columns": t.get("feature_history_num_columns", ""),
            "feature_history_run_name": t.get("feature_history_run_name", ""),
            "feature_transform_map": t.get("feature_transform_map", "{}"),
            "target_transformer": t.get("target_transformer", "none"),
            "r2": m.get("r2"),
            "rmse": m.get("rmse"),
            "mae": m.get("mae"),
            "mape": m.get("mape"),
            "mdape": m.get("mdape"),
            "rmsle": m.get("rmsle"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    direcao = "max" if metrica == "r2" else "min"
    ascending = direcao == "min"
    return df.sort_values(metrica, ascending=ascending).head(n).reset_index(drop=True)


def buscar_melhores_por_modelo(client, experiment_id, top_k=1, min_features=1, metrica="r2"):
    runs = buscar_todos_runs(client, experiment_id)
    rows = []
    for r in runs:
        if not r.data.metrics or metrica not in r.data.metrics:
            continue
        p, t, m = r.data.params, r.data.tags, r.data.metrics
        nf = int(t.get("n_features") or p.get("n_features", 0) or 0)
        if nf < min_features:
            continue
        eh_optuna = "_opt" in str(r.info.run_name or "")
        rows.append({
            "run_name": r.info.run_name or "",
            "modelo": t.get("modelo") or p.get("modelo", ""),
            "tratamento": t.get("tratamento") or p.get("tratamento", ""),
            "n_features": nf,
            "otimizacao": t.get("otimizacao") or ("optuna" if eh_optuna else "simples"),
            "transform": p.get("transform", "none"),
            "scaler": t.get("scaler", ""),
            "imputer_num": t.get("imputer_num", ""),
            "encoder": t.get("encoder", ""),
            "feature_history_columns": t.get("feature_history_columns", ""),
            "feature_history_num_columns": t.get("feature_history_num_columns", ""),
            "feature_history_run_name": t.get("feature_history_run_name", ""),
            "feature_transform_map": t.get("feature_transform_map", "{}"),
            "target_transformer": t.get("target_transformer", "none"),
            "r2": m.get("r2"),
            "rmse": m.get("rmse"),
            "mae": m.get("mae"),
            "mape": m.get("mape"),
            "mdape": m.get("mdape"),
            "rmsle": m.get("rmsle"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    direcao = "max" if metrica == "r2" else "min"
    ascending = direcao == "min"
    return (
        df.groupby("modelo", sort=False)
        .apply(lambda g: g.sort_values(metrica, ascending=ascending).head(top_k))
        .reset_index(drop=True)
    )


def carregar_dados(pasta_dados, mes_ref, cidade, cidade_nome=None):
    train_path = pasta_dados / f"{cidade}_train_{mes_ref}.parquet"
    test_path  = pasta_dados / f"{cidade}_test_{mes_ref}.parquet"

    if train_path.exists() and test_path.exists():
        train = pd.read_parquet(train_path)
        test  = pd.read_parquet(test_path)
        # O cache e um contrato implicito: se uma feature nova foi adicionada em
        # config_features e o parquet e antigo, carrega-lo em silencio faria a
        # feature desaparecer do modelo sem nenhum erro. Validar antes de aceitar.
        try:
            from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES
            esperadas = list(NUMERIC_FEATURES) + list(CATEGORICAL_FEATURES)
        except ImportError:
            esperadas = []
        faltando = [f for f in esperadas if f not in train.columns]
        if faltando:
            logger.warning(
                "Cache %s desatualizado (faltam %s) — regenerando a partir do imoveis_limpo",
                train_path.name, faltando,
            )
        else:
            logger.info("Dados carregados do cache: treino %s, teste %s", len(train), len(test))
            return train, test

    # ── Gerar cache inline a partir do imoveis_limpo ────────────────
    imoveis_path = pasta_dados / f"{cidade}_imoveis_limpo_{mes_ref}.parquet"

    if imoveis_path.exists():
        dados = pd.read_parquet(imoveis_path)
        logger.info("Cache não encontrado — gerando de %s ...", imoveis_path.name)
    else:
        padrao = f"{cidade}_imoveis_limpo_*_{mes_ref}.parquet"
        arquivos = sorted(pasta_dados.glob(padrao))
        if not arquivos:
            raise FileNotFoundError(
                f"Nem cache nem dados limpos encontrados para {cidade}/{mes_ref}. "
                "Execute coleta e limpeza primeiro."
            )
        dfs = [pd.read_parquet(a) for a in arquivos]
        dados = pd.concat(dfs, ignore_index=True)
        logger.info("Carregados %d fontes: %s linhas", len(arquivos), len(dados))
    cols_obrig = {'descricao', 'bairro', 'metragem', 'preco_por_m2', 'tipo_imovel'}
    if not cols_obrig.issubset(dados.columns):
        raise KeyError(f"Colunas obrigatorias ausentes: {cols_obrig - set(dados.columns)}")

    if cidade_nome:
        # Coordenadas de fallback do geocoder (12,6% da base, a 400-600 km)
        # precisam sair ANTES de calcular POIs: dist_centro e todos os score_*
        # derivam de lat/lng e ficariam apontando para outra cidade.
        from funcoes_engenharia_features import sanitizar_coordenadas
        dados = sanitizar_coordenadas(dados)
        logger.info("Calculando indices de localizacao...")
        indices = CriandoIndicesIndividuais(cidade=cidade_nome, cache_dir=pasta_dados)
        dados = indices.calcular_indices(imoveis_df=dados)

    df_modelo = dados[
        (dados["metragem"] > 10)
        & (dados["tipo_imovel"].isin(["casa", "apartamento"]))
        & (dados["preco_por_m2"] >= 100)
    ].copy()
    df_modelo = df_modelo.dropna(subset=["valor_imovel"])

    # Teto de R$/m²: typos com dígitos colados (R$1,05B num sobrado = 7,5M/m²)
    # explodem qualquer métrica quadrática sozinhos (~R$13M no RMSE).
    # Sem teto de metragem (terrenos grandes legítimos passam) e sem teto
    # de valor absoluto: o filtro é pela implausibilidade do metro quadrado.
    TETO_PRECO_POR_M2 = 100_000
    mask_pm2 = df_modelo["preco_por_m2"] <= TETO_PRECO_POR_M2
    fora = df_modelo.loc[~mask_pm2, ["url", "titulo", "bairro", "valor_imovel", "preco_por_m2"]]
    if not fora.empty:
        logger.warning(
            "Outliers de R$/m² barrados no treino (%d): %s",
            len(fora), fora.to_dict(orient="records"),
        )
    df_modelo = df_modelo.loc[mask_pm2].copy()

    # Metragem plausivel por tipo. O teto de R$/m2 nao pega isto: um apartamento
    # de 8.505 m2 por R$ 1,06 mi da R$ 124/m2, que passa no filtro acima, e vira
    # a maior predicao errada do modelo (R$ 4,5 mi). Sao erros de coleta.
    TETO_METRAGEM = {"apartamento": 1_000, "casa": 3_000}
    metragem_num = pd.to_numeric(df_modelo["metragem"], errors="coerce")
    teto = df_modelo["tipo_imovel"].map(TETO_METRAGEM)
    plausivel = (teto.isna() | (metragem_num <= teto)) & metragem_num.notna()
    if not plausivel.all():
        barrados = df_modelo.loc[~plausivel]
        logger.warning(
            "Metragem implausivel barrada no treino (%d de %d): %s",
            len(barrados), len(df_modelo),
            barrados[["tipo_imovel", "metragem", "valor_imovel", "preco_por_m2"]]
            .head(10).to_dict(orient="records"),
        )
        df_modelo = df_modelo.loc[plausivel].copy()

    train, test = train_test_split(df_modelo, test_size=0.25, random_state=42)
    train, test = engenharia_features_completa(train, test)

    train.to_parquet(train_path, index=False)
    
    test.to_parquet(test_path, index=False)
    
    logger.info("Cache salvo: %s, %s", train_path.name, test_path.name)

    return train, test


def deletar_runs_experimento(experimento_mlflow, confirmacao=False, databricks_workspace_path=None):
    from mlflow_manager import MLflowManager
    from mlflow.tracking import MlflowClient

    mgr = MLflowManager(
        nome_experimento=experimento_mlflow,
        databricks_workspace_path=databricks_workspace_path,
    )
    mgr.conectar()
    client = MlflowClient(mgr.get_tracking_uri())

    exp = client.get_experiment_by_name(mgr.nome_experimento)
    if not exp:
        exp = client.get_experiment_by_name(mgr.databricks_workspace_path)
    if not exp:
        logger.warning(f"Experimento '{experimento_mlflow}' nao encontrado, nada a deletar")
        return

    runs = buscar_todos_runs(client, exp.experiment_id)
    if not runs:
        logger.info("Nenhum run encontrado no experimento")
        return

    if not confirmacao:
        logger.warning(
            f"Encontrados {len(runs)} runs no experimento '{exp.name}'. "
            f"Defina confirmacao=True para deletar."
        )
        return

    for run in runs:
        client.delete_run(run.info.run_id)
    logger.info(f"{len(runs)} runs deletados do experimento '{exp.name}'")


def escolher_melhor_config(df_otim, criterio=None):
    """Indice da linha vencedora da tabela de otimizados.

    `criterio` pode ser "rmse" (default, comportamento historico) ou "mdape",
    ou vir da env CRITERIO_SELECAO. Medido em Joinville/2026-11, os dois
    rankings discordam:

        por RMSE  -> GradientBoosting 42 feats | R2 0,8620 | RMSE 404k | MdAPE 10,30%
        por MdAPE -> RandomForest     18 feats | R2 0,8305 | RMSE 447k | MdAPE  9,97%

    Ou seja: trocar para MdAPE ganha 0,33 p.p. no erro tipico e custa 3 pontos
    de R2 e R$ 44 mil de RMSE. Nao e uma correcao obvia, e uma escolha de
    produto — por isso o default continua sendo RMSE. A busca upstream usa
    MdAPE, entao quem quiser coerencia ponta a ponta liga CRITERIO_SELECAO=mdape.
    """
    if criterio is None:
        criterio = os.getenv("CRITERIO_SELECAO", "rmse")

    ordem = ["mdape_otimizado", "rmse_otimizado"] if criterio.lower() == "mdape" \
        else ["rmse_otimizado", "mdape_otimizado"]

    for chave in ordem:
        if chave in df_otim.columns and df_otim[chave].notna().any():
            logger.info("Melhor configuracao escolhida por %s", chave)
            alternativa = ordem[1]
            if alternativa in df_otim.columns and df_otim[alternativa].notna().any():
                alt = df_otim[alternativa].idxmin()
                detalhe = {
                    c: df_otim.loc[alt, c]
                    for c in ("r2_otimizado", "rmse_otimizado", "mdape_otimizado")
                    if c in df_otim.columns
                }
                logger.info("  (por %s a escolha seria a linha %s: %s)",
                            alternativa, alt, detalhe)
            return df_otim[chave].idxmin()
    raise KeyError("df_otim sem 'mdape_otimizado' nem 'rmse_otimizado'")


def orcamento_por_run(deadline, total_runs, indice, timeout_trial, min_por_run_s=300):
    """Segundos de Optuna para o run `indice` (0-based) dentro do orcamento global.

    Divide o tempo restante entre os runs que ainda faltam e nunca passa do teto
    por estudo. Retorna 0 quando nao ha tempo util; o chamador deve parar.
    """
    restante = deadline - time.monotonic()
    runs_faltando = total_runs - indice
    if runs_faltando <= 0 or restante <= min_por_run_s:
        return 0
    return int(min(timeout_trial, restante / runs_faltando))


def otimizar_melhores_incrementos(
    experimento_mlflow,
    train, test,
    numeric_features,
    categorical_features,
    n_trials=15,
    min_features=10,
    target_col="valor_imovel",
    metrica="r2",
    selection_mode="features",
    top_k=10,
    top_k_modelo=3,
    incluir_mlp=True,
    max_horas=4.5,
    timeout_trial=600,
):
    # Orcamento global: o job do GitHub Actions morre em 6h (limite da plataforma)
    # e a busca era `nº de runs x 600s` sem teto agregado — estourava o job e o
    # "Commit e Push" (que roda depois) nunca executava, perdendo tudo.
    deadline = time.monotonic() + max_horas * 3600

    logger.info(f"Buscando melhores incrementos no experimento '{experimento_mlflow}'")
    logger.info(f"Minimo de features: {min_features}")
    logger.info(f"Metrica: {metrica}")
    logger.info(f"Otimalizando {n_trials} vezes")
    logger.info(f"Modo de selecao: {selection_mode}")
    logger.info(f"Orcamento da otimizacao: {max_horas:.1f}h | teto por estudo: {timeout_trial}s")
    if selection_mode in ("top_n", "combinado"):
        logger.info(f"Top K geral: {top_k}")
    if selection_mode in ("por_modelo", "combinado"):
        logger.info(f"Top K por modelo: {top_k_modelo}")
    logger.info(f"Incluir MLP: {incluir_mlp}")
    logger.info(f"Features numericas: {numeric_features}")
    logger.info(f"Features categoricas: {categorical_features}")
    logger.info(f"Target: {target_col}")
    
    from mlflow_manager import MLflowManager

    mgr = MLflowManager(nome_experimento=experimento_mlflow)
    mgr.conectar()
    client = MlflowClient(mgr.get_tracking_uri())
    exp = client.get_experiment_by_name(mgr.nome_experimento)
    if not exp:
        exp = client.get_experiment_by_name(mgr.databricks_workspace_path)
    if not exp:
        for e in client.search_experiments():
            if mgr.nome_experimento in e.name or mgr.databricks_workspace_path in e.name:
                exp = e
                break
    if not exp:
        logger.error(f"Experimento '{experimento_mlflow}' nao encontrado")
        return pd.DataFrame()

    strategies = {
        "features": lambda: buscar_melhores_por_incremento(
            client, exp.experiment_id, min_features, metrica),
        "top_n": lambda: buscar_melhores_top_n(
            client, exp.experiment_id, top_k, min_features, metrica),
        "por_modelo": lambda: buscar_melhores_por_modelo(
            client, exp.experiment_id, top_k_modelo, min_features, metrica),
    }

    if selection_mode == "combinado":
        parts = [fn() for fn in strategies.values()]
        combo_cols = ["modelo", "tratamento", "transform", "n_features",
                      "scaler", "imputer_num", "encoder"]
        melhores = pd.concat(parts).drop_duplicates(subset=combo_cols).reset_index(drop=True)
    elif selection_mode in strategies:
        melhores = strategies[selection_mode]()
    else:
        logger.warning("Modo de selecao invalido: %s", selection_mode)
        return pd.DataFrame()

    if melhores.empty:
        logger.warning("Nenhum run encontrado")
        return pd.DataFrame()

    if not incluir_mlp:
        n_antes = len(melhores)
        melhores = melhores[melhores["modelo"] != "MLP"].reset_index(drop=True)
        logger.info("MLP removido: %d runs filtrados (restam %d)", n_antes - len(melhores), len(melhores))

    logger.info("Total de runs selecionados para otimizacao: %d", len(melhores))
    for _, r in melhores.iterrows():
        logger.info(
            "  %s | %s | %s | %.0f feats | %s | %s",
            r["modelo"], r["tratamento"], r["transform"],
            r["n_features"], r["scaler"], r["imputer_num"],
        )

    resultados = []
    total_runs = len(melhores)
    for i, (_, row) in enumerate(
        tqdm(melhores.iterrows(), total=total_runs, desc="Otimizando runs")
    ):
        timeout_run = orcamento_por_run(deadline, total_runs, i, timeout_trial)
        if timeout_run <= 0:
            logger.warning(
                "Orcamento de %.1fh esgotado: %d de %d runs nao otimizados. "
                "O parquet sera gravado com os %d runs concluidos.",
                max_horas, total_runs - i, total_runs, len(resultados),
            )
            break
        logger.info(
            "Run %d/%d | orcamento restante %.0f min | teto deste estudo %ds",
            i + 1, total_runs, (deadline - time.monotonic()) / 60, timeout_run,
        )

        feat_map = json.loads(row["feature_transform_map"])
        all_features = list(feat_map.keys())
        if not all_features:
            continue

        nf = int(row["n_features"])
        modelo_nome = row["modelo"]
        transform = row["transform"]
        scaler_cls = SCALER_MAP.get(row["scaler"], StandardScaler)
        imputer_str = row["imputer_num"] or "median"
        encoder_cls = ENCODER_MAP.get(row["encoder"], OneHotEncoder)

        num_feats = [c for c in all_features if c in numeric_features]
        cat_feats = [c for c in all_features if c in categorical_features]

        X_tr = train[all_features].copy()
        X_te = test[all_features].copy()
        y_tr = train[target_col].values
        y_te = test[target_col].values
        target_transform = row.get("target_transform", row.get("target_transformer", "none"))

        pp = PreprocessadorFactory(
            numeric_features=num_feats, categorical_features=cat_feats,
        ).criar(
            scaler=scaler_cls(),
            imputer_num=SimpleImputer(strategy=imputer_str),
            encoder=encoder_cls(),
            transform=transform if transform != "none" else None,
        )

        run_name = f"{modelo_nome}|{row['tratamento']}|{transform}_{nf}feats"

        # ── Modelos sem hiperparametros (Linear) — pula Optuna ─────────────
        if modelo_nome in ("Linear", "linear"):
            from sklearn.linear_model import LinearRegression
            best_params = {}
            best_cv_rmse = None
            modelo_best = LinearRegression()
            logger.info(
                "Treinando %s | tratamento=%s | n_features=%d | target_transform=%s",
                modelo_nome, row["tratamento"], nf, target_transform,
            )
            y_fit = np.log1p(y_tr) if target_transform == "log" else y_tr
            pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
            pipe.fit(X_tr, y_fit)
            y_pred_raw = pipe.predict(X_te)
            y_pred = np.expm1(y_pred_raw) if target_transform == "log" else y_pred_raw
            met = Avaliador.metricas(run_name, y_te, y_pred)

            with mgr.run_session(run_name=f"noopt_{modelo_nome}|{row['tratamento']}|{transform}_{nf}feats",
                                 tags={"categoria": "otimizado_melhor_incremento"}):
                import mlflow
                mlflow.log_metrics(met)
                mlflow.set_tag("modelo", modelo_nome)
                mlflow.set_tag("tratamento", row["tratamento"])
                mlflow.set_tag("n_features", nf)
                mlflow.set_tag("transform", transform)
                mlflow.set_tag("scaler", row["scaler"])
                mlflow.set_tag("imputer_num", row["imputer_num"])
                mlflow.set_tag("encoder", row["encoder"])
                mlflow.set_tag("feature_transform_map", row.get("feature_transform_map", ""))
                mlflow.set_tag("feature_history_columns", row.get("feature_history_columns", ""))
                mlflow.set_tag("feature_history_num_columns", row.get("feature_history_num_columns", ""))
                mlflow.set_tag("feature_history_run_name", row.get("feature_history_run_name", ""))
                mlflow.set_tag("target_transformer", target_transform)
            resultados.append({
                "n_features": nf,
                "modelo": modelo_nome,
                "tratamento": row["tratamento"],
                "transform": transform,
                "scaler": row["scaler"],
                "imputer_num": row["imputer_num"],
                "encoder": row["encoder"],
                "feature_history_columns": row.get("feature_history_columns", ""),
                "feature_history_num_columns": row.get("feature_history_num_columns", ""),
                "feature_history_run_name": row.get("feature_history_run_name", ""),
                "feature_transform_map": row.get("feature_transform_map", ""),
                "best_params": json.dumps(best_params),
                # CV no espaco do alvo. Auditoria: permite comparar configs sem
                # escolher pelo conjunto de teste.
                "best_cv_rmse": best_cv_rmse,
                "r2_original": row["r2"],
                "rmse_original": row["rmse"],
                "mae_original": row["mae"],
                "mape_original": row["mape"],
                "mdape_original": row["mdape"],
                "rmsle_original": row.get("rmsle"),
                "r2_otimizado": met.get("r2"),
                "rmse_otimizado": met.get("rmse"),
                "mae_otimizado": met.get("mae"),
                "mape_otimizado": met.get("mape"),
                "mdape_otimizado": met.get("mdape"),
                "rmsle_otimizado": met.get("rmsle"),
            })
            continue

        # ── MLP — Otimizador especifico (Keras) ────────────────────────────
        if modelo_nome == "MLP":
            from otimizador_optuna import OtimizadorMLP
            from sklearn.model_selection import train_test_split

            input_dim = X_tr.select_dtypes(include=[np.number]).shape[1]
            logger.info(
                "Otimizando %s | tratamento=%s | n_features=%d | target_transform=%s | input_dim=%d",
                modelo_nome, row["tratamento"], nf, target_transform, input_dim,
            )

            X_tr_mlp, X_val_mlp, y_tr_mlp, y_val_mlp = train_test_split(
                X_tr, y_tr, test_size=0.25, random_state=42
            )

            pp_mlp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_feats,
            ).criar(
                scaler=StandardScaler(),
                imputer_num=SimpleImputer(strategy=imputer_str),
                encoder=encoder_cls(),
                transform=None,
            )
            X_tr_t = pp_mlp.fit_transform(X_tr_mlp, y_tr_mlp)
            X_val_t = pp_mlp.transform(X_val_mlp)
            X_te_t = pp_mlp.transform(X_te)

            n_trials_mlp = min(n_trials, 20)
            otim_mlp = OtimizadorMLP(mlflow_manager=None, random_state=42)
            estudo, modelo_best = otim_mlp.otimizar(
                X_train=np.asarray(X_tr_t), y_train=np.asarray(y_tr_mlp),
                X_val=np.asarray(X_val_t), y_val=np.asarray(y_val_mlp),
                input_dim=input_dim,
                n_trials=n_trials_mlp,
                epochs=100,
                nome=f"optuna_{run_name}",
                timeout_trial=timeout_run,
            )
            if estudo is None:
                continue

            best_params = estudo.best_params if estudo else {}
            best_cv_rmse = getattr(estudo, 'best_value', None)

            y_pred = modelo_best.predict(np.asarray(X_te_t), verbose=0).ravel()
            met = Avaliador.metricas(f"optuna_{run_name}", y_te, y_pred)

            with mgr.run_session(run_name=f"best_{run_name}",
                                 tags={"categoria": "otimizado_melhor_incremento"}):
                import mlflow
                mlflow.log_params({f"best_{k}": str(v) for k, v in best_params.items()})
                if best_cv_rmse is not None:
                    mlflow.log_metric("best_cv_rmse", best_cv_rmse)
                mlflow.log_metrics(met)
                for tag in ["modelo","tratamento","n_features","transform",
                            "scaler","imputer_num","encoder",
                            "feature_transform_map","feature_history_columns",
                            "feature_history_num_columns","feature_history_run_name",
                            "target_transformer"]:
                    mlflow.set_tag(tag, row.get(tag, ""))
            resultados.append({
                "n_features": nf,
                "modelo": modelo_nome,
                "tratamento": row["tratamento"],
                "transform": transform,
                "scaler": row["scaler"],
                "imputer_num": row["imputer_num"],
                "encoder": row["encoder"],
                "feature_history_columns": row.get("feature_history_columns", ""),
                "feature_history_num_columns": row.get("feature_history_num_columns", ""),
                "feature_history_run_name": row.get("feature_history_run_name", ""),
                "feature_transform_map": row.get("feature_transform_map", ""),
                "target_transform": target_transform,
                "target_transformer": target_transform,
                "best_params": json.dumps(best_params),
                "best_cv_rmse": best_cv_rmse,
                "r2_original": row["r2"],
                "rmse_original": row["rmse"],
                "mae_original": row["mae"],
                "mape_original": row["mape"],
                "mdape_original": row["mdape"],
                "rmsle_original": row.get("rmsle"),
                "r2_otimizado": met.get("r2"),
                "rmse_otimizado": met.get("rmse"),
                "mae_otimizado": met.get("mae"),
                "mape_otimizado": met.get("mape"),
                "mdape_otimizado": met.get("mdape"),
                "rmsle_otimizado": met.get("rmsle"),
            })
            continue

        # ── Modelos com hiperparametros — Optuna normalmente ───────────────
        model_key = MODEL_KEY_MAP.get(modelo_nome, "")
        factory = getattr(FactoryModelos(), model_key, None)
        if not factory:
            logger.warning(f"Modelo '{modelo_nome}' nao mapeado, pulando")
            continue

        logger.info(
            "Otimizando %s com Optuna | tratamento=%s | n_features=%d | target_transform=%s | n_trials=%d",
            modelo_nome, row["tratamento"], nf, target_transform, n_trials,
        )

        y_fit = np.log1p(y_tr) if target_transform == "log" else y_tr

        otim = OtimizadorOptuna(
            preprocessador=pp, X=X_tr, y=y_fit,
            mlflow_manager=None,
            n_trials=n_trials, n_folds=5, timeout_trial=timeout_run,
        )
        estudo = otim.otimizar(f"optuna_{run_name}", factory, log_trials=False)
        if not estudo:
            continue

        best_params = estudo.best_params
        best_cv_rmse = estudo.best_value

        trial_fixo = optuna.trial.FixedTrial(best_params)
        modelo_best = factory(trial_fixo)
        pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
        pipe.fit(X_tr, y_fit)
        y_pred_raw = pipe.predict(X_te)
        y_pred = np.expm1(y_pred_raw) if target_transform == "log" else y_pred_raw
        met = Avaliador.metricas(f"optuna_{run_name}", y_te, y_pred)

        with mgr.run_session(run_name=f"best_{run_name}",
                             tags={"categoria": "otimizado_melhor_incremento"}):
            import mlflow
            mlflow.log_params({f"best_{k}": str(v) for k, v in best_params.items()})
            mlflow.log_metric("best_cv_rmse", best_cv_rmse)
            mlflow.log_metrics(met)
            mlflow.set_tag("modelo", modelo_nome)
            mlflow.set_tag("tratamento", row["tratamento"])
            mlflow.set_tag("n_features", nf)
            mlflow.set_tag("transform", transform)
            mlflow.set_tag("scaler", row["scaler"])
            mlflow.set_tag("imputer_num", row["imputer_num"])
            mlflow.set_tag("encoder", row["encoder"])
            mlflow.set_tag("feature_transform_map", row.get("feature_transform_map", ""))
            mlflow.set_tag("feature_history_columns", row.get("feature_history_columns", ""))
            mlflow.set_tag("feature_history_num_columns", row.get("feature_history_num_columns", ""))
            mlflow.set_tag("feature_history_run_name", row.get("feature_history_run_name", ""))
            mlflow.set_tag("target_transformer", target_transform)

        resultados.append({
            "n_features": nf,
            "modelo": modelo_nome,
            "tratamento": row["tratamento"],
            "transform": transform,
            "scaler": row["scaler"],
            "imputer_num": row["imputer_num"],
            "encoder": row["encoder"],
            "feature_history_columns": row.get("feature_history_columns", ""),
            "feature_history_num_columns": row.get("feature_history_num_columns", ""),
            "feature_history_run_name": row.get("feature_history_run_name", ""),
            "feature_transform_map": row.get("feature_transform_map", ""),
            "target_transform": target_transform,
            "target_transformer": target_transform,
            "best_params": json.dumps(best_params),
            "best_cv_rmse": best_cv_rmse,
            "r2_original": row["r2"],
            "rmse_original": row["rmse"],
            "mae_original": row["mae"],
            "mape_original": row["mape"],
            "mdape_original": row["mdape"],
            "rmsle_original": row.get("rmsle"),
            "r2_otimizado": met.get("r2"),
            "rmse_otimizado": met.get("rmse"),
            "mae_otimizado": met.get("mae"),
            "mape_otimizado": met.get("mape"),
            "mdape_otimizado": met.get("mdape"),
            "rmsle_otimizado": met.get("rmsle"),
        })

    df_out = pd.DataFrame(resultados)
    return df_out
