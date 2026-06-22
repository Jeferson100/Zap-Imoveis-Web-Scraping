import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_squared_log_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler, PowerTransformer


TRANSFORM_MAP = {
    None: "none",
    "log": "log1p",
    "sqrt": "sqrt",
    "boxcox": "box-cox",
    "yeojohnson": "yeo-johnson",
}

TRANSFORMACOES = {
    None: None,
    "log": FunctionTransformer(np.log1p, validate=False, feature_names_out="one-to-one"),
    "sqrt": FunctionTransformer(np.sqrt, validate=False, feature_names_out="one-to-one"),
    "boxcox": PowerTransformer(method="box-cox"),
    "yeojohnson": PowerTransformer(method="yeo-johnson"),
}


def _replace_inf(X):
    return np.nan_to_num(
        np.asarray(X, dtype=np.float64),
        nan=np.nan,
        posinf=np.nan,
        neginf=np.nan,
    )


_replacement_inf = FunctionTransformer(
    _replace_inf, validate=False, feature_names_out="one-to-one"
)


def _cleanup_transform(X):
    return np.nan_to_num(X, nan=0.0, posinf=1e10, neginf=-1e10)


class PreprocessadorFactory:
    """Cria ColumnTransformers para pre-processamento de features."""

    def __init__(self, numeric_features, categorical_features):
        self.numeric_features = list(numeric_features)
        self.categorical_features = list(categorical_features)

    def criar(
        self,
        imputer_num=None,
        imputer_cat=None,
        scaler=None,
        encoder=None,
        transform=None,
    ):
        if imputer_num is None:
            imputer_num = SimpleImputer(strategy="median")
        if imputer_cat is None:
            imputer_cat = SimpleImputer(strategy="constant", fill_value="desconhecido")
        if scaler is None:
            scaler = StandardScaler()
        if encoder is None:
            encoder = OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)

        transform_step = TRANSFORMACOES.get(transform) if isinstance(transform, str) else transform
        numeric_steps = [
            ("replace_inf", _replacement_inf),
            ("imputer", imputer_num),
        ]
        if transform_step is not None:
            numeric_steps.append(("transform", transform_step))
            numeric_steps.append(("cleanup", FunctionTransformer(
                _cleanup_transform,
                validate=False, feature_names_out="one-to-one")))
        numeric_steps.append(("scaler", scaler))

        numeric_pipe = Pipeline(numeric_steps)
        categorical_pipe = Pipeline([
            ("imputer", imputer_cat),
            ("ohe", encoder),
        ])

        transformers = []
        if self.numeric_features:
            transformers.append(("num", numeric_pipe, self.numeric_features))
        if self.categorical_features:
            transformers.append(("cat", categorical_pipe, self.categorical_features))

        return ColumnTransformer(transformers)


class Avaliador:
    """Calcula e exibe metricas de regressao."""

    @staticmethod
    def metricas(nome, y_true, y_pred):
        rmse = mean_squared_error(y_true, y_pred) ** 0.5
        mae = mean_absolute_error(y_true, y_pred)
        mape = np.mean(np.abs((y_true - y_pred) / y_true)) * 100
        mdape = np.median(np.abs((y_true - y_pred) / y_true)) * 100
        r2 = r2_score(y_true, y_pred)
        try:
            rmsle = float(np.sqrt(mean_squared_log_error(y_true, y_pred)))
        except ValueError:
            rmsle = float("nan")
        print(f"{nome}: RMSE=R$ {rmse:,.0f} | MAE=R$ {mae:,.0f} | MAPE={mape:.1f}% | MdAPE={mdape:.1f}% | R2={r2:.3f} | RMSLE={rmsle:.4f}")
        return {"rmse": rmse, "mae": mae, "mape": mape, "mdape": mdape, "r2": r2, "rmsle": rmsle}

    @staticmethod
    def rmse(y_true, y_pred):
        return float(mean_squared_error(y_true, y_pred) ** 0.5)

    @staticmethod
    def mae(y_true, y_pred):
        return float(mean_absolute_error(y_true, y_pred))

    @staticmethod
    def r2(y_true, y_pred):
        return float(r2_score(y_true, y_pred))


class TreinadorPipeline:
    """Treina pipelines sklearn com pre-processador."""

    def __init__(self, preprocessador):
        self.preprocessador = preprocessador

    def treinar(self, nome, estimador, X_tr, y_tr, X_te, y_te):
        pipe = Pipeline([
            ("preprocessador", self.preprocessador),
            ("modelo", estimador),
        ])
        pipe.fit(X_tr, y_tr)
        pred = pipe.predict(X_te)
        return pipe, Avaliador.metricas(nome, y_te, pred)

    def treinar_e_logar(self, nome, estimador, X_tr, y_tr, X_te, y_te, mlflow_manager=None):
        import mlflow

        if mlflow_manager:
            mlflow_manager.criar_run(run_name=nome)

        try:
            pipe, met = self.treinar(nome, estimador, X_tr, y_tr, X_te, y_te)
            if mlflow_manager:
                mlflow.log_params({f"modelo__{k}": str(v)[:100] for k, v in estimador.get_params().items()})
                mlflow.log_metrics(met)
                mlflow.sklearn.log_model(pipe, name=nome)
            return pipe, met
        finally:
            if mlflow_manager:
                mlflow.end_run()
