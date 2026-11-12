"""Calibracao monotonica pos-modelo, no espaco do alvo.

Motivo medido (Joinville 2026-11, teste honesto): o modelo de preco encolhe as
caudas. Vies mediano por faixa de preco:

    Q1 <400k     +4,3%
    Q2 400-650k  +1,5%
    Q3 650-920k  +1,3%
    Q4 920k-1.5M -2,0%
    Q5 >1.5M     -6,2%

Isso e regressao a media, nao falta de feature (as candidatas tabulares ja foram
testadas e estao saturadas). Como o alvo ja e log(preco), uma correcao
monotonica no log e MULTIPLICATIVA em R$, que e exatamente o formato do erro:
o erro relativo e quase constante entre as faixas.

O isotonic e ajustado sobre predicoes OUT-OF-FOLD. Ajusta-lo sobre o treino
faria ele aprender o overfitting do modelo base e piorar a vida fora da amostra.
"""

import logging

import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin, clone
from sklearn.isotonic import IsotonicRegression
from sklearn.model_selection import KFold

logger = logging.getLogger(__name__)


class CalibradorIsotonico(BaseEstimator, RegressorMixin):
    """Envolve um estimador e corrige a saida com uma isotonic aprendida em OOF.

    Parameters
    ----------
    estimador : estimator
        Modelo base ja configurado (classe ou instancia). E clonado no fit, entao
        o objeto passado nao e modificado.
    n_folds : int
        Folds da CV interna usada para gerar as predicoes OOF.
    ganho_minimo : float
        Se a correcao nao reduzir o MAE em CV, ela e descartada e o modelo
        publicado fica igual ao base. Protege contra calibrar ruido.
    """

    def __init__(self, estimador=None, n_folds=5, random_state=42, ganho_minimo=0.0):
        self.estimador = estimador
        self.n_folds = n_folds
        self.random_state = random_state
        self.ganho_minimo = ganho_minimo

    def _sub(self, X, idx):
        return X.iloc[idx] if hasattr(X, "iloc") else X[idx]

    def fit(self, X, y):
        if self.estimador is None:
            raise ValueError("CalibradorIsotonico exige `estimador`")

        y = np.asarray(y, dtype=np.float64)
        oof = np.full(len(y), np.nan, dtype=np.float64)
        for idx_fit, idx_pred in KFold(
            self.n_folds, shuffle=True, random_state=self.random_state
        ).split(X):
            fold = clone(self.estimador).fit(self._sub(X, idx_fit), y[idx_fit])
            oof[idx_pred] = fold.predict(self._sub(X, idx_pred))

        valido = np.isfinite(oof) & np.isfinite(y)
        if valido.sum() < 50:
            raise ValueError(
                f"CalibradorIsotonico: apenas {int(valido.sum())} linhas validas"
            )

        self.calibrador_ = IsotonicRegression(out_of_bounds="clip")
        self.calibrador_.fit(oof[valido], y[valido])

        mae_antes = float(np.mean(np.abs(oof[valido] - y[valido])))
        mae_depois = float(np.mean(np.abs(self.calibrador_.predict(oof[valido]) - y[valido])))
        self.mae_cv_antes_ = mae_antes
        self.mae_cv_depois_ = mae_depois
        self.aplicado_ = bool(mae_antes - mae_depois > self.ganho_minimo)

        logger.info(
            "Calibracao isotonica: MAE CV %.4f -> %.4f (ganho %.4f) | %s",
            mae_antes, mae_depois, mae_antes - mae_depois,
            "ATIVA" if self.aplicado_ else "descartada",
        )

        # O modelo final sempre e ajustado em todos os dados; se a calibracao for
        # descartada, `predict` apenas devolve a saida dele.
        self.estimador_ = clone(self.estimador).fit(X, y)
        return self

    def predict(self, X):
        p = self.estimador_.predict(X)
        return self.calibrador_.predict(p) if self.aplicado_ else p

    def __repr__(self):
        if not hasattr(self, "aplicado_"):
            return "CalibradorIsotonico(não ajustado)"
        return (
            f"CalibradorIsotonico({'ativo' if self.aplicado_ else 'inativo'}, "
            f"MAE_cv {self.mae_cv_antes_:.4f}->{self.mae_cv_depois_:.4f})"
        )
