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

from scraping_zap_imoveis import ChavesMaoColeta

URL_TEMPLATE = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-itajai/?pg={pagina}"

sys.path.append('..')
    
now = time.strftime("%Y-%m")

total_paginas = 100

output_file   = PASTA_DADOS / f'{cidade}_chave_mao_{now}.json' 

headless = os.getenv("HEADLESS", "True").lower() == "true"

max_concurrency = int(os.getenv("MAX_CONCURRENCY_CHAVE"))

orchestrator = ChavesMaoColeta(URL_TEMPLATE, 
                               headless=headless, 
                               max_concurrency=max_concurrency
                               )

resultado = asyncio.run(orchestrator.run(
    output_file=str(output_file),
    total_pages=total_paginas
))