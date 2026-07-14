import pandas as pd
from pathlib import Path
import sys
import asyncio
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

os.environ.setdefault(
    "PHOENIX_COLLECTOR_ENDPOINT",
    "https://app.phoenix.arize.com/s/sehnemjeferson",
)

PHOENIX_API_KEY = os.getenv("PHOENIX_API_KEY")
if not PHOENIX_API_KEY:
    raise RuntimeError(
        "PHOENIX_API_KEY não definida. "
        "Configure no ambiente ou no notebook antes de rodar."
    )

from phoenix.otel import register

tracer_provider = register(
    project_name="agente-imoveis",
    api_key=PHOENIX_API_KEY,
    auto_instrument=True,
    batch=True,
    protocol="http/protobuf",
)

cidade = 'joinville'
estado = 'sc'

BASE_DIR = Path.cwd().parent
PASTA_DADOS = BASE_DIR / 'dados' / cidade
df = pd.read_parquet(PASTA_DADOS / f'{cidade}_imoveis_limpo_2026-07.parquet')
sys.path.insert(0, r"C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis")

from src.agente_avaliacao_imagens.subgrafo_imagens import subgrafo_imagens, SubgrafoImagensState

NUM_IMOVEIS = min(10, len(df))
MAX_IMOVEIS_PARALELOS = int(os.getenv("TESTE_MAX_IMOVEIS_PARALELOS", "2"))
_imovel_sem = asyncio.Semaphore(MAX_IMOVEIS_PARALELOS)


async def processar_um(i: int) -> tuple[str, dict | Exception]:
    async with _imovel_sem:
        dados = df.iloc[i]
        urls = list(dados["fotos"])
        print(f"[{i+1}/{NUM_IMOVEIS}] {dados['url']}")
        try:
            response = await subgrafo_imagens.ainvoke(
                SubgrafoImagensState(fotos_urls=urls)
            )
            return dados["url"], response
        except Exception as e:
            logger.error("Falha no imovel %d: %s", i, e)
            return dados["url"], e


async def main():
    tarefas = [processar_um(i) for i in range(NUM_IMOVEIS)]
    resultados = await asyncio.gather(*tarefas, return_exceptions=True)

    respostas = {}
    for url, result in resultados:
        if isinstance(result, Exception):
            respostas[url] = None
        else:
            respostas[url] = result

    return respostas


if __name__ == "__main__":
    respostas = asyncio.run(main())
    tracer_provider.shutdown()
    print(f"\nProcessados {len(respostas)} imoveis com sucesso.")