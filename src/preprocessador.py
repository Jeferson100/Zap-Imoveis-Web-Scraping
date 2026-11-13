import logging

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_squared_log_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer, OneHotEncoder, StandardScaler, PowerTransformer
from sklearn.utils.validation import check_is_fitted

logger = logging.getLogger(__name__)

# Funcoes cruas, aplicadas coluna a coluna por TransformadorPorColuna.
TRANSFORM_FUNCS = {"log": np.log1p, "sqrt": np.sqrt}
TRANSFORM_INVERSA = {"log": np.expm1, "sqrt": np.square}


class TransformadorPorColuna(BaseEstimator, TransformerMixin):
    """Aplica a transformacao apenas nas colunas estritamente nao-negativas.

    log/sqrt em coluna negativa gera NaN, e o passo `cleanup` seguinte converte
    esse NaN em 0.0: a feature vira uma coluna de zeros e o modelo nem avisa.
    Foi assim que lat (-26) e lng (-49) deixaram de existir em producao.

    PowerTransformer (box-cox / yeo-johnson) nao passa por aqui: ja e ajustado
    por coluna e cuida do proprio dominio.
    """

    def __init__(self, metodo="log"):
        # `metodo`, nao `transform`: um atributo chamado `transform` sombrearia
        # o metodo transform() exigido pelo sklearn.
        self.metodo = metodo

    def fit(self, X, y=None):
        Xa = np.asarray(X, dtype=np.float64)
        self.positivas_ = np.all(np.isfinite(Xa) & (Xa >= 0), axis=0)
        omitidas = int((~self.positivas_).sum())
        if omitidas:
            logger.warning(
                "transform=%s ignorada em %d coluna(s) com valores negativos",
                self.metodo, omitidas,
            )
        return self

    def transform(self, X):
        Xa = np.asarray(X, dtype=np.float64).copy()
        Xa[:, self.positivas_] = TRANSFORM_FUNCS[self.metodo](Xa[:, self.positivas_])
        return Xa

    def inverse_transform(self, X):
        Xa = np.asarray(X, dtype=np.float64).copy()
        Xa[:, self.positivas_] = TRANSFORM_INVERSA[self.metodo](Xa[:, self.positivas_])
        return Xa

    def get_feature_names_out(self, input_features=None):
        """One-to-one: os nomes de entrada passam intactos.

        Contrato que o FunctionTransformer antigo cumpria via
        `feature_names_out="one-to-one"`. Sem ele,
        `ColumnTransformer.get_feature_names_out()` levanta AttributeError e o
        `_agregar_importancias_por_feature` do teste incremental engolia o erro,
        seguia com tamanhos desalinhados e estourava IndexError FORA do try —
        derrubando o run inteiro depois de ~90 min de busca.
        """
        check_is_fitted(self, "positivas_")
        n = self.positivas_.size
        if input_features is None:
            return np.asarray([f"x{i}" for i in range(n)], dtype=object)
        nomes = np.asarray(input_features, dtype=object)
        if nomes.shape[0] != n:
            raise ValueError(
                f"input_features tem {nomes.shape[0]} nomes, esperado {n}"
            )
        return nomes


TRANSFORM_MAP = {
    None: "none",
    "log": "log1p",
    "sqrt": "sqrt",
    "boxcox": "box-cox",
    "yeojohnson": "yeo-johnson",
}

TRANSFORMACOES = {
    None: None,
    "log": TransformadorPorColuna(metodo="log"),
    "sqrt": TransformadorPorColuna(metodo="sqrt"),
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


# Tipos confiáveis para serialização skops usada pelo mlflow.sklearn.log_model.
# O pipeline contém funções custom (_replace_inf/_cleanup_transform) e modelos
# de árvore (sklearn.tree._tree.Tree) que o skops bloqueia por padrão.
# Todos são gerados no próprio processo de treino, portanto seguros.
SKOPS_TRUSTED_TYPES = [
    "numpy.dtype",
    "preprocessador._replace_inf",
    "preprocessador._cleanup_transform",
    "preprocessador.TransformadorPorColuna",
    "calibracao.CalibradorIsotonico",
    "sklearn.tree._tree.Tree",
    # Regressores de terceiros candidatos em FactoryModelos (otimizador_optuna):
    # sem eles, o mês em que vencerem quebra o log_model no MLflow.
    "catboost.core.CatBoostRegressor",
    "lightgbm.sklearn.LGBMRegressor",
    "xgboost.sklearn.XGBRegressor",
]


class PreprocessadorFactory:
    """Cria ColumnTransformers para pre-processamento de features."""

    def __init__(self, numeric_features, categorical_features, categorical_max_categories=None):
        self.numeric_features = list(numeric_features)
        self.categorical_features = list(categorical_features)
        self.categorical_max_categories = categorical_max_categories or {}

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

        transformers = []
        if self.numeric_features:
            transformers.append(("num", numeric_pipe, self.numeric_features))

        if self.categorical_features:
            groups = {}
            for feat in self.categorical_features:
                mc = self.categorical_max_categories.get(feat, 30)
                groups.setdefault(mc, []).append(feat)

            if encoder is not None and len(groups) <= 1:
                cat_pipe = Pipeline([
                    ("imputer", imputer_cat),
                    ("ohe", encoder),
                ])
                transformers.append(("cat", cat_pipe, self.categorical_features))
            else:
                for i, (mc, feats) in enumerate(groups.items()):
                    ohe = OneHotEncoder(handle_unknown="ignore", max_categories=mc, sparse_output=False)
                    cat_pipe = Pipeline([
                        ("imputer", imputer_cat),
                        ("ohe", ohe),
                    ])
                    transformers.append((f"cat_{i}", cat_pipe, feats))

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
                mlflow.sklearn.log_model(pipe, name=nome, skops_trusted_types=SKOPS_TRUSTED_TYPES)
            return pipe, met
        finally:
            if mlflow_manager:
                mlflow.end_run()
