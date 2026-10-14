import asyncio
import logging
from typing import Any, Optional, Type

from pydantic import BaseModel

from .roteador_api_nvidia import RouterApiNvidia
from .roteador_cerebras import RouterCerebras
from .roteador_groq import RouterGroq
from .roteador_langchain_nvidia import RouterLangChainNvidia
from .roteador_openai_nvidia import RouterOpenaiNvidia
from .roteador_openrouter import RouterOpenRouter
from .roteador_zai import RouterZai

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)

logger = logging.getLogger(__name__)


class AllProvidersFailedError(Exception):
    """Exceção levantada quando todos os provedores LLM falham"""


# Circuit breaker em memória (por processo/job): provedor com N falhas
# completas seguidas é pulado no resto da execução. Evita repetir varreduras
# condenadas (~2 min de 410/429) a cada imóvel.
_FALHAS_PROVEDOR: dict = {}
_LIMITE_FALHAS_SEGUIDAS = 2


class LlmRouter:
    def __init__(
        self,
        messages: str,
        strutured_output: Optional[Type[BaseModel]] = None,
        **kwargs,
    ):
        self.messages = messages
        self.strutured_output = strutured_output

        # Seleção dinâmica: None = resolver via catálogo na hora do llm_router.
        # OpenRouter permanece fixo (decisão de custo: ["openrouter/free"]).
        # Nenhum id de modelo é escrito à mão aqui.
        self.models = {
            "Groq": kwargs.get("groq_models"),
            "Cerebras": kwargs.get("cerebras_models"),
            "API_Nvidia": kwargs.get("api_nvidia_models"),
            "Langchain_nvidia": kwargs.get("api_langchain_nvidia_models"),
            "Openai_nvidia": kwargs.get("api_openai_nvidia_models"),
            "OpenRouter": kwargs.get(
                "openrouter_models",
                ["openrouter/free"],
            ),
            "Zai": kwargs.get("zai_models"),
        }

    async def _try_provider(
        self, provider_name: str, router_class: Type, method_name: str
    ) -> Any:
        """
        Método genérico para tentar modelos de um provedor específico.
        """
        models = self.models.get(provider_name) or []
        for model in models:
            logger.info("Tentando %s %s", provider_name, model)
            try:
                router = router_class(self.messages, model, self.strutured_output)

                func = getattr(router, method_name)
                result = await func() if asyncio.iscoroutinefunction(func) else func()

                if result:
                    return result
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Falha no %s %s %s", provider_name, model, e)
                continue
        return None

    async def llm_router(self) -> Any:
        logger.info("Iniciando roteamento LLM")

        # Ordem por taxa de sucesso observada (probe 2026-10-14):
        # Nvidia/Groq primeiro; OpenRouter e Zai (cota 429) por último.
        # Cerebras fora da rota (402 Payment Required).
        providers = [
            ("API_Nvidia", RouterApiNvidia, "ainvoke"),
            (
                "Groq",
                RouterGroq,
                "llm_structured_groq" if self.strutured_output else "llm_groq",
            ),
            (
                "Openai_nvidia",
                RouterOpenaiNvidia,
                (
                    "llm_structured_openai_nvidia"
                    if self.strutured_output
                    else "llm_openai_nvidia"
                ),
            ),
            (
                "Langchain_nvidia",
                RouterLangChainNvidia,
                "llm_nvidia_structured" if self.strutured_output else "llm_nvidia",
            ),
            (
                "OpenRouter",
                RouterOpenRouter,
                (
                    "llm_openrouter_structured"
                    if self.strutured_output
                    else "llm_openrouter"
                ),
            ),
            (
                "Zai",
                RouterZai,
                (
                    "llm_zai_structured"
                    if self.strutured_output
                    else "llm_zai"
                ),
            ),
        ]

        # Resolução lazy: listas None viram seleção dinâmica pelo catálogo.
        # Visão (messages em lista, ex. fotos) ou texto, por provedor.
        capacidade = "visao" if isinstance(self.messages, list) else "texto"
        from .selecao_modelos import modelos_para_async

        for name in list(self.models):
            if self.models[name] is None and name != "OpenRouter":
                try:
                    self.models[name] = await modelos_para_async(capacidade, name)
                except Exception as e:  # sem catálogo nem live -> provedor vazio
                    logger.warning("Sem modelos para %s (%s)", name, e)
                    self.models[name] = []

        errors = {}
        for name, cls, method in providers:
            if _FALHAS_PROVEDOR.get(name, 0) >= _LIMITE_FALHAS_SEGUIDAS:
                logger.warning(
                    "⏭️ Pulando provedor %s (circuit breaker: %d falhas seguidas)",
                    name, _FALHAS_PROVEDOR[name],
                )
                errors[name] = "Pulado pelo circuit breaker"
                continue
            try:
                logger.info("🔄 Rotando para provedor %s", name)
                response = await self._try_provider(name, cls, method)

                if response:
                    logger.info("✅ %s sucesso", name)
                    _FALHAS_PROVEDOR[name] = 0
                    return response

                errors[name] = "Todos os modelos deste provedor falharam"
                _FALHAS_PROVEDOR[name] = _FALHAS_PROVEDOR.get(name, 0) + 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                errors[name] = str(e)
                _FALHAS_PROVEDOR[name] = _FALHAS_PROVEDOR.get(name, 0) + 1

        raise AllProvidersFailedError(f"Falha total: {errors}")
