
import asyncio
import sys
from pathlib import Path
import time

import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR    = Path(__file__).parent.parent.parent  

cidade = os.getenv("CIDADE_PASTA")

PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)   

sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import OLXColeta

#URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sc/norte-de-santa-catarina/blumenau?o={pagina}"

URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sc?q=blumenau&ss=91&se=200&o={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

total_paginas = 120

output_file   = PASTA_DADOS / f'{cidade}_olx_{now}_91_200.json' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY_OLX"))

orchestrator = OLXColeta(URL_TEMPLATE, headless=headless, max_concurrency=max_concurrency)

resultado = asyncio.run(orchestrator.run(
    output_file=str(output_file),
    total_pages=total_paginas
))