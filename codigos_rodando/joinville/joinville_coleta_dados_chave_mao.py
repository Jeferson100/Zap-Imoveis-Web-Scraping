import asyncio
import sys
from pathlib import Path
import time
import os

sys.path.append(str(Path(__file__).parent.parent))

from unificando_dados import consolidar_jsons, consolidar_parquet

from dotenv import load_dotenv

load_dotenv()

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent.parent.parent 

cidade = os.getenv("CIDADE_PASTA")
 
PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import ChavesMaoColeta

#URL_TEMPLATE = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg={pagina}"

URL_TEMPLATE = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?filtro=amin%3A{min}%2Camax%3A{max}&pg={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

total_paginas = 100

#output_file   = PASTA_DADOS / f'{cidade}_chave_mao_{now}.parquet' 

area_ranges = {'0': '50','51': '60','61': '65','66': '70','71': '75','76': '80','81': '90','91': '100',
               #'101': '110', '111': '120','121': '130','131': '150','151': '175','176': '200',
               #'201': '250','251': '300','301': '400',
               #'401': '500','501': '600','601': '3000000',
               
               }

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

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

consolidar_parquet('chave_mao', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")