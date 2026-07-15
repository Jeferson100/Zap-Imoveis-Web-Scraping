import logging
import os

logger = logging.getLogger(__name__)


def _parse_max_tentativas(raw: str) -> int:
    try:
        val = int(raw)
        if val < 0 or val > 10:
            raise ValueError(f"fora do intervalo [0, 10]: {val}")
        return val
    except (ValueError, TypeError) as e:
        logger.warning("IMAGENS_MAX_TENTATIVAS inválido (%s), usando padrão 1. Erro: %s", raw, e)
        return 1


def _parse_bool(raw: str | None, default: bool) -> bool:
    return raw.strip().lower() in ("1", "true", "yes") if raw else default


MAX_TENTATIVAS = _parse_max_tentativas(os.getenv("IMAGENS_MAX_TENTATIVAS", "0"))
TAMANHO_LOTE = int(os.getenv("IMAGENS_TAMANHO_LOTE", "5"))
TIMEOUT_DOWNLOAD = float(os.getenv("IMAGENS_TIMEOUT_DOWNLOAD", "15"))
TIMEOUT_LLM = float(os.getenv("IMAGENS_TIMEOUT_LLM", "30"))
MAX_BYTES_IMAGEM = int(os.getenv("IMAGENS_MAX_BYTES", str(10 * 1024 * 1024)))
MAX_CONCURRENT_LOTES = int(os.getenv("IMAGENS_MAX_CONCURRENT_LOTES", "8"))
MODEL_VISION = os.getenv("IMAGENS_MODEL_VISION", "mistralai/ministral-14b-instruct-2512")
#MODEL_TEXTO = os.getenv("IMAGENS_MODEL_TEXTO", "deepseek-ai/deepseek-v4-pro")
USAR_URL_DIRETA: bool = _parse_bool(os.getenv("IMAGENS_USAR_URL_DIRETA"), True)  # =true requer suporte do modelo LLM_Visão a URLs externas
CACHE_DOWNLOADS: bool = _parse_bool(os.getenv("IMAGENS_CACHE_DOWNLOADS"), True)
