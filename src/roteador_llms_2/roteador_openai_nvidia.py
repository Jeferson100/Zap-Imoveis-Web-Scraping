import asyncio
import logging
import os
import random
import re
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

from .rate_limit import acquire_nvidia_slot, register_429

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)
logger = logging.getLogger(__name__)

MAX_RETRIES = int(os.getenv("NVIDIA_MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.getenv("NVIDIA_RETRY_BASE_DELAY", "5.0"))


class RouterOpenaiNvidia:
    def __init__(
        self,
        messages: str,
        model_llm: str,
        strutured_output: Optional[BaseModel] = None,
        api_key: Optional[str] = None,
    ):
        self.messages = messages
        self.strutured_output = strutured_output
        self.model_llm = model_llm
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY não encontrada nas variáveis de ambiente.")
        self._client = AsyncOpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=self.api_key,
        )

    def _extrair_json(self, text: str) -> str:
        """Extrai o primeiro objeto JSON de dentro de qualquer texto."""
        match = re.search(r'\{.*\}', text, re.DOTALL)
        return match.group(0) if match else text.strip()

    async def llm_structured_openai_nvidia(self) -> Dict[str, Any] | None:
        """
        Chama modelo nvidia com saída estruturada

        """

        if self.strutured_output is None:
            raise ValueError(
                "structured_output precisa estar definido para usar essa função."
            )
        try:
            response = await self._client.chat.completions.parse(  # type: ignore[no-matching-overload]
                model=self.model_llm,
                messages=[
                    {"role": "user", "content": self.messages},
                ],
                response_format=self.strutured_output,  # type: ignore
            )
            raw = response.choices[0].message.content or "{}"
            cleaned = self._extrair_json(raw)
            return self.strutured_output.model_validate_json(cleaned)  # type: ignore
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error(
                "Erro ao chamar modelo Openai Nvidia com saída estruturada: %s", e
            )
        return None

    async def llm_openai_nvidia(self) -> str:
        """
        Chama modelo Openai Nvidia sem saída estruturada
        """
        response = await self._client.chat.completions.create(  # type: ignore[no-matching-overload]
            model=self.model_llm,
            messages=[
                {"role": "user", "content": self.messages},
            ],
        )
        return response.choices[0].message.content or ""

    async def llm_openai_nvidia_multimodal(self) -> str:
        for attempt in range(MAX_RETRIES):
            try:
                async with acquire_nvidia_slot():
                    response = await self._client.chat.completions.create(
                        model=self.model_llm,
                        messages=[{"role": "user", "content": self.messages}],
                    )
                    return response.choices[0].message.content or ""
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "too many requests" in err_str:
                    register_429()
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 2)
                    logger.warning(
                        "Retry OpenaiNvidia multimodal %d/%d em %.1fs: %s",
                        attempt + 1, MAX_RETRIES, delay, e,
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(
                    "Erro llm_openai_nvidia_multimodal apos %d tentativas: %s",
                    MAX_RETRIES, e,
                )
                raise
        return ""
