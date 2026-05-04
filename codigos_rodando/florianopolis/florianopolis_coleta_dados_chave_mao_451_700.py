import asyncio
import sys
from pathlib import Path
import time
import os

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

sys.path.append(str(Path(__file__).parent.parent))

from unificando_dados import consolidar_jsons, consolidar_parquet

from limpando_dados import criar_area_ranges

from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = Path(__file__).parent.parent.parent  

cidade = os.getenv("CIDADE_PASTA")

PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import ChavesMaoColeta

URL_TEMPLATE = "https://www.chavesnamao.com.br/imoveis/sc-florianopolis/?filtro=amin%3A{min}%2Camax%3A{max}&pg={pagina}"

area_ranges = criar_area_ranges(
    inicio_total=451,
    fim_total=700,
    regras_intervalo=[
        (700, 100),
    ]
)

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

total_paginas = 100

now = time.strftime("%Y-%m")

for min_area, max_area in area_ranges.items():
    
    logger.info(f"Coletando dados de {min_area} a {max_area}")
    
    output_file   = PASTA_DADOS / f'{cidade}_chave_mao_{now}_{min_area}_{max_area}.parquet'
    
    logger.info(f"Arquivo de dados gerado em: {output_file}")
    
    URL_TEMPLATE_NEW = URL_TEMPLATE.format(min=min_area, max=max_area, pagina="{pagina}")
        
    
    orchestrator = ChavesMaoColeta(URL_TEMPLATE_NEW, 
                                headless=headless,
                                max_concurrency=max_concurrency,)

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=total_paginas
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")

#consolidar_parquet('chave_mao', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")