"""Lista modelos disponíveis em cada provedor LLM.

Uso como biblioteca:
    from roteador_llms import listar_modelos
    modelos = await listar_modelos()

Uso como CLI (qualquer cwd com .env na raiz do repo):
    uv run listar_modelos.py [--todos] [--detalhado] [--out caminho.json]
Por padrão lista só pesos abertos; --todos mostra tudo.
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv


def _carregar_env() -> None:
    """Carrega o .env da raiz do repo (sobe até achar pyproject.toml).

    Permite rodar de qualquer cwd (ex. de dentro de src/roteador_llms/).
    Não sobrescreve variáveis já exportadas no ambiente.
    """
    aqui = Path(__file__).resolve()
    for pai in [aqui.parent, *aqui.parents]:
        if (pai / "pyproject.toml").exists():
            load_dotenv(pai / ".env", override=False)
            return
    load_dotenv(override=False)


_carregar_env()

logger = logging.getLogger(__name__)

PROVEDORES = ("nvidia", "groq", "cerebras", "zai", "openrouter")

# Famílias de pesos abertos (curadoria manual). NOTA: "família open" não
# garante licença OSI — glm-5.x e nemotron-3 precisam de checagem caso a caso
# para uso comercial estrito.
FAMILIAS_OSS = [
    "llama", "qwen", "gemma", "mistral", "ministral", "mixtral",
    "deepseek", "gpt-oss", "kimi", "glm", "phi", "granite", "yi",
    "dbrx", "arctic", "codellama", "starcoder", "codegemma", "jamba",
    "zamba", "sea-lion", "nemotron", "muse-glimmer", "muse-spark",
    "kosmos", "fuyu", "neva", "vila", "allam", "ui-tars",
]
# Modalidades/finalidades excluídas mesmo em família aberta.
EXCLUIR_OSS = [
    "embed", "guard", "parse", "riva", "whisper", "orpheus",
    "nemoguard", "safety", "translate", "detector", "deplot",
    "diffusion", "safeguard", "code",
]


def e_open_source(model_id: str) -> bool:
    """True se o id parece de família aberta e não é modalidade excluída."""
    m = model_id.lower().split(":")[0]
    return any(f in m for f in FAMILIAS_OSS) and not any(
        x in m for x in EXCLUIR_OSS
    )


def normalizar_id(model_id: str) -> str:
    """Normaliza id para cruzar catálogos: minúsculas, sem variante (:free),
    sem org (só base) e só alfanuméricos.

    Ex: 'z-ai/glm-5.3-flash' e 'glm-5.3-flash' -> 'glm53flash'.
    """
    import re

    base = model_id.lower().split(":")[0].split("/")[-1]
    return re.sub(r"[^a-z0-9]", "", base)


def enriquecer_com_openrouter(diretos: list, detalhado: list) -> list:
    """Herda flags do OpenRouter para modelos diretos com mesmo id normalizado.

    Retorna lista de dicts {id, aceita_imagem, suporta_tools,
    suporta_response_format, context, preco_in_usd_M, modalidades,
    flags_origem, flags_ambiguas}. Sem match -> flags None (origem 'direto').
    Variantes (:free/:batch) com flags divergentes usam a moda + ambigua=True.

    As flags valem para o MODELO, não garantem o deployment do provedor direto.
    """
    from collections import Counter

    por_norm: dict = {}
    for m in detalhado:
        por_norm.setdefault(normalizar_id(m["id"]), []).append(m)

    def moda(vals):
        return Counter(vals).most_common(1)[0][0]

    out = []
    for mid in diretos:
        cands = por_norm.get(normalizar_id(mid), [])
        if not cands:
            out.append({"id": mid, "flags_origem": "direto",
                        "flags_ambiguas": False})
            continue
        out.append({
            "id": mid,
            "aceita_imagem": moda([bool(c.get("aceita_imagem")) for c in cands]),
            "suporta_tools": moda([bool(c.get("suporta_tools")) for c in cands]),
            "suporta_response_format": moda(
                [bool(c.get("suporta_response_format")) for c in cands]),
            "context": moda([c.get("context") for c in cands]),
            "preco_in_usd_M": moda([c.get("preco_in_usd_M") for c in cands]),
            "modalidades": cands[0].get("modalidades"),
            "flags_origem": "openrouter",
            "flags_ambiguas": any(
                len({str(c.get(k)) for c in cands}) > 1
                for k in ("aceita_imagem", "suporta_tools",
                          "suporta_response_format")
            ),
        })
    return out


async def _get(client: httpx.AsyncClient, url: str, headers: Optional[dict] = None):
    try:
        r = await client.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"_erro": f"{type(e).__name__}: {str(e)[:150]}"}


async def _nvidia(client: httpx.AsyncClient):
    """Cobre API_Nvidia, Langchain_nvidia e Openai_nvidia (mesmo endpoint)."""
    key = os.getenv("NVIDIA_API_KEY")
    data = await _get(
        client,
        "https://integrate.api.nvidia.com/v1/models",
        {"Authorization": f"Bearer {key}"} if key else None,
    )
    if "_erro" in data:
        return data
    return sorted(m["id"] for m in data.get("data", []))


async def _groq():
    try:
        from groq import AsyncGroq

        ms = await AsyncGroq().models.list()
        return sorted(m.id for m in ms.data)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"_erro": f"{type(e).__name__}: {str(e)[:150]}"}


async def _cerebras():
    try:
        from cerebras.cloud.sdk import AsyncCerebras

        ms = await AsyncCerebras(api_key=os.getenv("CEREBRAS_API_KEY")).models.list()
        return sorted(m.id for m in ms.data)
    except Exception as e:  # pylint: disable=broad-exception-caught
        return {"_erro": f"{type(e).__name__}: {str(e)[:150]}"}


async def _zai(client: httpx.AsyncClient):
    key = os.getenv("ZAI_API_KEY")
    data = await _get(
        client,
        "https://api.z.ai/api/paas/v4/models",
        {"Authorization": f"Bearer {key}"} if key else None,
    )
    if "_erro" in data:
        return data
    return sorted(m["id"] for m in data.get("data", []))


async def _openrouter(client: httpx.AsyncClient):
    data = await _get(client, "https://openrouter.ai/api/v1/models")
    if "_erro" in data:
        return data
    return sorted(m["id"] for m in data.get("data", []))


async def listar_openrouter_detalhado() -> list | dict:
    """Modelos do OpenRouter com contexto, preço (USD/1M tokens) e modalidades."""
    async with httpx.AsyncClient() as client:
        data = await _get(client, "https://openrouter.ai/api/v1/models")
    if "_erro" in data:
        return data
    out = []
    for m in data.get("data", []):
        try:
            preco = float(m.get("pricing", {}).get("prompt", 0)) * 1e6
        except (TypeError, ValueError):
            preco = None
        modalidade = str(m.get("architecture", {}).get("modality", ""))
        entrada, _, _saida = modalidade.partition("->")
        params = m.get("supported_parameters") or []
        out.append(
            {
                "id": m["id"],
                "context": m.get("context_length"),
                "preco_in_usd_M": preco,
                "modalidades": modalidade,
                "aceita_imagem": "image" in entrada,
                "suporta_tools": "tools" in params,
                "suporta_response_format": "response_format" in params,
            }
        )
    return sorted(out, key=lambda x: x["id"])


def classificar_modelos(detalhado: list, so_open_source: bool = True) -> dict:
    """Separa modelos OpenRouter em visao / tools / ambos / texto_sem_tools.

    so_open_source=True aplica o filtro FAMILIAS_OSS antes de classificar.
    """
    grupos = {"visao": [], "tools": [], "ambos": [], "texto_sem_tools": []}
    for m in detalhado:
        if so_open_source and not e_open_source(m["id"]):
            continue
        visao = bool(m.get("aceita_imagem"))
        tools = bool(m.get("suporta_tools"))
        if visao and tools:
            grupos["ambos"].append(m)
        elif visao:
            grupos["visao"].append(m)
        elif tools:
            grupos["tools"].append(m)
        else:
            grupos["texto_sem_tools"].append(m)
    return grupos


async def listar_modelos(
    provedores: Optional[list] = None, so_open_source: bool = True
) -> dict:
    """Retorna {provedor: [ids] | {_erro}}. Um provedor fora não derruba os demais.

    Por padrão lista só famílias de pesos abertos (FAMILIAS_OSS);
    so_open_source=False mostra o catálogo cheio.
    """
    alvos = provedores or list(PROVEDORES)
    resultado: dict = {}
    async with httpx.AsyncClient() as client:
        if "nvidia" in alvos:
            resultado["nvidia"] = await _nvidia(client)
        if "groq" in alvos:
            resultado["groq"] = await _groq()
        if "cerebras" in alvos:
            resultado["cerebras"] = await _cerebras()
        if "zai" in alvos:
            resultado["zai"] = await _zai(client)
        if "openrouter" in alvos:
            resultado["openrouter"] = await _openrouter(client)
    if so_open_source:
        for prov, modelos in resultado.items():
            if isinstance(modelos, list):
                resultado[prov] = [m for m in modelos if e_open_source(m)]
    return resultado


async def exportar_catalogo_parquet(
    caminho, provedores: Optional[list] = None, so_open_source: bool = True
):
    """Coleta o catálogo e salva em Parquet. Retorna o caminho.

    Schema: provedor, id, grupo, context, preco_in_usd_M, modalidades,
    aceita_imagem, suporta_tools, suporta_response_format, flags_origem,
    flags_ambiguas, data_coleta. Diretos herdam flags do OpenRouter por id
    normalizado (origem 'openrouter'); sem match ficam 'nao_classificado'.
    """
    import datetime

    import pandas as pd

    data_coleta = datetime.date.today().isoformat()
    resultado = await listar_modelos(provedores, so_open_source=so_open_source)
    det, grupos_or = None, None
    if "openrouter" in (provedores or list(PROVEDORES)):
        det = await listar_openrouter_detalhado()
        if isinstance(det, dict):
            logger.warning("OpenRouter detalhado fora do parquet: %s", det["_erro"])
            det = None
    linhas = []
    for prov, modelos in resultado.items():
        if isinstance(modelos, dict):
            logger.warning("Provedor %s fora do parquet: %s", prov, modelos["_erro"])
            continue
        if prov == "openrouter":
            continue  # entra via detalhado/classificado abaixo
        enr = {e["id"]: e for e in enriquecer_com_openrouter(modelos, det or [])}
        for mid in modelos:
            e = enr[mid]
            visao = e.get("aceita_imagem")
            tools = e.get("suporta_tools")
            if visao is None and tools is None:
                grupo = "nao_classificado"
            else:
                grupo = ("ambos" if visao and tools else
                         "visao" if visao else
                         "tools" if tools else "texto_sem_tools")
            linhas.append({"provedor": prov, "id": mid, "grupo": grupo,
                          "context": e.get("context"),
                          "preco_in_usd_M": e.get("preco_in_usd_M"),
                          "modalidades": e.get("modalidades"),
                          "aceita_imagem": e.get("aceita_imagem"),
                          "suporta_tools": e.get("suporta_tools"),
                          "suporta_response_format": e.get("suporta_response_format"),
                          "flags_origem": e.get("flags_origem", "direto"),
                          "flags_ambiguas": e.get("flags_ambiguas", False)})
    if det is not None:
        grupos = classificar_modelos(det, so_open_source=so_open_source)
        for grupo, itens in grupos.items():
            for m in itens:
                linhas.append({
                    "provedor": "openrouter",
                    "id": m["id"],
                    "grupo": grupo,
                    "context": m.get("context"),
                    "preco_in_usd_M": m.get("preco_in_usd_M"),
                    "modalidades": m.get("modalidades"),
                    "aceita_imagem": m.get("aceita_imagem"),
                    "suporta_tools": m.get("suporta_tools"),
                    "suporta_response_format": m.get("suporta_response_format"),
                    "flags_origem": "openrouter",
                    "flags_ambiguas": False,
                })
    df = pd.DataFrame(linhas)
    df["data_coleta"] = data_coleta
    # Preserva conhecimento de probe do catálogo anterior por (provedor, id).
    df["status_probe"] = "nao_testado"
    df["data_probe"] = None
    try:
        from .selecao_modelos import _catalogo_mais_recente

        anterior = _catalogo_mais_recente()
        if anterior is not None and anterior.resolve() != Path(caminho).resolve():
            velho = pd.read_parquet(anterior, columns=["provedor", "id", "status_probe", "data_probe"])
            velho = velho.drop_duplicates(subset=["provedor", "id"], keep="last")
            df = df.merge(velho, on=["provedor", "id"], how="left", suffixes=("", "_velho"))
            df["status_probe"] = df["status_probe_velho"].fillna(df["status_probe"])
            df["data_probe"] = df["data_probe_velho"].where(
                df["data_probe_velho"].notna(), df["data_probe"])
            df = df.drop(columns=["status_probe_velho", "data_probe_velho"])
            logger.info("Status de probe herdados de %s.", anterior.name)
    except Exception as e:  # catálogo novo do zero
        logger.warning("Sem herança de probe (%s).", e)
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(caminho, index=False)
    return caminho


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Lista modelos disponíveis por provedor LLM.")
    parser.add_argument("--out", default=None, help="Caminho do JSON de saída.")
    parser.add_argument("--parquet", default=None, nargs="?", const="dados",
                        help="Salva catálogo em Parquet (padrão: dados/catalogo_modelos_<hoje>.parquet).")
    parser.add_argument(
        "--provedores", nargs="*", default=None, choices=list(PROVEDORES),
        help="Filtra provedores (padrão: todos).",
    )
    parser.add_argument("--detalhado", action="store_true",
                        help="Inclui metadados do OpenRouter (contexto/preço/modalidades).")
    parser.add_argument("--todos", action="store_true",
                        help="Mostra o catálogo cheio (padrão: só pesos abertos).")
    args = parser.parse_args(argv)

    async def _run():
        resultado = await listar_modelos(args.provedores, so_open_source=not args.todos)
        if args.detalhado:
            det = await listar_openrouter_detalhado()
            if isinstance(det, list):
                grupos = classificar_modelos(det, so_open_source=not args.todos)
                resultado["openrouter_grupos"] = {
                    k: [m["id"] for m in v] for k, v in grupos.items()
                }
                resultado["openrouter_detalhe"] = det
            else:
                resultado["openrouter"] = det
        return resultado

    resultado = asyncio.run(_run())
    for prov, modelos in resultado.items():
        if prov in ("openrouter_grupos", "openrouter_detalhe"):
            continue
        if isinstance(modelos, dict):
            print(f"{prov}: ERRO {modelos['_erro']}")
        else:
            print(f"{prov}: {len(modelos)} modelos")
            for m in modelos[:30]:
                print(f"  - {m if isinstance(m, str) else m['id']}")
            if len(modelos) > 30:
                print(f"  ... e mais {len(modelos) - 30}")
    if "openrouter_grupos" in resultado:
        for grupo, ids in resultado["openrouter_grupos"].items():
            print(f"\n### {grupo} ({len(ids)})")
            for mid in ids[:20]:
                print(f"  - {mid}")
            if len(ids) > 20:
                print(f"  ... e mais {len(ids) - 20}")
    if args.out:
        Path(args.out).write_text(
            json.dumps(resultado, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        print("salvo:", args.out)
    if args.parquet is not None:
        import datetime

        aqui = Path(__file__).resolve()
        raiz = next(
            (p for p in [aqui.parent, *aqui.parents] if (p / "pyproject.toml").exists()),
            Path.cwd(),
        )
        destino = (
            raiz / f"dados/catalogo_modelos_{datetime.date.today().isoformat()}.parquet"
            if args.parquet == "dados"
            else Path(args.parquet)
        )
        so_oss = not args.todos
        caminho = asyncio.run(
            exportar_catalogo_parquet(destino, args.provedores, so_open_source=so_oss)
        )
        print("parquet salvo:", caminho)
    return 0


if __name__ == "__main__":
    sys.exit(main())
