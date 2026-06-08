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
from sklearn.preprocessing import (
    StandardScaler, RobustScaler, MinMaxScaler,
    QuantileTransformer, PowerTransformer, OrdinalEncoder, OneHotEncoder,
)
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

import optuna
import mlflow

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MAX_CONCURRENT = 4

TRATAMENTOS = [
    {"nome": "std_median_ohe",       "scaler": StandardScaler(),
     "imputer_num": "median",        "encoder": OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "robust_median_ohe",    "scaler": RobustScaler(),
     "imputer_num": "median",        "encoder": OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "minmax_mean_ohe",      "scaler": MinMaxScaler(),
     "imputer_num": "mean",          "encoder": OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "quantile_median_ord",  "scaler": QuantileTransformer(output_distribution="normal"),
     "imputer_num": "median",        "encoder": OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)},
    {"nome": "power_median_ohe",     "scaler": PowerTransformer(),
     "imputer_num": "median",        "encoder": OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)},
    {"nome": "raw_zero_ord",         "scaler": None,
     "imputer_num": "constant",      "encoder": OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)},
]

MODELOS_OTIMIZAVEIS = {
    "Ridge_opt":        FactoryModelos().ridge,
    "RandomForest_opt": FactoryModelos().random_forest,
    "GradientBoosting_opt": FactoryModelos().gradient_boosting,
    "KNN_opt":          FactoryModelos().knn,
    "SVR_opt":          FactoryModelos().svr,
    "CatBoost_opt":     FactoryModelos().catboost,
    "LightGBM_opt":     FactoryModelos().lightgbm,
    "HistGB_opt":       FactoryModelos().hist_gb,
}

MODELOS_SIMPLES_TRAT = {
    "Linear": LinearRegression(),
}

now = time.strftime("%Y-%m")


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

    def _otimizar_modelos_optuna(self, preprocessor, X, y, mlflow_mgr):
        logger.info("Otimizando hiperparametros com OtimizadorOptuna...")
        otimizador = OtimizadorOptuna(
            preprocessador=preprocessor, X=X, y=y,
            mlflow_manager=mlflow_mgr, n_trials=self.n_trials_optuna,
        )
        factories = {}
        for nome_curto, metodo in self.modelos_optuna_nomes.items():
            factories[nome_curto] = getattr(self.factory, metodo)
        melhores_params, _ = otimizador.otimizar_varios(factories)
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
            logger.warning("MLflow nao disponivel: %s", e)
            self.mlflow_mgr = None

    # ─── executar_async ─────────────────────────────────────────────

    async def executar_async(
        self,
        train,
        test,
        target_col,
        numeric_features,
        categorical_features,
        otimizar_com_optuna=True,
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
                for mod_name, modelo in modelos_efetivos.items():
                    combos.append((esc_name, scaler, mod_name, modelo))

            async def executar_combo(args):
                esc_name, scaler, mod_name, modelo = args
                async with sem:
                    run_name = f"inc_{mod_name}_{n_feats:02d}feats_{esc_name}_{now}"
                    t0 = time.time()

                    try:
                        factory_pp = PreprocessadorFactory(
                            numeric_features=feats_num,
                            categorical_features=cat_fixas,
                        )
                        preprocessor = factory_pp.criar(scaler=scaler)

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
                                return y_pred, None
                            y_pred, _ = await asyncio.wait_for(
                                loop.run_in_executor(None, _treinar_rede), timeout=600
                            )
                            pipe = None

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
                                    nome=run_name,
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
                                return y_pred, study
                            y_pred, study = await asyncio.wait_for(
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
                                return pipe.predict(X_te_sel), None
                            y_pred, _ = await asyncio.wait_for(
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
                                return pipe.predict(X_te_sel), None
                            y_pred, _ = await asyncio.wait_for(
                                loop.run_in_executor(None, _treinar_simples), timeout=600
                            )

                        met = Avaliador.metricas(run_name, y_test, y_pred)

                        if self.mlflow_mgr:
                            await asyncio.wait_for(
                                loop.run_in_executor(None, self._log_executar_resultado,
                                                       run_name, n_feats, feats_num[-1],
                                                       esc_name, mod_name, met, modelo, X_tr_sel),
                                timeout=60
                            )

                        return {
                            "n_features": n_feats,
                            "features": "_".join(feats_num),
                            "ultima_feature": feats_num[-1],
                            "escalador": esc_name,
                            "modelo": mod_name,
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
                                 esc_name, mod_name, met, modelo, X_tr_sel):
        self.mlflow_mgr.criar_run(run_name=run_name, nested=True)
        mlflow.set_tag("teste", "incremental_features")
        mlflow.log_param("n_features", n_feats)
        mlflow.log_param("ultima_feature", ultima_feature)
        mlflow.log_param("escalador", esc_name)
        mlflow.log_param("modelo", mod_name)
        mlflow.log_metrics(met)
        if hasattr(modelo, "get_params"):
            mlflow.log_params({
                f"modelo__{k}": str(v)[:80] for k, v in modelo.get_params().items()
            })
        self.mlflow_mgr.log_feature_history(X_tr_sel, run_name=run_name)
        mlflow.end_run()

    # ─── testar_tratamentos_modelos_incrementais_async ──────────────

    async def testar_tratamentos_modelos_incrementais_async(
        self,
        train,
        test,
        target_col,
        features_testadas,
        categorical_features,
        n_trials_optuna=10,
        n_trials_mlp=15,
        otimizar_mlp=False,
        max_concurrent=MAX_CONCURRENT,
    ):
        """Versao async: testa N tratamentos x M modelos com features incrementais.
        Combinacoes rodam concorrentemente via asyncio com semaforo."""
        qtd_optuna = len(MODELOS_OTIMIZAVEIS)
        qtd_simples = len(MODELOS_SIMPLES_TRAT) + (1 if otimizar_mlp else 0)

        logger.info("=" * 60)
        logger.info("TESTE TRATAMENTOS x MODELOS x FEATURES (async)")
        logger.info("Tratamentos: %d | Modelos: %d (%d Optuna, %d simples%s)",
                    len(TRATAMENTOS), qtd_optuna + qtd_simples,
                    qtd_optuna, qtd_simples,
                    ", +MLP_opt" if otimizar_mlp else "")
        logger.info("Features candidatas: %d", len(features_testadas))
        logger.info("Optuna trials: %d | MLP trials: %d", n_trials_optuna, n_trials_mlp)
        logger.info("Max concurrent: %d", max_concurrent)
        logger.info("=" * 60)

        cat_fixas = [c for c in categorical_features if c in train.columns]
        cols_full = features_testadas + [c for c in cat_fixas if c not in features_testadas]
        x_test_full = test[cols_full].copy()
        y_train = train[target_col].values
        y_test = test[target_col].values

        await self._conectar_mlflow_async()

        colunas_validas = []
        resultados = []
        total = len(features_testadas) * len(TRATAMENTOS) * (qtd_optuna + qtd_simples)
        progresso = {"atual": 0}
        lock = asyncio.Lock()
        max_workers = min(max_concurrent, os.cpu_count() or 4)
        sem = asyncio.Semaphore(max_workers)
        loop = asyncio.get_event_loop()

        for idx_col, col in enumerate(features_testadas, 1):
            try:
                colunas_validas.append(col)
                num_feats = [c for c in colunas_validas if c not in cat_fixas]
                cols_loop = colunas_validas + [c for c in cat_fixas if c not in colunas_validas]
                X_tr = train[cols_loop].copy()
                X_te = x_test_full[cols_loop].copy()
            except Exception as e:
                logger.warning("Feature %s falhou na selecao: %s", col, e)
                colunas_validas.pop(-1)
                continue

            # Monta todas as combinacoes para este incremento
            combos = []
            for trat in TRATAMENTOS:
                for mod_name, factory_fn in MODELOS_OTIMIZAVEIS.items():
                    combos.append(("optuna", trat, mod_name, factory_fn, None))
                for mod_name, modelo in MODELOS_SIMPLES_TRAT.items():
                    combos.append(("simples", trat, mod_name, None, modelo))
                if otimizar_mlp:
                    combos.append(("mlp", trat, None, None, None))

            n_features_atual = len(colunas_validas)

            async def executar_combo(args):
                tipo, trat, mod_name, factory_fn, modelo = args
                async with sem:
                    run_name = f"{mod_name or 'MLP_opt'}|{trat['nome']}|feat{idx_col:02d}_{col}_{now}"
                    t0 = time.time()

                    try:
                        if tipo == "optuna":
                            result = await self._combo_optuna(
                                loop, trat, mod_name, factory_fn,
                                num_feats, cat_fixas, X_tr, X_te, y_train, y_test,
                                n_trials_optuna, run_name, n_features_atual, col,
                            )
                        elif tipo == "simples":
                            result = await self._combo_simples(
                                loop, trat, mod_name, modelo,
                                num_feats, cat_fixas, X_tr, X_te, y_train, y_test,
                                run_name, n_features_atual, col,
                            )
                        else:
                            result = await self._combo_mlp(
                                loop, trat, num_feats, cat_fixas,
                                X_tr, X_te, y_train, y_test, target_col,
                                n_trials_mlp, run_name, n_features_atual, col,
                            )

                        return result

                    except Exception as exc:
                        logger.debug("Falha %s %s feat%s: %s",
                                     mod_name or "MLP_opt", trat["nome"], col, exc)
                        return {
                            "n_features": n_features_atual,
                            "ultima_feature": col,
                            "tratamento": trat["nome"],
                            "modelo": mod_name or "MLP_opt",
                            "rmse": float("nan"), "mae": float("nan"),
                            "mape": float("nan"), "mdape": float("nan"), "r2": float("nan"),
                        }

            tasks = [executar_combo(c) for c in combos]
            for coro in asyncio.as_completed(tasks):
                resultado = await coro
                resultados.append(resultado)
                async with lock:
                    progresso["atual"] += 1
                r2v = resultado.get("r2", float("nan"))
                r2s = f"{r2v:.4f}" if isinstance(r2v, (int, float)) and not np.isnan(r2v) else "FAIL"
                sys.stdout.write(
                    f"\r[{progresso['atual']:4d}/{total}] "
                    f"{idx_col:2d}feats {resultado.get('tratamento', ''):>18} "
                    f"{resultado.get('modelo', ''):>18} R2={r2s}     "
                )
                sys.stdout.flush()

        print()
        df = pd.DataFrame(resultados)
        if not df.empty:
            saida = Path.cwd().parent / "scripts"
            saida.mkdir(parents=True, exist_ok=True)
            df.to_csv(saida / "resultados_tratamentos_modelos_async.csv", index=False)
            logger.info("Resultados salvos em scripts/resultados_tratamentos_modelos_async.csv")
        return df

    # ─── combo helpers ──────────────────────────────────────────────

    async def _combo_optuna(self, loop, trat, mod_name, factory_fn,
                             num_feats, cat_fixas, X_tr, X_te,
                             y_train, y_test, n_trials, run_name,
                             n_features, col):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]
            scaler = trat["scaler"]
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_fixas,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder)

            otim = OtimizadorOptuna(
                preprocessador=pp, X=X_tr, y=y_train,
                mlflow_manager=self.mlflow_mgr,
                n_trials=n_trials, n_folds=3, n_jobs=1,
            )
            estudo = otim.otimizar(run_name, factory_fn)

            trial_fixo = optuna.trial.FixedTrial(estudo.best_params)
            modelo_best = factory_fn(trial_fixo)
            pipe = Pipeline([("preprocessador", pp), ("modelo", modelo_best)])
            pipe.fit(X_tr, y_train)
            y_pred = pipe.predict(X_te)
            met = Avaliador.metricas(run_name, y_test, y_pred)

            if self.mlflow_mgr:
                self.mlflow_mgr.criar_run(run_name=run_name, nested=True)
                mlflow.set_tag("teste", "tratamentos_modelos")
                mlflow.log_param("tratamento", trat["nome"])
                mlflow.log_param("modelo", mod_name)
                mlflow.log_param("n_features", n_features)
                mlflow.log_param("ultima_feature", col)
                mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in estudo.best_params.items()})
                mlflow.log_metrics(met)
                self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                mlflow.end_run()

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                "best_rmse_cv": float(estudo.best_value),
                **met,
            }

        return await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=600
        )

    async def _combo_simples(self, loop, trat, mod_name, modelo,
                              num_feats, cat_fixas, X_tr, X_te,
                              y_train, y_test, run_name, n_features, col):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]
            scaler = trat["scaler"]
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_fixas,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder)

            pipe = Pipeline([("preprocessador", pp), ("modelo", modelo)])
            pipe.fit(X_tr, y_train)
            y_pred = pipe.predict(X_te)
            met = Avaliador.metricas(run_name, y_test, y_pred)

            if self.mlflow_mgr:
                self.mlflow_mgr.criar_run(run_name=run_name, nested=True)
                mlflow.set_tag("teste", "tratamentos_modelos")
                mlflow.log_param("tratamento", trat["nome"])
                mlflow.log_param("modelo", mod_name)
                mlflow.log_param("n_features", n_features)
                mlflow.log_param("ultima_feature", col)
                mlflow.log_metrics(met)
                self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                mlflow.end_run()

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": mod_name,
                **met,
            }

        return await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=600
        )

    async def _combo_mlp(self, loop, trat, num_feats, cat_fixas,
                          X_tr, X_te, y_train, y_test, target_col,
                          n_trials, run_name, n_features, col):
        def _run():
            imputer_num = SimpleImputer(strategy=trat["imputer_num"])
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
            encoder = trat["encoder"]
            scaler = trat["scaler"]
            pp = PreprocessadorFactory(
                numeric_features=num_feats, categorical_features=cat_fixas,
            ).criar(scaler=scaler, imputer_num=imputer_num,
                    imputer_cat=imputer_cat, encoder=encoder)

            X_tr_proc = pp.fit_transform(X_tr)
            X_te_proc = pp.transform(X_te)
            input_dim = X_tr_proc.shape[1]

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
                nome=run_name,
            )
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

            if self.mlflow_mgr:
                self.mlflow_mgr.criar_run(run_name=run_name, nested=True)
                mlflow.set_tag("teste", "tratamentos_modelos")
                mlflow.log_param("tratamento", trat["nome"])
                mlflow.log_param("modelo", "MLP_opt")
                mlflow.log_param("n_features", n_features)
                mlflow.log_param("ultima_feature", col)
                mlflow.log_params({f"best_{k}": str(v)[:80] for k, v in study.best_params.items()})
                mlflow.log_metrics(met)
                self.mlflow_mgr.log_feature_history(X_tr, run_name=run_name)
                mlflow.end_run()

            return {
                "n_features": n_features,
                "ultima_feature": col,
                "tratamento": trat["nome"],
                "modelo": "MLP_opt",
                "best_rmse_cv": float(study.best_value),
                **met,
            }

        return await asyncio.wait_for(
            loop.run_in_executor(None, _run), timeout=600
        )


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
