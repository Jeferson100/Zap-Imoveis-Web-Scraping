"""
Gera {prefix}_features_modelo_{mes}.json a partir dos parquets de otimizacao
existentes — SEM rodar retreino.

Para cada prefixo (cidade ou bairro) com
`{prefix}_otimizados_melhores_incrementos_{mes}.parquet`:
  1. Pega a melhor linha (menor rmse_otimizado).
  2. Extrai as features de `feature_transform_map`.
  3. Se existir `{prefix}_modelo_geral_*.joblib`, valida contra as features
     reais do pipeline (joblib prevalece em caso de divergencia).
  4. Escreve o JSON no MESMO SCHEMA que melhor_modelo_geral.py gera.

Uso:
    python scripts/gerar_features_modelo.py [--force] [--cidade joinville]
"""
import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
try:
    from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES
except Exception:  # pragma: no cover - config minimalista de contingência
    NUMERIC_FEATURES, CATEGORICAL_FEATURES = [], []

TOPIC_PREFIX = "componente_"
OTIM_PATTERN = re.compile(r"^(.*)_otimizados_melhores_incrementos_(\d{4}-\d{2})$")


def split_num_cat(feats):
    num = [f for f in feats if f in NUMERIC_FEATURES or f.startswith(TOPIC_PREFIX)]
    cat = [f for f in feats if f in CATEGORICAL_FEATURES]
    resto = [f for f in feats if f not in num and f not in cat]
    # Sem config ou feature desconhecida: trata como numérica (imputável/escalável).
    num = num + resto
    return num, cat


def extrair_features_joblib(joblib_path):
    """Extrai a lista de features do preprocessor do pipeline salvo."""
    import joblib

    modelo = joblib.load(joblib_path)
    ct = modelo.named_steps["preprocessador"]
    cols = []
    for _, _, c in ct.transformers_:
        cols.extend(list(c))
    return cols


def mes_do_stem(stem):
    return stem.split("_")[-1]


def processar_prefixo(pasta, prefixo, arquivos_otim, force=False):
    arquivos_otim = sorted(arquivos_otim)
    otim_path = arquivos_otim[-1]
    m = OTIM_PATTERN.match(otim_path.stem)
    if not m:
        logger.warning("Padrao inesperado, pulando: %s", otim_path.name)
        return None
    _, mes_otim = m.group(1), m.group(2)

    df = pd.read_parquet(otim_path)
    if df.empty or "rmse_otimizado" not in df.columns:
        logger.warning("Sem linhas válidas: %s", otim_path.name)
        return None
    best = df.loc[df["rmse_otimizado"].idxmin()]

    try:
        feat_map = json.loads(best.get("feature_transform_map") or "{}")
    except (TypeError, ValueError):
        feat_map = {}
    feats = list(feat_map.keys())
    if not feats:
        logger.warning("feature_transform_map vazio na melhor linha: %s", otim_path.name)
        return None

    fonte = "otimizados"
    mes_saida = mes_otim

    joblibs = sorted(pasta.glob(f"{prefixo}_modelo_geral_*.joblib"))
    if joblibs:
        joblib_path = joblibs[-1]
        try:
            feats_joblib = extrair_features_joblib(joblib_path)
            mes_saida = mes_do_stem(joblib_path.stem)
            if set(feats_joblib) != set(feats):
                logger.warning(
                    "%s: divergencia otimizados(%d) x joblib(%d) — prevalece joblib (%s)",
                    prefixo, len(feats), len(feats_joblib), joblib_path.name,
                )
                feats = list(feats_joblib)
            fonte = "joblib+otimizados"
        except Exception as exc:
            logger.warning("%s: falha ao ler joblib %s (%s) — usando otimizados",
                           prefixo, joblib_path.name, exc)

    num, cat = split_num_cat(feats)
    try:
        best_params = json.loads(best.get("best_params") or "{}")
    except (TypeError, ValueError):
        best_params = {}

    payload = {
        "features": feats,
        "features_numericas": num,
        "features_categoricas": cat,
        "n_features": len(feats),
        "modelo": str(best.get("modelo", "")),
        "tratamento": str(best.get("tratamento", "")),
        "transform": str(best.get("transform", "none")),
        "scaler": str(best.get("scaler", "")),
        "imputer_num": str(best.get("imputer_num", "")),
        "encoder": str(best.get("encoder", "")),
        "target_transform": str(best.get("target_transform", best.get("target_transformer", "none"))),
        "best_params": best_params,
        "rmse_otimizado": float(best["rmse_otimizado"]),
        "r2_otimizado": float(best.get("r2_otimizado", 0) or 0),
        "mes_ref": mes_saida,
        "data_treino": datetime.now().isoformat(),
        "fonte": f"backfill-{fonte}",
    }

    saida = pasta / f"{prefixo}_features_modelo_{mes_saida}.json"
    if saida.exists() and not force:
        logger.info("%s: já existe, pulando (use --force): %s", prefixo, saida.name)
        return None
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
    logger.info("%s: %s (%d features, %s)", prefixo, saida.name, len(feats), fonte)
    return saida


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Sobrescreve JSONs existentes")
    ap.add_argument("--cidade", default=None, help="Filtra por pasta ou prefixo (ex.: joinville)")
    args = ap.parse_args()

    base = Path(__file__).resolve().parent.parent / "dados"
    alvos = {}
    for otim_path in base.rglob("*_otimizados_melhores_incrementos_*.parquet"):
        m = OTIM_PATTERN.match(otim_path.stem)
        if not m:
            continue
        prefixo = m.group(1)
        if args.cidade and args.cidade not in otim_path.parent.name and args.cidade not in prefixo:
            continue
        alvos.setdefault((otim_path.parent, prefixo), []).append(otim_path)

    if not alvos:
        logger.warning("Nenhum parquet de otimizados encontrado.")
        return

    criados = 0
    for (pasta, prefixo), arquivos in sorted(alvos.items(), key=lambda kv: kv[0][1]):
        try:
            if processar_prefixo(pasta, prefixo, arquivos, force=args.force):
                criados += 1
        except Exception as exc:
            logger.warning("%s: erro (%s)", prefixo, exc)

    logger.info("Concluído: %d JSONs criados (%d prefixos).", criados, len(alvos))


if __name__ == "__main__":
    main()
