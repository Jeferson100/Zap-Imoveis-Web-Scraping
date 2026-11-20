import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)
logger = logging.getLogger(__name__)


class RouterOpenaiNvidia:
    def __init__(
        self,
        messages: str,
        model_llm: str,
        strutured_output: Optional[BaseModel] = None,
    ):
        self.messages = messages
        self.strutured_output = strutured_output
        self.model_llm = model_llm
        # Cliente lazy: sem NVIDIA_API_KEY o import nao quebra; o LlmRouter
        # captura o ValueError e pula o provedor.
        self.client = self._get_client()

    def _get_client(self) -> AsyncOpenAI:
        api_key = os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError(
                "NVIDIA_API_KEY não está definida nas variáveis de ambiente."
            )
        return AsyncOpenAI(
            base_url="https://integrate.api.nvidia.com/v1", api_key=api_key
        )

    async def llm_structured_openai_nvidia(self) -> Dict[str, Any] | None:
        """
        Chama modelo nvidia com saída estruturada

        """

        if self.strutured_output is None:
            raise ValueError(
                "structured_output precisa estar definido para usar essa função."
            )
        try:
            response = await self.client.chat.completions.parse(  # type: ignore[no-matching-overload]
                model=self.model_llm,
                messages=[
                    {"role": "user", "content": self.messages},
                ],
                response_format=self.strutured_output,  # type: ignore
            )
            content = response.choices[0].message.parsed or "{}"
            return content  # type: ignore
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Erro ao chamar modelo Openai Nvidia com saída estruturada: %s", e
            )
        return None

    async def llm_openai_nvidia(self) -> str:
        """
        Chama modelo Openai Nvidia sem saída estruturada
        """
        response = await self.client.chat.completions.create(  # type: ignore[no-matching-overload]
            model=self.model_llm,
            messages=[
                {"role": "user", "content": self.messages},
            ],
        )
        return response.choices[0].message.content or ""
