"""Fabrica do chat model dos agentes flip (sombra).

Default: OpenRouter + `openai/gpt-oss-120b` (tool/structured calling verificados).
Overrides por env, sem tocar codigo:
    FLIP_MODEL     -> id do modelo (ex.: openai/gpt-oss-20b)
    FLIP_BASE_URL  -> endpoint OpenAI-compativel (ex.: https://integrate.api.nvidia.com/v1)
    FLIP_API_KEY   -> chave (default: OPENROUTER_API_KEY)
    FLIP_TIMEOUT   -> timeout por chamada em segundos (default 120)

A chave nunca e obrigatoria na importacao: sem env, usa um placeholder e o
erro so aparece na chamada (mantem `import agente_potencial_flip` e os testes
offline funcionando).
"""

import os

from langchain_openai import ChatOpenAI

BASE_URL_PADRAO = "https://openrouter.ai/api/v1"
MODELO_PADRAO = "openai/gpt-oss-120b"
            #"meta/muse-glimmer-30b"
            #"nvidia/nemotron-3.5-super-vl-120b-a12b"
CHAVE_PLACEHOLDER = "sem-chave-configurada"


def modelo_flip_padrao() -> str:
    return os.environ.get("FLIP_MODEL", "").strip() or MODELO_PADRAO


def criar_modelo_flip(model: str | None = None, **kwargs) -> ChatOpenAI:
    """Cria o ChatOpenAI dos agentes flip respeitando os overrides de env."""
    base_url = os.environ.get("FLIP_BASE_URL", "").strip() or BASE_URL_PADRAO
    api_key = (
        os.environ.get("FLIP_API_KEY", "").strip()
        or os.environ.get("OPENROUTER_API_KEY", "").strip()
        or CHAVE_PLACEHOLDER
    )
    timeout = int(os.environ.get("FLIP_TIMEOUT", "120"))
    return ChatOpenAI(
        base_url=base_url,
        api_key=api_key,
        model=model or modelo_flip_padrao(),
        timeout=timeout,
        max_retries=1,
        **kwargs,
    )
