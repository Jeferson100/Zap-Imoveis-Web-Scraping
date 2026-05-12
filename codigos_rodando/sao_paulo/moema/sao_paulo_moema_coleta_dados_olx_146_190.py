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

sys.path.append(str(Path(__file__).parent.parent.parent))

from limpando_dados import criar_area_ranges

cidade = os.getenv("CIDADE_PASTA")

BASE_DIR    = Path(__file__).parent.parent.parent.parent

cidade = os.getenv("CIDADE_PASTA")

bairro = os.getenv("BAIRRO")
 
PASTA_DADOS = BASE_DIR / 'dados' / cidade  / bairro

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent.parent))

from scraping_zap_imoveis import OLXColeta

#URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sp?q=sao+paulo&o={pagina}"

URL_TEMPLATE = os.getenv("URL_TEMPLATE_OLX")

now = time.strftime("%Y-%m")

total_paginas = 50

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY_OLX"))

area_ranges = criar_area_ranges(
    inicio_total=146,
    fim_total=190,
    regras_intervalo=[
        (190, 10),
    ]
)

for min_area, max_area in area_ranges.items():
    
    logger.info(f"Coletando dados de {min_area} a {max_area}")
    
    output_file   = PASTA_DADOS / f'{cidade}_{bairro}_olx_{now}_{min_area}_{max_area}.json'
    
    logger.info(f"Arquivo de dados gerado em: {output_file}")
    
    URL_TEMPLATE_NEW = URL_TEMPLATE.format(min=min_area, max=max_area, pagina="{pagina}")
    
    orchestrator = OLXColeta(URL_TEMPLATE_NEW, headless=headless, max_concurrency=max_concurrency)

    resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        #total_pages=total_paginas
    ))
logger.info(f"Arquivo de dados gerado em: {output_file}")
