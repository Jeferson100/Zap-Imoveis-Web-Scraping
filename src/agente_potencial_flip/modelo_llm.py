"""Fabrica do chat model dos agentes flip (sombra).

Default: NVIDIA + `nvidia/nemotron-3.5-bolt-e4b` (tool calling verificado, ~1s
por chamada). OpenRouter segue como alternativa via env.
Overrides por env, sem tocar codigo:
    FLIP_MODEL     -> id do modelo (ex.: openai/gpt-oss-20b)
    FLIP_BASE_URL  -> endpoint OpenAI-compativel (ex.: https://openrouter.ai/api/v1)
    FLIP_API_KEY   -> chave (default: NVIDIA_API_KEY, depois OPENROUTER_API_KEY)
    FLIP_TIMEOUT   -> timeout por chamada em segundos (default 120)
    FLIP_MAX_TOKENS -> teto de tokens de saida por chamada (default 4096)

O `.env` do repo e carregado de forma preguicosa (override=False), porque nem
todo entrypoint chama `load_dotenv`: assim a chave existe mesmo em script puro.

A chave nunca e obrigatoria na importacao: sem env, usa um placeholder e o
erro so aparece na chamada (mantem `import agente_potencial_flip` e os testes
offline funcionando).
"""

import os
import logging

from openai import APIConnectionError, APIStatusError, APITimeoutError


from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

BASE_URL_PADRAO = "https://integrate.api.nvidia.com/v1"
MODELO_PADRAO = "nvidia/nemotron-3.5-bolt-e4b"
CHAVE_PLACEHOLDER = "sem-chave-configurada"

MAX_TOKENS_PADRAO = 4096


def _carregar_env() -> None:
    """Carrega o .env do repo sem sobrescrever variaveis ja definidas."""
    try:
        from dotenv import find_dotenv, load_dotenv

        caminho = find_dotenv(usecwd=True)
        if caminho:
            load_dotenv(caminho, override=False)
    except Exception:  # python-dotenv ausente ou .env ilegivel: segue com os.environ
        pass


def modelo_flip_padrao() -> str:
    return os.environ.get("FLIP_MODEL", "").strip() or MODELO_PADRAO


def criar_modelo_flip(model: str | None = None, **kwargs) -> ChatOpenAI:
    """Cria o ChatOpenAI dos agentes flip respeitando os overrides de env."""
    _carregar_env()
    base_url = os.environ.get("FLIP_BASE_URL", "").strip() or BASE_URL_PADRAO
    api_key = (
        os.environ.get("FLIP_API_KEY", "").strip()
        or os.environ.get("NVIDIA_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
        or CHAVE_PLACEHOLDER
    )
    timeout = int(os.environ.get("FLIP_TIMEOUT", "120"))
    # Sem teto explicito o provedor reserva o contexto inteiro do modelo
    # (~112k no OpenRouter) e devolve 402 quando o saldo nao cobre esse pior caso.
    max_tokens = kwargs.pop("max_tokens", None)
    if max_tokens is None:
        max_tokens = int(os.environ.get("FLIP_MAX_TOKENS", str(MAX_TOKENS_PADRAO)))
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model or modelo_flip_padrao(),
        timeout=timeout,
        max_retries=1,
        max_tokens=max_tokens,
        **kwargs,
    )


FALLBACKS_PADRAO = (
    "nvidia/nemotron-3-ultra-550b-a55b,"
    "nvidia/nemotron-3.5-bolt-e4b,"
    "mistralai/mistral-large-4-1t-a52b,"
    "meta/muse-glimmer-30b"
)


def modelos_fallback() -> list[str]:
    """Lista da env (lida por chamada). Vazia = sem fallback."""
    bruto = os.environ.get("FLIP_MODEL_FALLBACKS", "").strip() or FALLBACKS_PADRAO
    return [x.strip() for x in bruto.split(",") if x.strip()]


def criar_modelo_flip_com_fallbacks():
    """Principal (lightning no CI) + cadeia testada, por chamada LLM."""
    principal = criar_modelo_flip()
    fallbacks = [criar_modelo_flip(model=x) for x in modelos_fallback()]
    if not fallbacks:
        return principal
    logger.warning("modelo principal: %s | fallbacks: %s",
                   modelo_flip_padrao(), ",".join(modelos_fallback()))
    return principal.with_fallbacks(
        fallbacks,
        exceptions_to_handle=(APIStatusError, APITimeoutError, APIConnectionError),
    )
