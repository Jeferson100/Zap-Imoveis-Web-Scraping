import asyncio
import logging
import os
import time
import sys
import warnings
from pathlib import Path
from functools import partial

import numpy as np
import pandas as pd
from scipy.stats import pearsonr
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.neighbors import KNeighborsRegressor
from sklearn.svm import SVR
from catboost import CatBoostRegressor
from sklearn.preprocessing import (
    StandardScaler, RobustScaler, MinMaxScaler,
    QuantileTransformer, PowerTransformer, OrdinalEncoder, OneHotEncoder,
)
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split, cross_validate
from sklearn.metrics import make_scorer
from otimizador_optuna import _mdape, _rmsle

from preprocessador import PreprocessadorFactory, Avaliador
from mlflow_manager import MLflowManager
from otimizador_optuna import (
    OtimizadorOptuna,
    FactoryModelos,
    OtimizadorMLP,
)

import optuna
import mlflow
import mlflow.data

try:
    import shap
except ImportError:
    shap = None

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MAX_CONCURRENT = 10

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

MODELOS_OTIMIZAVEIS = {
    "Ridge_opt":        FactoryModelos().ridge,
    "RandomForest_opt": FactoryModelos().random_forest,
    "GradientBoosting_opt": FactoryModelos().gradient_boosting,
    "KNN_opt":          FactoryModelos().knn,
    #"SVR_opt":          FactoryModelos().svr,
    "CatBoost_opt":     FactoryModelos().catboost,
    "LightGBM_opt":     FactoryModelos().lightgbm,
    "HistGB_opt":       FactoryModelos().hist_gb,
}

MODELOS_SIMPLES_TRAT = {
    #"Linear": lambda: LinearRegression(),
    #"Ridge": lambda: Ridge(),
    "DecisionTree": lambda: DecisionTreeRegressor(random_state=42),
    "RandomForest": lambda: RandomForestRegressor(
        n_estimators=200, max_depth=12, random_state=42, n_jobs=-1
    ),
    "GradientBoosting": lambda: GradientBoostingRegressor(
        n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42
    ),
    #"KNeighbors": lambda: KNeighborsRegressor(n_jobs=-1),
    #"SVR": lambda: SVR(kernel="rbf"),
    "CatBoost": lambda: CatBoostRegressor(verbose=0, random_seed=42),
    "MLP": None,
}

SCALE_INVARIANT = {
    "Linear", "Ridge", "DecisionTree",
    "RandomForest", "GradientBoosting", "CatBoost",
    "Ridge_opt", "RandomForest_opt", "GradientBoosting_opt",
}

now = time.strftime("%Y-%m")


def _agregar_importancias_por_feature(importances, preprocessor, feat_names):
    """Agrega importancias SHAP de colunas OHE de volta pra feature original."""
    trans_names = preprocessor.get_feature_names_out()
    agg = {f: 0.0 for f in feat_names}
    for i, tn in enumerate(trans_names):
        stem = tn.split('__', 1)[-1] if '__' in tn else tn
        for fn in feat_names:
            if stem == fn or (stem.startswith(fn + '_') and fn):
                agg[fn] += importances[i]
                break
        else:
            agg[feat_names[i % len(feat_names)]] += importances[i]
    return np.array([agg[f] for f in feat_names])


class TesteIncrementalFeaturesAsync:
    """Versao assincrona do teste incremental de features com modelos."""

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
        "CatBoost": CatBoostRegressor(verbose=0, random_seed=42),
    }

    ESCALADORES_PADRAO = {
        "raw": None,
        "standard": StandardScaler(),
        "robust": RobustScaler(),
        "minmax": MinMaxScaler(),
    }

    TRANSFORM_OPCOES = {
        "none": None,
        "log": "log",
        "sqrt": "sqrt",
        "boxcox": "boxcox",
        "yeojohnson": "yeojohnson",
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
        n_trials_optuna=5,
        n_trials_mlp=15,
        usar_xgboost=True,
        usar_rede_neural=True,
        usar_mlp_otimizado=True,
        feature_start=1,
        experimento_mlflow="teste-incremental-features",
        log_level=logging.INFO,
        max_samples=None,
        target_log=False,
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
        self.max_samples = max_samples
        self.optuna_params_otimizados = {}
        self.usar_mlp_otimizado = usar_mlp_otimizado
        self.target_log = target_log

        if usar_xgboost:
            self._tentar_adicionar_xgboost()
        if usar_rede_neural:
            self.modelos_simples["RedesNeurais"] = None

        self.resultados = []
        self.modelos_treinados = {}
        self.predictions = {}
        self.mlflow_mgr = None
        self.factory = FactoryModelos()

    # ─── helpers sync (reaproveitados da versao sync) ───────────────

    def _tentar_adicionar_xgboost(self):
        try:
            from xgboost import XGBRegressor
            self.modelos_simples["XGBoost"] = XGBRegressor(
                n_estimators=200, max_depth=8, learning_rate=0.1,
                random_state=42, n_jobs=-1, verbosity=0,
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
            optimizer="adam", loss="mse",
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

    @staticmethod
    def _build_transform_map(num_feats, cat_feats, transf_name, encoder_name="ohe"):
        import json
        fmap = {}
        for f in (num_feats or []):
            fmap[str(f)] = str(transf_name or "none")
        for f in (cat_feats or []):
            fmap[str(f)] = str(encoder_name)
        return json.dumps(fmap, default=str)

    @staticmethod
    def _shap_order_por_combo(X_tr_proc, X_te_proc, y_train, feat_names,
                               preprocessor=None, shap_sample=500):
        if shap is None:
            return list(feat_names)
        import xgboost as xgb

        n_tr = min(shap_sample, len(X_tr_proc))
        idx_tr = np.random.RandomState(42).choice(len(X_tr_proc), n_tr, replace=False)
        X_tr_s = X_tr_proc[idx_tr] if isinstance(X_tr_proc, np.ndarray) else X_tr_proc.iloc[idx_tr]
        y_tr_s = y_train.iloc[idx_tr] if hasattr(y_train, 'iloc') else y_train[idx_tr]

        n_te = min(shap_sample, len(X_te_proc))
        idx_te = np.random.RandomState(42).choice(len(X_te_proc), n_te, replace=False)
        X_te_s = X_te_proc[idx_te] if isinstance(X_te_proc, np.ndarray) else X_te_proc.iloc[idx_te]

        model = xgb.XGBRegressor(n_estimators=100, max_depth=6,
                                 random_state=42, verbosity=0)
        model.fit(X_tr_s, y_tr_s)
        explainer = shap.Explainer(model, X_te_s)
        importances = np.abs(explainer(X_te_s).values).mean(axis=0)

        # Agrega importancias OHE de volta para as features originais
        if preprocessor is not None and len(importances) != len(feat_names):
            try:
                importances = _agregar_importancias_por_feature(
                    importances, preprocessor, feat_names
                )
            except Exception as exc:
                logger.warning("Falha ao agregar SHAP: %s", exc)

        return [feat_names[i] for i in np.argsort(importances)[::-1]]

    def _otimizar_modelos_optuna(self, preprocessor, X, y, mlflow_mgr, log_trials=False):
        logger.info("Otimizando hiperparametros com OtimizadorOptuna...")
        otimizador = OtimizadorOptuna(
            preprocessador=preprocessor, X=X, y=y,
            mlflow_manager=mlflow_mgr, n_trials=self.n_trials_optuna,
        )
        factories = {}
        for nome_curto, metodo in self.modelos_optuna_nomes.items():
            factories[nome_curto] = getattr(self.factory, metodo)
        melhores_params, _ = otimizador.otimizar_varios(factories, log_trials=log_trials)
        self.optuna_params_otimizados = dict(melhores_params)
        for nome, params in melhores_params.items():
            logger.info("  %s: %s", nome, params)
        return melhores_params

    def _resultado_dataframe(self):
        df = pd.DataFrame(self.resultados)
        if not df.empty:
            saida = Path.cwd().parent / "scripts"
            saida.mkdir(parents=True, exist_ok=True)
            df.to_csv(saida / "resultados_incremental_src_async.csv", index=False)
        return df

    # ─── conexao MLflow async ───────────────────────────────────────

    async def _conectar_mlflow_async(self):
        loop = asyncio.get_event_loop()
        try:
            self.mlflow_mgr = MLflowManager(
                nome_experimento=self.experimento_mlflow,
                databricks_workspace_path=(
                    f"/Workspace/Users/sehnemjeferson@gmail.com/{self.experimento_mlflow}"
                ),
            )
            await asyncio.wait_for(
                loop.run_in_executor(None, self.mlflow_mgr.conectar), timeout=60
            )
        except Exception as e:
            logger.warning("MLflow conexao inicial falhou (tentara novamente depois): %s", e)
            logger.exception("Detalhes da falha MLflow:")

    # ─── executar_async ─────────────────────────────────────────────

    async def executar_async(
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
        max_concurrent=MAX_CONCURRENT,
    ):
        logger.info("=" * 60)
        logger.info("TESTE INCREMENTAL DE FEATURES (async)")
        logger.info("Modelos simples: %s", list(self.modelos_simples.keys()))
        if otimizar_com_optuna:
            logger.info("Modelos Optuna: %s (%d trials)",
                        list(self.modelos_optuna_nomes.keys()), self.n_trials_optuna)
        if otimizar_mlp:
            logger.info("MLP otimizado: %d trials", self.n_trials_mlp)
        logger.info("Escaladores: %s", list(self.escaladores.keys()))
        logger.info("Features numericas: %d", len(numeric_features))
        logger.info("Max concurrent: %d", max_concurrent)
        logger.info("=" * 60)

        cat_fixas = [c for c in categorical_features if c in train.columns]
        features_ordenadas, corr_list = self.ordenar_features(
            train, target_col, numeric_features
        )
        features_ordenadas = [f for f in features_ordenadas if f in train.columns]

        logger.info("Top 10 features por correlacao:")
        for i, (col, abs_r, r) in enumerate(corr_list[:10], 1):
            logger.info("  %2d. %-35s %s%.4f", i, col, "+" if r >= 0 else "-", abs_r)

        await self._conectar_mlflow_async()

        x_train_columns = train[numeric_features + cat_fixas].copy()
        x_test_columns = test[numeric_features + cat_fixas].copy()
        y_train = train[target_col].values
        y_test = test[target_col].values

        loop = asyncio.get_event_loop()

        if otimizar_com_optuna and self.modelos_optuna_nomes:
            factory_todas = PreprocessadorFactory(
                numeric_features=features_ordenadas,
                categorical_features=cat_fixas,
            )
            preprocessor_todas = factory_todas.criar()
            X_todas = train[features_ordenadas + cat_fixas].copy()
            y_todas = train[target_col].copy()
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    partial(self._otimizar_modelos_optuna, preprocessor_todas, X_todas, y_todas, self.mlflow_mgr),
                ), timeout=600
            )

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
        logger.info("Combinacoes: %d feats x %d scalers x %d modelos = %d",
                    len(features_ordenadas), len(self.escaladores), len(modelos_efetivos), total)

        max_workers = min(max_concurrent, os.cpu_count() or 4)
        sem = asyncio.Semaphore(max_workers)
        progresso = {"atual": 0}
        lock = asyncio.Lock()

        for n_feats in range(self.feature_start, len(features_ordenadas) + 1):
            feats_num = features_ordenadas[:n_feats]
            cols_ativas = feats_num + cat_fixas

            X_tr_sel = x_train_columns[cols_ativas].copy()
            X_te_sel = x_test_columns[cols_ativas].copy()

            combos = []
            for esc_name, scaler in self.escaladores.items():
                for transf_name, transf_val in self.TRANSFORM_OPCOES.items():
                    for mod_name, modelo in modelos_efetivos.items():
                        combos.append((esc_name, scaler, transf_name, mod_name, modelo))

            async def executar_combo(args):
                esc_name, scaler, transf_name, mod_name, modelo = args
                async with sem:
                    run_name = f"inc_{mod_name}_{n_feats:02d}feats_{esc_name}_{now}"
                    t0 = time.time()

                    try:
                        if transf_name == "boxcox" and feats_num and X_tr_sel[feats_num].min().min() <= 0:
                            transf_name = "yeojohnson"
                        factory_pp = PreprocessadorFactory(
                            numeric_features=feats_num,
                            categorical_features=cat_fixas,
                        )
                        preprocessor = factory_pp.criar(scaler=scaler, transform=transf_name)

                        cv_scoring = {
                            "rmse": "neg_root_mean_squared_error",
                            "mae": "neg_mean_absolute_error",
                            "mape": "neg_mean_absolute_percentage_error",
                            "mdape": make_scorer(_mdape, greater_is_better=False),
                            "r2": "r2",
                            "rmsle": make_scorer(_rmsle, greater_is_better=False),
                        }

                        if mod_name == "RedesNeurais":
                            def _treinar_rede():
                                import keras as _keras
                                input_dim = X_tr_sel.shape[1]
                                rede = self._construir_rede_neural(input_dim)
                                X_tr_proc = preprocessor.fit_transform(X_tr_sel)
                                X_te_proc = preprocessor.transform(X_te_sel)
                                rede.fit(X_tr_proc, y_train, epochs=epochs_rede,
                                         batch_size=batch_size_rede, verbose=0)
                                y_pred = rede.predict(X_te_proc, verbose=0).squeeze()
                                return y_pred, {}
                            y_pred, cv_met_inline = await asyncio.wait_for(
                                loop.run_in_executor(None, _treinar_rede), timeout=600
                            )

                        elif mod_name == "MLP_opt" and otimizar_mlp:
                            def _treinar_mlp_opt():
                                import keras
                                X_tr_proc = preprocessor.fit_transform(X_tr_sel)
                                X_te_proc = preprocessor.transform(X_te_sel)
                                input_dim = X_tr_proc.shape[1]

                                X_tr_s, X_val_s, y_tr_s, y_val_s = train_test_split(
                                    X_tr_proc, y_train, test_size=0.2, random_state=42
                                )
                                otim_mlp = OtimizadorMLP(
                                    mlflow_manager=self.mlflow_mgr,
                                    target_name=target_col,
                                )
                                study, _ = otim_mlp.otimizar(
                                    X_train=X_tr_s, y_train=y_tr_s,
                                    X_val=X_val_s, y_val=y_val_s,
                                    input_dim=input_dim,
                                    n_trials=self.n_trials_mlp, epochs=100,
                                    nome=run_name, log_trials=False,
                                )
                                model_mlp = OtimizadorMLP.construir_de_trial(
                                    optuna.trial.FixedTrial(study.best_params), input_dim,
                                )
                                early_stop = keras.callbacks.EarlyStopping(
                                    monitor="loss", patience=10, restore_best_weights=True
                                )
                                model_mlp.fit(X_tr_proc, y_train, epochs=100,
                                              batch_size=study.best_params.get("batch_size", 128),
                                              callbacks=[early_stop], verbose=0)
                                y_pred = model_mlp.predict(X_te_proc, verbose=0).ravel()
                                return y_pred, {}
                            y_pred, cv_met_inline = await asyncio.wait_for(
                                loop.run_in_executor(None, _treinar_mlp_opt), timeout=600
                            )

                        elif (
                            mod_name in self.modelos_optuna_nomes
                            and mod_name in self.optuna_params_otimizados
                        ):
                            def _treinar_optuna():
                                params = self.optuna_params_otimizados[mod_name]
                                trial_fixo = optuna.trial.FixedTrial(params)
                                factory_method_name = self.modelos_optuna_nomes[mod_name]
                                construtor = getattr(self.factory, factory_method_name)
                                modelo_opt = construtor(trial_fixo)
                                pipe = Pipeline([
                                    ("preprocessador", preprocessor),
                                    ("modelo", modelo_opt),
                                ])
                                pipe.fit(X_tr_sel, y_train)
                                y_pred = pipe.predict(X_te_sel)
                                cv_scores = cross_validate(pipe, X_tr_sel, y_train, cv=3, scoring=cv_scoring, n_jobs=1)
                                cv_met = {
                                    "cv_rmse": -cv_scores["test_rmse"].mean(),
                                    "cv_mae": -cv_scores["test_mae"].mean(),
                                    "cv_mape": -cv_scores["test_mape"].mean(),
                                    "cv_mdape": -cv_scores["test_mdape"].mean(),
                                    "cv_r2": cv_scores["test_r2"].mean(),
                                    "cv_rmsle": -cv_scores["test_rmsle"].mean(),
                                }
                                return y_pred, cv_met
                            y_pred, cv_met_inline = await asyncio.wait_for(
                                loop.run_in_executor(None, _treinar_optuna), timeout=600
                            )

                        else:
                            def _treinar_simples():
                                fit_kw = (
                                    {"modelo__verbose": 0}
                                    if mod_name == "CatBoost" else {}
                                )
                                pipe = Pipeline([
                                    ("preprocessador", preprocessor),
                                    ("modelo", modelo),
                                ])
                                pipe.fit(X_tr_sel, y_train, **fit_kw)
                                y_pred = pipe.predict(X_te_sel)
                                cv_scores = cross_validate(pipe, X_tr_sel, y_train, cv=3, scoring=cv_scoring, n_jobs=1)
                                cv_met = {
                                    "cv_rmse": -cv_scores["test_rmse"].mean(),
                                    "cv_mae": -cv_scores["test_mae"].mean(),
                                    "cv_mape": -cv_scores["test_mape"].mean(),
                                    "cv_mdape": -cv_scores["test_mdape"].mean(),
                                    "cv_r2": cv_scores["test_r2"].mean(),
                                    "cv_rmsle": -cv_scores["test_rmsle"].mean(),
                                }
                                return y_pred, cv_met
                            y_pred, cv_met_inline = await asyncio.wait_for(
                                loop.run_in_executor(None, _treinar_simples), timeout=600
                            )

                        met = Avaliador.metricas(run_name, y_test, y_pred)
                        met_all = {**met, **cv_met_inline}

                        if self.mlflow_mgr:
                            await asyncio.wait_for(
                                loop.run_in_executor(None, self._log_executar_resultado,
                                                       run_name, n_feats, feats_num[-1],
                                                       esc_name, mod_name, met_all, modelo, X_tr_sel,
                                                       transf_name, feats_num, cat_fixas,
                                                       y_train, X_te_sel, y_test),
                                timeout=60
                            )

                        return {
                            "n_features": n_feats,
                            "features": "_".join(feats_num),
                            "ultima_feature": feats_num[-1],
                            "escalador": esc_name,
                            "modelo": mod_name,
                            **cv_met_inline,
                            **met,
                        }

                    except Exception as exc:
                        logger.warning("Erro %s %dfeats %s: %s", mod_name, n_feats, esc_name, exc)
                        return {
                            "n_features": n_feats,
                            "features": "_".join(feats_num),
                            "ultima_feature": feats_num[-1],
                            "escalador": esc_name,
                            "modelo": mod_name,
                            "rmse": float("nan"), "mae": float("nan"),
                            "mape": float("nan"), "mdape": float("nan"), "r2": float("nan"),
                            "rmsle": float("nan"),
                        }

            tasks = [executar_combo(c) for c in combos]
            for coro in asyncio.as_completed(tasks):
                resultado = await coro
                self.resultados.append(resultado)
                async with lock:
                    progresso["atual"] += 1
                r2v = resultado.get("r2", float("nan"))
                r2s = f"{r2v:.4f}" if isinstance(r2v, (int, float)) and not np.isnan(r2v) else "FAIL"
                sys.stdout.write(
                    f"\r[{progresso['atual']:3d}/{total}] "
                    f"{n_feats:2d}feats | {resultado.get('escalador', ''):>8} | "
                    f"{resultado.get('modelo', ''):>16} | R2={r2s}  "
                )
                sys.stdout.flush()

        print()
        logger.info("Teste incremental concluido.")
        return self._resultado_dataframe()

    def _log_executar_resultado(self, run_name, n_feats, ultima_feature,
                                 esc_name, mod_name, met, modelo, X_tr_sel,
                                 transf_name="none", feats_num=None, cat_fixas=None,
                                 y_train=None, X_te_sel=None, y_test=None):
        try:
            with self.mlflow_mgr.run_session(run_name=run_name):
                mlflow.set_tag("teste", "incremental_features")
                mlflow.log_param("n_features", n_feats)
                mlflow.log_param("ultima_feature", ultima_feature)
                mlflow.log_param("escalador", esc_name)
                mlflow.log_param("modelo", mod_name)
                mlflow.log_param("transform", transf_name)
                if feats_num or cat_fixas:
                    mlflow.set_tag("feature_transform_map",
                                   self._build_transform_map(feats_num, cat_fixas, transf_name))
                if y_train is not None and X_te_sel is not None and y_test is not None:
                    train_df = pd.concat([X_tr_sel.reset_index(drop=True),
                                          pd.Series(y_train, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                    test_df = pd.concat([X_te_sel.reset_index(drop=True),
                                         pd.Series(y_test, name="target")], axis=1)
                    mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                mlflow.log_metrics(met)
                if hasattr(modelo, "get_params"):
                    mlflow.log_params({
                        f"modelo__{k}": str(v)[:80] for k, v in modelo.get_params().items()
                    })
                self.mlflow_mgr.log_feature_history(X_tr_sel, run_name=run_name)
        except Exception as e_mlflow:
            logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
            logger.exception("Detalhes:")

    # ─── testar_tratamentos_modelos_incrementais_async ──────────────

    async def testar_tratamentos_modelos_incrementais_async(
        self,
        train,
        test,
        target_col,
        features_testadas,
        categorical_features,
        n_trials_optuna=0,
        n_trials_mlp=15,
        otimizar_mlp=False,
        max_concurrent=MAX_CONCURRENT,
        feature_selection="sequential",
        random_start=3,
        random_limit=10,
        random_seed=42,
        categorical_fixas=None,
        modo="simples",
        cidade="joinville",
    ):
        import random as _random
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
        logger.info("TESTE TRATAMENTOS x MODELOS x FEATURES (async)")
        logger.info("Tratamentos: %d | Modelos: %d (%d Optuna, %d simples%s)",
                    len(TRATAMENTOS), qtd_optuna + qtd_simples,
                    qtd_optuna, qtd_simples,
                    ", +MLP_opt" if otimizar_mlp else "")
        logger.info("Selecao: %s", feature_selection)
        logger.info("Features candidatas: %d", len(features_testadas))
        logger.info("Optuna trials: %d | MLP trials: %d", n_trials_optuna, n_trials_mlp)
        logger.info("Max concurrent: %d", max_concurrent)
        logger.info("=" * 60)

        # Amostragem se dados forem muito grandes
        if self.max_samples is not None and len(train) > self.max_samples:
            ratio = self.max_samples / len(train)
            n_test = max(1, int(len(test) * ratio))
            logger.info("Amostrando treino: %d -> %d", len(train), self.max_samples)
            train = train.sample(n=self.max_samples, random_state=42)
            logger.info("Amostrando teste: %d -> %d", len(test), n_test)
            test = test.sample(n=n_test, random_state=42)

        categorical_fixas_list = list(categorical_fixas or [])
        pool = [f for f in features_testadas + [c for c in categorical_features if c in train.columns and c not in features_testadas]
                if f not in categorical_fixas_list]
        y_train = train[target_col].values
        y_test = test[target_col].values

        await self._conectar_mlflow_async()

        resultados = []
        progresso = {"atual": 0}
        lock = asyncio.Lock()
        max_workers = min(max_concurrent, os.cpu_count() or 4)
        sem = asyncio.Semaphore(max_workers)
        sem_mlp = asyncio.Semaphore(min(2, max_workers))
        loop = asyncio.get_event_loop()
        cols_full = categorical_fixas_list + pool
        x_test_full = test[cols_full].copy() if cols_full else test[pool].copy()

        if feature_selection == "shap":
            n_transf = len(self.TRANSFORM_OPCOES)
            n_modelos = qtd_optuna + qtd_simples
            total = len(TRATAMENTOS) * n_transf * len(pool) * n_modelos
            for trat in TRATAMENTOS:
                for transf_name in self.TRANSFORM_OPCOES:
                    num_feats = [c for c in pool if c not in categorical_features]
                    cat_feats = [c for c in pool if c in categorical_features]
                    cols_full = categorical_fixas_list + num_feats + cat_feats

                    _transf = transf_name
                    if _transf == "boxcox" and num_feats and train[num_feats].min().min() <= 0:
                        _transf = "yeojohnson"

                    factory_pp = PreprocessadorFactory(
                        numeric_features=num_feats,
                        categorical_features=cat_feats,
                    )
                    pp = factory_pp.criar(
                        scaler=trat["scaler"](),
                        transform=_transf,
                    )
                    X_tr_p = pp.fit_transform(train[cols_full], y_train)
                    X_te_p = pp.transform(x_test_full[cols_full])

                    ordem = self._shap_order_por_combo(
                        X_tr_p, X_te_p, y_train,
                        num_feats + cat_feats,
                        preprocessor=pp,
                    )

                    colunas_validas = list(categorical_fixas_list)
                    for idx_col, col in enumerate(ordem, 1):
                        colunas_validas.append(col)
                        num_inc = [c for c in colunas_validas
                                   if c not in categorical_features]
                        cat_inc = [c for c in colunas_validas
                                   if c in categorical_features]
                        X_tr_inc = train[colunas_validas].copy()
                        X_te_inc = x_test_full[colunas_validas].copy()

                        await self._rodar_combos_incremento(
                            loop, sem, lock, progresso, total,
                            idx_col, col,
                            tratamentos=[trat],
                            num_feats=num_inc, cat_feats=cat_inc,
                            X_tr=X_tr_inc, X_te=X_te_inc,
                            y_train=y_train, y_test=y_test,
                            target_col=target_col,
                            modelos_otimizaveis=modelos_otimizaveis,
                            modelos_simples=modelos_simples,
                            n_features_atual=len(colunas_validas),
                            n_trials_optuna=n_trials_optuna,
                            n_trials_mlp=n_trials_mlp,
                            otimizar_mlp=otimizar_mlp,
                            resultados=resultados,
                            run_name_base=f"{trat['nome']}|{transf_name}",
                            transf_unica=transf_name,
                        )
        elif feature_selection == "sequential":
            all_candidates = categorical_fixas_list + list(pool)
            n_transf = len(self.TRANSFORM_OPCOES)
            total = len(all_candidates) * len(TRATAMENTOS) * n_transf * (qtd_optuna + qtd_simples)
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

                logger.debug("Incremento %d/%d: %d features [%s ...]",
                             idx_col, len(all_candidates), len(colunas_validas),
                             colunas_validas[0] if colunas_validas else "")
                n_features_atual = len(colunas_validas)
                await self._rodar_combos_incremento(
                    loop, sem, lock, progresso, total, idx_col, col,
                    sem_mlp=sem_mlp,
                    tratamentos=TRATAMENTOS, num_feats=num_feats, cat_feats=cat_feats,
                    X_tr=X_tr, X_te=X_te, y_train=y_train, y_test=y_test,
                    target_col=target_col, modelos_otimizaveis=modelos_otimizaveis,
                    modelos_simples=modelos_simples, n_features_atual=n_features_atual,
                    n_trials_optuna=n_trials_optuna, n_trials_mlp=n_trials_mlp,
                    otimizar_mlp=otimizar_mlp, resultados=resultados,
                    run_name_base=col,
                )
        elif feature_selection == "random":
            n_transf = len(self.TRANSFORM_OPCOES)
            total = (random_limit - random_start + 1) * len(TRATAMENTOS) * n_transf * (qtd_optuna + qtd_simples)

            for size in range(random_start, random_limit + 1):
                _random.seed(random_seed + size)
                amostra = _random.sample(pool, min(size, len(pool)))
                colunas_validas = categorical_fixas_list + amostra
                num_feats = [c for c in colunas_validas if c not in categorical_features]
                cat_feats = [c for c in colunas_validas if c in categorical_features]
                X_tr = train[colunas_validas].copy()
                X_te = x_test_full[colunas_validas].copy()
                n_features_atual = len(colunas_validas)
                logger.debug("Incremento random size=%d/%d: %d features",
                             size, random_limit, n_features_atual)
                await self._rodar_combos_incremento(
                    loop, sem, lock, progresso, total, size, f"random{size}",
                    sem_mlp=sem_mlp,
                    tratamentos=TRATAMENTOS, num_feats=num_feats, cat_feats=cat_feats,
                    X_tr=X_tr, X_te=X_te, y_train=y_train, y_test=y_test,
                    target_col=target_col, modelos_otimizaveis=modelos_otimizaveis,
                    modelos_simples=modelos_simples, n_features_atual=n_features_atual,
                    n_trials_optuna=n_trials_optuna, n_trials_mlp=n_trials_mlp,
                    otimizar_mlp=otimizar_mlp, resultados=resultados,
                    run_name_base=str(size),
                )
        print()
        df = pd.DataFrame(resultados)
        if not df.empty:
            saida = Path.cwd().parent / "dados" / cidade
            saida.mkdir(parents=True, exist_ok=True)
            df.to_csv(saida / f"resultados_treinamento_incremental_{cidade}_{now}.csv", index=False)
            logger.info(f"Resultados salvos em {saida}")
        return df

    # ─── combo helpers ──────────────────────────────────────────────

    async def _rodar_combos_incremento(
        self, loop, sem, lock, progresso, total, idx, col,
        sem_mlp=None,
        tratamentos=None, num_feats=None, cat_feats=None,
        X_tr=None, X_te=None, y_train=None, y_test=None,
        target_col=None, modelos_otimizaveis=None, modelos_simples=None, n_features_atual=None,
        n_trials_optuna=None, n_trials_mlp=None, otimizar_mlp=None, resultados=None,
        run_name_base="",
        transf_unica=None,
    ):
        tasks = []
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
            transforms = ([transf_unica] if transf_unica is not None
                          else list(self.TRANSFORM_OPCOES.keys()))
            for transf_name in transforms:
                for mod_name, factory_fn in modelos_otimizaveis.items():
                    if not cat_feats and mod_name in SCALE_INVARIANT and trat != tratamentos_filtrados[0]:
                        continue
                    tasks.append(self._executar_combo_individual(
                        "optuna", loop, sem, trat, mod_name, factory_fn, None,
                        num_feats, cat_feats, X_tr, X_te, y_train, y_test, target_col,
                        n_trials_optuna, n_trials_mlp, n_features_atual, col,
                        lock, progresso, total, resultados, run_name_base,
                        transf_name=transf_name,
                    ))
                for mod_name, modelo in modelos_simples.items():
                    if not cat_feats and mod_name in SCALE_INVARIANT and trat != tratamentos_filtrados[0]:
                        continue
                    tipo = "mlp_simples" if mod_name == "MLP" else "simples"
                    tasks.append(self._executar_combo_individual(
                        tipo, loop, sem, trat, mod_name, None, modelo,
                        num_feats, cat_feats, X_tr, X_te, y_train, y_test, target_col,
                        n_trials_optuna, n_trials_mlp, n_features_atual, col,
                        lock, progresso, total, resultados, run_name_base,
                        transf_name=transf_name,
                    ))
                if otimizar_mlp:
                    mlp_sem = sem_mlp or sem
                    tasks.append(self._executar_combo_individual(
                        "mlp", loop, mlp_sem, trat, "MLP_opt", None, None,
                        num_feats, cat_feats, X_tr, X_te, y_train, y_test, target_col,
                        n_trials_optuna, n_trials_mlp, n_features_atual, col,
                        lock, progresso, total, resultados, run_name_base,
                        transf_name=transf_name,
                    ))
        for coro in asyncio.as_completed(tasks):
            await coro

    async def _executar_combo_individual(
        self, tipo, loop, sem, trat, mod_name, factory_fn, modelo,
        num_feats, cat_feats, X_tr, X_te, y_train, y_test, target_col,
        n_trials_optuna, n_trials_mlp, n_features, col,
        lock, progresso, total, resultados, run_name_base,
        transf_name="none",
    ):
        if transf_name == "boxcox" and num_feats and X_tr[num_feats].min().min() <= 0:
            logger.debug("Fallback boxcox->yeojohnson para %s (dados nao positivos)", run_name_base)
            transf_name = "yeojohnson"
        async with sem:
            target_transforms = ["none", "log"] if self.target_log else ["none"]

            for tt in target_transforms:
                tt_suffix = f"|tgt_{tt}" if self.target_log else ""
                run_name = f"{mod_name}|{trat['nome']}|{transf_name}_{run_name_base}{tt_suffix}_{time.strftime('%Y_%m')}"
                logger.debug("Task: %s | %s | %s | target=%s", mod_name, trat["nome"], transf_name, tt)
                try:
                    if tipo == "optuna":
                        result = await self._combo_optuna(
                            loop, trat, mod_name, factory_fn,
                            num_feats, cat_feats, X_tr, X_te, y_train, y_test,
                            n_trials_optuna, run_name, n_features, col,
                            transf_name=transf_name, target_transform=tt,
                        )
                    elif tipo == "simples":
                        result = await self._combo_simples(
                            loop, trat, mod_name, modelo,
                            num_feats, cat_feats, X_tr, X_te, y_train, y_test,
                            run_name, n_features, col,
                            transf_name=transf_name, target_transform=tt,
                        )
                    elif tipo == "mlp_simples":
                        result = await self._combo_mlp_simples(
                            loop, trat, num_feats, cat_feats,
                            X_tr, X_te, y_train, y_test, target_col,
                            run_name, n_features, col,
                            transf_name=transf_name,
                        )
                    else:
                        result = await self._combo_mlp(
                            loop, trat, num_feats, cat_feats,
                            X_tr, X_te, y_train, y_test, target_col,
                            n_trials_mlp, run_name, n_features, col,
                            transf_name=transf_name,
                        )

                    result["target_transform"] = tt
                    resultados.append(result)
                    async with lock:
                        progresso["atual"] += 1
                        pct = progresso["atual"] / total * 100 if total else 0
                        logger.info("[%d/%d] %s | %s R2=%s",
                                    progresso["atual"], total,
                                    f"{n_features}feats".ljust(12),
                                    run_name.ljust(55),
                                    result.get("r2", "FAIL"))
                except Exception as e_tudo:
                    logger.warning("Falha geral %s: %s", run_name, e_tudo, exc_info=True)
                    resultados.append({
                        "n_features": n_features,
                        "ultima_feature": col,
                        "tratamento": trat["nome"],
                        "modelo": mod_name,
                        "transform": transf_name,
                        "target_transform": tt,
                        "status": "erro_geral",
                    })

    async def _combo_optuna(self, loop, trat, mod_name, factory_fn,
                             num_feats, cat_feats, X_tr, X_te,
                             y_train, y_test, n_trials, run_name, n_features, col,
                             transf_name="none", target_transform="none"):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]()
            scaler = trat["scaler"]()
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_feats,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder,
                    transform=transf_name)

            # ── Treino / Avaliacao ──
            met = {}
            best_params = {}
            erro = ""
            try:
                y_fit = np.log1p(y_train) if target_transform == "log" else y_train

                otim = OtimizadorOptuna(
                    preprocessador=pp, X=X_tr, y=y_fit,
                    mlflow_manager=self.mlflow_mgr,
                    n_trials=n_trials, n_folds=3, n_jobs=1,
                )
                estudo = otim.otimizar(run_name, factory_fn, log_trials=False)
                if estudo is None:
                    return {
                        "n_features": n_features,
                        "ultima_feature": col,
                        "tratamento": trat["nome"],
                        "modelo": mod_name,
                        "transform": transf_name,
                        "target_transform": target_transform,
                        "status": "failed_no_trials",
                    }
                best_params = estudo.best_params

                trial_fixo = optuna.trial.FixedTrial(estudo.best_params)
                modelo_best = factory_fn(trial_fixo)
                pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
                pipe.fit(X_tr, y_fit)

                y_pred_raw = pipe.predict(X_te)
                y_pred = np.expm1(y_pred_raw) if target_transform == "log" else y_pred_raw

                met = Avaliador.metricas(run_name, y_test, y_pred)
            except Exception as e_train:
                erro = str(e_train)[:200]
                logger.warning("Falha treino/avaliacao %s: %s", run_name, e_train, exc_info=True)
                logger.warning("met=%s", met)

            # ── MLflow (só se há métrica para logar) ──
            if self.mlflow_mgr and met:
                try:
                    with self.mlflow_mgr.run_session(run_name=run_name):
                        mlflow.set_tag("teste", "tratamentos_modelos")
                        mlflow.set_tag("otimizacao", "optuna")
                        mlflow.set_tag("target_transformer", target_transform)
                        mlflow.set_tag("scaler", trat["scaler"]().__class__.__name__ if trat["scaler"] else "None")
                        mlflow.set_tag("imputer_num", trat["imputer_num"])
                        mlflow.set_tag("encoder", type(trat["encoder"]()).__name__)
                        mlflow.log_param("tratamento", trat["nome"])
                        mlflow.log_param("modelo", mod_name)
                        mlflow.log_param("n_features", n_features)
                        mlflow.log_param("ultima_feature", col)
                        mlflow.log_param("transform", transf_name)
                        if best_params:
                            mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in best_params.items()})
                        mlflow.log_metrics(met)
                        encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]()).__name__ else "ohe"
                        mlflow.set_tag("feature_transform_map",
                                       self._build_transform_map(num_feats, cat_feats, transf_name, encoder_name))
                        train_df = pd.concat([X_tr.reset_index(drop=True),
                                              pd.Series(y_train, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                        test_df = pd.concat([X_te.reset_index(drop=True),
                                             pd.Series(y_test, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                        self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "transform": transf_name,
                "target_transform": target_transform,
                **met,
            }

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=600
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout _combo_optuna %s", run_name)
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "transform": transf_name,
                "status": "timeout",
            }

    async def _combo_simples(self, loop, trat, mod_name, modelo_factory,
                              num_feats, cat_feats, X_tr, X_te,
                              y_train, y_test, run_name, n_features, col,
                              transf_name="none", target_transform="none"):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]()
            scaler = trat["scaler"]()
            modelo = modelo_factory()
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_feats,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder,
                    transform=transf_name)

            # ── Treino / Avaliacao ──
            met = {}
            erro = ""
            try:
                y_fit = np.log1p(y_train) if target_transform == "log" else y_train

                pipe = Pipeline([("preprocessador", pp), ("modelo", modelo)])
                pipe.fit(X_tr, y_fit)

                y_pred_raw = pipe.predict(X_te)
                y_pred = np.expm1(y_pred_raw) if target_transform == "log" else y_pred_raw

                met = Avaliador.metricas(run_name, y_test, y_pred)
            except Exception as e_train:
                erro = str(e_train)[:200]
                logger.warning("Falha treino/avaliacao %s: %s", run_name, e_train, exc_info=True)
                logger.warning("met=%s", met)

            # ── MLflow (só se há métrica para logar) ──
            if self.mlflow_mgr and met:
                try:
                    with self.mlflow_mgr.run_session(run_name=run_name):
                        mlflow.set_tag("teste", "tratamentos_modelos")
                        mlflow.set_tag("otimizacao", "simples")
                        mlflow.set_tag("target_transformer", target_transform)
                        mlflow.set_tag("scaler", trat["scaler"]().__class__.__name__ if trat["scaler"] else "None")
                        mlflow.set_tag("imputer_num", trat["imputer_num"])
                        mlflow.set_tag("encoder", type(trat["encoder"]()).__name__)
                        mlflow.log_param("tratamento", trat["nome"])
                        mlflow.log_param("modelo", mod_name)
                        mlflow.log_param("n_features", n_features)
                        mlflow.log_param("ultima_feature", col)
                        mlflow.log_param("transform", transf_name)
                        mlflow.log_metrics(met)
                        encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]()).__name__ else "ohe"
                        mlflow.set_tag("feature_transform_map",
                                       self._build_transform_map(num_feats, cat_feats, transf_name, encoder_name))
                        train_df = pd.concat([X_tr.reset_index(drop=True),
                                              pd.Series(y_train, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                        test_df = pd.concat([X_te.reset_index(drop=True),
                                             pd.Series(y_test, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                        self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "transform": transf_name,
                "target_transform": target_transform,
                **met,
            }

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=600
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout _combo_simples %s", run_name)
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "transform": transf_name,
                "status": "timeout",
            }

    async def _combo_mlp_simples(self, loop, trat, num_feats, cat_feats,
                                   X_tr, X_te, y_train, y_test, target_col,
                                   run_name, n_features, col, transf_name="none"):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]()
            scaler = trat["scaler"]()
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_feats,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder,
                    transform=transf_name)

            met = {}
            erro = ""
            try:
                X_tr_proc = pp.fit_transform(X_tr)
                X_te_proc = pp.transform(X_te)
                input_dim = X_tr_proc.shape[1]
                if input_dim == 0:
                    return {
                        "n_features": n_features,
                        "ultima_feature": col,
                        "tratamento": trat["nome"],
                        "modelo": "MLP",
                        "transform": transf_name,
                        "status": "no_features",
                    }

                from optuna.trial import FixedTrial
                fixed_params = {
                    "num_camadas": 2,
                    "unidades_0": 64,
                    "unidades_1": 32,
                    "dropout_0": 0.2,
                    "dropout_1": 0.2,
                    "learning_rate": 0.001,
                }
                model_mlp = OtimizadorMLP.construir_de_trial(FixedTrial(fixed_params), input_dim)
                import keras
                early_stop = keras.callbacks.EarlyStopping(
                    monitor="loss", patience=10, restore_best_weights=True
                )
                model_mlp.fit(X_tr_proc, y_train, epochs=50,
                              batch_size=64, callbacks=[early_stop], verbose=0)
                y_pred = model_mlp.predict(X_te_proc, verbose=0).ravel()
                met = Avaliador.metricas(run_name, y_test, y_pred)
            except Exception as e_train:
                erro = str(e_train)[:200]
                logger.warning("Falha treino/avaliacao %s: %s", run_name, e_train, exc_info=True)

            if self.mlflow_mgr and met:
                try:
                    with self.mlflow_mgr.run_session(run_name=run_name):
                        mlflow.set_tag("teste", "tratamentos_modelos")
                        mlflow.set_tag("otimizacao", "simples")
                        mlflow.set_tag("scaler", trat["scaler"]().__class__.__name__ if trat["scaler"] else "None")
                        mlflow.set_tag("imputer_num", trat["imputer_num"])
                        mlflow.set_tag("encoder", type(trat["encoder"]()).__name__)
                        mlflow.set_tag("tratamento", trat["nome"])
                        mlflow.set_tag("modelo", "MLP")
                        mlflow.set_tag("n_features", n_features)
                        mlflow.set_tag("ultima_feature", col)
                        mlflow.log_param("transform", transf_name)
                        mlflow.log_metrics(met)
                        encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]()).__name__ else "ohe"
                        mlflow.set_tag("feature_transform_map",
                                       self._build_transform_map(num_feats, cat_feats, transf_name, encoder_name))
                        train_df = pd.concat([X_tr.reset_index(drop=True),
                                              pd.Series(y_train, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                        test_df = pd.concat([X_te.reset_index(drop=True),
                                             pd.Series(y_test, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                        self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP",
                "transform": transf_name,
                **met,
            }

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=120
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout _combo_mlp_simples %s (120s)", run_name)
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP",
                "transform": transf_name,
                "status": "timeout",
            }

    async def _combo_mlp(self, loop, trat, num_feats, cat_feats,
                          X_tr, X_te, y_train, y_test, target_col,
                          n_trials, run_name, n_features, col,
                          transf_name="none"):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]()
            scaler = trat["scaler"]()
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_feats,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder,
                    transform=transf_name)

            # ── Treino / Avaliacao ──
            met = {}
            best_params = {}
            erro = ""
            try:
                X_tr_proc = pp.fit_transform(X_tr)
                X_te_proc = pp.transform(X_te)
                input_dim = X_tr_proc.shape[1]
                if input_dim == 0:
                    return {
                        "n_features": n_features,
                        "ultima_feature": col,
                        "tratamento": trat["nome"],
                        "modelo": "MLP_opt",
                        "transform": transf_name,
                        "status": "no_features",
                    }

                X_tr_s, X_val_s, y_tr_s, y_val_s = train_test_split(
                    X_tr_proc, y_train, test_size=0.2, random_state=42
                )
                otim_mlp = OtimizadorMLP(
                    mlflow_manager=self.mlflow_mgr, target_name=target_col,
                )
                study, _ = otim_mlp.otimizar(
                    X_train=X_tr_s, y_train=y_tr_s,
                    X_val=X_val_s, y_val=y_val_s,
                    input_dim=input_dim, n_trials=n_trials, epochs=100,
                    nome=run_name, log_trials=False,
                )
                if study is None:
                    return {
                        "n_features": n_features,
                        "ultima_feature": col,
                        "tratamento": trat["nome"],
                        "modelo": "MLP_opt",
                        "transform": transf_name,
                        "status": "failed_no_trials",
                    }
                best_params = study.best_params
                model_mlp = OtimizadorMLP.construir_de_trial(
                    optuna.trial.FixedTrial(study.best_params), input_dim,
                )
                import keras
                early_stop = keras.callbacks.EarlyStopping(
                    monitor="loss", patience=10, restore_best_weights=True
                )
                model_mlp.fit(X_tr_proc, y_train, epochs=100,
                              batch_size=study.best_params.get("batch_size", 128),
                              callbacks=[early_stop], verbose=0)
                y_pred = model_mlp.predict(X_te_proc, verbose=0).ravel()
                met = Avaliador.metricas(run_name, y_test, y_pred)
            except Exception as e_train:
                erro = str(e_train)[:200]
                logger.warning("Falha treino/avaliacao %s: %s", run_name, e_train, exc_info=True)
                logger.warning("met=%s", met)

            # ── MLflow (só se há métrica para logar) ──
            if self.mlflow_mgr and met:
                try:
                    with self.mlflow_mgr.run_session(run_name=run_name):
                        mlflow.set_tag("teste", "tratamentos_modelos")
                        mlflow.set_tag("otimizacao", "optuna")
                        mlflow.set_tag("scaler", trat["scaler"]().__class__.__name__ if trat["scaler"] else "None")
                        mlflow.set_tag("imputer_num", trat["imputer_num"])
                        mlflow.set_tag("encoder", type(trat["encoder"]()).__name__)
                        mlflow.log_param("tratamento", trat["nome"])
                        mlflow.log_param("modelo", "MLP_opt")
                        mlflow.log_param("n_features", n_features)
                        mlflow.log_param("ultima_feature", col)
                        mlflow.log_param("transform", transf_name)
                        if best_params:
                            mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in best_params.items()})
                        mlflow.log_metrics(met)
                        encoder_name = "ordinal" if "Ordinal" in type(trat["encoder"]()).__name__ else "ohe"
                        mlflow.set_tag("feature_transform_map",
                                       self._build_transform_map(num_feats, cat_feats, transf_name, encoder_name))
                        train_df = pd.concat([X_tr.reset_index(drop=True),
                                              pd.Series(y_train, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(train_df, name="train"), context="training")
                        test_df = pd.concat([X_te.reset_index(drop=True),
                                             pd.Series(y_test, name="target")], axis=1)
                        mlflow.log_input(mlflow.data.from_pandas(test_df, name="test"), context="test")
                        self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                except Exception as e_mlflow:
                    logger.warning("Falha ao logar MLflow para %s: %s", run_name, e_mlflow)
                    logger.exception("Detalhes:")

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP_opt",
                "transform": transf_name,
                **met,
            }

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _run), timeout=120
            )
        except asyncio.TimeoutError:
            logger.warning("Timeout _combo_mlp %s (120s)", run_name)
            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP_opt",
                "transform": transf_name,
                "status": "timeout",
            }


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
    logger.info("  %s | %d features | escalador=%s | R2=%.4f | RMSE=%.0f",
                melhor["modelo"], int(melhor["n_features"]),
                melhor["escalador"], melhor["r2"], melhor["rmse"])

    logger.info("")
    logger.info("MELHOR POR MODELO:")
    for mod in sorted(df_ok["modelo"].unique()):
        sub = df_ok[df_ok["modelo"] == mod]
        best = sub.loc[sub["r2"].idxmax()]
        logger.info("  %20s: %2d feats | R2=%.4f | escalador=%s",
                    mod, int(best["n_features"]), best["r2"], best["escalador"])

    logger.info("")
    logger.info("EVOLUCAO R2 POR N_DE_FEATURES:")
    evol = df_ok.groupby("n_features")["r2"].agg(["mean", "max", "std"]).reset_index()
    for _, row in evol.iterrows():
        logger.info("  %2d features -> R2 medio=%.4f | max=%.4f | std=%.4f",
                    int(row["n_features"]), row["mean"], row["max"], row["std"])
    return df_ok
