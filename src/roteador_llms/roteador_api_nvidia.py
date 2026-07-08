import json
import logging
import os
import re
from typing import Any, Optional

import httpx
import requests
from pydantic import BaseModel, ValidationError

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%m/%d/%Y %I:%M:%S %p"
)
logger = logging.getLogger(__name__)


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

    # @retry(stop_max_attempt_number=2, wait_fixed=2000)
    def invoke(self) -> Any:
        """
        Método unificado. Se schema for passado, retorna objeto Pydantic.
        Caso contrário, retorna string.
        """
        payload = {
            "model": self.model_llm,
            "messages": [],
            "temperature": 0.1,  # Baixa temperatura para saídas estruturadas
        }

        if self.strutured_output:
            payload["messages"].append(  # type: ignore
                {
                    "role": "system",
                    "content": f"Respond EXCLUSIVELY in JSON. Schema: {json.dumps(self.strutured_output.model_json_schema())}",
                }
            )

        payload["messages"].append({"role": "user", "content": self.messages})  # type: ignore

        try:
            response = self.session.post(
                self.base_url, headers=self._headers, json=payload, timeout=30
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

            if self.strutured_output:
                clean_json = self._extract_json(content)
                return self.strutured_output.model_validate_json(clean_json)

            return content

        except requests.exceptions.RequestException as e:
            logger.error("Erro na chamada da API: Nvidia: %s", e)
            return None
        except (ValidationError, json.JSONDecodeError) as e:
            logger.error("Erro ao processar formato estruturado: %s", e)
            return None

    # @retry(stop_max_attempt_number=2, wait_fixed=2000)
    async def ainvoke(self) -> Any:
        """
        Versão assíncrona do método invoke.
        """
        payload = {"model": self.model_llm, "messages": [], "temperature": 0.1}

        if self.strutured_output:
            payload["messages"].append(  # type: ignore
                {
                    "role": "system",
                    "content": f"Respond EXCLUSIVELY in JSON. Schema: {json.dumps(self.strutured_output.model_json_schema())}",
                }
            )

        payload["messages"].append({"role": "user", "content": self.messages})  # type: ignore

        async with httpx.AsyncClient(timeout=180.0) as client:
            try:
                response = await client.post(
                    self.base_url, headers=self._headers, json=payload
                )
                response.raise_for_status()

                content = response.json()["choices"][0]["message"]["content"]

                if self.strutured_output:
                    logger.info("Raw LLM response (primeiros 500 chars): %s", content[:500])
                    clean_json = self._extract_json(content)
                    return self.strutured_output.model_validate_json(clean_json)

                return content

            except httpx.HTTPStatusError as e:
                logger.error("Erro HTTP na chamada da API Nvidia: %s", e)
                return None
            except (ValidationError, json.JSONDecodeError) as e:
                logger.error("Erro de parsing do JSON estruturado: %s | Raw(200): %s", e, content[:200])
                return None
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error("Erro inesperado na chamada da API Nvidia: %s", e)
                return None
