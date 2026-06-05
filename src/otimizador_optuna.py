import numpy as np
import optuna
from sklearn.model_selection import KFold, cross_validate
from sklearn.pipeline import Pipeline


class OtimizadorOptuna:
    """Otimizacao de hiperparametros com Optuna + cross-validation + MLflow."""

    def __init__(self, preprocessador, X, y, mlflow_manager=None, n_trials=40, n_folds=3, random_state=42):
        self.preprocessador = preprocessador
        self.X = X
        self.y = y
        self.mlflow = mlflow_manager
        self.n_trials = n_trials
        self.n_folds = n_folds
        self.random_state = random_state
        self.cv = KFold(n_splits=n_folds, shuffle=True, random_state=random_state)
        self.melhores_params = {}
        self.estudos = {}

    def _log_trial(self, nome, trial, metrics, X_train):
        import mlflow

        with mlflow.start_run(nested=True, run_name=f"{nome}_trial_{trial.number}"):
            mlflow.set_tag("modelo", nome)
            mlflow.set_tag("trial", trial.number)
            for k, v in trial.params.items():
                mlflow.log_param(k, str(v)[:100])
            mlflow.log_metrics(metrics)
            if self.mlflow:
                self.mlflow.log_feature_history(X_train, run_name=f"optuna_{nome}")
                self.mlflow.log_feature_store(X_train, run_name=f"optuna_{nome}",
                                              feature_group_name="joinville_imoveis",
                                              description=f"Features usadas para otimizar {nome}",
                                              source="joinville_historico_imoveis")

    def _objective(self, nome, factory):
        def objective(trial):
            modelo = factory(trial)
            pipe = Pipeline([
                ("preprocessador", self.preprocessador),
                ("modelo", modelo),
            ])
            scoring = {
                "rmse": "neg_root_mean_squared_error",
                "mae": "neg_mean_absolute_error",
                "mape": "neg_mean_absolute_percentage_error",
                "r2": "r2",
            }
            scores = cross_validate(pipe, self.X, self.y, cv=self.cv, scoring=scoring, n_jobs=-1)
            metrics = {
                "rmse": -scores["test_rmse"].mean(),
                "mae": -scores["test_mae"].mean(),
                "mape": -scores["test_mape"].mean(),
                "r2": scores["test_r2"].mean(),
            }
            self._log_trial(nome, trial, metrics, self.X)
            return metrics["rmse"]
        return objective

    def otimizar(self, nome, factory):
        import mlflow

        run_name = f"{nome}"
        if self.mlflow:
            self.mlflow.criar_run(run_name=run_name)
        else:
            mlflow.start_run(run_name=run_name)

        try:
            mlflow.set_tag("otimizacao", "optuna")
            mlflow.set_tag("modelo", nome)
            mlflow.log_param("n_trials", self.n_trials)
            mlflow.log_param("n_folds", self.n_folds)

            if self.mlflow:
                self.mlflow.log_feature_history(self.X, run_name=run_name)
                self.mlflow.log_feature_store(self.X, run_name=run_name,
                                              feature_group_name="joinville_imoveis",
                                              description=f"Features usadas para otimizar {nome}",
                                              source="joinville_historico_imoveis")

            study = optuna.create_study(
                direction="minimize",
                study_name=nome,
                sampler=optuna.samplers.TPESampler(seed=self.random_state),
            )
            study.optimize(self._objective(nome, factory), n_trials=self.n_trials, show_progress_bar=True)

            self.melhores_params[nome] = study.best_params
            self.estudos[nome] = study

            for k, v in study.best_params.items():
                mlflow.log_param(f"best_{k}", str(v)[:100])
            mlflow.log_metric("best_rmse", study.best_value)

            print(f"{nome}: melhor RMSE CV = {study.best_value:,.2f} | params = {study.best_params}")
            return study
        finally:
            if self.mlflow:
                mlflow.end_run()
            else:
                mlflow.end_run()

    def otimizar_varios(self, factories):
        for nome, factory in factories.items():
            self.otimizar(nome, factory)
        return self.melhores_params, self.estudos


class FactoryModelos:
    """Factories de hiperparametros para modelos suportados pelo Optuna."""

    def __init__(self, random_state=42):
        self.random_state = random_state

    def linear(self, trial):
        from sklearn.linear_model import LinearRegression

        return LinearRegression()

    def ridge(self, trial):
        from sklearn.linear_model import Ridge

        return Ridge(
            alpha=trial.suggest_float("alpha", 0.01, 100.0, log=True),
            random_state=self.random_state,
        )

    def decision_tree(self, trial):
        from sklearn.tree import DecisionTreeRegressor

        return DecisionTreeRegressor(
            max_depth=trial.suggest_int("max_depth", 3, 30),
            min_samples_split=trial.suggest_int("min_samples_split", 2, 20),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 10),
            max_features=trial.suggest_categorical("max_features", [None, "sqrt", "log2"]),
            random_state=self.random_state,
        )

    def random_forest(self, trial):
        from sklearn.ensemble import RandomForestRegressor

        return RandomForestRegressor(
            n_estimators=trial.suggest_int("n_estimators", 100, 500, step=50),
            max_depth=trial.suggest_int("max_depth", 6, 30),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 8),
            min_samples_split=trial.suggest_int("min_samples_split", 2, 20),
            max_features=trial.suggest_categorical("max_features", ["sqrt", "log2", 0.7, 0.9]),
            random_state=self.random_state,
            n_jobs=-1,
        )

    def gradient_boosting(self, trial):
        from sklearn.ensemble import GradientBoostingRegressor

        return GradientBoostingRegressor(
            n_estimators=trial.suggest_int("n_estimators", 100, 500, step=50),
            max_depth=trial.suggest_int("max_depth", 3, 12),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 10),
            random_state=self.random_state,
        )

    def knn(self, trial):
        from sklearn.neighbors import KNeighborsRegressor

        return KNeighborsRegressor(
            n_neighbors=trial.suggest_int("n_neighbors", 3, 30),
            weights=trial.suggest_categorical("weights", ["uniform", "distance"]),
            p=trial.suggest_int("p", 1, 2),
            n_jobs=-1,
        )

    def svr(self, trial):
        from sklearn.svm import SVR

        return SVR(
            kernel=trial.suggest_categorical("kernel", ["rbf", "linear", "poly"]),
            C=trial.suggest_float("C", 0.1, 1000.0, log=True),
            epsilon=trial.suggest_float("epsilon", 0.001, 1.0, log=True),
            gamma=trial.suggest_categorical("gamma", ["scale", "auto"]),
        )

    def catboost(self, trial):
        from catboost import CatBoostRegressor

        return CatBoostRegressor(
            iterations=trial.suggest_int("iterations", 200, 800, step=50),
            depth=trial.suggest_int("depth", 4, 10),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            l2_leaf_reg=trial.suggest_float("l2_leaf_reg", 1.0, 10.0, log=True),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
            loss_function="RMSE",
            random_seed=self.random_state,
            verbose=0,
        )

    def lightgbm(self, trial):
        from lightgbm import LGBMRegressor

        return LGBMRegressor(
            n_estimators=trial.suggest_int("n_estimators", 200, 800, step=50),
            max_depth=trial.suggest_int("max_depth", 4, 14),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            num_leaves=trial.suggest_int("num_leaves", 16, 128),
            subsample=trial.suggest_float("subsample", 0.6, 1.0),
            colsample_bytree=trial.suggest_float("colsample_bytree", 0.6, 1.0),
            reg_alpha=trial.suggest_float("reg_alpha", 1e-3, 10.0, log=True),
            reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True),
            random_state=self.random_state,
            n_jobs=-1,
            verbose=-1,
        )

    def hist_gb(self, trial):
        from sklearn.ensemble import HistGradientBoostingRegressor

        return HistGradientBoostingRegressor(
            max_iter=trial.suggest_int("max_iter", 200, 800, step=50),
            max_depth=trial.suggest_int("max_depth", 4, 14),
            learning_rate=trial.suggest_float("learning_rate", 0.01, 0.2, log=True),
            min_samples_leaf=trial.suggest_int("min_samples_leaf", 5, 50),
            l2_regularization=trial.suggest_float("l2_regularization", 1e-3, 10.0, log=True),
            random_state=self.random_state,
        )

    def todos(self):
        return {
            "linear": self.linear,
            "ridge": self.ridge,
            "decision_tree": self.decision_tree,
            "random_forest": self.random_forest,
            "gradient_boosting": self.gradient_boosting,
            "knn": self.knn,
            "svr": self.svr,
            "catboost": self.catboost,
            "lightgbm": self.lightgbm,
            "hist_gradient_boosting": self.hist_gb,
        }


class ConstrutorKeras:
    """Constroi modelos Keras tunaveis com Hyperparameters do Keras Tuner."""

    @staticmethod
    def construir_modelo_otimizavel(hp, input_dim):
        import keras
        from keras import layers

        modelo = keras.Sequential()
        modelo.add(layers.Input(shape=(input_dim,)))
        for i in range(hp.Int("num_camadas", min_value=1, max_value=4, default=3)):
            modelo.add(layers.Dense(
                units=hp.Int(f"unidades_{i}", min_value=64, max_value=512, step=64),
                activation="relu",
            ))
            modelo.add(layers.Dropout(rate=hp.Float(f"dropout_{i}", min_value=0.0, max_value=0.4, step=0.1)))
        modelo.add(layers.Dense(1))
        lr = hp.Choice("learning_rate", values=[1e-2, 1e-3, 1e-4, 1e-5])
        modelo.compile(
            optimizer=keras.optimizers.Adam(learning_rate=lr),
            loss="mse",
            metrics=["mae"],
        )
        return modelo


class OtimizadorMLP:
    """Otimizacao de MLP (Keras) com Optuna + MLflow."""

    def __init__(self, mlflow_manager=None, target_name="preco_por_m2", random_state=42):
        self.mlflow = mlflow_manager
        self.target_name = target_name
        self.random_state = random_state

    @staticmethod
    def construir_de_trial(trial, input_dim):
        """Reconstroi modelo Keras a partir dos parametros de um trial Optuna."""
        import keras
        from keras import layers

        def _trial_param(name):
            params = getattr(trial, "_params", None) or getattr(trial, "params", None) or {}
            return params.get(name, None)

        model = keras.Sequential()
        model.add(layers.Input(shape=(input_dim,)))
        num_camadas = _trial_param("num_camadas")
        if num_camadas is None:
            num_camadas = trial.suggest_int("num_camadas", 1, 4)
        for i in range(num_camadas):
            unidades = _trial_param(f"unidades_{i}")
            if unidades is None:
                unidades = trial.suggest_int(f"unidades_{i}", 64, 512, step=64)
            dropout = _trial_param(f"dropout_{i}")
            if dropout is None:
                dropout = trial.suggest_float(f"dropout_{i}", 0.0, 0.4, step=0.1)
            model.add(layers.Dense(int(unidades), activation="relu"))
            if dropout and float(dropout) > 0:
                model.add(layers.Dropout(float(dropout)))
        model.add(layers.Dense(1))
        lr = _trial_param("learning_rate")
        if lr is None:
            lr = trial.suggest_categorical("learning_rate", [1e-2, 1e-3, 1e-4, 1e-5])
        model.compile(
            optimizer=keras.optimizers.Adam(learning_rate=lr),
            loss="mse",
            metrics=["mae"],
        )
        return model

    def otimizar(self, X_train, y_train, X_val, y_val, input_dim, n_trials=30, epochs=100, nome="mlp_keras"):
        import mlflow
        import keras
        from sklearn.metrics import mean_absolute_error, mean_absolute_percentage_error, r2_score

        if self.mlflow:
            self.mlflow.criar_run(run_name=nome)
        else:
            mlflow.start_run(run_name=nome)

        try:
            mlflow.set_tag("modelo", "keras")
            mlflow.set_tag("target", self.target_name)
            if self.mlflow:
                self.mlflow.log_feature_history(X_train, run_name=nome)
                self.mlflow.log_feature_store(X_train, run_name=nome,
                                              feature_group_name="joinville_imoveis",
                                              description="Features do MLP otimizado",
                                              source="joinville_historico_imoveis")
            mlflow.log_param("n_trials", n_trials)
            mlflow.log_param("epochs", epochs)
            mlflow.log_param("input_dim", input_dim)

            def objective_mlp(trial):
                model = self.construir_de_trial(trial, input_dim)
                batch_size = trial.suggest_categorical("batch_size", [64, 128, 256, 512])
                early_stop = keras.callbacks.EarlyStopping(
                    monitor="val_loss", patience=10, restore_best_weights=True
                )
                history = model.fit(
                    X_train, y_train, validation_data=(X_val, y_val),
                    epochs=epochs, batch_size=batch_size,
                    callbacks=[early_stop], verbose=0
                )
                preds_log = model.predict(X_val, verbose=0).ravel()
                y_val_real = np.expm1(y_val)
                preds_real = np.expm1(preds_log)
                rmse = float(np.sqrt(np.mean((y_val_real - preds_real) ** 2)))
                mae = float(mean_absolute_error(y_val_real, preds_real))
                mape = float(mean_absolute_percentage_error(y_val_real, preds_real))
                r2 = float(r2_score(y_val_real, preds_real))

                with mlflow.start_run(nested=True, run_name=f"{nome}_trial_{trial.number}"):
                    mlflow.set_tag("modelo", "keras")
                    for k, v in trial.params.items():
                        mlflow.log_param(k, str(v)[:100])
                    mlflow.log_metric("rmse", rmse)
                    mlflow.log_metric("mae", mae)
                    mlflow.log_metric("mape", mape)
                    mlflow.log_metric("r2", r2)
                    mlflow.log_metric("best_epoch", len(history.history.get("loss", [])))
                    if self.mlflow:
                        self.mlflow.log_feature_history(X_train, run_name=nome)
                        self.mlflow.log_feature_store(X_train, run_name=nome,
                                                      feature_group_name="joinville_imoveis",
                                                      description="Features do MLP otimizado",
                                                      source="joinville_historico_imoveis")
                return rmse

            study = optuna.create_study(
                direction="minimize",
                sampler=optuna.samplers.TPESampler(seed=self.random_state),
            )
            study.optimize(objective_mlp, n_trials=n_trials, show_progress_bar=True)

            for k, v in study.best_params.items():
                mlflow.log_param(f"best_{k}", str(v)[:100])
            mlflow.log_metric("best_rmse", study.best_value)
            mlflow.log_metric("total_trials", n_trials)

            best_model = self.construir_de_trial(
                optuna.trial.FixedTrial(study.best_params), input_dim
            )
            early_stop = keras.callbacks.EarlyStopping(
                monitor="val_loss", patience=15, restore_best_weights=True
            )
            best_model.fit(
                X_train, y_train, validation_data=(X_val, y_val), epochs=200,
                batch_size=study.best_params.get("batch_size", 256),
                callbacks=[early_stop], verbose=0,
            )
            mlflow.keras.log_model(best_model, name="keras_model_best")
            print(f"MLP otimizado: melhor RMSE = {study.best_value:,.4f}")
            return study, best_model
        finally:
            mlflow.end_run()
