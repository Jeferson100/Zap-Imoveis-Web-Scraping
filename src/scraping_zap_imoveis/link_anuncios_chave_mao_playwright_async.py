import asyncio
import logging
from playwright.async_api import async_playwright, BrowserContext
from playwright_stealth import Stealth
from typing import Optional
import random

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ChaveMaoScraperLinksAsync:
    

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # segundos
    def __init__(self,headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._pw_cm = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        try:
            self._pw_cm = Stealth().use_async(async_playwright())
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            )
            self._page = await self._context.new_page()
            return self
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def get_links(self, url: str, retries=3) -> list[str]:
        # Criamos uma nova página dentro do contexto existente
        for i in range(retries):
            page = await self._context.new_page()

            try:
                logger.info(f"Acessando: {url}")
                # Navegação com timeout e espera baseada em domcontentloaded (mais rápido que 'load')
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # 1. Espera os seletores de anúncios aparecerem
                await page.wait_for_selector("a[href*='/imovel/']", timeout=15000)

                # 2. Scroll para carregar elementos de lazy loading
                await page.evaluate("window.scrollBy(0, 1000)")
                # Pequena pausa para o JS do site processar o scroll
                await asyncio.sleep(1)

                # 3. Extração dos links
                links = await page.locator("a[href*='/imovel/']").evaluate_all(
                    "elements => elements.map(el => el.href)"
                )

                # Filtra links válidos e remove duplicatas usando set
                links_validos = list(set([l for l in links if "/imovel/" in l]))
                
                if links_validos:
                    logger.info("Links encontrados para a URL %s", url)
                    return list(set(links_validos))
                    
                logger.warning(f"Tentativa {i+1}: Nenhum link encontrado na {url}")

            except Exception as e:
                logger.error(f"Tentativa {i+1} falhou para {url}: {e}")
            finally:
                await page.close()
        
            await asyncio.sleep(random.uniform(10, 20))
            
        return []
if __name__ == "__main__":
    
    async def main():
        link = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg=2"
        
        # Note o uso de 'async with'
        async with ChaveMaoScraperLinksAsync(headless=True) as scanner:
            links = await scanner.get_links(link)
            print(f"Links encontrados: {len(links)}")
            print(f"Primeiro link: {links}")
    asyncio.run(main())