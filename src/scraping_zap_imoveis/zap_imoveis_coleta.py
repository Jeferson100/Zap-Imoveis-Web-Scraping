import asyncio
import time
import logging
import json
import sys
from .extrair_dados_zap_imoveis_playwright_async import ZapScraperDadosImovelAsync
from .total_pagina_zap_imovel_playwright_async import ZapScraperTotalPaginaAsync
from .link_anuncios_zap_imoveis_playwright_async import ZapScraperLinksAsync
from tqdm import tqdm


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ZapImoveisColeta:
    def __init__(self, base_url_template, headless=True, max_concurrency=5):
        self.base_url_template = base_url_template
        self.headless = headless
        self.max_concurrency = max_concurrency
        self.lista_dados = []
    
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    async def _get_total_pages(self):
        url_inicial = self.base_url_template.format(pagina=1)
        logger.info(f"Obtendo total de páginas para: {url_inicial}")
        async with ZapScraperTotalPaginaAsync(headless=self.headless) as scanner:
            return await scanner.get_total_pages(url_inicial)

    async def _get_links_from_page(self, page_number):
        url = self.base_url_template.format(pagina=page_number)
        async with ZapScraperLinksAsync(headless=self.headless) as scanner:
            links = await scanner.get_links(url)
            logger.info(f"Página {page_number}: {len(links)} links encontrados.")
            return links

    async def _get_item_data(self, url, semaphore):
        async with semaphore:
            try:
                # Note: Passamos a URL para o extrator de detalhes
                async with ZapScraperDadosImovelAsync(url, headless=self.headless) as scraper:
                    return await scraper.extrair()
            except Exception as e:
                logger.error(f"Erro ao extrair {url}: {e}")
                return None

    async def run(self, output_file="resultados.json", total_pages: int = None):
        
        if total_pages is not None:
            total_paginas = total_pages
        else:
            total_paginas = await self._get_total_pages()
            
        if not total_paginas:
            logger.error("Não foi possível determinar o total de páginas.")
            return
        
        logger.info("Determinando o total de %s páginas ", total_paginas)
        
        semaphore = asyncio.Semaphore(self.max_concurrency)

        for pagina in tqdm(range(1, total_paginas + 1)):
            
            logger.info(f"--- Processando Página {pagina}/{total_paginas} ---")
            
            links = await self._get_links_from_page(pagina)
            
            if not links:
                logger.warning("Página %s não retornou links, pulando.", pagina)
                continue

            tasks = [self._get_item_data(link, semaphore) for link in links]
            
            resultados_pagina = await asyncio.gather(*tasks)
            
            valid_results = [r for r in resultados_pagina if r is not None]
            
            self.lista_dados.extend(valid_results)
            
            logger.info("Página %s finalizada. %s imóveis processados.", pagina, len(valid_results))

        self._save_to_json(output_file)
    
        logger.info("Execução finalizada. Total de imóveis coletados: %s", len(self.lista_dados))
        
        return self.lista_dados


    def _save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump([d.to_dict() for d in self.lista_dados], f, indent=4, ensure_ascii=False)
        logger.info(f"Dados salvos em {filename}")

if __name__ == "__main__":
    # Template da URL com o marcador {pagina} para substituição dinâmica
    URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?transacao=venda&onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&page={pagina}"

    orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)
    
    asyncio.run(orchestrator.run())