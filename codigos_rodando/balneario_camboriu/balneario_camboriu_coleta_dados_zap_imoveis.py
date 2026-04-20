
import asyncio
import sys
from pathlib import Path
import time

sys.path.append(str(Path(__file__).parent.parent))

from unificando_dados import consolidar_jsons

import os

from dotenv import load_dotenv

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR  = Path(__file__).parent.parent.parent


cidade = os.getenv("CIDADE_PASTA")

PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import ZapImoveisColeta

URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+balneario-camboriu/?onde=%2CSanta+Catarina%2CBalne%C3%A1rio+Cambori%C3%BA%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EBalneario+Camboriu%2C-26.997984%2C-48.63258%2C&pagina={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

area_ranges = {'0': '50',
               '51': '60',
               '61': '70',
               '71': '80',
               '81': '90',
               '91': '100',
               '101': '120',
               '121': '140',
               '141': '160',
               '161': '180',
               '181': '200',
               '201': '250',
               '251': '300',
               '301': '400',
               '401': '500',
               '501': '600',
               '601': '3000000',
               
               }


total_paginas = 50

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for area_min, area_max in area_ranges.items():
    
    logger.info(f"Coletando dados de {area_min} a {area_max}")

    output_file   = PASTA_DADOS / f'{cidade}_zap_{now}_{area_min}_{area_max}.json' 
    
    logger.info(f"Arquivo de dados gerado em: {output_file}")

    URL_TEMPLATE_NEW = URL_TEMPLATE.replace(
        "{pagina}", 
        f"{{pagina}}&areaMaxima={area_max}&areaMinima={area_min}"
        )
    
    orchestrator = ZapImoveisColeta(URL_TEMPLATE_NEW, 
                                  headless=headless,
                                  max_concurrency=max_concurrency,
                                  retries=1
                                  )

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=total_paginas,
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")

consolidar_jsons('zap', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")

