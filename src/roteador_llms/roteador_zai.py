import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel

load_dotenv()

logger = logging.getLogger(__name__)


class RouterZai:
    def __init__(
        self,
        messages: str,
        model_llm: str,
        strutured_output: Optional[BaseModel] = None,
    ):
        self.messages = messages
        self.model_llm = model_llm
        self.strutured_output = strutured_output
        self._client = None

    def _get_client(self) -> Optional[AsyncOpenAI]:
        if self._client is None:
            api_key = os.getenv("ZAI_API_KEY")
            if not api_key:
                return None
            self._client = AsyncOpenAI(
                base_url="https://api.z.ai/api/paas/v4/",
                api_key=api_key,
            )
        return self._client

    async def llm_zai(self) -> Optional[str]:
        client = self._get_client()
        if client is None:
            logger.warning("ZAI_API_KEY nao configurada, pulando Z.ai")
            return None
        try:
            response = await client.chat.completions.create(
                model=self.model_llm,
                messages=[{"role": "user", "content": self.messages}],
                temperature=0.1,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("Erro no Z.ai (%s): %s", self.model_llm, e)
            return None

    async def llm_zai_structured(self) -> Optional[Any]:
        if self.strutured_output is None:
            raise ValueError("structured_output precisa estar definido")
        client = self._get_client()
        if client is None:
            logger.warning("ZAI_API_KEY nao configurada, pulando Z.ai")
            return None
        try:
            response = await client.chat.completions.create(
                model=self.model_llm,
                messages=[{"role": "user", "content": self.messages}],
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if content:
                return self.strutured_output.model_validate_json(content)
            return None
        except Exception as e:
            logger.error("Erro no Z.ai structured (%s): %s", self.model_llm, e)
            return None
