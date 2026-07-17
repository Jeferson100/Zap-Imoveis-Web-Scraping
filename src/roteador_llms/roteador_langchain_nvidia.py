import asyncio
import logging
from typing import Any, Optional

from langchain_nvidia_ai_endpoints import ChatNVIDIA
from pydantic import BaseModel

logger = logging.getLogger(__name__)


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

    async def llm_nvidia(self) -> Optional[str]:
        try:
            llm = ChatNVIDIA(model=self.model_llm)
            response = await asyncio.wait_for(
                llm.ainvoke([{"role": "user", "content": self.messages}]),
                timeout=60,
            )
            return response.content

        except asyncio.TimeoutError:
            logger.error("Timeout de 60s no llm_nvidia (%s)", self.model_llm)
            return None
        except Exception as e:
            logger.error("Erro no llm_nvidia (%s): %s", self.model_llm, e)
            return None

    async def llm_nvidia_structured(self) -> Optional[Any]:
        if self.strutured_output is None:
            raise ValueError(
                "structured_output precisa estar definido para usar essa função."
            )

        try:
            llm = ChatNVIDIA(model=self.model_llm, tokenizer_mode="hf")
            llm.nvidia_structured_output_backend = "xgrammar"
            llm_strutured = llm.with_structured_output(self.strutured_output)

            response = await asyncio.wait_for(
                llm_strutured.ainvoke(
                    [{"role": "user", "content": self.messages}]
                ),
                timeout=60,
            )

            if response is None:
                logger.warning(
                    "Resposta nula do modelo %s", self.model_llm,
                )

            return response

        except asyncio.TimeoutError:
            logger.error("Timeout de 60s no llm_nvidia_structured (%s)", self.model_llm)
            return None
        except Exception as e:
            logger.error("Erro no llm_nvidia_structured (%s): %s", self.model_llm, e)
            return None
