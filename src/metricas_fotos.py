"""Indices padrao de classificacao a partir das probabilidades.

Recebe `y` (rotulo humano) e `prob` (B x classes) e devolve acuracia, acuracia
balanceada, F1 macro/ponderado e, por classe, precisao, recall (sensibilidade),
especificidade, F1 e suporte.
"""
import numpy as np
import pandas as pd
from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                             confusion_matrix, f1_score,
                             precision_recall_fscore_support)


def _normalizar(prob):
    p = np.asarray(prob, dtype=np.float64)
    return p / p.sum(axis=1, keepdims=True)


def indices(y, prob, nomes):
    """Acuracia, F1 e matriz de confusao, com P/R/F1/especificidade por classe."""
    y = np.asarray(y, dtype=int)
    p = _normalizar(prob)
    pred = p.argmax(1)
    k = len(nomes)
    pr, rc, f1, sup = precision_recall_fscore_support(
        y, pred, labels=range(k), zero_division=0)
    cm = confusion_matrix(y, pred, labels=range(k))
    total = cm.sum()
    classes = {}
    esp = []
    for i, nome in enumerate(nomes):
        tp = int(cm[i, i])
        fn = int(cm[i, :].sum() - tp)
        fp = int(cm[:, i].sum() - tp)
        tn = int(total - tp - fn - fp)
        e = tn / max(tn + fp, 1)
        esp.append(e)
        classes[nome] = {"precisao": float(pr[i]), "recall": float(rc[i]),
                         "especificidade": float(e), "f1": float(f1[i]),
                         "n": int(sup[i])}
    return {
        "n": int(len(y)),
        "nomes": list(nomes),
        "acc": float(accuracy_score(y, pred)),
        "balanced_acc": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "weighted_f1": float(f1_score(y, pred, average="weighted", zero_division=0)),
        "especificidade_macro": float(np.mean(esp)),
        "matriz": cm.tolist(),
        "por_classe": classes,
    }


def tabela_indices(resultados):
    """Resumo em uma linha por tarefa."""
    linhas = [{"tarefa": tarefa, "n": r["n"], "acc": r["acc"],
               "balanced_acc": r["balanced_acc"], "macro_f1": r["macro_f1"],
               "weighted_f1": r["weighted_f1"],
               "especificidade_macro": r["especificidade_macro"]}
              for tarefa, r in resultados.items()]
    return pd.DataFrame(linhas)


def tabela_classes(res):
    """Precisao, recall, especificidade, F1 e suporte por classe."""
    d = pd.DataFrame(res["por_classe"]).T.rename_axis("classe").reset_index()
    return d.astype({"n": int})


def matriz_normalizada(res):
    """Matriz normalizada por linha (recall por classe na diagonal)."""
    m = np.array(res["matriz"], dtype=float)
    return pd.DataFrame(m / np.maximum(m.sum(1, keepdims=True), 1),
                        index=res["nomes"], columns=res["nomes"])
