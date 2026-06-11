import logging
import time
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.svm import SVR
from sklearn.preprocessing import StandardScaler, RobustScaler, MinMaxScaler, QuantileTransformer, PowerTransformer, OrdinalEncoder, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split

from preprocessador import PreprocessadorFactory, Avaliador
from mlflow_manager import MLflowManager
from otimizador_optuna import (
    OtimizadorOptuna,
    FactoryModelos,
    OtimizadorMLP,
)

import time

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ─── Configuracoes de tratamento ───────────────────────────────
TRATAMENTOS = [
    {"nome": "std_median_ohe",       "scaler": lambda: StandardScaler(),
     "imputer_num": "median",        "encoder": lambda: OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "robust_median_ohe",    "scaler": lambda: RobustScaler(),
     "imputer_num": "median",        "encoder": lambda: OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "minmax_mean_ohe",      "scaler": lambda: MinMaxScaler(),
     "imputer_num": "mean",          "encoder": lambda: OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "quantile_median_ord",  "scaler": lambda: QuantileTransformer(output_distribution="normal"),
     "imputer_num": "median",        "encoder": lambda: OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)},
    {"nome": "power_median_ohe",     "scaler": lambda: PowerTransformer(),
     "imputer_num": "median",        "encoder": lambda: OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "raw_zero_ord",         "scaler": lambda: None,
     "imputer_num": "constant",      "encoder": lambda: OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)},
]

# ─── Modelos que serao otimizados com Optuna ────────────────────
MODELOS_OTIMIZAVEIS = {
    "Ridge_opt":        FactoryModelos().ridge,
    #"DecisionTree_opt": FactoryModelos().decision_tree,
    "RandomForest_opt": FactoryModelos().random_forest,
    "GradientBoosting_opt": FactoryModelos().gradient_boosting,
    "KNN_opt":          FactoryModelos().knn,
    "SVR_opt":          FactoryModelos().svr,
    "CatBoost_opt":     FactoryModelos().catboost,
    "LightGBM_opt":     FactoryModelos().lightgbm,
    "HistGB_opt":       FactoryModelos().hist_gb,
}

# ─── Modelos simples (sem Optuna) ──────────────────────────────
MODELOS_SIMPLES_TRAT = {
    "Linear": lambda: LinearRegression(),
    "Ridge": lambda: Ridge(),
    "DecisionTree": lambda: DecisionTreeRegressor(random_state=42),
    "RandomForest": lambda: RandomForestRegressor(
        n_estimators=200, max_depth=12, random_state=42, n_jobs=-1
    ),
    "GradientBoosting": lambda: GradientBoostingRegressor(
        n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42
    ),
    "KNeighbors": lambda: KNeighborsRegressor(n_jobs=-1),
    "SVR": lambda: SVR(kernel="rbf"),
}

now = time.strftime("%Y-%m")

class TesteIncrementalFeatures:
    """Testa modelos (incluindo otimizados via Optuna) com features incrementais."""

    MODELOS_SIMPLES = {
        "Linear": LinearRegression(),
        "Ridge": Ridge(),
        "DecisionTree": DecisionTreeRegressor(random_state=42),
        "RandomForest": RandomForestRegressor(
            n_estimators=200, max_depth=12, random_state=42, n_jobs=-1
        ),
        "GradientBoosting": GradientBoostingRegressor(
            n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42
        ),
        "KNeighbors": KNeighborsRegressor(n_jobs=-1),
        "SVR": SVR(kernel="rbf"),
    }

    ESCALADORES_PADRAO = {
        "raw": None,
        "standard": StandardScaler(),
        "robust": RobustScaler(),
        "minmax": MinMaxScaler(),
    }

    MODELOS_OPTUNA = {
        "Ridge_opt": "ridge",
        "DecisionTree_opt": "decision_tree",
        "RandomForest_opt": "random_forest",
        "GradientBoosting_opt": "gradient_boosting",
        "KNN_opt": "knn",
        "SVR_opt": "svr",
        "CatBoost_opt": "catboost",
        "LightGBM_opt": "lightgbm",
        "HistGB_opt": "hist_gradient_boosting",
    }

    def __init__(
        self,
        modelos_simples=None,
        escaladores=None,
        modelos_optuna=None,
        n_trials_optuna=20,
        n_trials_mlp=15,
        usar_xgboost=True,
        usar_rede_neural=True,
        usar_mlp_otimizado=True,
        feature_start=1,
        experimento_mlflow="teste-incremental-features",
        log_level=logging.INFO,
    ):
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S",
        )
        self.modelos_simples = dict(modelos_simples or self.MODELOS_SIMPLES)
        self.escaladores = dict(escaladores or self.ESCALADORES_PADRAO)
        self.modelos_optuna_nomes = dict(
            modelos_optuna or self.MODELOS_OPTUNA
        )
        self.n_trials_optuna = n_trials_optuna
        self.n_trials_mlp = n_trials_mlp
        self.feature_start = feature_start
        self.experimento_mlflow = experimento_mlflow
        self.optuna_params_otimizados = {}
        self.usar_mlp_otimizado = usar_mlp_otimizado

        if usar_xgboost:
            self._tentar_adicionar_xgboost()
        if usar_rede_neural:
            self.modelos_simples["RedesNeurais"] = None

        self.resultados = []
        self.modelos_treinados = {}
        self.predictions = {}
        self.mlflow_mgr = None
        self.factory = FactoryModelos()

    def _tentar_adicionar_xgboost(self):
        try:
            from xgboost import XGBRegressor

            self.modelos_simples["XGBoost"] = XGBRegressor(
                n_estimators=200,
                max_depth=8,
                learning_rate=0.1,
                random_state=42,
                n_jobs=-1,
                verbosity=0,
            )
        except ImportError:
            logger.debug("XGBoost nao disponivel")

    @staticmethod
    def _construir_rede_neural(input_dim):
        import keras
        from keras import layers

        model = keras.Sequential()
        model.add(layers.Dense(40, activation="relu", input_shape=(input_dim,)))
        model.add(layers.Dense(60, activation="relu"))
        model.add(layers.Dense(40, activation="relu"))
        model.add(layers.Dense(1, activation="linear"))
        model.compile(
            optimizer="adam",
            loss="mse",
            metrics=[keras.metrics.RootMeanSquaredError()],
        )
        return model

    @staticmethod
    def ordenar_features(train, target, features):
        corr_list = []
        for col in features:
            try:
                v = train[[col, target]].dropna()
                if len(v) > 10:
                    r, _ = pearsonr(v[col], v[target])
                    corr_list.append((col, abs(r), r))
                else:
                    corr_list.append((col, 0.0, 0.0))
            except Exception:
                corr_list.append((col, 0.0, 0.0))
        corr_list.sort(key=lambda x: x[1], reverse=True)
        return [c[0] for c in corr_list], corr_list

    def _otimizar_modelos_optuna(self,preprocessor, X, y, mlflow_mgr):
        logger.info("Otimizando hiperparametros com OtimizadorOptuna...")
        otimizador = OtimizadorOptuna(
            preprocessador=preprocessor,
            X=X,
            y=y,
            mlflow_manager=mlflow_mgr,
            n_trials=self.n_trials_optuna,
        )
        factories = {}
        for nome_curto, metodo in self.modelos_optuna_nomes.items():
            factories[nome_curto] = getattr(self.factory, metodo)

        melhores_params, _ = otimizador.otimizar_varios(factories)
        self.optuna_params_otimizados = dict(melhores_params)
        for nome, params in melhores_params.items():
            logger.info("  %s: %s", nome, params)
        return melhores_params

    def executar(
        self,
        train,
        test,
        target_col,
        numeric_features,
        categorical_features,
        otimizar_com_optuna=False,
        otimizar_mlp=False,
        epochs_rede=50,
        batch_size_rede=200,
    ):
        logger.info("=" * 60)
        logger.info("TESTE INCREMENTAL DE FEATURES")
        logger.info("Modelos simples: %s", list(self.modelos_simples.keys()))
        if otimizar_com_optuna:
            logger.info(
                "Modelos Optuna: %s (%d trials)",
                list(self.modelos_optuna_nomes.keys()),
                self.n_trials_optuna,
            )
        if otimizar_mlp:
            logger.info("MLP otimizado: %d trials", self.n_trials_mlp)
        logger.info("Escaladores: %s", list(self.escaladores.keys()))
        logger.info("Features numericas: %d", len(numeric_features))
        logger.info("=" * 60)

        cat_fixas = [c for c in categorical_features if c in train.columns]
        features_ordenadas, corr_list = self.ordenar_features(
            train, target_col, numeric_features
        )
        features_ordenadas = [f for f in features_ordenadas if f in train.columns]

        logger.info("Top 10 features por correlacao:")
        for i, (col, abs_r, r) in enumerate(corr_list[:10], 1):
            logger.info(
                "  %2d. %-35s %s%.4f",
                i,
                col,
                "+" if r >= 0 else "-",
                abs_r,
            )

        try:
            self.mlflow_mgr = MLflowManager(
                nome_experimento=self.experimento_mlflow,
                databricks_workspace_path=f"/Workspace/Users/sehnemjeferson@gmail.com/{self.experimento_mlflow}",

            )
            self.mlflow_mgr.conectar()
        except Exception as e:
            logger.warning("MLflow conexao inicial falhou (tentara novamente depois): %s", e)
            logger.exception("Detalhes da falha MLflow:")

        x_train_columns = train[numeric_features + cat_fixas].copy()
        x_test_columns = test[numeric_features + cat_fixas].copy()
        y_train = train[target_col].values
        y_test = test[target_col].values

        # --- Otimizacao com Optuna (uma vez, full features) ---
        if otimizar_com_optuna and self.modelos_optuna_nomes:
            factory_todas = PreprocessadorFactory(
                numeric_features=features_ordenadas,
                categorical_features=cat_fixas,
            )
            preprocessor_todas = factory_todas.criar()
            X_todas = train[features_ordenadas + cat_fixas].copy()
            y_todas = train[target_col].copy()
            self._otimizar_modelos_optuna(
                preprocessor_todas, X_todas, y_todas, self.mlflow_mgr
            )

        # --- Montar dicionario de modelos efetivos ---
        modelos_efetivos = dict(self.modelos_simples)
        if otimizar_com_optuna and self.optuna_params_otimizados:
            for nome_curto in self.modelos_optuna_nomes:
                modelos_efetivos[nome_curto] = None
        if otimizar_mlp:
            modelos_efetivos["MLP_opt"] = None

        total = (
            len(features_ordenadas)
            * len(self.escaladores)
            * len(modelos_efetivos)
        )
        logger.info(
            "Combinacoes: %d feats x %d scalers x %d modelos = %d",
            len(features_ordenadas),
            len(self.escaladores),
            len(modelos_efetivos),
            total,
        )

        atual = 0
        for n_feats in range(self.feature_start, len(features_ordenadas) + 1):
            feats_num = features_ordenadas[:n_feats]
            cols_ativas = feats_num + cat_fixas
            inicio = time.time()

            X_tr_sel = x_train_columns[cols_ativas].copy()
            X_te_sel = x_test_columns[cols_ativas].copy()

            for esc_name, scaler in self.escaladores.items():
                for mod_name, modelo in modelos_efetivos.items():
                    atual += 1
                    run_name = f"inc_{mod_name}_{n_feats:02d}feats_{esc_name}_{now}"
                    factory_pp = PreprocessadorFactory(
                        numeric_features=feats_num,
                        categorical_features=cat_fixas,
                    )
                    preprocessor = factory_pp.criar(scaler=scaler)

                    try:
                        if mod_name == "RedesNeurais":
                            import keras as _keras

                            input_dim = X_tr_sel.shape[1]
                            rede = self._construir_rede_neural(input_dim)
                            X_tr_proc = preprocessor.fit_transform(X_tr_sel)
                            X_te_proc = preprocessor.transform(X_te_sel)
                            rede.fit(
                                X_tr_proc,
                                y_train,
                                epochs=epochs_rede,
                                batch_size=batch_size_rede,
                                verbose=0,
                            )
                            y_pred = rede.predict(X_te_proc, verbose=0).squeeze()
                            pipe = rede

                        elif mod_name == "MLP_opt" and otimizar_mlp:
                            import optuna
                            import keras

                            X_tr_proc = preprocessor.fit_transform(X_tr_sel)
                            X_te_proc = preprocessor.transform(X_te_sel)
                            input_dim = X_tr_proc.shape[1]

                            X_tr_split, X_val_split, y_tr_split, y_val_split = train_test_split(
                                X_tr_proc, y_train, test_size=0.2, random_state=42
                            )
                            otimizador_mlp = OtimizadorMLP(
                                mlflow_manager=self.mlflow_mgr,
                                target_name=target_col,
                            )
                            study, _ = otimizador_mlp.otimizar(
                                X_train=X_tr_split, y_train=y_tr_split,
                                X_val=X_val_split, y_val=y_val_split,
                                input_dim=input_dim,
                                n_trials=self.n_trials_mlp, epochs=100,
                                nome=run_name,
                            )
                            if study is None:
                                continue
                            model_mlp = OtimizadorMLP.construir_de_trial(
                                optuna.trial.FixedTrial(study.best_params),
                                input_dim,
                            )
                            early_stop = keras.callbacks.EarlyStopping(
                                monitor="loss", patience=10, restore_best_weights=True
                            )
                            model_mlp.fit(
                                X_tr_proc,
                                y_train,
                                epochs=100,
                                batch_size=study.best_params.get("batch_size", 128),
                                callbacks=[early_stop],
                                verbose=0,
                            )
                            y_pred = model_mlp.predict(X_te_proc, verbose=0).ravel()
                            pipe = model_mlp

                        elif (
                            mod_name in self.modelos_optuna_nomes
                            and mod_name in self.optuna_params_otimizados
                        ):
                            import optuna

                            params = self.optuna_params_otimizados[mod_name]
                            trial_fixo = optuna.trial.FixedTrial(params)
                            factory_method_name = self.modelos_optuna_nomes[mod_name]
                            construtor = getattr(self.factory, factory_method_name)
                            modelo_opt = construtor(trial_fixo)
                            pipe = Pipeline(
                                [
                                    ("preprocessador", preprocessor),
                                    ("modelo", modelo_opt),
                                ]
                            )
                            pipe.fit(X_tr_sel, y_train)
                            y_pred = pipe.predict(X_te_sel)
                        else:
                            fit_kwargs = (
                                {"modelo__verbose": 0}
                                if mod_name == "CatBoost"
                                else {}
                            )
                            pipe = Pipeline(
                                [
                                    ("preprocessador", preprocessor),
                                    ("modelo", modelo),
                                ]
                            )
                            pipe.fit(X_tr_sel, y_train, **fit_kwargs)
                            y_pred = pipe.predict(X_te_sel)

                        met = Avaliador.metricas(run_name, y_test, y_pred)
                        self.modelos_treinados[f"{mod_name}_{n_feats}"] = pipe
                        self.predictions[f"{mod_name}_{n_feats}"] = y_pred

                        self.resultados.append(
                            {
                                "n_features": n_feats,
                                "features": "_".join(feats_num),
                                "ultima_feature": feats_num[-1],
                                "escalador": esc_name,
                                "modelo": mod_name,
                                **met,
                            }
                        )

                        if self.mlflow_mgr and met:
                            try:
                                with self.mlflow_mgr.run_session(run_name=run_name):
                                    mlflow.set_tag("teste", "incremental_features")
                                    mlflow.log_param("n_features", n_feats)
                                    mlflow.log_param("ultima_feature", feats_num[-1])
                                    mlflow.log_param("escalador", esc_name)
                                    mlflow.log_param("modelo", mod_name)
                                    mlflow.log_metrics(met)
                                    if hasattr(modelo, "get_params"):
                                        mlflow.log_params(
                                            {
                                                f"modelo__{k}": str(v)[:80]
                                                for k, v in modelo.get_params().items()
                                            }
                                        )
                                    self.mlflow_mgr.log_feature_history(
                                        X_tr_sel, run_name=run_name
                                    )
                            except Exception as e_mlflow:
                                logger.warning("Falha MLflow %s: %s", run_name, e_mlflow)
                                logger.exception("Detalhes:")

                    except Exception as exc:
                        self.resultados.append(
                            {
                                "n_features": n_feats,
                                "features": "_".join(feats_num),
                                "ultima_feature": feats_num[-1],
                                "escalador": esc_name,
                                "modelo": mod_name,
                                "rmse": float("nan"),
                                "mae": float("nan"),
                                "mape": float("nan"),
                                "mdape": float("nan"),
                                "r2": float("nan"),
                            }
                        )
                        logger.warning(
                            "Erro %s %dfeats %s: %s",
                            mod_name,
                            n_feats,
                            esc_name,
                            exc,
                        )

                    dt = time.time() - inicio
                    r2_val = self.resultados[-1].get("r2", float("nan"))
                    r2_str = (
                        f"{r2_val:.4f}"
                        if isinstance(r2_val, (int, float)) and not np.isnan(r2_val)
                        else "FAIL"
                    )
                    sys.stdout.write(
                        f"\r[{atual:3d}/{total}] "
                        f"{n_feats:2d}feats | "
                        f"{esc_name:>8} | "
                        f"{mod_name:>16} | "
                        f"R2={r2_str} | "
                        f"{dt:4.0f}s  "
                    )
                    sys.stdout.flush()

        print()
        logger.info("Teste incremental concluido.")
        return self._resultado_dataframe()

    def testar_tratamentos_modelos_incrementais(
        self,
        train,
        test,
        target_col,
        features_testadas,
        categorical_features,
        n_trials_optuna=0,
        n_trials_mlp=15,
        otimizar_mlp=False,
        epochs_rede=50,
        feature_selection="sequential",
        random_start=3,
        random_limit=10,
        random_seed=42,
        categorical_fixas=None,
        modo="simples",
    ):
        import random as _random
        import optuna
        import mlflow

        if modo == "simples":
            modelos_otimizaveis = {}
            modelos_simples = MODELOS_SIMPLES_TRAT
        elif modo == "optuna":
            modelos_otimizaveis = MODELOS_OTIMIZAVEIS
            modelos_simples = {}
        elif modo == "ambos":
            modelos_otimizaveis = MODELOS_OTIMIZAVEIS
            modelos_simples = MODELOS_SIMPLES_TRAT
        else:
            raise ValueError(f"modo invalido: {modo}")
        qtd_optuna = len(modelos_otimizaveis)
        qtd_simples = len(modelos_simples) + (1 if otimizar_mlp else 0)

        logger.info("=" * 60)
        logger.info("TESTE TRATAMENTOS x MODELOS x FEATURES (incremental defensivo)")
        logger.info("Tratamentos: %d | Modelos: %d (%d Optuna, %d simples%s)",
                    len(TRATAMENTOS), qtd_optuna + qtd_simples,
                    qtd_optuna, qtd_simples,
                    ", +MLP_opt" if otimizar_mlp else "")
        logger.info("Selecao: %s", feature_selection)
        logger.info("Features candidatas: %d", len(features_testadas))
        logger.info("Optuna trials: %d | MLP trials: %d", n_trials_optuna, n_trials_mlp)
        logger.info("=" * 60)

        categorical_fixas_list = list(categorical_fixas or [])
        pool = [f for f in features_testadas + [c for c in categorical_features if c in train.columns and c not in features_testadas]
                if f not in categorical_fixas_list]
        y_train = train[target_col].values
        y_test = test[target_col].values

        try:
            self.mlflow_mgr = MLflowManager(nome_experimento=self.experimento_mlflow)
            self.mlflow_mgr.conectar()
        except Exception as e:
            logger.warning("MLflow conexao inicial falhou (tentara novamente depois): %s", e)
            logger.exception("Detalhes da falha MLflow:")

        resultados = []
        cols_full = categorical_fixas_list + pool
        x_test_full = test[cols_full].copy() if cols_full else test[pool].copy()

        if feature_selection == "sequential":
            all_candidates = categorical_fixas_list + list(pool)
            total = len(all_candidates) * len(TRATAMENTOS) * (qtd_optuna + qtd_simples)
            cont = {"atual": 0}
            colunas_validas = []

            for idx_col, col in enumerate(all_candidates, 1):
                try:
                    colunas_validas.append(col)
                    num_feats = [c for c in colunas_validas if c not in categorical_features]
                    cat_feats = [c for c in colunas_validas if c in categorical_features]
                    X_tr = train[colunas_validas].copy()
                    X_te = x_test_full[colunas_validas].copy()
                except Exception as e:
                    logger.warning("Feature %s falhou na selecao: %s", col, e)
                    colunas_validas.pop(-1)
                    continue

                self._executar_combos_incremento_sync(
                    idx_col, col, cont,
                    TRATAMENTOS, num_feats, cat_feats, X_tr, X_te, y_train, y_test,
                    target_col, modelos_otimizaveis, modelos_simples, len(colunas_validas),
                    n_trials_optuna, n_trials_mlp, otimizar_mlp, epochs_rede,
                    resultados, total,
                )

        elif feature_selection == "random":
            total = (random_limit - random_start + 1) * len(TRATAMENTOS) * (qtd_optuna + qtd_simples)
            cont = {"atual": 0}

            for size in range(random_start, random_limit + 1):
                _random.seed(random_seed + size)
                amostra = _random.sample(pool, min(size, len(pool)))
                colunas_validas = categorical_fixas_list + amostra
                num_feats = [c for c in colunas_validas if c not in categorical_features]
                cat_feats = [c for c in colunas_validas if c in categorical_features]
                X_tr = train[colunas_validas].copy()
                X_te = x_test_full[colunas_validas].copy()

                self._executar_combos_incremento_sync(
                    size, f"random{size}", cont,
                    TRATAMENTOS, num_feats, cat_feats, X_tr, X_te, y_train, y_test,
                    target_col, modelos_otimizaveis, modelos_simples, len(colunas_validas),
                    n_trials_optuna, n_trials_mlp, otimizar_mlp, epochs_rede,
                    resultados, total,
                )

        print()
        df = pd.DataFrame(resultados)
        if not df.empty:
            saida = Path.cwd().parent / "scripts"
            saida.mkdir(parents=True, exist_ok=True)
            df.to_csv(saida / "resultados_tratamentos_modelos.csv", index=False)
            logger.info("Resultados salvos em scripts/resultados_tratamentos_modelos.csv")
        return df

    def _executar_combos_incremento_sync(
        self, idx_col, col, cont,
        tratamentos, num_feats, cat_feats, X_tr, X_te, y_train, y_test,
        target_col, modelos_otimizaveis, modelos_simples, n_features_atual,
        n_trials_optuna, n_trials_mlp, otimizar_mlp, epochs_rede,
        resultados, total,
    ):
        import optuna
        import mlflow

        if not cat_feats:
            vistos = set()
            tratamentos_filtrados = []
            for t in tratamentos:
                key = t["imputer_num"]
                if key not in vistos:
                    vistos.add(key)
                    tratamentos_filtrados.append(t)
        else:
            tratamentos_filtrados = tratamentos

        for trat in tratamentos_filtrados:
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]()
            scaler = trat["scaler"]()
            factory_pp = PreprocessadorFactory(
                numeric_features=num_feats,
                categorical_features=cat_feats,
            )

            for mod_name, factory_fn in modelos_otimizaveis.items():
                cont["atual"] += 1
                run_name = f"{mod_name}|{trat['nome']}|{col}_{idx_col}"
                t0 = time.time()

                met = {}
                best_params = {}
                pp = None
                try:
                    pp = factory_pp.criar(scaler=scaler,
                                          imputer_num=imputer_num,
                                          imputer_cat=imputer_cat,
                                          encoder=encoder)

                    otim = OtimizadorOptuna(
                        preprocessador=pp,
                        X=X_tr,
                        y=y_train,
                        mlflow_manager=self.mlflow_mgr,
                        n_trials=n_trials_optuna,
                        n_folds=3,
                    )
                    estudo = otim.otimizar(run_name, factory_fn)
                    if estudo is None:
                        resultados.append({
                            "n_features": n_features_atual,
                            "ultima_feature": col,
                            "tratamento": trat["nome"],
                            "modelo": mod_name,
                            "status": "failed_no_trials",
                        })
                        continue
                    best_params = estudo.best_params

                    trial_fixo = optuna.trial.FixedTrial(estudo.best_params)
                    modelo_best = factory_fn(trial_fixo)
                    pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
                    pipe.fit(X_tr, y_train)
                    y_pred = pipe.predict(X_te)
                    met = Avaliador.metricas(run_name, y_test, y_pred)
                except Exception as exc:
                    logger.warning("Falha optuna %s %s %s: %s", mod_name, trat["nome"], col, exc)
                    logger.exception("Traceback completo:")

                resultados.append({
                    "n_features": n_features_atual,
                    "ultima_feature": col,
                    "tratamento": trat["nome"],
                    "modelo": mod_name,
                    **met,
                })

                if self.mlflow_mgr and met:
                    try:
                        with self.mlflow_mgr.run_session(run_name=run_name):
                            mlflow.set_tag("teste", "tratamentos_modelos")
                            mlflow.log_param("tratamento", trat["nome"])
                            mlflow.log_param("modelo", mod_name)
                            mlflow.log_param("n_features", n_features_atual)
                            mlflow.log_param("ultima_feature", col)
                            if best_params:
                                mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in best_params.items()})
                            mlflow.log_metrics(met)
                            self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                    except Exception as e_mlflow:
                        logger.warning("Falha MLflow %s: %s", run_name, e_mlflow)
                        logger.exception("Detalhes:")

                dt = time.time() - t0
                r2v = resultados[-1].get("r2", float("nan"))
                r2s = f"{r2v:.4f}" if isinstance(r2v, (int, float)) and not np.isnan(r2v) else "FAIL"
                sys.stdout.write(f"\r[{cont['atual']:4d}/{total}] {n_features_atual:2d}feats {trat['nome']:>18} {mod_name:>18} R2={r2s} {dt:4.0f}s")
                sys.stdout.flush()

            for mod_name, modelo_factory in modelos_simples.items():
                cont["atual"] += 1
                run_name = f"{mod_name}|{trat['nome']}|{col}_{idx_col}"
                t0 = time.time()

                met = {}
                try:
                    pp = factory_pp.criar(scaler=scaler,
                                          imputer_num=imputer_num,
                                          imputer_cat=imputer_cat,
                                          encoder=encoder)
                    pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_factory())])
                    pipe.fit(X_tr, y_train)
                    y_pred = pipe.predict(X_te)
                    met = Avaliador.metricas(run_name, y_test, y_pred)
                except Exception as exc:
                    logger.warning("Falha simples %s %s %s: %s", mod_name, trat["nome"], col, exc)
                    logger.exception("Traceback completo:")

                resultados.append({
                    "n_features": n_features_atual,
                    "ultima_feature": col,
                    "tratamento": trat["nome"],
                    "modelo": mod_name,
                    **met,
                })

                if self.mlflow_mgr and met:
                    try:
                        with self.mlflow_mgr.run_session(run_name=run_name):
                            mlflow.set_tag("teste", "tratamentos_modelos")
                            mlflow.log_param("tratamento", trat["nome"])
                            mlflow.log_param("modelo", mod_name)
                            mlflow.log_param("n_features", n_features_atual)
                            mlflow.log_param("ultima_feature", col)
                            mlflow.log_metrics(met)
                            self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                    except Exception as e_mlflow:
                        logger.warning("Falha MLflow %s: %s", run_name, e_mlflow)
                        logger.exception("Detalhes:")

                dt = time.time() - t0
                r2v = resultados[-1].get("r2", float("nan"))
                r2s = f"{r2v:.4f}" if isinstance(r2v, (int, float)) and not np.isnan(r2v) else "FAIL"
                sys.stdout.write(f"\r[{cont['atual']:4d}/{total}] {n_features_atual:2d}feats {trat['nome']:>18} {mod_name:>18} R2={r2s} {dt:4.0f}s")
                sys.stdout.flush()

            if otimizar_mlp:
                mod_name = "MLP_opt"
                cont["atual"] += 1
                run_name = f"{mod_name}|{trat['nome']}|{col}_{idx_col}"
                t0 = time.time()

                met = {}
                best_params = {}
                try:
                    pp_mlp_inc = PreprocessadorFactory(
                        numeric_features=num_feats,
                        categorical_features=cat_feats,
                    ).criar(scaler=scaler, imputer_num=imputer_num, imputer_cat=imputer_cat, encoder=encoder)

                    X_tr_proc = pp_mlp_inc.fit_transform(X_tr)
                    X_te_proc = pp_mlp_inc.transform(X_te)
                    input_dim = X_tr_proc.shape[1]
                    if input_dim == 0:
                        logger.warning("input_dim=0 MLP %s %s %s", mod_name, trat["nome"], col)
                        continue

                    X_tr_split, X_val_split, y_tr_split, y_val_split = train_test_split(
                        X_tr_proc, y_train, test_size=0.2, random_state=42
                    )
                    otimizador_mlp = OtimizadorMLP(
                        mlflow_manager=self.mlflow_mgr,
                        target_name=target_col,
                    )
                    study, _ = otimizador_mlp.otimizar(
                        X_train=X_tr_split, y_train=y_tr_split,
                        X_val=X_val_split, y_val=y_val_split,
                        input_dim=input_dim,
                        n_trials=n_trials_mlp, epochs=100,
                        nome=run_name,
                    )
                    if study is None:
                        resultados.append({
                            "n_features": n_features_atual,
                            "ultima_feature": col,
                            "tratamento": trat["nome"],
                            "modelo": "MLP_opt",
                            "status": "failed_no_trials",
                        })
                        continue
                    best_params = study.best_params
                    model_mlp = OtimizadorMLP.construir_de_trial(
                        optuna.trial.FixedTrial(study.best_params),
                        input_dim,
                    )
                    import keras
                    early_stop = keras.callbacks.EarlyStopping(
                        monitor="loss", patience=10, restore_best_weights=True
                    )
                    model_mlp.fit(
                        X_tr_proc, y_train,
                        epochs=100,
                        batch_size=study.best_params.get("batch_size", 128),
                        callbacks=[early_stop], verbose=0,
                    )
                    y_pred = model_mlp.predict(X_te_proc, verbose=0).ravel()
                    met = Avaliador.metricas(run_name, y_test, y_pred)
                except Exception as exc:
                    logger.warning("Falha MLP %s %s: %s", trat["nome"], col, exc)
                    logger.exception("Traceback completo:")

                resultados.append({
                    "n_features": n_features_atual,
                    "ultima_feature": col,
                    "tratamento": trat["nome"],
                    "modelo": mod_name,
                    **met,
                })

                if self.mlflow_mgr and met:
                    try:
                        with self.mlflow_mgr.run_session(run_name=run_name):
                            mlflow.set_tag("teste", "tratamentos_modelos")
                            mlflow.log_param("tratamento", trat["nome"])
                            mlflow.log_param("modelo", mod_name)
                            mlflow.log_param("n_features", n_features_atual)
                            mlflow.log_param("ultima_feature", col)
                            if best_params:
                                mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in best_params.items()})
                            mlflow.log_metrics(met)
                            self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                    except Exception as e_mlflow:
                        logger.warning("Falha MLflow %s: %s", run_name, e_mlflow)
                        logger.exception("Detalhes:")

                dt = time.time() - t0
                r2v = resultados[-1].get("r2", float("nan"))
                r2s = f"{r2v:.4f}" if isinstance(r2v, (int, float)) and not np.isnan(r2v) else "FAIL"
                sys.stdout.write(f"\r[{cont['atual']:4d}/{total}] {n_features_atual:2d}feats {trat['nome']:>18} {mod_name:>18} R2={r2s} {dt:4.0f}s")
                sys.stdout.flush()

    def _resultado_dataframe(self):
        df = pd.DataFrame(self.resultados)
        if not df.empty:
            saida = Path.cwd().parent / "scripts"
            saida.mkdir(parents=True, exist_ok=True)
            df.to_csv(saida / "resultados_incremental_src.csv", index=False)
        return df


def resumo(resultados_df):
    """Exibe sumario dos melhores resultados."""
    if resultados_df is None or resultados_df.empty:
        logger.warning("Nenhum resultado disponivel.")
        return
    df_ok = resultados_df.dropna(subset=["r2"])
    if df_ok.empty:
        logger.warning("Nenhum resultado valido.")
        return

    logger.info("")
    logger.info("=" * 60)
    logger.info("MELHOR RESULTADO GERAL")
    melhor = df_ok.loc[df_ok["r2"].idxmax()]
    logger.info(
        "  %s | %d features | escalador=%s | R2=%.4f | RMSE=%.0f",
        melhor["modelo"],
        int(melhor["n_features"]),
        melhor["escalador"],
        melhor["r2"],
        melhor["rmse"],
    )

    logger.info("")
    logger.info("MELHOR POR MODELO:")
    for mod in sorted(df_ok["modelo"].unique()):
        sub = df_ok[df_ok["modelo"] == mod]
        best = sub.loc[sub["r2"].idxmax()]
        logger.info(
            "  %20s: %2d feats | R2=%.4f | escalador=%s",
            mod,
            int(best["n_features"]),
            best["r2"],
            best["escalador"],
        )

    logger.info("")
    logger.info("EVOLUCAO R2 POR N_DE_FEATURES:")
    evol = (
        df_ok.groupby("n_features")["r2"]
        .agg(["mean", "max", "std"])
        .reset_index()
    )
    for _, row in evol.iterrows():
        logger.info(
            "  %2d features -> R2 medio=%.4f | max=%.4f | std=%.4f",
            int(row["n_features"]),
            row["mean"],
            row["max"],
            row["std"],
        )

    return df_ok
