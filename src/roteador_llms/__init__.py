from .roteador_api_nvidia import RouterApiNvidia
from .roteador_cerebras import RouterCerebras
from .roteador_groq import RouterGroq
try:
    from .roteador_huggingface import RouterPydanticAI
except ImportError:  # dependência opcional (pydantic-ai-slim[huggingface])
    RouterPydanticAI = None
from .roteador_langchain_nvidia import RouterLangChainNvidia
from .roteador_llms import LlmRouter
from .roteador_openai_nvidia import RouterOpenaiNvidia
from .roteador_openrouter import RouterOpenRouter
from .roteador_zai import RouterZai
from .listar_modelos import (
    listar_modelos,
    listar_openrouter_detalhado,
    classificar_modelos,
    exportar_catalogo_parquet,
    normalizar_id,
    enriquecer_com_openrouter,
)
from .selecao_modelos import modelos_para, modelos_para_async, registrar_probe

__all__ = [
    "RouterGroq",
    "RouterCerebras",
    "RouterLangChainNvidia",
    "RouterOpenaiNvidia",
    "RouterOpenRouter",
    "RouterZai",
    "LlmRouter",
    "RouterApiNvidia",
    "listar_modelos",
    "listar_openrouter_detalhado",
    "classificar_modelos",
    "exportar_catalogo_parquet",
    "normalizar_id",
    "enriquecer_com_openrouter",
    "modelos_para",
    "modelos_para_async",
    "registrar_probe",
]

if RouterPydanticAI is not None:
    __all__.append("RouterPydanticAI")
