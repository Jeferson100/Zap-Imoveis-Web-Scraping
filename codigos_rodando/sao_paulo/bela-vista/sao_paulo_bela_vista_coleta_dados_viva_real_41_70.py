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

from scraping_zap_imoveis import VivaRealColeta

URL_TEMPLATE = str(os.getenv("URL_TEMPLATE_VIVAREAL"))

sys.path.append('..')
    
now = time.strftime("%Y-%m")

area_ranges = criar_area_ranges(
    inicio_total=41,
    fim_total=70,
    regras_intervalo=[
        (50, 2),
        (70, 5),
    ]
)

total_paginas = 50

output_file   = PASTA_DADOS / f'{cidade}_vivareal_{now}.parquet' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for area_min, area_max in area_ranges.items():

    output_file   = PASTA_DADOS / f'{cidade}_{bairro}_vivareal_{now}_{area_min}_{area_max}.parquet' 

    URL_TEMPLATE_NEW = URL_TEMPLATE.replace(
        "{pagina}", 
        f"{{pagina}}&areaMaxima={area_max}&areaMinima={area_min}"
        )
    
    orchestrator = VivaRealColeta(URL_TEMPLATE_NEW, 
                                  headless=headless,
                                  max_concurrency=max_concurrency,
                                  retries=1
                                  )

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=total_paginas,
    ))
    

logger.info(f"Arquivo de dados gerado em: {output_file}")

#consolidar_jsons('vivareal', cidade, PASTA_DADOS)
#consolidar_parquet('vivareal', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")

