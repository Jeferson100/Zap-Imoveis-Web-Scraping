
from playwright.sync_api import Playwright, sync_playwright, BrowserContext
from playwright_stealth import Stealth
import logging
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ChaveMaoScraperLinks:

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._playwright = Stealth().use_sync(sync_playwright()).__enter__()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context: BrowserContext = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        self._page = self._context.new_page()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()

    def get_links(self, url: str, retries=3) -> list[str]:
        
        for i in range(retries):
            page = self._context.new_page()

            try:
                # Aumentamos o timeout e usamos um seletor mais comum em anúncios
                page.goto(url, wait_until="load", timeout=60000)
                
                # 1. Espera qualquer span de slider ou link de card aparecer
                # Usamos 'or' no seletor para ser mais resiliente
                page.wait_for_selector("span[id^='sl-'], a[href*='/imovel/']", timeout=15000)

                # 2. Rola a página para garantir que o lazy loading carregue os links
                page.evaluate("window.scrollBy(0, 1000)")

                # 3. Extração usando uma função JS válida
                links = page.locator("a[href*='/imovel/']").evaluate_all(
                    "elements => elements.map(el => el.href)"
                )

                # Filtra apenas links que contenham o padrão de anúncio e remove duplicados
                links_validos = list(set([l for l in links if "/imovel/" in l]))
                
                if links_validos:
                    logger.info("Links encontrados para a URL %s", url)
                    return list(set(links_validos))
                    
                logger.warning(f"Tentativa {i+1}: Nenhum link encontrado na {url}")

            except Exception as e:
                logger.error(f"Tentativa {i+1} falhou para {url}: {e}")
            finally:
                page.close()
                
                # Se falhou, espera um tempo maior antes de tentar de novo
            random.uniform(10, 20)
            
        return []

# Uso:
if __name__ == "__main__":
    #link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"
    link = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg=0"
    
    with ChaveMaoScraperLinks(headless=True) as scanner:
        total = scanner.get_links(link)
        print(f"Total de páginas: {total}")
