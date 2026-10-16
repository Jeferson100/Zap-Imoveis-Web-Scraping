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

# Ordem viva da run, preenchida por preflight_modelos().
# {(capacidade, provedor_router): [ids]} — só memória, nada no parquet.
ORDEM_PREFLIGHT: dict = {}

SINAIS_VIDA = ("visao", "vl", "omni", "scout", "image")
TIMEOUT_PREFLIGHT_S = 25


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


def _e_visao_candidato(model_id: str) -> bool:
    m = model_id.lower()
    return any(s in m for s in SINAIS_VIDA)


def _msg_visao():
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return [{"type": "text", "text": "Descreva em uma palavra."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]


async def preflight_modelos() -> dict:
    """Testa os modelos do catálogo (via listar_modelos) e fixa a ordem da run.

    Vivos primeiro (ordem de resposta); 429/5xx/timeout no fim da fila;
    410/404/402/401 fora. Só memória — nada é gravado no parquet.
    """
    import asyncio
    import time

    from .listar_modelos import listar_modelos
    from .roteador_llms import AllProvidersFailedError, LlmRouter

    catalogo = await listar_modelos(["nvidia", "groq", "cerebras", "zai"],
                                    so_open_source=True)
    chave_router = {"nvidia": "api_nvidia_models", "groq": "groq_models",
                    "cerebras": "cerebras_models", "zai": "zai_models"}
    vazio = {k: [] for k in ("groq_models", "cerebras_models", "api_nvidia_models",
                             "api_langchain_nvidia_models", "api_openai_nvidia_models",
                             "openrouter_models", "zai_models")}

    async def testar(prov_cat: str, mid: str):
        import src.roteador_llms.roteador_llms as _R

        for com_imagem in (False, True):
            if com_imagem and not _e_visao_candidato(mid):
                continue
            # Isola o teste: o breaker global acumularia falhas entre modelos
            # e pularia tudo após 2 falhas (foi o que zerou a 1ª versão).
            # _MODELOS_MORTOS acumula de propósito (acelera os próximos testes).
            _R._FALHAS_PROVEDOR.clear()
            kw = dict(vazio)
            kw[chave_router[prov_cat]] = [mid]
            msg = _msg_visao() if com_imagem else "oi"
            t0 = time.monotonic()
            try:
                await asyncio.wait_for(LlmRouter(msg, **kw).llm_router(),
                                       timeout=TIMEOUT_PREFLIGHT_S)
                return (mid, "vivo", round(time.monotonic() - t0, 1))
            except AllProvidersFailedError as e:
                texto = str(e)
                if any(s in texto for s in ("410", "404", "402", "401", "Gone",
                                            "Not Found", "Payment Required",
                                            "Unauthorized")):
                    return (mid, "morto", round(time.monotonic() - t0, 1))
            except Exception:
                pass
        return (mid, "adiado", round(time.monotonic() - t0, 1))

    ORDEM_PREFLIGHT.clear()
    for prov_cat, ids in catalogo.items():
        if isinstance(ids, dict):  # provedor fora: pula sem derrubar os demais
            logger.warning("Pre-flight pulou %s: %s", prov_cat, ids["_erro"])
            continue
        vivos, adiados = [], []
        for mid in ids:
            _, status, dt = await testar(prov_cat, mid)
            logger.info("pre-flight %s %s -> %s (%.1fs)", prov_cat, mid, status, dt)
            if status == "vivo":
                vivos.append(mid)
            elif status == "adiado":
                adiados.append(mid)
        for capacidade in ("texto", "visao"):
            ORDEM_PREFLIGHT[(capacidade, prov_cat)] = list(vivos) + list(adiados)
    import src.roteador_llms.roteador_llms as _R2

    _R2._FALHAS_PROVEDOR.clear()  # breaker do flip começa limpo
    n_v = sum(1 for v in ORDEM_PREFLIGHT.values() for _ in v)
    logger.info("pre-flight concluído: %d modelos ordenados.", n_v)
    return ORDEM_PREFLIGHT


def _via_preflight(capacidade: str, provedor: str, n: int):
    """Ordem do pre-flight mapeada para nomes do catálogo, ou None."""
    provedor_cat = MAPA_PROVEDOR.get(provedor)
    if provedor_cat is None:
        return None
    ordem = ORDEM_PREFLIGHT.get((capacidade, provedor_cat))
    if not ordem:
        return None
    logger.info("modelos_para(%s, %s) via pre-flight -> %s",
                capacidade, provedor, ordem[:n])
    return list(ordem[:n])


async def modelos_para_async(
    capacidade: str, provedor: str, n: int = 3
) -> list:
    """Top-N ids para (capacidade, provedor). Assíncrono (pode listar ao vivo)."""
    assert capacidade in ("visao", "texto"), capacidade
    grupos = GRUPOS_VISAO if capacidade == "visao" else GRUPOS_TEXTO
    provedor_cat = MAPA_PROVEDOR.get(provedor)
    if provedor_cat is None:
        raise ValueError(f"provedor fora da seleção dinâmica: {provedor}")
    pre = _via_preflight(capacidade, provedor, n)
    if pre:
        return pre
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
    """Versão síncrona (pre-flight > catálogo; erro explícito sem nenhum)."""
    assert capacidade in ("visao", "texto"), capacidade
    grupos = GRUPOS_VISAO if capacidade == "visao" else GRUPOS_TEXTO
    provedor_cat = MAPA_PROVEDOR.get(provedor)
    if provedor_cat is None:
        raise ValueError(f"provedor fora da seleção dinâmica: {provedor}")
    pre = _via_preflight(capacidade, provedor, n)
    if pre:
        return pre
    out = _filtrar(_df_catalogo(), provedor_cat, grupos, n)
    if not out:
        raise ValueError(
            "Regere o catálogo: uv run listar_modelos.py --parquet "
            f"(capacidade={capacidade}, provedor={provedor})"
        )
    logger.info("modelos_para(%s, %s) -> %s", capacidade, provedor, out)
    return out
