
import asyncio
import sys
from pathlib import Path
import time

sys.path.append(str(Path(__file__).parent.parent))

from unificando_dados import consolidar_jsons, consolidar_parquet

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

URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+balneario-picarras/?transacao=venda&onde=%2CSanta+Catarina%2CBalne%C3%A1rio+Pi%C3%A7arras%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EBalneario+Picarras%2C-26.771375%2C-48.678034%2C&pagina={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

area_ranges = {'0': '90',
               '91': '150',
               '151': '30000000'
               }

total_paginas = 50

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for area_min, area_max in area_ranges.items():
    
    logger.info(f"Coletando dados de {area_min} a {area_max}")

    output_file   = PASTA_DADOS / f'{cidade}_zap_{now}_{area_min}_{area_max}.parquet' 
    
    logger.info(f"Arquivo de dados gerado em: {output_file}")

    URL_TEMPLATE_NEW = URL_TEMPLATE.replace(
        "{pagina}", 
        f"{{pagina}}&areaMaxima={area_max}&areaMinima={area_min}"
        )
    
    orchestrator = ZapImoveisColeta(URL_TEMPLATE_NEW, 
                                  headless=headless,
                                  max_concurrency=max_concurrency
                                  )

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        #total_pages=total_paginas,
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")

#consolidar_jsons('zap', cidade, PASTA_DADOS)
consolidar_parquet('zap', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")

