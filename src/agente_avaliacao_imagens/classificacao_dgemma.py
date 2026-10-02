"""Classificação do estado de conservação das fotos via classifier.dev (modelo dgemma).

Contrato (https://classifier.dev/developers, seção IMAGE CLASSIFICATION):
- POST /v1/systemone com model="dgemma", images=data URLs base64, questions Choice/Score.
- Máx 4 imagens e 900.000 chars de data URL no total, body 1 MB. Sem chave (quota anônima).
- Erros: 503 dgemma_unavailable (fora do ar), 429 + Retry-After (cheio),
  400 images_unsupported/dgemma_input (corpo fora do contrato).

Uso no notebook:
    from agente_avaliacao_imagens.classificacao_dgemma import (
        sonda_dgemma, classifica_conservacao, agrega_conservacao,
    )
    res = await classifica_conservacao(fotos_urls[:4], nota="Apartamento 67m², Joinville.")
"""

import asyncio
import base64
import io
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

SYSTEMONE_URL = "https://classifier.dev/v1/systemone"
MODELS_URL = "https://classifier.dev/v1/models"

MAX_IMGS = 4
# Redimensionamento na origem (CDN honra dimension=WxH; verificado: 400x400 → ~23KB).
# Evita baixar a foto grande para reduzir localmente.
DIMENSAO_CDN = "400x400"
# Rede de segurança: se o CDN ignorar o dimension e vier arquivo grande, reduz local.
LIMITE_BYTES_SEM_DOWNSCALE = 200_000
LADO_MAX = 512
JPG_Q = 60
TETO_CHARS = 900_000

LABELS_CONSERVACAO = ["bem conservado", "desgaste leve", "desgastado", "precário"]
ORDEM_CONSERVACAO = ["bem conservado", "desgaste leve", "desgastado", "precário"]


async def sonda_dgemma(timeout: int = 20) -> bool:
    """Sonda gratuita (GET /v1/models não gasta quota). True = serviço de pé."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(MODELS_URL)
        logger.info("sonda dgemma/models: %s", r.status_code)
        return r.status_code == 200
    except Exception as e:
        logger.warning("sonda dgemma falhou: %s", e)
        return False


def _url_redimensionada(url: str) -> str:
    """Reescreve dimension=WxH do CDN para DIMENSAO_CDN (resize na origem).

    Ex: ...?action=fit-in&dimension=870x707 → ...?action=fit-in&dimension=400x400.
    URLs sem o parâmetro voltam intactas (downscale local cobre nesses casos).
    """
    try:
        nova, n = re.subn(r"([?&]dimension=)\d+x\d+", r"\g<1>" + DIMENSAO_CDN, str(url or ""))
        return nova if n else str(url)
    except Exception:
        return str(url)


def _como_jpeg(conteudo: bytes) -> bytes:
    """Normaliza quaisquer bytes de imagem p/ JPEG (MIME do data-URL sempre confere).

    Aplica thumbnail local SOMENTE se o CDN ignorou o dimension e veio arquivo
    grande; caso contrário mantém os pixels que o CDN já redimensionou.
    """
    img = Image.open(io.BytesIO(conteudo)).convert("RGB")
    if len(conteudo) > LIMITE_BYTES_SEM_DOWNSCALE:
        img.thumbnail((LADO_MAX, LADO_MAX))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPG_Q)
    return buf.getvalue()


def fotos_para_dataurls(fotos_urls: List[str]) -> List[str]:
    """Baixa até MAX_IMGS fotos (redimensionadas na origem) e devolve data-URLs JPEG.

    Reduz nº de fotos (nunca a qualidade abaixo do útil) para caber no teto.
    """
    out: List[str] = []
    for url in (fotos_urls or [])[:MAX_IMGS]:
        try:
            r = httpx.get(_url_redimensionada(url), timeout=25, follow_redirects=True)
            r.raise_for_status()
            out.append("data:image/jpeg;base64," + base64.b64encode(_como_jpeg(r.content)).decode())
        except Exception as e:
            logger.warning("foto ignorada %s: %s", str(url)[:80], e)
    while out and sum(map(len, out)) > TETO_CHARS and len(out) > 1:
        out.pop()
    return out


def _payload_conservacao(dataurls: List[str], nota: str) -> Dict[str, Any]:
    return {
        "model": "dgemma",
        "state": {"note": nota},
        "images": dataurls,
        "questions": {
            "conservacao": {
                "type": "choice",
                "instructions": "Qual o estado de conservação visível do imóvel?",
                "criteria": {label: None for label in LABELS_CONSERVACAO},
            }
        },
    }


async def classifica_conservacao(
    fotos_urls: List[str],
    nota: str = "Imóvel em Joinville. Avalie conservação.",
    tentativas: tuple = (0, 60, 180),
    timeout: int = 120,
) -> Dict[str, Any]:
    """Classifica a conservação das fotos, com retry/backoff e chave nova por tentativa.

    Retorna o JSON do /v1/systemone ou {"erro": ...} (repetir Idempotency-Key dá 409,
    por isso cada tentativa usa chave nova).
    """
    dataurls = fotos_para_dataurls(fotos_urls)
    if not dataurls:
        return {"erro": "sem fotos acessíveis"}
    payload = _payload_conservacao(dataurls, nota)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for i, espera in enumerate(tentativas):
            if espera:
                logger.info("dgemma: tentativa %d em %ds...", i + 1, espera)
                await asyncio.sleep(espera)
            try:
                r = await client.post(
                    SYSTEMONE_URL, json=payload,
                    headers={"Idempotency-Key": str(uuid.uuid4())},
                )
            except Exception as e:
                logger.warning("dgemma: falha de rede (%s)", e)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                logger.warning("dgemma_busy (Retry-After=%s)", r.headers.get("Retry-After"))
                continue
            if r.status_code == 503:
                logger.warning("dgemma_unavailable")
                continue
            return {"erro": f"http {r.status_code}", "corpo": r.text[:300]}
    return {"erro": "dgemma esgotado, usar fallback"}


def agrega_conservacao(labels: List[Optional[str]]) -> Optional[str]:
    """Agrega labels por imóvel pelo pior caso (coerente com o flip conservador)."""
    validos = [l for l in labels if l in ORDEM_CONSERVACAO]
    if not validos:
        return None
    return max(validos, key=lambda l: ORDEM_CONSERVACAO.index(l))
