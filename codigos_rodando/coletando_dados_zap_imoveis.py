
import asyncio
import sys
import os
from scraping_zap_imoveis import ZapImoveisColeta
import time

URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?transacao=venda&onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&page={pagina}"

orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)

sys.path.append('..')
    
# Criar o diretório se não existir
os.makedirs("../dados", exist_ok=True)

now = time.strftime("%Y-%m-%d")

total_paginas = 333

resultado = asyncio.run(orchestrator.run(output_file=f"../dados/zap_imoveis_joinville_{now}.json", total_pages=total_paginas))