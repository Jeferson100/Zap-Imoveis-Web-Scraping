import asyncio
import base64
import logging

import httpx
from roteador_llms import LlmRouter

from .config import MAX_BYTES_IMAGEM, MAX_CONCURRENT_LOTES, TIMEOUT_DOWNLOAD
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


async def _baixar(client: httpx.AsyncClient, url: str) -> tuple[str, str] | None:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        if len(resp.content) > MAX_BYTES_IMAGEM:
            logger.warning("Imagem excede limite de %d bytes: %s", MAX_BYTES_IMAGEM, url)
            return None
        mime = _detectar_mime(resp)
        b64 = base64.b64encode(resp.content).decode("utf-8")
        return mime, b64
    except Exception as e:
        logger.warning("Falha ao baixar %s: %s", url, e)
        return None
    


async def _processar_um_lote(
    client: httpx.AsyncClient,
    urls: list[str],
    prompt: str,
    lote_idx: int,
) -> str:
    downloads = await asyncio.gather(*[_baixar(client, url) for url in urls])

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

    llm = LlmRouter(conteudo,
                    api_nvidia_models=[
                    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                    "meta/llama-3.2-11b-vision-instruct",
                    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                    "meta/llama-3.2-90b-vision-instruct",
                    "mistralai/ministral-14b-instruct-2512",      
                ])
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

    sem = asyncio.Semaphore(MAX_CONCURRENT_LOTES)
    lotes = [dados_fotos[i : i + tamanho_lote] for i in range(0, len(dados_fotos), tamanho_lote)]

    async def _com_semaforo(lote_idx: int, lote: list[str]) -> str:
        async with sem:
            async with httpx.AsyncClient(
                timeout=TIMEOUT_DOWNLOAD,
                follow_redirects=True,
            ) as client:
                return await _processar_um_lote(
                    client, lote, prompt, lote_idx
                )

    resultados = await asyncio.gather(
        *[_com_semaforo(idx, lote) for idx, lote in enumerate(lotes)],
        return_exceptions=True,
    )

    partes: list[str] = []
    for idx, resultado in enumerate(resultados):
        if isinstance(resultado, Exception):
            logger.error("Lote %d falhou: %s", idx + 1, resultado)
            partes.append(f"--- Lote {idx + 1} ---\nFalha ao processar lote: {resultado}")
            continue
        partes.append(resultado)

    return "\n\n".join(partes)
