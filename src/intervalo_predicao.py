"""Wrapper para predicao com intervalo de confianca via Conformal Prediction (MAPIE)."""

import numpy as np
import joblib
import logging

logger = logging.getLogger(__name__)

try:
    from mapie.regression import SplitConformalRegressor
    _MAPIE_DISPONIVEL = True
except ImportError:
    _MAPIE_DISPONIVEL = False
    logger.warning("MAPIE nao instalado. `pip install mapie`")


class PreditorComIntervalo:
    """Wrapper que adiciona intervalo de predicao via conformal prediction.

    Requer um pipeline sklearn ja treinado + um conjunto de calibracao
    (held-out, nao usado no treino) para computar os nonconformity scores.

    Parameters
    ----------
    alpha : float
        Nivel de significancia (default 0.1 → intervalo de 90%).

    Uso
    ----
    >>> pipe = joblib.load("modelo.joblib")
    >>> pred = PreditorComIntervalo(alpha=0.1)
    >>> pred.fit(pipe, X_cal, y_cal)
    >>> y_pred, y_lo, y_hi = pred.predict(X_novo)
    """

    def __init__(self, alpha: float = 0.1):
        if not _MAPIE_DISPONIVEL:
            raise ImportError("MAPIE necessario. Instale com `pip install mapie`")
        self.alpha = alpha
        self.mapie_: SplitConformalRegressor | None = None
        self.estimador_ = None

    def fit(self, pipe, X_cal, y_cal):
        """Calibra o intervalo conformal usando dados held-out.

        O pipeline `pipe` deve estar ja treinado (pre-fitted).
        `X_cal`, `y_cal` sao dados de calibracao SEPARADOS dos dados de treino.
        """
        self.estimador_ = pipe
        self.mapie_ = SplitConformalRegressor(
            estimator=pipe,
            confidence_level=1.0 - self.alpha,
            prefit=True,
        )
        self.mapie_.conformalize(X_cal, y_cal)
        logger.info(
            "Intervalo conformal calibrado: alpha=%.2f, cal=%d amostras",
            self.alpha, len(X_cal),
        )
        return self

    def predict(self, X, alpha: float | None = None):
        """Retorna (y_pred, y_lo, y_hi)."""
        y_pred = self.mapie_.predict(X)
        _, intervals = self.mapie_.predict_interval(X)
        y_lo = intervals[:, 0, 0]
        y_hi = intervals[:, 1, 0]
        return y_pred.ravel(), y_lo, y_hi

    def save(self, path):
        """Salva o preditor + estimador em um .joblib."""
        joblib.dump({
            "mapie": self.mapie_,
            "estimador": self.estimador_,
        }, path, compress=3)
        logger.info("PreditorComIntervalo salvo: %s", path)

    @classmethod
    def load(cls, path):
        """Carrega um PreditorComIntervalo salvo."""
        data = joblib.load(path)
        obj = cls()
        obj.mapie_ = data["mapie"]
        obj.estimador_ = data["estimador"]
        return obj
