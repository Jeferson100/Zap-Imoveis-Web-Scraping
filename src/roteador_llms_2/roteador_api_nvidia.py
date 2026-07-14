import asyncio
import json
import logging
import os
import random
import re
import time
from typing import Any, Optional

import httpx
import requests
from pydantic import BaseModel, ValidationError

from .rate_limit import COOLDOWN_429, acquire_nvidia_slot, register_429

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)
logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = int(os.getenv("NVIDIA_MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.getenv("NVIDIA_RETRY_BASE_DELAY", "5.0"))


def _retry_delay(response, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return float(retry_after)
        except ValueError:
            pass
    return RETRY_BASE_DELAY * (2**attempt) + random.uniform(0, 2)


class RouterApiNvidia:
    def __init__(
        self,
        messages: str,
        model_llm: str,
        strutured_output: Optional[BaseModel] = None,
        api_key: Optional[str] = None,
    ):
        self.messages = messages
        self.model_llm = model_llm
        self.strutured_output = strutured_output
        self.api_key = api_key or os.getenv("NVIDIA_API_KEY")
        self.base_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        self.session = requests.Session()

        if not self.api_key:
            raise ValueError("NVIDIA_API_KEY não encontrada nas variáveis de ambiente.")

    @property
    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    def _extract_json(self, text: str) -> str:
        """Extrai o conteúdo JSON de dentro de blocos de código markdown, se existirem."""
        match = re.search(r"```[Jj][Ss][Oo][Nn]\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            return brace_match.group(0)
        return text.strip()

    def _build_payload(self) -> dict:
        payload: dict = {
            "model": self.model_llm,
            "messages": [],
            "temperature": 0.1,
        }
        if self.strutured_output:
            payload["messages"].append({
                "role": "system",
                "content": (
                    "Respond EXCLUSIVELY in JSON. Schema: "
                    f"{json.dumps(self.strutured_output.model_json_schema())}"
                ),
            })
        payload["messages"].append({"role": "user", "content": self.messages})
        return payload

    def _parse_content(self, content: str) -> Any:
        if self.strutured_output:
            clean_json = self._extract_json(content)
            return self.strutured_output.model_validate_json(clean_json)
        return content

    def invoke(self) -> Any:
        """
        Método unificado. Se schema for passado, retorna objeto Pydantic.
        Caso contrário, retorna string.
        """
        payload = self._build_payload()

        for attempt in range(MAX_RETRIES):
            try:
                response = self.session.post(
                    self.base_url, headers=self._headers, json=payload, timeout=30
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                return self._parse_content(content)

            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                if status in RETRY_STATUS and attempt < MAX_RETRIES - 1:
                    if status == 429:
                        register_429()
                    delay = _retry_delay(e.response, attempt)
                    logger.warning(
                        "Rate limit %s — cooldown global %ds, retry %d/%d em %.1fs",
                        status, COOLDOWN_429, attempt + 1, MAX_RETRIES, delay,
                    )
                    time.sleep(delay)
                    continue
                logger.error("Erro na chamada da API Nvidia: %s", e)
                return None
            except requests.exceptions.RequestException as e:
                logger.error("Erro na chamada da API Nvidia: %s", e)
                return None
            except (ValidationError, json.JSONDecodeError) as e:
                logger.error("Erro ao processar formato estruturado: %s", e)
                return None

        return None

    async def ainvoke(self) -> Any:
        """
        Versão assíncrona do método invoke.
        """
        payload = self._build_payload()

        async with httpx.AsyncClient(timeout=180.0) as client:
            for attempt in range(MAX_RETRIES):
                content = ""
                try:
                    async with acquire_nvidia_slot():
                        response = await client.post(
                            self.base_url, headers=self._headers, json=payload
                        )
                        response.raise_for_status()

                        content = response.json()["choices"][0]["message"]["content"]

                        if self.strutured_output:
                            logger.info(
                                "Raw LLM response (primeiros 500 chars): %s",
                                content[:500],
                            )
                        return self._parse_content(content)

                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status in RETRY_STATUS and attempt < MAX_RETRIES - 1:
                        if status == 429:
                            register_429()
                        delay = _retry_delay(e.response, attempt)
                        logger.warning(
                            "Rate limit %s — cooldown global %ds, retry %d/%d em %.1fs",
                            status, COOLDOWN_429, attempt + 1, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error("Erro HTTP na chamada da API Nvidia: %s", e)
                    return None
                except (ValidationError, json.JSONDecodeError) as e:
                    logger.error(
                        "Erro de parsing do JSON estruturado: %s | Raw(200): %s",
                        e,
                        content[:200],
                    )
                    return None
                except Exception as e:
                    logger.error("Erro inesperado na chamada da API Nvidia: %s", e)
                    return None

        return None

    async def ainvoke_multimodal(self) -> Any:
        payload = {
            "model": self.model_llm,
            "messages": [{"role": "user", "content": self.messages}],
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=180.0) as client:
            for attempt in range(MAX_RETRIES):
                content = ""
                try:
                    async with acquire_nvidia_slot():
                        response = await client.post(
                            self.base_url, headers=self._headers, json=payload
                        )
                        response.raise_for_status()
                        content = response.json()["choices"][0]["message"]["content"]
                        return self._parse_content(content)

                except httpx.HTTPStatusError as e:
                    status = e.response.status_code
                    if status in RETRY_STATUS and attempt < MAX_RETRIES - 1:
                        if status == 429:
                            register_429()
                        delay = _retry_delay(e.response, attempt)
                        logger.warning(
                            "Rate limit %s, retry %d/%d em %.1fs",
                            status, attempt + 1, MAX_RETRIES, delay,
                        )
                        await asyncio.sleep(delay)
                        continue
                    logger.error("Erro HTTP: %s", e)
                    return None
                except (ValidationError, json.JSONDecodeError) as e:
                    logger.error("Erro de parsing: %s | Raw(200): %s", e, content[:200])
                    return None
                except Exception as e:
                    logger.error("Erro inesperado: %s", e)
                    return None

        return None
