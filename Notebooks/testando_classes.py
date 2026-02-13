from time import time
from scraping_zap_imoveis import ZapScraperTotalPagina
from scraping_zap_imoveis import ZapScraperLinks
from scraping_zap_imoveis import ZapScraperLinksAsync
from scraping_zap_imoveis import ZapScraperTotalPaginaAsync
from scraping_zap_imoveis import ZapScraperDadosImovel
from scraping_zap_imoveis import ZapScraperDadosImovelAsync, DadosImovel
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time


urls = ['https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-elevador-campestre-santo-andre-sp-62m2-id-2818274726/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-casa-de-condominio-2-quartos-com-piscina-alphaville-nova-esplanada-votorantim-sp-226m2-id-2866295152/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-com-jardim-butanta-zona-oeste-sao-paulo-sp-350m2-id-2763317088/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-piscina-bom-retiro-sao-paulo-65m2-id-2863929162/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-redencao-manaus-198m2-id-2750221407/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-espaco-gourmet-pinheiros-sao-paulo-95m2-id-2863933126/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-piscina-cidade-moncoes-sao-paulo-98m2-id-2857696093/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-1-quarto-mobiliado-vila-clementino-sao-paulo-39m2-id-2863930483/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-casa-de-condominio-2-quartos-com-piscina-liberdade-parnamirim-75m2-id-2818646620/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-terreno-lote-condominio-centro-barra-dos-coqueiros-300m2-id-2718205444/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-piscina-campo-belo-sao-paulo-103m2-id-2857695917/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-mobiliado-serraria-maceio-67m2-id-2828546615/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-1-quarto-mobiliado-vila-olimpia-sao-paulo-95m2-id-2486367295/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-mobiliado-pinheiros-sao-paulo-40m2-id-2857688536/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-loja-salao-jardins-aracaju-51m2-id-2848732925/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-1-quarto-mobiliado-campo-belo-sao-paulo-49m2-id-2857683242/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-piscina-jardim-sao-paulo-zona-norte-sao-paulo-74m2-id-2719473505/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-mobiliado-jardim-aeroporto-sao-paulo-74m2-id-2857698061/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-mobiliado-itaim-bibi-sao-paulo-105m2-id-2857695436/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-piscina-perdizes-sao-paulo-151m2-id-2857688046/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-mobiliado-vila-nova-conceicao-sao-paulo-70m2-id-2857694351/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-parque-guajara-icoaraci-belem-160m2-id-2845651256/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-1-quarto-com-churrasqueira-caicara-praia-grande-49m2-id-2861320153/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-mobiliado-parque-colonial-sao-paulo-118m2-id-2857696967/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-piscina-grajau-belo-horizonte-85m2-id-2863926629/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-mobiliado-vila-olimpia-sao-paulo-64m2-id-2857686152/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-pinheiros-sao-paulo-95m2-id-2863928539/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-cerqueira-cesar-sao-paulo-95m2-id-2857698454/?source=ranking%2Crp',
                'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-piscina-pinheiros-sao-paulo-90m2-id-2857690789/?source=ranking%2Crp']


"""if __name__ == "__main__":
    
    link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"
    
    with ZapScraperTotalPagina(headless=True) as scanner:
        total = scanner.get_total_pages(link)
        print(f"Resultado Final: {total}")"""
        
"""if __name__ == "__main__":
    link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"

    with ZapScraperLinks(headless=True) as scanner:
        links = scanner.get_links(link)
        print(f"Total de links: {len(links)}")
        print(f"Primeiro link: {links}")"""
        
"""if __name__ == "__main__":
    
    link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"
    
    async def main():
        link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"

        async with ZapScraperLinksAsync(headless=True) as scanner:
            links = await scanner.get_links(link)
            print(f"Total de links: {len(links)}")
            print(f"Primeiro link: {links}")

    asyncio.run(main())"""
    
"""if __name__ == "__main__":
    link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"
    
    async def main():
        link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"

        async with ZapScraperTotalPaginaAsync(headless=True) as scanner:
            total = await scanner.get_total_pages(link)
            print(f"Total de páginas: {total}")

    asyncio.run(main())"""
    
"""if __name__ == "__main__":
    
    import json

    lista_dados = []
    
    time_start = time.time()
    
    with ZapScraperDadosImovel(urls[0], headless=True) as scraper:
        dados = scraper.extrair()
        lista_dados.append(dados)

    #print(json.dumps(da, indent=4, ensure_ascii=False))
    print(dados)

    time_end = time.time()
    print(f"Tempo de execução: {time_end - time_start} segundos")"""
    
"""if __name__ == "__main__":
    import json
    
    def scrape_url(url: str) -> DadosImovel:
        
        asyncio.set_event_loop(None)  # ← garante que não há loop nesta thread
        
        with ZapScraperDadosImovel(url, headless=True) as scraper:
            return scraper.extrair()
        
    lista_dados = []
    time_start = time.time()

    with ThreadPoolExecutor(max_workers=1) as executor:
        for url in urls:
            dados = executor.submit(scrape_url, url).result()
            lista_dados.append(dados)
            print(f"✓ {url}")

    for dados in lista_dados:
        print(json.dumps(dados.to_dict(), indent=4, ensure_ascii=False))

    time_end = time.time()
    print(f"\nTotal de imóveis: {len(lista_dados)}")
    print(f"Tempo de execução: {time_end - time_start:.2f} segundos")"""
    
"""import json
    async def main():
        async def scrape(url: str) -> DadosImovel:
            async with ZapScraperDadosImovelAsync(url, headless=True) as scraper:
                return await scraper.extrair()

        resultados = await asyncio.gather(*[scrape(url) for url in urls])
        return resultados
    start_time = time.time()
    resultado = asyncio.run(main())
    end_time = time.time()
    
    print(resultado)
    import json
    async def main():
        semaforo = asyncio.Semaphore(5)

        async def scrape(url: str) -> DadosImovel:
            async with semaforo:
                async with ZapScraperDadosImovelAsync(url, headless=True) as scraper:
                    return await scraper.extrair()

        resultados = await asyncio.gather(*[scrape(url) for url in urls])
        return resultados

    start_time = time.time()
    resultado = asyncio.run(main())
    end_time = time.time()

    print(resultado)
    
    with open("resultados.json", "w", encoding="utf-8") as f:
        json.dump([dados.to_dict() for dados in resultado], f, indent=4, ensure_ascii=False)
    print(f"Tempo de execução: {end_time - start_time} segundos")"""
    

from time import time
from scraping_zap_imoveis import ZapScraperTotalPagina
from scraping_zap_imoveis import ZapScraperLinks
from scraping_zap_imoveis import ZapScraperLinksAsync
from scraping_zap_imoveis import ZapScraperTotalPaginaAsync
from scraping_zap_imoveis import ZapScraperDadosImovel
from scraping_zap_imoveis import ZapScraperDadosImovelAsync, DadosImovel
import asyncio
from concurrent.futures import ThreadPoolExecutor
import time
import logging
import json

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def pegando_total_de_paginas(url):
    async with ZapScraperTotalPaginaAsync(headless=True) as scanner:
        total = await scanner.get_total_pages(url)
    return total

async def pegando_links(link):
    async with ZapScraperLinksAsync(headless=True) as scanner:
        links = await scanner.get_links(link)
    return links

async def pegando_dados(urls):
    semaforo = asyncio.Semaphore(5)

    async def scrape(url: str) -> DadosImovel:
        async with semaforo:
            async with ZapScraperDadosImovelAsync(url, headless=True) as scraper:
                return await scraper.extrair()

    resultados = await asyncio.gather(*[scrape(url) for url in urls])
    return resultados


star_time = time.time()
            
link = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?transacao=venda&onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&page=1"



total_paginas = asyncio.run(pegando_total_de_paginas(link))

logger.info(f"Total de páginas: {total_paginas}")

lista_dados = []

for pagina in range(1, total_paginas + 1):
    link = f"https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?transacao=venda&onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&page={pagina}"
    
    links_da_pagina = asyncio.run(pegando_links(link))
    
    logger.info(f"Total de links: {len(links_da_pagina)}")
    
    logger.info(f"Primeiro link: {links_da_pagina}")
    
    dados_paginas = asyncio.run(pegando_dados(links_da_pagina))
    
    logger.info(f"Total de dados: {len(dados_paginas)}")

    lista_dados.extend(dados_paginas)
    
    logger.info("Dados salvos com sucesso")


with open("resultados.json", "w", encoding="utf-8") as f:
    json.dump([dados.to_dict() for dados in lista_dados], f, indent=4, ensure_ascii=False)
    
end_time = time.time()

logger.info(f"Tempo de execução: {end_time - star_time} segundos")
    