import asyncio
import sys
from pathlib import Path
import time
import os

sys.path.append(str(Path(__file__).parent.parent.parent))

from unificando_dados import consolidar_jsons, consolidar_parquet

from limpando_dados import criar_area_ranges

from dotenv import load_dotenv

load_dotenv()

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent.parent.parent.parent

cidade = os.getenv("CIDADE_PASTA")

bairro = os.getenv("BAIRRO")
 
PASTA_DADOS = BASE_DIR / 'dados' / cidade  / bairro

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import ChavesMaoColeta

URL_TEMPLATE  = str(os.getenv("URL_TEMPLATE_CHAVES"))

sys.path.append('..')
    
now = time.strftime("%Y-%m")

total_paginas = 100

#output_file   = PASTA_DADOS / f'{cidade}_chave_mao_{now}.parquet' 

area_ranges = criar_area_ranges(
    inicio_total=0,
    fim_total=100,
    regras_intervalo=[
        (100, 10),
    ]
)

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for min_area, max_area in area_ranges.items():
    
    logger.info(f"Coletando dados de {min_area} a {max_area}")
    
    output_file   = PASTA_DADOS / f'{cidade}_{bairro}_chave_mao_{now}_{min_area}_{max_area}.parquet'
    
    logger.info(f"Arquivo de dados gerado em: {output_file}")
    
    URL_TEMPLATE_NEW = URL_TEMPLATE.format(min=min_area, max=max_area, pagina="{pagina}")
        
    
    orchestrator = ChavesMaoColeta(URL_TEMPLATE_NEW, 
                                headless=headless,
                                max_concurrency=max_concurrency,)

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        #total_pages=total_paginas
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")
