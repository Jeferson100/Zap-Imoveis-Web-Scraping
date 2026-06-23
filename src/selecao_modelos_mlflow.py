import json
import logging
import pandas as pd
import numpy as np
import optuna
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


def buscar_melhores_top_n(client, experiment_id, n=10, min_features=1, metrica="r2"):
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


def buscar_melhores_por_modelo(client, experiment_id, top_k=2, min_features=1, metrica="r2"):
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
        logger.info("Dados carregados do cache: treino %s, teste %s", len(train), len(test))
        return train, test

    # ── Gerar cache inline a partir do imoveis_limpo ────────────────
    imoveis_path = pasta_dados / f"{cidade}_imoveis_limpo_{mes_ref}.parquet"
    if not imoveis_path.exists():
        raise FileNotFoundError(
            f"Nem cache nem dados limpos encontrados para {cidade}/{mes_ref}. "
            "Execute coleta e limpeza primeiro."
        )

    logger.info("Cache não encontrado — gerando de %s ...", imoveis_path.name)
    dados = pd.read_parquet(imoveis_path)
    cols_obrig = {'descricao', 'bairro', 'metragem', 'preco_por_m2', 'tipo_imovel'}
    if not cols_obrig.issubset(dados.columns):
        raise KeyError(f"Colunas obrigatorias ausentes: {cols_obrig - set(dados.columns)}")

    if cidade_nome:
        logger.info("Calculando indices de localizacao...")
        indices = CriandoIndicesIndividuais(cidade=cidade_nome, cache_dir=pasta_dados)
        dados = indices.calcular_indices(imoveis_df=dados)

    df_modelo = dados[
        (dados["metragem"] > 10)
        & (dados["tipo_imovel"].isin(["casa", "apartamento"]))
        & (dados["preco_por_m2"] >= 100)
    ].copy()

    train, test = train_test_split(df_modelo, test_size=0.25, random_state=42)
    train, test = engenharia_features_completa(train, test)

    train.to_parquet(train_path, index=False)
    test.to_parquet(test_path, index=False)
    logger.info("Cache salvo: %s, %s", train_path.name, test_path.name)

    return train, test


def deletar_runs_experimento(experimento_mlflow, confirmacao=False):
    from mlflow_manager import MLflowManager
    from mlflow.tracking import MlflowClient

    mgr = MLflowManager(nome_experimento=experimento_mlflow)
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


def otimizar_melhores_incrementos(
    experimento_mlflow,
    train, test,
    numeric_features,
    categorical_features,
    n_trials=15,
    min_features=1,
    target_col="valor_imovel",
    metrica="r2",
    selection_mode="features",
    top_k=10,
):
    logger.info(f"Buscando melhores incrementos no experimento '{experimento_mlflow}'")
    logger.info(f"Minimo de features: {min_features}")
    logger.info(f"Metrica: {metrica}")
    logger.info(f"Otimalizando {n_trials} vezes")
    logger.info(f"Modo de selecao: {selection_mode}")
    if selection_mode in ("top_n", "por_modelo", "combinado"):
        logger.info(f"Top K: {top_k}")
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
            client, exp.experiment_id, top_k, min_features, metrica),
    }

    if selection_mode == "combinado":
        parts = [fn() for fn in strategies.values()]
        melhores = pd.concat(parts).drop_duplicates(subset="run_name").reset_index(drop=True)
    elif selection_mode in strategies:
        melhores = strategies[selection_mode]()
    else:
        logger.warning("Modo de selecao invalido: %s", selection_mode)
        return pd.DataFrame()

    if melhores.empty:
        logger.warning("Nenhum run encontrado")
        return pd.DataFrame()

    resultados = []
    for _, row in melhores.iterrows():
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

        pp = PreprocessadorFactory(
            numeric_features=num_feats, categorical_features=cat_feats,
        ).criar(
            scaler=scaler_cls(),
            imputer_num=SimpleImputer(strategy=imputer_str),
            encoder=encoder_cls(),
            transform=transform if transform != "none" else None,
        )

        model_key = MODEL_KEY_MAP.get(modelo_nome, "")
        factory = getattr(FactoryModelos(), model_key, None)
        if not factory:
            logger.warning(f"Modelo '{modelo_nome}' nao mapeado, pulando")
            continue

        run_name = f"optuna_{modelo_nome}|{row['tratamento']}|{transform}_{nf}feats"
        otim = OtimizadorOptuna(
            preprocessador=pp, X=X_tr, y=y_tr,
            mlflow_manager=None,
            n_trials=n_trials, n_folds=5,
        )
        estudo = otim.otimizar(run_name, factory, log_trials=False)
        if not estudo:
            continue

        best_params = estudo.best_params
        best_cv_rmse = estudo.best_value

        trial_fixo = optuna.trial.FixedTrial(best_params)
        modelo_best = factory(trial_fixo)
        pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
        pipe.fit(X_tr, y_tr)
        y_pred = pipe.predict(X_te)
        met = Avaliador.metricas(run_name, y_te, y_pred)

        with mgr.run_session(run_name=f"best_{modelo_nome}|{row['tratamento']}|{transform}_{nf}feats",
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
