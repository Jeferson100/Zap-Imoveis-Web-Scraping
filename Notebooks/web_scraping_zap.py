from marshmallow.fields import URL
from scraping_zap_imoveis import ZapImoveisColeta
import asyncio
import time

#URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&pagina={pagina}&areaMaxima=50&areaMinima=0"

#URL_TEMPLATE = "https://www.zapimoveis.com.br/aluguel/imoveis/sc+joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C"
URL_TEMPLATE = "https://www.vivareal.com.br/aluguel/santa-catarina/joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C"

orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)

total_paginas = 1

orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)

output_file = "viva_real_alugueis.json"

resultado = asyncio.run(orchestrator.run(
    output_file=str(output_file),
    total_pages=total_paginas
))