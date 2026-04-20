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

BASE_DIR    = Path(__file__).parent.parent.parent  

cidade = os.getenv("CIDADE_PASTA")


PASTA_DADOS = BASE_DIR / 'dados' / cidade
PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import VivaRealColeta

URL_TEMPLATE = "https://www.vivareal.com.br/venda/parana/curitiba/?onde=%2CParan%C3%A1%2CCuritiba%2C%2C%2C%2C%2Ccity%2CBR%3EParana%3ENULL%3ECuritiba%2C-25.437238%2C-49.269973%2C&pagina={pagina}"

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

output_file   = PASTA_DADOS / f'{cidade}_vivareal_{now}.json' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for area_min, area_max in area_ranges.items():

    output_file   = PASTA_DADOS / f'{cidade}_vivareal_{now}_{area_min}_{area_max}.json' 

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

consolidar_jsons('vivareal', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")
