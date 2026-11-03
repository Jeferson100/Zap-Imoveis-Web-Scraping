"""Treina o classificador de fotos: ambiente e conservacao.

Input do modelo: SOMENTE a imagem. Rotulos humanos de dados/rotulos_conservacao.csv.
Expansao com fotos irmas (rotulo fraco) fica desligada por padrao: EXPANDIR=1.

Uso:
    uv run python scripts/treinar_classificador_fotos.py
    RAPIDO=1 uv run python scripts/treinar_classificador_fotos.py
    LIMITE=80 RAPIDO=1 TAREFA=ambiente uv run python scripts/treinar_classificador_fotos.py

Env: TAREFA, FOLDS, EPOCAS, IMG_SIZE, BATCH, PACIENCIA, EXPANDIR, SIBLINGS_MAX,
     MODELO_BASE, RAPIDO, LIMITE, SAIDA.
"""
import json
import logging
import os
import random
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from classificador_fotos import (AMBIENTES, LABELS, REPO, baixar_todas,
                                 bootstrap_ic, carregar_checkpoint, definir_seed,
                                 metricas_tarefa, prever_caminhos, treinar_fold)

from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

logger = logging.getLogger("treino")


class _SemRuido(logging.Filter):
    RUINS = ("httpx", "httpcore", "urllib3", "huggingface_hub", "filelock", "PIL")

    def filter(self, record):
        return not record.name.startswith(self.RUINS)


def configurar_log(pasta):
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
    arquivo = logging.FileHandler(pasta / "treino.log", encoding="utf-8")
    for h in (logging.StreamHandler(), arquivo):
        h.setFormatter(fmt)
        h.addFilter(_SemRuido())
        raiz.addHandler(h)
    for nome in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(nome).setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.ERROR)


def salvar_estado(pasta, dados):
    tmp = pasta / "estado.json.tmp"
    tmp.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, pasta / "estado.json")

PARQUET = sorted((REPO / "dados" / "joinville").glob("*imoveis_limpo*.parquet"))[-1]
HUMANO = REPO / "dados" / "rotulos_conservacao.csv"

TAREFA = os.getenv("TAREFA", "ambas")
FOLDS = int(os.getenv("FOLDS", "5"))
EPOCAS = int(os.getenv("EPOCAS", "18"))
IMG = int(os.getenv("IMG_SIZE", "192"))
BATCH = int(os.getenv("BATCH", "24"))
PACIENCIA = int(os.getenv("PACIENCIA", "4"))
SELECAO = os.getenv("SELECAO", "logloss")
EXPANDIR = os.getenv("EXPANDIR", "0") == "1"
SIBLINGS = int(os.getenv("SIBLINGS_MAX", "8"))
HOLDOUT = float(os.getenv("HOLDOUT", "0.2"))
LIMITE = int(os.getenv("LIMITE", "0"))
BASE = os.getenv("MODELO_BASE", "facebook/convnext-tiny-224")
SAIDA = Path(os.getenv("SAIDA", str(REPO / "dados" / "modelo_fotos")))
RAPIDO = os.getenv("RAPIDO", "0") == "1"
if RAPIDO:
    FOLDS, EPOCAS, IMG, BATCH, PACIENCIA = 3, 6, 160, 32, 2


def fotos_por_anuncio(anuncios):
    d = pd.read_parquet(PARQUET, columns=["url", "fotos"])
    m = d[d["url"].isin(set(anuncios))]
    return {u: list(fs) for u, fs in zip(m["url"], m["fotos"])}


def montar_quadro(expandir):
    hum = pd.read_csv(HUMANO, dtype=str, keep_default_na=False)
    mapa = fotos_por_anuncio(hum["url_anuncio"]) if expandir else {}
    rng = random.Random(42)
    linhas = []
    for _, r in hum.iterrows():
        linhas.append({"url_foto": r["url_foto"], "y": LABELS.index(r["label"]),
                       "peso": 1.0, "origem": "humano", "url_anuncio": r["url_anuncio"]})
        if expandir:
            extras = [f for f in mapa.get(r["url_anuncio"], []) if f != r["url_foto"]]
            rng.shuffle(extras)
            for f in extras[:SIBLINGS]:
                linhas.append({"url_foto": f, "y": LABELS.index(r["label"]),
                               "peso": 0.5, "origem": "fraco", "url_anuncio": r["url_anuncio"]})
    return pd.DataFrame(linhas)


def limitar(df, n):
    if not n:
        return df
    por_classe = max(1, n // df["y"].nunique())
    return df.groupby("y", group_keys=False).head(por_classe).reset_index(drop=True)


def preparar(df):
    ok, falhas = baixar_todas(df["url_foto"])
    if falhas:
        logger.warning("falhas de download: %d", len(falhas))
    df = df[df["url_foto"].isin(ok)].copy()
    df["path"] = df["url_foto"].map(ok)
    return df, falhas


def dividir(df, tarefa):
    y = df["y"].values
    n_splits = min(FOLDS, int(np.bincount(y).min()))
    if n_splits < 2:
        raise SystemExit(f"poucas amostras por classe para {FOLDS} folds: {np.bincount(y).tolist()}")
    if tarefa == "conservacao" and df["url_anuncio"].nunique() > 0:
        sk = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)
        splits = list(sk.split(df, y, df["url_anuncio"].values))
    else:
        sk = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        splits = list(sk.split(df, y))
    for tr, va in splits:
        assert not (set(df["url_anuncio"].iloc[tr]) & set(df["url_anuncio"].iloc[va]))
    return splits


def metrica_de(nomes):
    """QWK para alvo ordenado, balanced acc para binario; nunca devolve NaN."""
    if len(nomes) > 2:
        def base(a, b):
            return cohen_kappa_score(a, b, weights="quadratic")
    else:
        base = balanced_accuracy_score

    def segura(a, b):
        a, b = np.asarray(a), np.asarray(b)
        v = base(a, b)
        return float(v) if np.isfinite(v) else float((a == b).mean())

    return segura


def separar_holdout(df, tarefa):
    """Reserva uma fatia que nunca entra no CV, para uma nota final sem vies."""
    if HOLDOUT <= 0:
        return df, df.iloc[0:0]
    n_splits = max(2, int(round(1 / HOLDOUT)))
    y = df["y"].values
    if tarefa == "conservacao":
        sk = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=42)
        partes = list(sk.split(df, y, df["url_anuncio"].values))
    else:
        sk = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        partes = list(sk.split(df, y))
    ajuste, teste = partes[0]
    return df.iloc[ajuste].reset_index(drop=True), df.iloc[teste].reset_index(drop=True)


def probs_ensemble(df, tarefa, nomes, size=None):
    """Probabilidade media (softmax) dos folds do CV, para fotos fora do CV."""
    prob = np.zeros((len(df), len(nomes)), dtype=np.float32)
    usados = 0
    for k in range(1, FOLDS + 1):
        caminho = SAIDA / tarefa / f"fold{k}.pt"
        if not caminho.exists():
            continue
        modelo, ck = carregar_checkpoint(caminho)
        prob += prever_caminhos(modelo, ck["base"], df["path"].values, size=size or IMG)
        usados += 1
    if not usados:
        return None, 0
    return prob / usados, usados


def avaliar_holdout(df, tarefa, nomes, size=None):
    if not len(df):
        return None
    prob, usados = probs_ensemble(df, tarefa, nomes, size=size)
    if prob is None:
        return None
    res = metricas_tarefa(df["y"].values, prob, nomes)
    res["ic"] = bootstrap_ic(df["y"].values, prob, metrica_de(nomes))
    res["folds_ensemble"] = usados
    return res


def rodar(tarefa, df):
    nomes = LABELS if tarefa == "conservacao" else AMBIENTES
    n_classes = len(nomes)
    splits = dividir(df, tarefa)
    oof = np.zeros((len(df), n_classes), dtype=np.float32)
    fold_de = np.zeros(len(df), dtype=int)
    folds = []
    metrica_segura = metrica_de(nomes)
    pasta = SAIDA / tarefa
    pasta.mkdir(parents=True, exist_ok=True)

    for k, (tr, va) in enumerate(splits, 1):
        logger.info("%s fold %d/%d: treino=%d val=%d | classes treino=%s",
                    tarefa, k, len(splits), len(tr), len(va),
                    np.bincount(df.iloc[tr]["y"].values, minlength=n_classes).tolist())

        def callback(info, tarefa=tarefa, k=k):
            salvar_estado(SAIDA, {"tarefa": tarefa, "fold": k, "folds": len(splits),
                                  **info,
                                  "atualizado": datetime.now().isoformat(timespec="seconds")})

        modelo, hist, prob = treinar_fold(
            df.iloc[tr], df.iloc[va], BASE, n_classes,
            size=IMG, epocas=EPOCAS, batch=BATCH,
            lr_backbone=5e-5 if tarefa == "conservacao" else 3e-5,
            lr_head=1e-3, congelar_epocas=2, paciencia=PACIENCIA,
            selecao=SELECAO, callback=callback,
        )
        oof[va] = prob
        fold_de[va] = k
        y_va = df["y"].values[va]
        nota = metrica_segura(y_va, prob.argmax(1))
        melhor = (min(hist, key=lambda h: h["logloss"]) if SELECAO == "logloss"
                  else max(hist, key=lambda h: h["val"]))
        folds.append({"fold": k, "n_val": int(len(va)), "nota": float(nota),
                      "epoca_selecionada": melhor["epoca"], "historico": hist})
        torch.save({"state_dict": modelo.state_dict(), "base": BASE,
                    "n_classes": n_classes, "nomes": nomes, "img": IMG},
                   pasta / f"fold{k}.pt")
        logger.info("%s fold %d: nota=%.3f (epoca selecionada %d de %d, %.1fs)",
                    tarefa, k, nota, melhor["epoca"], len(hist),
                    melhor.get("tempo_s", 0.0))

    y = df["y"].values
    resumo = metricas_tarefa(y, oof, nomes)
    resumo["ic"] = bootstrap_ic(y, oof, metrica_segura)
    resumo["n_rotulos_humanos"] = int((df["origem"] == "humano").sum())
    resumo["n_rotulos_fracos"] = int((df["origem"] == "fraco").sum())
    resumo["folds"] = folds
    resumo["n_treino_medio"] = float(np.mean([len(tr) for tr, _ in splits]))

    # grava as probabilidades aqui: o notebook nao depende mais de um script extra
    ordenado = np.sort(oof, axis=1)
    tabela = pd.DataFrame({
        "url_foto": df["url_foto"].values,
        "url_anuncio": df["url_anuncio"].values,
        "origem": df["origem"].values,
        "fold": fold_de,
        "y": y,
        "pred": oof.argmax(1),
        "margem": ordenado[:, -1] - ordenado[:, -2],
    })
    for i in range(n_classes):
        tabela[f"p{i}"] = oof[:, i]
    tabela.to_csv(SAIDA / f"probs_oof_{tarefa}_{IMG}.csv", index=False)
    return resumo, oof


def main():
    definir_seed()
    SAIDA.mkdir(parents=True, exist_ok=True)
    configurar_log(SAIDA)
    salvar_estado(SAIDA, {"status": "iniciado", "tarefa": TAREFA,
                          "atualizado": datetime.now().isoformat(timespec="seconds")})
    resultados = {"base": BASE, "gerado": datetime.now().isoformat(timespec="seconds"),
                  "input": "somente imagem",
                  "n_rotulos": int(len(pd.read_csv(HUMANO))),
                  "config": {"tarefa": TAREFA, "folds": FOLDS, "epocas": EPOCAS,
                             "img": IMG, "batch": BATCH, "paciencia": PACIENCIA,
                             "selecao": SELECAO, "expandir": EXPANDIR,
                             "siblings_max": SIBLINGS, "holdout": HOLDOUT,
                             "limite": LIMITE, "rapido": RAPIDO,
                             "parquet": str(PARQUET)}}

    if TAREFA in ("ambiente", "ambas"):
        hum = pd.read_csv(HUMANO, dtype=str, keep_default_na=False)
        df_amb = hum[hum["ambiente"].isin(AMBIENTES)].copy()
        df_amb["y"] = df_amb["ambiente"].map(AMBIENTES.index)
        df_amb["peso"] = 1.0
        df_amb["origem"] = "humano"
        df_amb = limitar(df_amb, LIMITE)
        df_amb, falhas = preparar(df_amb)
        df_cv, df_ho = separar_holdout(df_amb, "ambiente")
        resultados["ambiente"], oof_a = rodar("ambiente", df_cv)
        resultados["ambiente"]["falhas_download"] = len(falhas)
        resultados["ambiente"]["holdout"] = avaliar_holdout(df_ho, "ambiente", AMBIENTES)
        pd.DataFrame({"url_foto": df_cv["url_foto"], "y": df_cv["y"],
                      "pred": oof_a.argmax(1)}).to_csv(SAIDA / "oof_ambiente.csv", index=False)

    if TAREFA in ("conservacao", "ambas"):
        df_con = limitar(montar_quadro(expandir=EXPANDIR), LIMITE)
        df_con, falhas = preparar(df_con)
        df_cv, df_ho = separar_holdout(df_con, "conservacao")
        resultados["conservacao"], oof_c = rodar("conservacao", df_cv)
        resultados["conservacao"]["falhas_download"] = len(falhas)
        resultados["conservacao"]["holdout"] = avaliar_holdout(df_ho, "conservacao", LABELS)
        pd.DataFrame({"url_foto": df_cv["url_foto"], "url_anuncio": df_cv["url_anuncio"],
                      "origem": df_cv["origem"], "peso": df_cv["peso"],
                      "y": df_cv["y"], "pred": oof_c.argmax(1)}).to_csv(
            SAIDA / "oof_conservacao.csv", index=False)

    destino = SAIDA / "metricas_fotos.json"
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, destino)
    salvar_estado(SAIDA, {"status": "concluido", "gerado": resultados["gerado"],
                          "atualizado": datetime.now().isoformat(timespec="seconds")})
    logger.info("metricas: %s", destino)
    for tarefa in ("ambiente", "conservacao"):
        if tarefa in resultados:
            r = resultados[tarefa]
            chave = "kappa" if "kappa" in r else "balanced_acc"
            logger.info("%s: %s=%.3f ic=%s", tarefa, chave, r[chave],
                        [round(v, 3) for v in r["ic"]])
            h = r.get("holdout")
            if h:
                logger.info("%s holdout: n=%d %s=%.3f ic=%s bal_acc=%.3f macro_f1=%.3f",
                            tarefa, h["n"], chave, h[chave], [round(v, 3) for v in h["ic"]],
                            h["balanced_acc"], h["macro_f1"])


if __name__ == "__main__":
    main()
