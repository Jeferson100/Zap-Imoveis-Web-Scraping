
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

URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sc/norte-de-santa-catarina/balneario-camboriu?ss=121&se=170&o={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

total_paginas = 100

output_file   = PASTA_DADOS / f'{cidade}_olx_{now}_121_170.json' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY_OLX"))

orchestrator = OLXColeta(URL_TEMPLATE, headless=headless, max_concurrency=max_concurrency)

resultado = asyncio.run(orchestrator.run(
    output_file=str(output_file),
    total_pages=total_paginas
))