
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

URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/pr+curitiba/?pagina={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

area_ranges = {
               '0': '25','26': '34','35': '43','44': '50', '51': '55','56': '60','61': '64','65': '68','69': '70','71': '74','75': '77','78': '80',
               '81': '84','88': '89','90': '94','95': '99','100': '104','105': '110','111': '116','117': '122','123': '129','130': '135','136': '145',
               '146': '155','156': '165','166': '177','178': '190',
               '191': '205','206': '220','221': '240','241': '265','266': '295','296': '320','321': '355','356': '390',
               '391': '440','441': '490','491': '600','601': '900','901': '2000','2001': '3000000'
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
                                  retries=1,
                                  max_concurrency_links=1
                                  )

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=total_paginas,
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")

consolidar_jsons('zap', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")