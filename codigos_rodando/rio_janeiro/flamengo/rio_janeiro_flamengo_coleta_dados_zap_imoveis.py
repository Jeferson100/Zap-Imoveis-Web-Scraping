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

from scraping_zap_imoveis import ZapImoveisColeta

#URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/apartamentos/sp+sao-paulo+zona-sul+itaim-bibi/?onde=%2CS%C3%A3o+Paulo%2CS%C3%A3o+Paulo%2CZona+Sul%2CItaim+Bibi%2C%2C%2Cneighborhood%2CBR%3ESao+Paulo%3ENULL%3ESao+Paulo%3EZona+Sul%3EItaim+Bibi%2C-23.583748%2C-46.678074%2C&tipos=apartamento_residencial&pagina={pagina}"


URL_TEMPLATE = str(os.getenv("URL_TEMPLATE_ZAP"))

sys.path.append('..')
    
now = time.strftime("%Y-%m")

area_ranges = criar_area_ranges(
    inicio_total=0,
    fim_total=10000000000,
    regras_intervalo=[
        (100, 10),
        (300, 20),
    ]
)

total_paginas = 50

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "3"))

for area_min, area_max in area_ranges.items():
    
    logger.info(f"Coletando dados de {area_min} a {area_max}")

    output_file   = PASTA_DADOS / f'{cidade}_{bairro}_zap_{now}_{area_min}_{area_max}.parquet' 
    
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
        #total_pages=total_paginas,

    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")

#consolidar_jsons('zap', cidade, PASTA_DADOS)
#consolidar_parquet('zap', cidade, PASTA_DADOS)

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")

