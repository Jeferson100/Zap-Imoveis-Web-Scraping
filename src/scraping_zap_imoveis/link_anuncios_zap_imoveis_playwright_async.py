import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import logging
import warnings

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ZapScraperLinksAsync:

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._pw_cm = None

    async def __aenter__(self):
        try:
            self._pw_cm = Stealth().use_async(async_playwright())
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context()
            return self
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw_cm:
                await self._pw_cm.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.error("Erro ao fechar recursos: %s", e)

    async def get_links(self, url: str) -> list[str]:
        page = await self._context.new_page()

        try:
            await page.goto(url)

            links = await page.locator('.listings-wrapper a.olx-core-surface').evaluate_all(
                "nodes => nodes.map(n => n.href)"
            )
            
            logger.info("Links encontrados para a URL %s",url)
            return links

        except Exception as e:
            logger.error("Erro ao obter links para a URL:%s, error:%s", url, e)
            return []

        finally:
            await page.close()


if __name__ == "__main__":
    

    async def main():
        link = "https://www.zapimoveis.com.br/venda/?pagina=2&transacao=Venda"

        async with ZapScraperLinksAsync(headless=True) as scanner:
            links = await scanner.get_links(link)
            print(f"Total de links: {len(links)}")
            print(f"Primeiro link: {links}")
    
    
    asyncio.run(main())
    
    

    