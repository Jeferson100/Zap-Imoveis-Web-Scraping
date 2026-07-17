import pandas as pd
from pathlib import Path
import sys
import asyncio
import logging
import os
from dotenv import load_dotenv
from phoenix.otel import register

load_dotenv()

logger = logging.getLogger(__name__)

tracer_provider = register(
  project_name="agente-imoveis",
  auto_instrument=True
)

cidade = 'joinville'
estado = 'sc'

BASE_DIR = Path.cwd().parent
PASTA_DADOS = BASE_DIR / 'dados' / cidade
df = pd.read_parquet(PASTA_DADOS / f'{cidade}_imoveis_limpo_2026-07.parquet')
sys.path.insert(0, r"C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis")

from src.agente_avaliacao_imagens.subgrafo_imagens import subgrafo_imagens, SubgrafoImagensState
from src.agente_validacao.subgrafo_validacao import subgrafo_validacao, SubgrafoValidacaoState
from src.agente_potencial_flip import grafo_principal, EstadoGlobal

NUM_IMOVEIS = min(10, len(df))
MAX_IMOVEIS_PARALELOS = int(os.getenv("TESTE_MAX_IMOVEIS_PARALELOS", "2"))
_imovel_sem = asyncio.Semaphore(MAX_IMOVEIS_PARALELOS)

colunas = ['metragem', 'banheiros', 'vagas', 'quartos', 'valor_imovel','bairro','tipo_imovel','p50_bairro','valor_predito',] 
async def processar_um(i: int) -> tuple[str, dict | Exception]:
    async with _imovel_sem:
        row = df.iloc[i]
        url = row['url']
        dados_selecionados = {col: row[col] for col in colunas}
        descricao = row['descricao']
        fotos = row['fotos']
        print(f"[{i+1}/{NUM_IMOVEIS}] {url}")
        try:
            
            estado = EstadoGlobal(
                fotos_urls= fotos,
                dados_imovel=dados_selecionados,
                descricao_texto=descricao,
            
            )
            response = await grafo_principal.ainvoke(estado)
            return url, response
        except Exception as e:
            logger.error("Falha no imovel %d: %s", i, e)
            return url, e
        
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