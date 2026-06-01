import numpy as np
import pandas as pd
from typing import Tuple

def clean_target(X, y, max_abs_value: float = 1e200) -> Tuple:
    """Limpa y removendo NaN e Inf e alinha X com y.

    - Converte y para Series numérica (coerce errors -> NaN).
    - Marca valores NaN, Inf ou abs(y) > max_abs_value como inválidos.
    - Remove as linhas correspondentes em X e y mantendo tipo de X (np.ndarray or pd.DataFrame).

    Retorna: X_clean, y_clean
    """
    # preparar y
    y_ser = pd.to_numeric(pd.Series(y).copy(), errors="coerce")

    # preparar X para alinhamento (converter em DataFrame temporariamente)
    X_is_df = isinstance(X, pd.DataFrame)
    try:
        X_df = X.copy() if X_is_df else pd.DataFrame(X)
    except Exception:
        X_df = pd.DataFrame(np.asarray(X))

    # alinhar índices: use interseção de índices se possível
    common_index = X_df.index.intersection(y_ser.index)
    if len(common_index) == 0:
        min_len = min(len(X_df), len(y_ser))
        if len(X_df) != len(y_ser):
            print(f"clean_target: índices diferentes, truncando X/y para {min_len}")
        X_df = X_df.iloc[:min_len].copy()
        y_ser = y_ser.iloc[:min_len].copy()
    else:
        X_df = X_df.loc[common_index].copy()
        y_ser = y_ser.loc[common_index].copy()

    # detectar infinitos e valores absurdos após alinhamento
    bad_mask = y_ser.isna() | np.isinf(y_ser) | (y_ser.abs() > max_abs_value)
    n_bad = int(bad_mask.sum())
    if n_bad > 0:
        print(f"clean_target: removendo {n_bad} observações com NaN/Inf/valores extremos de y")

    keep_mask = ~bad_mask
    X_clean = X_df.loc[keep_mask].copy()
    y_clean = y_ser.loc[keep_mask].copy().reset_index(drop=True)

    # devolver no mesmo tipo de X
    if not X_is_df:
        X_out = X_clean.values
    else:
        X_out = X_clean

    return X_out, y_clean
