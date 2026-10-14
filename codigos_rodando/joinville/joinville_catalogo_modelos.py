"""Coleta mensal do catálogo de modelos LLM + probe da seleção em uso.

Roda dia 2 de cada mês (antes do primeiro flip, dia 3):
1. Gera dados/catalogo_modelos_<hoje>.parquet (herda status_probe anterior).
2. Proba os modelos da seleção em uso (visao/texto x nvidia/groq/zai).
3. Registra vivo/morto no parquet (morto só em 410/404/402/401 ou
   timeout repetido; 429/5xx isolado não marca).
"""
import asyncio
import base64
import io
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.roteador_llms import registrar_probe  # noqa: E402
from src.roteador_llms.listar_modelos import exportar_catalogo_parquet  # noqa: E402
from src.roteador_llms.roteador_llms import AllProvidersFailedError, LlmRouter  # noqa: E402
from src.roteador_llms.selecao_modelos import modelos_para  # noqa: E402

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)

CHAVE_ROUTER = {"nvidia": "api_nvidia_models", "groq": "groq_models", "zai": "zai_models"}
KEY_ROUTER = {"API_Nvidia": "nvidia", "Groq": "groq", "Zai": "zai"}
TIMEOUT_S = 90


def _msg_visao():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return [{"type": "text", "text": "Descreva em uma palavra."},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}}]


async def _probar(prov_cat: str, model: str, modo: str) -> str:
    """Retorna 'vivo', 'morto' ou 'inconclusivo'."""
    import src.roteador_llms.roteador_llms as R

    R._FALHAS_PROVEDOR.clear()
    kw = {"groq_models": [], "cerebras_models": [], "api_nvidia_models": [],
          "api_langchain_nvidia_models": [], "api_openai_nvidia_models": [],
          "openrouter_models": [], "zai_models": []}
    kw[CHAVE_ROUTER[prov_cat]] = [model]
    msg = _msg_visao() if modo == "visao" else "Responda apenas com a palavra: ok"
    timeouts = 0
    for tentativa in (1, 2):
        try:
            await asyncio.wait_for(LlmRouter(msg, **kw).llm_router(), timeout=TIMEOUT_S)
            return "vivo"
        except AllProvidersFailedError as e:
            texto = str(e)
            if any(s in texto for s in ("410", "404", "402", "401", "Gone",
                                        "Not Found", "Payment Required",
                                        "Unauthorized")):
                return "morto"
            return "inconclusivo"
        except (asyncio.TimeoutError, TimeoutError):
            timeouts += 1
            logger.warning("Timeout %s %s (tentativa %d/2)", prov_cat, model, tentativa)
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Erro %s %s: %s %s", prov_cat, model, type(e).__name__, str(e)[:100])
            return "inconclusivo"
    return "morto" if timeouts >= 2 else "inconclusivo"


async def main() -> None:
    hoje = date.today().isoformat()
    destino = BASE_DIR / "dados" / f"catalogo_modelos_{hoje}.parquet"
    caminho = await exportar_catalogo_parquet(destino)
    logger.info("Catálogo salvo em %s", caminho)

    alvos = []  # (prov_cat, id, modo)
    vistos = set()
    for provedor, capacidade in [("API_Nvidia", "texto"), ("API_Nvidia", "visao"),
                                 ("Groq", "texto"), ("Zai", "texto")]:
        try:
            for mid in modelos_para(capacidade, provedor):
                chave = (KEY_ROUTER[provedor], mid, capacidade)
                if chave not in vistos:
                    vistos.add(chave)
                    alvos.append(chave)
        except Exception as e:
            logger.warning("Seleção %s/%s indisponível: %s", capacidade, provedor, e)
    logger.info("%d modelos na seleção para probar.", len(alvos))

    resultados = {}
    for prov_cat, mid, modo in alvos:
        t0 = time.monotonic()
        status = await _probar(prov_cat, mid, modo)
        logger.info("%s %s %s -> %s (%.1fs)", prov_cat, mid, modo, status,
                    time.monotonic() - t0)
        if status in ("vivo", "morto"):
            resultados[(prov_cat, mid)] = status
    if resultados:
        registrar_probe(resultados)
    logger.info("Probe concluído: %d registrados.", len(resultados))


if __name__ == "__main__":
    asyncio.run(main())
