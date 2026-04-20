from playwright.sync_api import Playwright, sync_playwright
from playwright_stealth import Stealth
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ZapScraperTotalPagina:
    
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
    
    def __enter__(self):
        self._playwright = Stealth().use_sync(sync_playwright()).__enter__()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
    
    def get_total_pages(self, url: str) -> int:
        page = self._context.new_page()
        
        try:
            page.goto(url)
            
            page.keyboard.press("End")
            
            ultimo_botao = page.locator('.olx-core-pagination__button').last
            
            ultimo_botao.wait_for(state="attached", timeout=15000)
            
            texto = ultimo_botao.inner_text()
            
            total_paginas = int(texto.replace('.', '').strip())
            
            return total_paginas
        
        except Exception as e:
            logger.error("Erro ao obter o total de páginas: %s", e)
            return 0
        
        finally:
            page.close()


# Uso:
if __name__ == "__main__":
    #link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"
    link = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?transacao=venda&onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&page=1"
    
    with ZapScraperTotalPagina(headless=True) as scanner:
        total = scanner.get_total_pages(link)
        print(f"Total de páginas: {total}")
