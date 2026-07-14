import asyncio
import logging
import os
import random
from typing import Any, Optional

from langchain_nvidia_ai_endpoints import ChatNVIDIA  # pylint: disable=import-error
from pydantic import BaseModel

from .rate_limit import acquire_nvidia_slot, register_429

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)

logger = logging.getLogger(__name__)

MAX_RETRIES = int(os.getenv("NVIDIA_MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.getenv("NVIDIA_RETRY_BASE_DELAY", "5.0"))


class RouterLangChainNvidia:
    def __init__(
        self,
        messages: str,
        model_llm: str,
        strutured_output: Optional[BaseModel] = None,
    ):
        self.messages = messages
        self.model_llm = model_llm
        self.strutured_output = strutured_output

    # @retry(stop_max_attempt_number=2, wait_fixed=2000)
    async def llm_nvidia(self) -> Optional[str]:
        """
        Chama modelo Nvidia via LangChain
        """
        try:
            llm = ChatNVIDIA(model=self.model_llm)
            response = await llm.ainvoke([{"role": "user", "content": self.messages}])
            return response.content  # type:ignore

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Erro no llm_nvidia: %s", e)
            raise

    # @retry(stop_max_attempt_number=2, wait_fixed=2000)
    async def llm_nvidia_structured(self) -> Optional[Any] | BaseModel:
        """
        Chama modelo Nvidia via LangChain com saída estruturada
        """
        if self.strutured_output is None:
            raise ValueError(
                "structured_output precisa estar definido para usar essa função."
            )

        try:
            llm = ChatNVIDIA(model=self.model_llm)
            llm_strutured = llm.with_structured_output(  # type:ignore
                self.strutured_output  # type:ignore
            )

            response = await llm_strutured.ainvoke(  # type:ignore
                [{"role": "user", "content": self.messages}]
            )  # type:ignore

            if response is None:
                logger.warning(
                    "Resposta nula recebida do modelo Nvidia. O modelo model_llm=%s pode não suportar saída estruturada.",
                    self.model_llm,
                )

            return response  # type:ignore

        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Erro no llm_nvidia_structured: %s", e)
            raise

    async def llm_nvidia_multimodal(self) -> Optional[str]:
        from langchain_core.messages import HumanMessage

        for attempt in range(MAX_RETRIES):
            try:
                async with acquire_nvidia_slot():
                    llm = ChatNVIDIA(model=self.model_llm)
                    response = await llm.ainvoke([HumanMessage(content=self.messages)])
                    return response.content
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "too many requests" in err_str:
                    register_429()
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 2)
                    logger.warning(
                        "Retry LangChainNvidia multimodal %d/%d em %.1fs: %s",
                        attempt + 1, MAX_RETRIES, delay, e,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "Erro llm_nvidia_multimodal apos %d tentativas: %s",
                    MAX_RETRIES, e,
                )
                raise
        return None
