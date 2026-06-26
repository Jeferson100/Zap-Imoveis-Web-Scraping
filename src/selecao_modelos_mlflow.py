import json
import logging
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
    df_modelo = df_modelo.dropna(subset=["valor_imovel"])

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
    top_k_modelo=3,
    incluir_mlp=True,
):
    logger.info(f"Buscando melhores incrementos no experimento '{experimento_mlflow}'")
    logger.info(f"Minimo de features: {min_features}")
    logger.info(f"Metrica: {metrica}")
    logger.info(f"Otimalizando {n_trials} vezes")
    logger.info(f"Modo de selecao: {selection_mode}")
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
    for _, row in tqdm(melhores.iterrows(), total=len(melhores), desc="Otimizando runs"):
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

        run_name = f"{modelo_nome}|{row['tratamento']}|{transform}_{nf}feats"

        # ── Modelos sem hiperparametros (Linear) — pula Optuna ─────────────
        if modelo_nome in ("Linear", "linear"):
            from sklearn.linear_model import LinearRegression
            best_params = {}
            best_cv_rmse = None
            modelo_best = LinearRegression()
            pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
            pipe.fit(X_tr, y_tr)
            y_pred = pipe.predict(X_te)
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
            continue

        # ── MLP — Otimizador especifico (Keras) ────────────────────────────
        if modelo_nome == "MLP":
            from otimizador_optuna import OtimizadorMLP
            from sklearn.model_selection import train_test_split

            input_dim = X_tr.select_dtypes(include=[np.number]).shape[1]

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
                            "feature_history_num_columns","feature_history_run_name"]:
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
            continue

        # ── Modelos com hiperparametros — Optuna normalmente ───────────────
        model_key = MODEL_KEY_MAP.get(modelo_nome, "")
        factory = getattr(FactoryModelos(), model_key, None)
        if not factory:
            logger.warning(f"Modelo '{modelo_nome}' nao mapeado, pulando")
            continue

        otim = OtimizadorOptuna(
            preprocessador=pp, X=X_tr, y=y_tr,
            mlflow_manager=None,
            n_trials=n_trials, n_folds=5,
        )
        estudo = otim.otimizar(f"optuna_{run_name}", factory, log_trials=False)
        if not estudo:
            continue

        best_params = estudo.best_params
        best_cv_rmse = estudo.best_value

        trial_fixo = optuna.trial.FixedTrial(best_params)
        modelo_best = factory(trial_fixo)
        pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
        pipe.fit(X_tr, y_tr)
        y_pred = pipe.predict(X_te)
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
