import asyncio
import base64
import logging

import httpx
from roteador_llms import LlmRouter

from .config import (
    CACHE_DOWNLOADS,
    MAX_BYTES_IMAGEM,
    MAX_CONCURRENT_LOTES,
    TIMEOUT_DOWNLOAD,
    USAR_URL_DIRETA,
)
from .prompts import PROMPT_DESCREVER_FOTO

logger = logging.getLogger(__name__)

_MAGIC_MIME = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
    b"GIF87a": "image/gif",
    b"GIF89a": "image/gif",
    b"RIFF": "image/webp",
}


def _detectar_mime(resp: httpx.Response) -> str:
    content_type = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type.startswith("image/"):
        return content_type

    content = resp.content[:12]
    for magic, mime in _MAGIC_MIME.items():
        if content.startswith(magic):
            if magic == b"RIFF" and len(content) >= 12 and content[8:12] != b"WEBP":
                continue
            return mime
    return "image/jpeg"


def _montar_item_url_direta(url: str, idx: int) -> dict | None:
    """Monta item de payload com URL direta para o LLM de visão.

    Retorna None e loga warning se a URL for vazia ou None,
    ou retorna o dict no formato esperado pelo LLM.
    """
    if not url:
        logger.warning("URL vazia na posição %d, omitindo do payload.", idx)
        return None
    return {"type": "image_url", "image_url": {"url": url}}


async def _baixar(
    client: httpx.AsyncClient,
    url: str,
    cache: dict | None = None,
) -> tuple[str, str] | None:
    if cache is not None and url in cache:
        return cache[url]

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        if len(resp.content) > MAX_BYTES_IMAGEM:
            logger.warning("Imagem excede limite de %d bytes: %s", MAX_BYTES_IMAGEM, url)
            return None
        mime = _detectar_mime(resp)
        b64 = base64.b64encode(resp.content).decode("utf-8")
        resultado = (mime, b64)
        if cache is not None:
            cache[url] = resultado
        return resultado
    except Exception as e:
        logger.warning("Falha ao baixar %s: %s", url, e)
        return None


async def _processar_um_lote(
    client: httpx.AsyncClient,
    urls: list[str],
    prompt: str,
    lote_idx: int,
    cache: dict | None = None,
    usar_url_direta: bool = False,
) -> str:
    if usar_url_direta:
        itens = [_montar_item_url_direta(u, i) for i, u in enumerate(urls)]
        conteudo = [{"type": "text", "text": prompt}] + [x for x in itens if x is not None]
        fotos_ok = sum(1 for x in itens if x is not None)
    else:
        downloads = await asyncio.gather(*[_baixar(client, url, cache) for url in urls])
        conteudo = [{"type": "text", "text": prompt}]
        fotos_ok = 0
        for item in downloads:
            if item is None:
                continue
            mime, b64 = item
            fotos_ok += 1
            conteudo.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"}
            })

    if fotos_ok == 0:
        logger.error("Nenhuma imagem valida no lote %d", lote_idx + 1)
        return f"--- Lote {lote_idx + 1} ---\nNenhuma imagem valida neste lote."

    llm = LlmRouter(
        conteudo,
        # API_Nvidia: modelos de visão via httpx direto
        api_nvidia_models=[
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "meta/llama-3.2-11b-vision-instruct",
            "meta/llama-3.2-90b-vision-instruct",
            "mistralai/ministral-14b-instruct-2512",
        ],
        # Langchain_nvidia: modelos de visão via ChatNVIDIA (suportam content como lista)
        api_langchain_nvidia_models=[
            "meta/llama-4-maverick-17b-128e-instruct",
            "nvidia/nemotron-nano-12b-v2-vl",
            "microsoft/phi-4-multimodal-instruct",
        ],
        # Openai_nvidia: modelos de visão via AsyncOpenAI + Nvidia
        api_openai_nvidia_models=[
            "meta/llama-4-maverick-17b-128e-instruct",
            "nvidia/nemotron-nano-12b-v2-vl",
        ],
        # Groq: suporta visão com llama-4-scout
        groq_models=[
            "meta-llama/llama-4-scout-17b-16e-instruct",
        ],
        # Cerebras não tem modelos de visão
        cerebras_models=[],
    )
    response = await llm.llm_router()
    logger.info("Lote %d pronto (%d/%d imagens)", lote_idx + 1, fotos_ok, len(urls))
    return f"--- Lote {lote_idx + 1} ---\n{response}"


async def processar_todos_lotes(
    dados_fotos: list[str],
    tamanho_lote: int,
    prompt: str = PROMPT_DESCREVER_FOTO,
) -> str:
    if not dados_fotos:
        return ""

    cache: dict[str, tuple[str, str]] | None = (
        {} if CACHE_DOWNLOADS and not USAR_URL_DIRETA else None
    )
    sem = asyncio.Semaphore(MAX_CONCURRENT_LOTES)
    lotes = [dados_fotos[i : i + tamanho_lote] for i in range(0, len(dados_fotos), tamanho_lote)]

    client = httpx.AsyncClient(timeout=TIMEOUT_DOWNLOAD, follow_redirects=True)
    try:
        async def _com_semaforo(lote_idx: int, lote: list[str]) -> str:
            async with sem:
                return await _processar_um_lote(
                    client, lote, prompt, lote_idx,
                    cache=cache,
                    usar_url_direta=USAR_URL_DIRETA,
                )

        resultados = await asyncio.gather(
            *[_com_semaforo(idx, lote) for idx, lote in enumerate(lotes)],
            return_exceptions=True,
        )
    finally:
        await client.aclose()

    partes: list[str] = []
    for idx, resultado in enumerate(resultados):
        if isinstance(resultado, Exception):
            logger.error("Lote %d falhou: %s — %s", idx + 1, type(resultado).__name__, resultado)
            partes.append(f"--- Lote {idx + 1} ---\nFalha ao processar lote: {resultado}")
            continue
        partes.append(resultado)

    return "\n\n".join(partes)
