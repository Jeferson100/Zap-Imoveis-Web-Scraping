from scraping_zap_imoveis import ZapImoveisColeta
import asyncio
import time

URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&pagina={pagina}&areaMaxima=50&areaMinima=0"

orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)

total_paginas = 30

orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)

output_file = "zap_imoveis_joinville_0_50.json"

resultado = asyncio.run(orchestrator.run(
    output_file=str(output_file),
    total_pages=total_paginas
))