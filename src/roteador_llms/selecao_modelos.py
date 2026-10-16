"""Seleção dinâmica de modelos por capacidade, a partir do catálogo Parquet.

Nenhum id de modelo é escrito à mão aqui (exceção: OpenRouter, mantido
fixo em ["openrouter/free"] por decisão de custo — ver roteador_llms.py).

Regras:
- capacidade 'visao' -> grupos ambos/visao; 'texto' -> ambos/tools.
- Ordena por preco_in_usd_M (nulo por último); flags_ambiguas=True nunca entra.
- Provedores openai_nvidia/langchain_nvidia usam as linhas 'nvidia'
  do catálogo (mesmo endpoint/deployment).
- Sem parquet válido (<30 dias) -> live listing via listar_modelos() na hora.
- Se tudo falhar -> erro explícito (sem fallback manual).
"""
import functools
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

GRUPOS_VISAO = ("ambos", "visao")
GRUPOS_TEXTO = ("ambos", "tools")
IDADE_MAX_DIAS = 30

# Provedores do LlmRouter -> provedor do catálogo (None = fora da seleção).
MAPA_PROVEDOR = {
    "API_Nvidia": "nvidia",
    "Langchain_nvidia": "nvidia",
    "Openai_nvidia": "nvidia",
    "Groq": "groq",
    "Cerebras": "cerebras",
    "Zai": "zai",
}


def _raiz_repo() -> Path:
    aqui = Path(__file__).resolve()
    return next(
        (p for p in [aqui.parent, *aqui.parents] if (p / "pyproject.toml").exists()),
        Path.cwd(),
    )


def _catalogo_mais_recente():
    cands = sorted((_raiz_repo() / "dados").glob("catalogo_modelos_*.parquet"))
    return cands[-1] if cands else None


@functools.lru_cache(maxsize=1)
def _df_catalogo() -> pd.DataFrame:
    """DataFrame do catálogo (cache por processo). Erro se ausente/velho."""
    import datetime

    path = _catalogo_mais_recente()
    if path is None:
        raise FileNotFoundError("sem catalogo_modelos_*.parquet em dados/")
    idade = (datetime.date.today() - datetime.date.fromisoformat(path.stem[-10:])).days
    if idade > IDADE_MAX_DIAS:
        raise ValueError(f"catalogo velho: {path.name} ({idade} dias)")
    return pd.read_parquet(path)


STATUS_MORTO = "morto"
STATUS_VIVO = "vivo"


def _filtrar(df: pd.DataFrame, provedor_cat: str, grupos: tuple, n: int) -> list:
    if "status_probe" not in df.columns:
        df = df.assign(status_probe="nao_testado")
    sel = df[
        (df["provedor"] == provedor_cat)
        & (df["grupo"].isin(grupos))
        & (~df["flags_ambiguas"].fillna(False))
        & (df["status_probe"] != STATUS_MORTO)
    ]
    sel = sel.assign(_vivo=(sel["status_probe"] == STATUS_VIVO).astype(int))
    sel = sel.sort_values(["_vivo", "preco_in_usd_M"], ascending=[False, True],
                          na_position="last")
    return sel["id"].head(n).tolist()


def registrar_probe(resultados: dict, caminho=None) -> Path:
    """Grava status de probe ('vivo'/'morto') no parquet. Chave: (provedor, id).

    resultados: {(provedor, id): 'vivo' | 'morto'}.
    """
    import datetime

    path = Path(caminho) if caminho else _catalogo_mais_recente()
    if path is None:
        raise FileNotFoundError("sem catalogo para registrar probe")
    df = pd.read_parquet(path)
    if "status_probe" not in df.columns:
        df["status_probe"] = "nao_testado"
    if "data_probe" not in df.columns:
        df["data_probe"] = None
    hoje = datetime.date.today().isoformat()
    for (prov, mid), status in resultados.items():
        mask = (df["provedor"] == prov) & (df["id"] == mid)
        df.loc[mask, "status_probe"] = status
        df.loc[mask, "data_probe"] = hoje
    df.to_parquet(path, index=False)
    logger.info("Probe registrado em %s: %d resultados.", path.name, len(resultados))
    return path


async def _live_listing(provedor_cat: str, grupos: tuple, n: int) -> list:
    """Fallback sem parquet: lista ao vivo e classifica na hora."""
    from .listar_modelos import (
        listar_modelos,
        listar_openrouter_detalhado,
        normalizar_id,
    )

    if provedor_cat == "nvidia":
        # Mesmo endpoint cobre os 3 roteadores Nvidia; detalhado não se aplica.
        resultado = await listar_modelos(["nvidia"], so_open_source=True)
        ids = resultado.get("nvidia", [])
        if isinstance(ids, dict):
            raise ValueError(f"live listing nvidia falhou: {ids['_erro']}")
        return ids[: max(n, 5)]
    # Demais diretos: sem metadados ao vivo -> usa o detalhado OpenRouter
    # como referência de grupo, restrito aos ids do provedor.
    prov_arg = {"groq": "groq", "cerebras": "cerebras", "zai": "zai"}.get(provedor_cat)
    if prov_arg is None:
        raise ValueError(f"provedor sem live listing: {provedor_cat}")
    det = await listar_openrouter_detalhado()
    if isinstance(det, dict):
        raise ValueError(f"live listing falhou: {det['_erro']}")
    refs = {}
    for m in det:
        refs.setdefault(normalizar_id(m["id"]), []).append(m)
    ids = (await listar_modelos([prov_arg], so_open_source=True))[prov_arg]
    if isinstance(ids, dict):
        raise ValueError(f"live listing {prov_arg} falhou: {ids['_erro']}")
    out = []
    for mid in ids:
        cands = refs.get(normalizar_id(mid), [])
        if not cands:
            continue
        visao = any(bool(c.get("aceita_imagem")) for c in cands)
        tools = any(bool(c.get("suporta_tools")) for c in cands)
        grupo = ("ambos" if visao and tools else
                 "visao" if visao else "tools" if tools else "texto_sem_tools")
        if grupo in grupos:
            out.append(mid)
        if len(out) >= n:
            break
    if not out:
        raise ValueError(f"live listing vazio para {provedor_cat}")
    return out


async def modelos_para_async(
    capacidade: str, provedor: str, n: int = 3
) -> list:
    """Top-N ids para (capacidade, provedor). Assíncrono (pode listar ao vivo)."""
    assert capacidade in ("visao", "texto"), capacidade
    grupos = GRUPOS_VISAO if capacidade == "visao" else GRUPOS_TEXTO
    provedor_cat = MAPA_PROVEDOR.get(provedor)
    if provedor_cat is None:
        raise ValueError(f"provedor fora da seleção dinâmica: {provedor}")
    try:
        out = _filtrar(_df_catalogo(), provedor_cat, grupos, n)
        if not out:
            raise ValueError("seleção vazia no catálogo")
        logger.info("modelos_para(%s, %s) via catálogo -> %s", capacidade, provedor, out)
        return out
    except Exception as e:
        logger.warning("Catálogo indisponível (%s) — live listing.", e)
    out = await _live_listing(provedor_cat, grupos, n)
    logger.info("modelos_para(%s, %s) via live -> %s", capacidade, provedor, out)
    return out


def modelos_para(capacidade: str, provedor: str, n: int = 3) -> list:
    """Versão síncrona (só catálogo; erro explícito sem parquet válido)."""
    assert capacidade in ("visao", "texto"), capacidade
    grupos = GRUPOS_VISAO if capacidade == "visao" else GRUPOS_TEXTO
    provedor_cat = MAPA_PROVEDOR.get(provedor)
    if provedor_cat is None:
        raise ValueError(f"provedor fora da seleção dinâmica: {provedor}")
    out = _filtrar(_df_catalogo(), provedor_cat, grupos, n)
    if not out:
        raise ValueError(
            "Regere o catálogo: uv run listar_modelos.py --parquet "
            f"(capacidade={capacidade}, provedor={provedor})"
        )
    logger.info("modelos_para(%s, %s) -> %s", capacidade, provedor, out)
    return out
