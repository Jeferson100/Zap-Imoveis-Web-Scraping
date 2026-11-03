"""Classificador de fotos de imoveis: ambiente (interna/externa) e conservacao.

O modelo recebe SOMENTE a imagem (pixels). Nenhuma variavel tabular
(bairro, valor, titulo, area, url) entra como feature.

Fine-tune de backbone do transformers (ConvNext/ViT) sem torchvision:
augmentacao e pre-processamento em PIL. Metricas: QWK e balanced accuracy.
"""
import hashlib
import io
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import torch
from PIL import Image, ImageEnhance
from sklearn.metrics import (balanced_accuracy_score, cohen_kappa_score,
                             confusion_matrix, f1_score)
from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold
from transformers import AutoImageProcessor, AutoModel

logger = logging.getLogger(__name__)
logging.getLogger("transformers").setLevel(logging.ERROR)

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / "dados" / "imagens_cache"
LABELS = ["bem conservado", "desgaste leve", "desgastado", "precário"]
AMBIENTES = ["interna", "externa"]
SEED = 42


def definir_seed(semente=SEED):
    random.seed(semente)
    np.random.seed(semente)
    torch.manual_seed(semente)


def _destino(url):
    return CACHE / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ".webp")


def baixar(url, lado=384, forcar=False):
    destino = _destino(url)
    if destino.exists() and not forcar:
        return destino
    CACHE.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=40, follow_redirects=True) as cli:
        r = cli.get(url)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGB")
        img.thumbnail((lado, lado), Image.LANCZOS)
        img.save(destino, "WEBP", quality=85)
    return destino


def baixar_todas(urls, lado=384, workers=8):
    urls = list(dict.fromkeys(urls))
    ok, falhas = {}, []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futuros = {ex.submit(baixar, u, lado): u for u in urls}
        for feitos, f in enumerate(as_completed(futuros), 1):
            u = futuros[f]
            try:
                ok[u] = str(f.result())
            except Exception as e:
                falhas.append((u, f"{type(e).__name__}: {e}"))
            if feitos % 50 == 0 or feitos == len(urls):
                logger.info("cache: %d/%d", feitos, len(urls))
    logger.info("cache: %d ok, %d falhas", len(ok), len(falhas))
    return ok, falhas


def _augmentar(img, size):
    w, h = img.size
    escala = random.uniform(0.7, 1.0)
    cw, ch = max(1, int(w * escala)), max(1, int(h * escala))
    x, y = random.randint(0, w - cw), random.randint(0, h - ch)
    img = img.crop((x, y, x + cw, y + ch)).resize((size, size), Image.BILINEAR)
    if random.random() < 0.5:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if random.random() < 0.5:
        img = img.rotate(random.uniform(-10, 10), resample=Image.BILINEAR)
    if random.random() < 0.5:
        img = ImageEnhance.Color(img).enhance(random.uniform(0.8, 1.2))
        img = ImageEnhance.Brightness(img).enhance(random.uniform(0.85, 1.15))
        img = ImageEnhance.Contrast(img).enhance(random.uniform(0.85, 1.15))
    return img


def _avaliar_preparo(img, size):
    w, h = img.size
    s = int(round(size * 1.14))
    if w <= h:
        nw, nh = s, max(s, int(round(h * s / w)))
    else:
        nw, nh = max(s, int(round(w * s / h))), s
    img = img.resize((nw, nh), Image.BILINEAR)
    w, h = img.size
    esq, topo = (w - size) // 2, (h - size) // 2
    return img.crop((esq, topo, esq + size, topo + size))


class DatasetFotos(torch.utils.data.Dataset):
    """Devolve apenas (imagem, alvo, peso). `path` e a unica coluna usada."""

    COLUNAS = ("path", "y")

    def __init__(self, df, size, treino, media, desvio):
        self.df = df.reset_index(drop=True)
        self.size = size
        self.treino = treino
        self.media = np.asarray(media, dtype=np.float32)
        self.desvio = np.asarray(desvio, dtype=np.float32)

    def __len__(self):
        return len(self.df)

    def __getitem__(self, i):
        r = self.df.iloc[i]
        img = Image.open(r["path"]).convert("RGB")
        img = _augmentar(img, self.size) if self.treino else _avaliar_preparo(img, self.size)
        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - self.media) / self.desvio
        x = torch.from_numpy(np.ascontiguousarray(arr.transpose(2, 0, 1)))
        return x, int(r["y"]), torch.tensor(float(r.get("peso", 1.0)), dtype=torch.float32)


class ModeloFotos(torch.nn.Module):
    """Backbone + cabeca linear. Entrada: pixel_values (B, 3, H, W)."""

    def __init__(self, base, n_classes, dropout=0.2):
        super().__init__()
        self.backbone = AutoModel.from_pretrained(base)
        cfg = self.backbone.config
        dim = getattr(cfg, "hidden_size", None) or cfg.hidden_sizes[-1]
        self.head = torch.nn.Sequential(torch.nn.Dropout(dropout), torch.nn.Linear(dim, n_classes))

    def congelar(self, congelado=True):
        for p in self.backbone.parameters():
            p.requires_grad = not congelado

    def forward(self, pixel_values):
        return self.head(self.backbone(pixel_values=pixel_values).pooler_output)


@torch.no_grad()
def prever(modelo, loader, tta=True):
    modelo.eval()
    saidas = []
    for x, _, _ in loader:
        p = torch.softmax(modelo(x), dim=-1)
        if tta:
            p = (p + torch.softmax(modelo(torch.flip(x, dims=[3])), dim=-1)) / 2
        saidas.append(p.numpy())
    return np.concatenate(saidas)


def _metrica(y, pred, n_classes):
    if n_classes > 2:
        nota = cohen_kappa_score(y, pred, weights="quadratic")
    else:
        nota = balanced_accuracy_score(y, pred)
    if not np.isfinite(nota):
        nota = float((pred == y).mean())
    return nota


def dividir_interna(df, frac=0.2):
    """Separa um split interno do treino para escolher a epoca.

    O fold de validacao que gera o OOF nunca participa da selecao do modelo,
    senao o numero reportado fica otimista.
    """
    n_splits = max(2, int(round(1 / frac)))
    y = df["y"].values
    if "url_anuncio" in df.columns and df["url_anuncio"].nunique() > 0:
        sk = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
        partes = list(sk.split(df, y, df["url_anuncio"].values))
    else:
        sk = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
        partes = list(sk.split(df, y))
    ajuste, selecao = partes[0]
    return (df.iloc[ajuste].reset_index(drop=True),
            df.iloc[selecao].reset_index(drop=True))


def treinar_fold(df_tr, df_va, base, n_classes, size=192, epocas=18, batch=24,
                 lr_backbone=5e-5, lr_head=1e-3, congelar_epocas=2, paciencia=4,
                 frac_interna=0.2, selecao="logloss", callback=None):
    definir_seed()
    proc = AutoImageProcessor.from_pretrained(base)
    media, desvio = proc.image_mean, proc.image_std

    if frac_interna > 0:
        df_ajuste, df_sel = dividir_interna(df_tr, frac_interna)
    else:
        df_ajuste, df_sel = df_tr, df_va

    ds_tr = DatasetFotos(df_ajuste, size, True, media, desvio)
    ds_sel = DatasetFotos(df_sel, size, False, media, desvio)
    ds_va = DatasetFotos(df_va, size, False, media, desvio)
    ld_tr = torch.utils.data.DataLoader(ds_tr, batch_size=batch, shuffle=True, num_workers=0)
    ld_sel = torch.utils.data.DataLoader(ds_sel, batch_size=batch, shuffle=False, num_workers=0)
    ld_va = torch.utils.data.DataLoader(ds_va, batch_size=batch, shuffle=False, num_workers=0)

    modelo = ModeloFotos(base, n_classes)
    modelo.congelar(True)
    opt = torch.optim.AdamW([
        {"params": modelo.backbone.parameters(), "lr": lr_backbone},
        {"params": modelo.head.parameters(), "lr": lr_head},
    ])
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max(1, epocas))

    contagem = np.bincount(df_ajuste["y"].values, minlength=n_classes).astype(np.float32)
    pesos = np.sqrt(len(df_ajuste) / (n_classes * np.maximum(contagem, 1)))
    criterio = torch.nn.CrossEntropyLoss(weight=torch.tensor(pesos),
                                         label_smoothing=0.05, reduction="none")

    melhor_alvo, melhor_nota, melhor_estado, sem_melhora = -np.inf, -1.0, None, 0
    historico = []
    inicio = time.time()
    for epoca in range(1, epocas + 1):
        if epoca == congelar_epocas + 1:
            modelo.congelar(False)
        modelo.train()
        t_epoca = time.time()
        soma, vistos = 0.0, 0
        for x, y, w in ld_tr:
            opt.zero_grad()
            perda = (criterio(modelo(x), y) * w).mean()
            perda.backward()
            opt.step()
            soma += float(perda.detach()) * len(y)
            vistos += len(y)
        sched.step()

        y_sel = df_sel["y"].values
        prob_sel = prever(modelo, ld_sel)
        nota = _metrica(y_sel, prob_sel.argmax(1), n_classes)
        nota_ext = _metrica(df_va["y"].values, prever(modelo, ld_va).argmax(1), n_classes)
        # log-loss e menos ruidoso que QWK num split interno pequeno
        logloss = float(-np.log(np.clip(prob_sel[np.arange(len(y_sel)), y_sel],
                                        1e-6, 1.0)).mean())
        alvo = -logloss if selecao == "logloss" else nota
        perda_media = soma / max(vistos, 1)
        historico.append({"epoca": epoca, "loss": perda_media, "val": float(nota),
                          "val_externa": float(nota_ext), "logloss": logloss,
                          "selecao": selecao,
                          "tempo_s": round(time.time() - inicio, 1)})
        decorrido = time.time() - inicio
        eta = decorrido / epoca * (epocas - epoca)
        logger.info("  ep %02d/%02d loss=%.3f logloss=%.3f val=%.3f lr=%.2e "
                    "%.1fs/ep total=%ds eta~%ds",
                    epoca, epocas, perda_media, logloss, nota,
                    opt.param_groups[0]["lr"], time.time() - t_epoca,
                    int(decorrido), int(eta))
        if callback:
            callback({"epoca": epoca, "epocas": epocas, "loss": perda_media,
                      "logloss": logloss, "val": float(nota),
                      "melhor": float(max(melhor_nota, nota)),
                      "lr": opt.param_groups[0]["lr"],
                      "tempo_s": round(decorrido, 1), "eta_s": round(eta, 1)})
        if alvo > melhor_alvo:
            melhor_alvo, melhor_nota, sem_melhora = alvo, float(nota), 0
            melhor_estado = {k: v.detach().clone() for k, v in modelo.state_dict().items()}
        else:
            sem_melhora += 1
            if sem_melhora >= paciencia:
                break

    modelo.load_state_dict(melhor_estado)
    prob = prever(modelo, ld_va)
    return modelo, historico, prob


def metricas_tarefa(y, prob, nomes):
    pred = prob.argmax(1)
    out = {
        "n": int(len(y)),
        "acc": float((pred == y).mean()),
        "balanced_acc": float(balanced_accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", zero_division=0)),
        "matriz": confusion_matrix(y, pred, labels=range(len(nomes))).tolist(),
        "nomes": list(nomes),
        "distribuicao_humana": np.bincount(y, minlength=len(nomes)).tolist(),
        "distribuicao_prevista": np.bincount(pred, minlength=len(nomes)).tolist(),
    }
    if len(nomes) > 2:
        out["kappa"] = float(cohen_kappa_score(y, pred, weights="quadratic"))
        out["kappa_linear"] = float(cohen_kappa_score(y, pred))
        out["recall_por_classe"] = {
            nome: float(((pred == i) & (y == i)).sum() / max((y == i).sum(), 1))
            for i, nome in enumerate(nomes)
        }
    return out


def bootstrap_ic(y, prob, metrica, n=1000, semente=SEED, estratificado=True):
    """IC por bootstrap; estratificado mantem o tamanho de cada classe."""
    rng = np.random.default_rng(semente)
    y = np.asarray(y, dtype=int)
    pred = np.asarray(prob).argmax(1)
    grupos = [np.flatnonzero(y == c) for c in np.unique(y)] if estratificado else None
    vals = []
    for _ in range(n):
        idx = (np.concatenate([rng.choice(g, len(g), replace=True) for g in grupos])
               if grupos else rng.integers(0, len(y), len(y)))
        if len(np.unique(y[idx])) < 2:
            continue
        vals.append(metrica(y[idx], pred[idx]))
    if not vals:
        return [float("nan"), float("nan")]
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def carregar_checkpoint(caminho):
    """Carrega um fold salvo em disco (pesos + metadados)."""
    ck = torch.load(caminho, map_location="cpu", weights_only=False)
    modelo = ModeloFotos(ck["base"], ck["n_classes"])
    modelo.load_state_dict(ck["state_dict"])
    modelo.eval()
    return modelo, ck


def prever_caminhos(modelo, base, caminhos, size=192, batch=32, tta=True):
    """Probabilidades para uma lista de arquivos locais."""
    proc = AutoImageProcessor.from_pretrained(base)
    df = pd.DataFrame({"path": [str(c) for c in caminhos], "y": 0, "peso": 1.0})
    ds = DatasetFotos(df, size, False, proc.image_mean, proc.image_std)
    ld = torch.utils.data.DataLoader(ds, batch_size=batch, shuffle=False, num_workers=0)
    return prever(modelo, ld, tta=tta)
