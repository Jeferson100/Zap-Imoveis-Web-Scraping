import asyncio
import logging
import time
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


# Breaker em dois níveis (por processo/job):
# - MORTE (410/404/402 no modelo): pula o MODELO no resto da execução.
# - THROTTLE (429/503/timeout e demais falhas do provedor): backoff com
#   half-open — após _MEIA_VIDA_THROTTLE_S, 1 tentativa-teste é liberada.
#   Sucesso zera tudo. Sem isso, 2 falhas no início do job desligavam
#   todos os provedores para as 6h restantes.
_FALHAS_PROVEDOR: dict = {}  # provedor -> [falhas_seguidas, timestamp_ultimo_trip]
_MODELOS_MORTOS: set = set()  # (provedor, modelo) com morte confirmada
_LIMITE_FALHAS_SEGUIDAS = 2
_MEIA_VIDA_THROTTLE_S = 180  # 3 min
_SINAIS_MORTE = ("410", "404", "402", "Gone", "Not Found",
                 "Payment Required", "Unauthorized")


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

        - Modelos com morte confirmada (410/404/402) são pulados.
        - Se strutured_output foi pedido e o provedor devolveu str (ex. Cerebras),
          tenta validar no schema; se não der, descarta (refletores nunca
          recebem str -> fim do "'str' has no attribute 'feedback'").
        """
        models = self.models.get(provider_name) or []
        for model in models:
            if (provider_name, model) in _MODELOS_MORTOS:
                continue
            logger.info("Tentando %s %s", provider_name, model)
            try:
                router = router_class(self.messages, model, self.strutured_output)

                func = getattr(router, method_name)
                result = await func() if asyncio.iscoroutinefunction(func) else func()

                if result and self.strutured_output and isinstance(result, str):
                    try:
                        result = self.strutured_output.model_validate_json(result)
                    except Exception:
                        logger.warning(
                            "Descartando str não-validável de %s %s",
                            provider_name, model,
                        )
                        continue
                if result:
                    return result
            except Exception as e:  # pylint: disable=broad-exception-caught
                if any(s in str(e) for s in _SINAIS_MORTE):
                    logger.warning(
                        "💀 Modelo morto %s %s — fora do resto do job",
                        provider_name, model,
                    )
                    _MODELOS_MORTOS.add((provider_name, model))
                else:
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
            trip = _FALHAS_PROVEDOR.get(name)
            if trip and trip[0] >= _LIMITE_FALHAS_SEGUIDAS:
                parado_ha = time.monotonic() - trip[1]
                if parado_ha < _MEIA_VIDA_THROTTLE_S:
                    logger.warning(
                        "⏭️ Pulando provedor %s (throttle há %.0fs, reteste em %.0fs)",
                        name, parado_ha, _MEIA_VIDA_THROTTLE_S - parado_ha,
                    )
                    errors[name] = "Em backoff (throttle)"
                    continue
                logger.info("🔓 Half-open: retestando provedor %s", name)
            try:
                logger.info("🔄 Rotando para provedor %s", name)
                response = await self._try_provider(name, cls, method)

                if response:
                    logger.info("✅ %s sucesso", name)
                    _FALHAS_PROVEDOR.pop(name, None)
                    return response

                errors[name] = "Todos os modelos deste provedor falharam"
                anterior = _FALHAS_PROVEDOR.get(name, [0, 0.0])[0]
                _FALHAS_PROVEDOR[name] = [anterior + 1, time.monotonic()]
            except Exception as e:  # pylint: disable=broad-exception-caught
                errors[name] = str(e)
                anterior = _FALHAS_PROVEDOR.get(name, [0, 0.0])[0]
                _FALHAS_PROVEDOR[name] = [anterior + 1, time.monotonic()]

        raise AllProvidersFailedError(f"Falha total: {errors}")
