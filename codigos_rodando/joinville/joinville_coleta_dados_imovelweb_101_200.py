import asyncio
import os
import sys
import time
from pathlib import Path

import logging

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR = Path(__file__).parent.parent.parent

cidade = os.getenv("CIDADE_PASTA")

PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)

sys.path.append(str(Path(__file__).parent.parent))

sys.path.append(str(BASE_DIR / 'src'))

from unificando_dados import consolidar_parquet
from scraping_zap_imoveis import ImovelWebColeta

URL_TEMPLATE = "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-{area_min}-{area_max}-m2-pagina-{pagina}.html"

area_ranges = {
               '101': '120','121': '140','141': '160',
               '161': '180',
               '181': '200',
               #'201': '250','251': '300','301': '400','401': '500','501': '600','601': '3000000',

               }

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY", "5"))

now = time.strftime("%Y-%m")

for area_min, area_max in area_ranges.items():

    logger.info(f"Coletando dados de {area_min} a {area_max}")

    output_file = PASTA_DADOS / f'{cidade}_imovelweb_{now}_{area_min}_{area_max}.parquet'

    logger.info(f"Arquivo de dados gerado em: {output_file}")

    URL_TEMPLATE_FAIXA = URL_TEMPLATE.replace("{area_min}", area_min).replace("{area_max}", area_max)

    orchestrator = ImovelWebColeta(URL_TEMPLATE_FAIXA,
                                   headless=headless,
                                   max_concurrency=max_concurrency,
                                   retries=3,
                                   modo='sincrono',
                                   )

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        #total_pages=1,
    ))
