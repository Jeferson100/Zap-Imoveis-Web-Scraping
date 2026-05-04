
import asyncio
import sys
from pathlib import Path
import time

import os

from dotenv import load_dotenv

load_dotenv()

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

sys.path.append(str(Path(__file__).parent.parent))

from limpando_dados import criar_area_ranges

# Paths
BASE_DIR    = Path(__file__).parent.parent.parent 

cidade = os.getenv("CIDADE_PASTA") 

PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import OLXColeta

#URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sc/florianopolis-e-regiao?lis=home_body_search_bar_1001&o={pagina}"

URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sc?q=florianopolis&ss={min}&se={max}&o={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

total_paginas = 100

output_file   = PASTA_DADOS / f'{cidade}_olx_{now}.json' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY_OLX"))

config_intervalos = [
    (40, 10),
    (250, 5),
    (400, 20),
    (1000, 100)
]

area_ranges = criar_area_ranges(
    inicio_total=0, 
    fim_total=30000000, 
    regras_intervalo=config_intervalos
)


for min, max in area_ranges.items():
    
    URL_TEMPLATE_NEW = URL_TEMPLATE.format(min=min, max=max, pagina="{pagina}")
    
    logger.info(f"Coletando dados de {min} a {max}")

    output_file  = PASTA_DADOS / f'{cidade}_olx_{now}_{min}_{max}.json' 

    orchestrator = OLXColeta(URL_TEMPLATE_NEW, headless=headless, max_concurrency=max_concurrency)

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=total_paginas
    ))

logger.info(f"Arquivo de dados gerado em: {output_file}")