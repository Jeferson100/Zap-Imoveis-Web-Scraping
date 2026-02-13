from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import warnings
import logging

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ZapScraperLinks:

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

    def get_links(self, url: str) -> list[str]:
        page = self._context.new_page()

        try:
            page.goto(url)

            links = page.locator('.listings-wrapper a.olx-core-surface').evaluate_all(
                "nodes => nodes.map(n => n.href)"
            )

            logger.info("Links encontrados para a URL %s", url)

            return links

        except Exception as e:
            logger.error("Erro ao obter links para a URL:%s, error:%s", url, e)
            return []

        finally:
            page.close()


# Uso:
if __name__ == "__main__":
    link = "https://www.zapimoveis.com.br/venda/?pagina=2&transacao=Venda"

    with ZapScraperLinks(headless=True) as scanner:
        links = scanner.get_links(link)
        print(f"Total de links: {len(links)}")
        print(f"Primeiro link: {links}")