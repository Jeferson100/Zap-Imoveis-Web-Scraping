import json
import logging
import os
import re
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
        if not isinstance(self.messages, str):
            logger.warning("Z.ai nao suporta multimodal, pulando")
            return None
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

    def _extract_json(self, text: str) -> str:
        pattern = r"```json\s*(.*?)\s*```"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else text.strip()

    def _extrair_objeto(self, text: str) -> str:
        parsed = json.loads(text)
        while isinstance(parsed, dict) and len(parsed) == 1:
            inner = next(iter(parsed.values()))
            if isinstance(inner, list):
                parsed = inner[0] if inner else parsed
                break
            elif isinstance(inner, dict):
                parsed = inner
            else:
                break
        if isinstance(parsed, list):
            parsed = parsed[0]
        return json.dumps(parsed)

    async def llm_zai_structured(self) -> Optional[Any]:
        if self.strutured_output is None:
            raise ValueError("structured_output precisa estar definido")
        client = self._get_client()
        if client is None:
            logger.warning("ZAI_API_KEY nao configurada, pulando Z.ai")
            return None
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        f"Respond EXCLUSIVELY with a raw JSON object matching the schema below. "
                        f"Do NOT wrap it in 'answer', 'response', or any other key.\n\n"
                        f"Schema: {json.dumps(self.strutured_output.model_json_schema())}"
                    ),
                },
                {"role": "user", "content": self.messages},
            ]
            response = await client.chat.completions.create(
                model=self.model_llm,
                messages=messages,
                temperature=0.1,
            )
            content = response.choices[0].message.content
            if content:
                clean = self._extract_json(content)
                clean = self._extrair_objeto(clean)
                return self.strutured_output.model_validate_json(clean)
            return None
        except Exception as e:
            logger.error("Erro no Z.ai structured (%s): %s", self.model_llm, e)
            return None
