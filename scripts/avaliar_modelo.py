"""Avalia o modelo treinado nas imagens, sem treinar nada.

Duas partes:
  1. probabilidades OOF (cada foto prevista pelo fold que nao a viu), em varias
     resolucoes, para ranquear erros por confianca;
  2. consistencia nas fotos irmas (todas as fotos dos anuncios rotulados),
     comparando a classe modal do anuncio com o rotulo humano da foto rotulada.

Uso:
    uv run python scripts/avaliar_modelo.py
    SIZES=192 IRMAOS=0 uv run python scripts/avaliar_modelo.py

Env: SIZES, TAREFAS, IRMAOS, IRMAOS_FOLDS, IRMAOS_TTA, IRMAOS_MAX, WORKERS,
     LADO, BATCH, FOLDS, SAIDA.
"""
import json
import logging
import os
import sys

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from classificador_fotos import (AMBIENTES, LABELS, baixar_todas,
                                 bootstrap_ic, carregar_checkpoint, definir_seed,
                                 metricas_tarefa, prever_caminhos)
import treinar_classificador_fotos as treino

logger = logging.getLogger("avaliacao")


class _SemRuido(logging.Filter):
    RUINS = ("httpx", "httpcore", "urllib3", "huggingface_hub", "filelock", "PIL")

    def filter(self, record):
        return not record.name.startswith(self.RUINS)


SIZES = [int(s) for s in os.getenv("SIZES", "192,224").split(",") if s.strip()]
TAREFAS = [t for t in os.getenv("TAREFAS", "ambiente,conservacao").split(",") if t.strip()]
IRMAOS = os.getenv("IRMAOS", "1") == "1"
WORKERS = int(os.getenv("WORKERS", "6"))
LADO = int(os.getenv("LADO", "384"))
BATCH = int(os.getenv("BATCH", "32"))
FOLDS = int(os.getenv("FOLDS", "5"))
IRMAOS_FOLDS = int(os.getenv("IRMAOS_FOLDS", "3"))
IRMAOS_MAX = int(os.getenv("IRMAOS_MAX", "10"))
IRMAOS_TTA = os.getenv("IRMAOS_TTA", "0") == "1"
SAIDA = treino.SAIDA


def configurar_log():
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
    h = logging.StreamHandler()
    h.setFormatter(fmt)
    h.addFilter(_SemRuido())
    raiz.addHandler(h)
    logging.getLogger("transformers").setLevel(logging.ERROR)


def quadro(tarefa):
    hum = pd.read_csv(treino.HUMANO, dtype=str, keep_default_na=False)
    if tarefa == "ambiente":
        df = hum[hum["ambiente"].isin(AMBIENTES)].copy()
        df["y"] = df["ambiente"].map(AMBIENTES.index)
        df["peso"] = 1.0
        df["origem"] = "humano"
        return treino.limitar(df, treino.LIMITE)
    return treino.limitar(treino.montar_quadro(expandir=False), treino.LIMITE)


def conferir(df, tarefa):
    atual = pd.read_csv(SAIDA / f"oof_{tarefa}.csv")
    if len(atual) != len(df):
        raise SystemExit(f"{tarefa}: {len(df)} fotos agora vs {len(atual)} no treino "
                         "(cache/download mudou); refaca o treino")
    if not (atual["url_foto"].values == df["url_foto"].values).all():
        raise SystemExit(f"{tarefa}: ordem das fotos difere do treino")
    if not (atual["y"].values == df["y"].values).all():
        raise SystemExit(f"{tarefa}: rotulos diferem do treino")
    return atual


def probs_oof(tarefa, df, splits, size):
    pasta = SAIDA / tarefa
    nomes = LABELS if tarefa == "conservacao" else AMBIENTES
    n = len(nomes)
    prob = np.zeros((len(df), n), dtype=np.float32)
    fold_de = np.zeros(len(df), dtype=int)
    notas = []
    for k, (_, va) in enumerate(splits, 1):
        caminho = pasta / f"fold{k}.pt"
        if not caminho.exists():
            raise SystemExit(f"checkpoint ausente: {caminho}")
        modelo, ck = carregar_checkpoint(caminho)
        t0 = time.time()
        prob[va] = prever_caminhos(modelo, ck["base"], df["path"].iloc[va],
                                   size=size, batch=BATCH)
        fold_de[va] = k
        y_va = df["y"].values[va]
        pred = prob[va].argmax(1)
        nota = (cohen_kappa_score(y_va, pred, weights="quadratic") if n > 2
                else balanced_accuracy_score(y_va, pred))
        notas.append(float(nota))
        logger.info("%s %dpx fold %d/%d: %s=%.3f (%.0fs)", tarefa, size, k,
                    len(splits), "kappa" if n > 2 else "bal_acc", nota,
                    time.time() - t0)
    return prob, fold_de, notas


def avaliar_tarefa(tarefa):
    df = quadro(tarefa)
    df, falhas = treino.preparar(df)
    df_cv, df_ho = treino.separar_holdout(df, tarefa)
    atual = conferir(df_cv, tarefa)
    splits = treino.dividir(df_cv, tarefa)
    nomes = LABELS if tarefa == "conservacao" else AMBIENTES
    n = len(nomes)

    def metrica(a, b):
        v = (cohen_kappa_score(a, b, weights="quadratic") if n > 2
             else balanced_accuracy_score(a, b))
        return v if np.isfinite(v) else float((a == b).mean())

    info = {"n": int(len(df_cv)), "n_holdout": int(len(df_ho)),
            "falhas_download": len(falhas), "resolucoes": {}}
    for size in SIZES:
        prob, fold_de, notas = probs_oof(tarefa, df_cv, splits, size)
        pred = prob.argmax(1)
        ordenado = np.sort(prob, axis=1)
        tabela = {
            "url_foto": df_cv["url_foto"].values,
            "fold": fold_de,
            "y": df_cv["y"].values,
            "pred": pred,
            "margem": ordenado[:, -1] - ordenado[:, -2],
        }
        if "url_anuncio" in df_cv.columns:
            tabela["url_anuncio"] = df_cv["url_anuncio"].values
        saida = pd.DataFrame(tabela)
        for i in range(n):
            saida[f"p{i}"] = prob[:, i]
        saida.to_csv(SAIDA / f"oof_probs_{tarefa}_{size}.csv", index=False)

        m = metricas_tarefa(df_cv["y"].values, prob, nomes)
        m["ic"] = bootstrap_ic(df_cv["y"].values, prob, metrica)
        m["folds"] = notas
        m["media_folds"] = float(np.mean(notas))
        m["dp_folds"] = float(np.std(notas))
        if size == SIZES[0]:
            div = int((pred != atual["pred"].values).sum())
            m["divergentes_vs_treino"] = div
            logger.info("%s: pred divergente do treino em %d/%d fotos",
                        tarefa, div, len(df_cv))
            m["holdout"] = treino.avaliar_holdout(df_ho, tarefa, nomes, size=size)
            ho = m["holdout"]
            if ho:
                logger.info("%s %dpx holdout: n=%d %s=%.3f bal_acc=%.3f macro_f1=%.3f",
                            tarefa, size, ho["n"], "kappa" if n > 2 else "balanced_acc",
                            ho["kappa"] if n > 2 else ho["balanced_acc"],
                            ho["balanced_acc"], ho["macro_f1"])
        chave = "kappa" if n > 2 else "balanced_acc"
        logger.info("%s %dpx: %s=%.3f ic=%s acc=%.3f macro_f1=%.3f",
                    tarefa, size, chave, m[chave],
                    [round(v, 3) for v in m["ic"]], m["acc"], m["macro_f1"])
        info["resolucoes"][str(size)] = m
    return info


def irmaos():
    hum = pd.read_csv(treino.HUMANO, dtype=str, keep_default_na=False)
    mapa = treino.fotos_por_anuncio(hum["url_anuncio"])
    linhas = [(u, a) for a, fs in mapa.items() for u in fs[:IRMAOS_MAX]]
    df = (pd.DataFrame(linhas, columns=["url_foto", "url_anuncio"])
          .drop_duplicates("url_foto").reset_index(drop=True))
    logger.info("irmas: %d fotos em %d anuncios (max %d por anuncio)",
                len(df), df["url_anuncio"].nunique(), IRMAOS_MAX)

    ok, falhas = baixar_todas(df["url_foto"], lado=LADO, workers=WORKERS)
    df = df[df["url_foto"].isin(ok)].copy()
    df["path"] = df["url_foto"].map(ok)
    logger.info("irmas: %d ok, %d falhas de download", len(df), len(falhas))
    if df.empty:
        return {"n_fotos": 0, "falhas": len(falhas)}

    saida = df[["url_foto", "url_anuncio"]].copy()
    resumo = {"n_fotos": int(len(df)), "n_falhas": int(len(falhas)),
              "n_anuncios": int(df["url_anuncio"].nunique())}
    for tarefa in ("ambiente", "conservacao"):
        nomes = LABELS if tarefa == "conservacao" else AMBIENTES
        prob = np.zeros((len(df), len(nomes)), dtype=np.float32)
        usados = 0
        for k in range(1, min(FOLDS, IRMAOS_FOLDS) + 1):
            caminho = SAIDA / tarefa / f"fold{k}.pt"
            if not caminho.exists():
                continue
            modelo, ck = carregar_checkpoint(caminho)
            t0 = time.time()
            prob += prever_caminhos(modelo, ck["base"], df["path"].values,
                                    size=192, batch=BATCH, tta=IRMAOS_TTA)
            usados += 1
            logger.info("irmas %s fold %d: %.0fs", tarefa, k, time.time() - t0)
        if not usados:
            continue
        prob /= usados
        saida[f"pred_{tarefa}"] = prob.argmax(1)
        saida[f"grade_{tarefa}"] = prob @ np.arange(len(nomes), dtype=np.float32)
        for i in range(len(nomes)):
            saida[f"{tarefa}_p{i}"] = prob[:, i]
        resumo[f"checkpoints_{tarefa}"] = usados
        logger.info("irmas %s: %d fotos, ensemble de %d folds", tarefa, len(df), usados)
    saida.to_csv(SAIDA / "siblings_probs.csv", index=False)
    if "pred_conservacao" not in saida.columns:
        return resumo

    g = saida.groupby("url_anuncio")
    cons = pd.DataFrame({
        "n_fotos": g.size(),
        "grade_medio": g["grade_conservacao"].mean(),
        "grade_desvio": g["grade_conservacao"].std(ddof=0),
        "frac_interna": g["pred_ambiente"].agg(lambda s: float((s == 0).mean())),
        "pred_modal": g["pred_conservacao"].agg(lambda s: int(s.mode().iloc[0])),
        "frac_modal": g["pred_conservacao"].agg(
            lambda s: float(s.value_counts(normalize=True).iloc[0])),
    })
    hy = hum.assign(y_humano=hum["label"].map({l: i for i, l in enumerate(LABELS)}))
    hy = (hy[["url_anuncio", "y_humano", "bairro", "valor_imovel"]]
          .drop_duplicates("url_anuncio").set_index("url_anuncio"))
    cons = cons.join(hy)
    cons["concorda"] = cons["pred_modal"] == cons["y_humano"]
    cons["dif_grade"] = cons["grade_medio"] - cons["y_humano"]
    cons = cons.reindex(cons["dif_grade"].abs().sort_values(ascending=False).index)
    cons.to_csv(SAIDA / "consistencia_anuncios.csv")

    resumo.update({
        "concordancia_modal": float(cons["concorda"].mean()),
        "frac_modal_medio": float(cons["frac_modal"].mean()),
        "grade_desvio_medio": float(cons["grade_desvio"].mean()),
        "discordantes_1nivel": int((cons["dif_grade"].abs() >= 1).sum()),
    })
    logger.info("consistencia: modal concorda com humano em %.1f%% | desvio medio "
                "intra-anuncio %.2f | %d anuncios com |dif| >= 1",
                100 * resumo["concordancia_modal"], resumo["grade_desvio_medio"],
                resumo["discordantes_1nivel"])
    return resumo


def main():
    definir_seed()
    torch.set_num_threads(8)
    SAIDA.mkdir(parents=True, exist_ok=True)
    configurar_log()
    treino_gerado = json.loads((SAIDA / "metricas_fotos.json")
                               .read_text(encoding="utf-8")).get("gerado")
    resumo = {"gerado": datetime.now().isoformat(timespec="seconds"),
              "treino_gerado": treino_gerado,
              "folds": FOLDS, "sizes": SIZES, "tarefas": {}}
    for tarefa in TAREFAS:
        resumo["tarefas"][tarefa] = avaliar_tarefa(tarefa)
    if IRMAOS:
        resumo["irmas"] = irmaos()
    destino = SAIDA / "metricas_avaliacao.json"
    destino.write_text(json.dumps(resumo, ensure_ascii=False, indent=2, default=float),
                       encoding="utf-8")
    logger.info("metricas: %s", destino)


if __name__ == "__main__":
    main()
