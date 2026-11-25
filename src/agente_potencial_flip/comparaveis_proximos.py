"""Busca deterministica de imoveis comparaveis proximos (mesma rua ou raio em metros).

Usado pelo agente ReAct de flip quando a publicacao informa uma rua real
(`rua != "s/r"`): fornece estatisticas (P25/P50/P75 de R$/m2) e exemplos de
vizinhos, e permite que o ARV blend use `p50_m2_proximos` no lugar de
`p50_bairro` quando ha massa critica (`n_comparaveis >= min_arv`, default 5).
"""

import os
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

RUAS_INVALIDAS = {"", "s/r", "sem rua", "none", "nan", "-"}


def rua_valida(rua: Any) -> bool:
    """True se a rua da publicacao e um logradouro real (nao 's/r'/vazio)."""
    s = str(rua or "").strip().lower()
    return bool(s) and s not in RUAS_INVALIDAS


def preparar_pool_comparaveis(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Prepara base limpa, sana e deduplicada entre portais para busca rapida."""
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()
    pool = df_raw.copy()
    pool["_tipo"] = pool.get("tipo_imovel", "").astype(str).str.strip().str.lower()
    pool["_bairro"] = pool.get("bairro", "").astype(str).str.strip().str.lower()
    pool["_rua"] = pool.get("rua", "").astype(str).str.strip().str.lower()
    pool["_valor"] = pd.to_numeric(pool.get("valor_imovel"), errors="coerce")
    pool["_metr"] = pd.to_numeric(pool.get("metragem"), errors="coerce")
    pool["_ppm2"] = pd.to_numeric(pool.get("preco_por_m2"), errors="coerce")
    pool["_lat"] = pd.to_numeric(pool.get("lat"), errors="coerce")
    pool["_lng"] = pd.to_numeric(pool.get("lng"), errors="coerce")

    sano = (
        (pool["_valor"] > 0)
        & (pool["_ppm2"] >= 1500)
        & (pool["_metr"] >= 30)
        & pool["_ppm2"].notna()
    )
    pool = pool[sano].copy()
    quartos = pool["quartos"].astype(str) if "quartos" in pool.columns else "0"
    pool["_chave_dedup"] = (
        pool["_bairro"]
        + "|"
        + pool["_metr"].round(1).astype(str)
        + "|"
        + pool["_valor"].round(0).astype(str)
        + "|"
        + quartos
    )
    return pool.drop_duplicates("_chave_dedup", keep="first").reset_index(drop=True)


def _haversine_m(lat1: float, lng1: float, lat2_arr: np.ndarray, lng2_arr: np.ndarray) -> np.ndarray:
    r = 6_371_000.0
    p1 = np.radians(lat1)
    p2 = np.radians(lat2_arr)
    dp = np.radians(lat2_arr - lat1)
    dl = np.radians(lng2_arr - lng1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * r * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def buscar_comparaveis_proximos(
    linha: Any,
    pool: pd.DataFrame,
    *,
    min_rua: int = 3,
    raio_m: float = 300.0,
    tol_metragem: float = 0.35,
    top_k: int = 5,
) -> Optional[Dict[str, Any]]:
    """Retorna comparaveis proximos quando o anuncio tem rua valida; senao None.

    - Nivel 1 (`mesma_rua`): mesma `rua` + mesmo `bairro`.
    - Nivel 2 (`raio_300m`): quando a mesma rua tem `< min_rua` comparaveis,
      busca vizinhos com rua valida no raio de `raio_m` metros (preferindo
      metragem dentro de `+/- tol_metragem`).
    - Sem rua valida (`s/r`), devolve None (evita usar centroide do bairro).
    """
    if pool is None or pool.empty:
        return None
    rua = str(linha.get("rua") or "").strip().lower()
    if not rua_valida(rua):
        return None

    bairro = str(linha.get("bairro") or "").strip().lower()
    tipo = str(linha.get("tipo_imovel") or "apartamento").strip().lower()
    url_self = str(linha.get("url") or "")
    metr = float(pd.to_numeric(linha.get("metragem"), errors="coerce") or 0.0)
    valor_self = float(pd.to_numeric(linha.get("valor_imovel"), errors="coerce") or 0.0)
    ppm2_self = float(pd.to_numeric(linha.get("preco_por_m2"), errors="coerce") or 0.0)
    lat = pd.to_numeric(linha.get("lat"), errors="coerce")
    lng = pd.to_numeric(linha.get("lng"), errors="coerce")

    cand = pool[pool["_tipo"] == tipo]
    if url_self and "url" in cand.columns:
        cand = cand[cand["url"].astype(str) != url_self]
    if metr > 0 and valor_self > 0:
        mesmo_imovel = (cand["_metr"].sub(metr).abs() <= 0.5) & (cand["_valor"].sub(valor_self).abs() <= 1000)
        cand = cand[~mesmo_imovel]

    # Nivel 1: mesma rua + mesmo bairro
    escolhidos = cand[(cand["_bairro"] == bairro) & (cand["_rua"] == rua)].copy()
    origem = "mesma_rua"

    # Nivel 2: raio geografico (so quando ha rua valida -> coordenada precisa)
    if len(escolhidos) < min_rua and pd.notna(lat) and pd.notna(lng):
        com_geo = cand[
            cand["_lat"].notna() & cand["_lng"].notna() & cand["_rua"].map(rua_valida)
        ].copy()
        if len(com_geo):
            dists = _haversine_m(
                float(lat), float(lng), com_geo["_lat"].to_numpy(), com_geo["_lng"].to_numpy()
            )
            com_geo["_dist_m"] = dists
            no_raio = com_geo[com_geo["_dist_m"] <= raio_m]
            if metr > 0 and len(no_raio) >= min_rua:
                faixa = no_raio[
                    (no_raio["_metr"] >= metr * (1.0 - tol_metragem))
                    & (no_raio["_metr"] <= metr * (1.0 + tol_metragem))
                ]
                if len(faixa) >= min_rua:
                    no_raio = faixa
            if len(no_raio) > len(escolhidos):
                escolhidos = no_raio
                origem = f"raio_{int(raio_m)}m"

    if len(escolhidos) == 0:
        return None

    ppm2s = escolhidos["_ppm2"].astype(float)
    p25, p50, p75 = np.percentile(ppm2s, [25, 50, 75])
    desc_pct = round((p50 - ppm2_self) / p50 * 100, 2) if (p50 > 0 and ppm2_self > 0) else None

    if metr > 0:
        escolhidos = escolhidos.assign(_diff_m2=(escolhidos["_metr"] - metr).abs()).sort_values("_diff_m2")

    exemplos = []
    for _, r in escolhidos.head(top_k).iterrows():
        ex = {
            "rua": str(r["_rua"]),
            "metragem": round(float(r["_metr"]), 1),
            "quartos": int(r["quartos"]) if ("quartos" in r and pd.notna(r["quartos"])) else None,
            "valor_imovel": round(float(r["_valor"]), 0),
            "preco_por_m2": round(float(r["_ppm2"]), 0),
        }
        if "_dist_m" in r and pd.notna(r["_dist_m"]):
            ex["dist_m"] = round(float(r["_dist_m"]), 0)
        exemplos.append(ex)

    return {
        "origem": origem,
        "rua_anuncio": rua,
        "n_comparaveis": int(len(escolhidos)),
        "p25_m2_proximos": round(float(p25), 2),
        "p50_m2_proximos": round(float(p50), 2),
        "p75_m2_proximos": round(float(p75), 2),
        "desconto_vs_proximos_pct": desc_pct,
        "exemplos_proximos": exemplos,
    }


def usar_proximos_no_arv() -> bool:
    """Flag de env (default True): permite desligar substituicao do p50_bairro no ARV."""
    return os.environ.get("FLIP_ARV_USAR_PROXIMOS", "1").strip().lower() not in ("0", "false", "no")


def min_comparaveis_arv() -> int:
    """Minimo de comparaveis exigido para trocar p50_bairro por p50_m2_proximos no ARV."""
    try:
        return max(1, int(os.environ.get("FLIP_PROXIMOS_MIN_ARV", "5")))
    except (TypeError, ValueError):
        return 5
