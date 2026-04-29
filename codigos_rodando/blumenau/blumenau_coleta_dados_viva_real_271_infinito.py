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

BASE_DIR    = Path(__file__).parent.parent.parent  

cidade = os.getenv("CIDADE_PASTA")


PASTA_DADOS = BASE_DIR / 'dados' / cidade
PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import VivaRealColeta

URL_TEMPLATE = "https://www.vivareal.com.br/venda/santa-catarina/blumenau/?onde=%2CSanta+Catarina%2CBlumenau%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EBlumenau%2C-26.916579%2C-49.071733%2C&pagina={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

area_ranges = {#'0': '60','61': '89', '90': '140','141': '220',
               '271': '350',
               '351': '600',
               '601': '3000000'
               }

total_paginas = 50

output_file   = PASTA_DADOS / f'{cidade}_vivareal_{now}.parquet' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for area_min, area_max in area_ranges.items():

    output_file   = PASTA_DADOS / f'{cidade}_vivareal_{now}_{area_min}_{area_max}.parquet' 

    URL_TEMPLATE_NEW = URL_TEMPLATE.replace(
        "{pagina}", 
        f"{{pagina}}&areaMaxima={area_max}&areaMinima={area_min}"
        )
    
    orchestrator = VivaRealColeta(URL_TEMPLATE_NEW, 
                                  headless=headless,
                                  max_concurrency=max_concurrency
                                  )

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=total_paginas,
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")

#consolidar_jsons('vivareal', cidade, PASTA_DADOS)
consolidar_parquet('vivareal', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")