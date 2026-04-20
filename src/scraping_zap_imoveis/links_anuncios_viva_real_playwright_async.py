import asyncio
from playwright.async_api import async_playwright, Playwright
from playwright_stealth import Stealth
import logging
import warnings
import random

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class VivaRealScraperLinksAsync:

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
            self._browser = await self._playwright.chromium.launch(headless=self.headless,
                                                                   args=[
                                                                    '--disable-blink-features=AutomationControlled',
                                                                    '--disable-web-resources'
                                                                ])
            self._context = await self._browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            self._page = await self._context.new_page()
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

    """async def get_links(self, url: str) -> list[str]:
        page = await self._context.new_page()

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)

            await page.wait_for_selector('.listings-wrapper a.olx-core-surface', timeout=15000)

            links = await page.locator('.listings-wrapper a.olx-core-surface').evaluate_all(
                "nodes => nodes.map(n => n.href)"
            )
            
            logger.info("Links encontrados para a URL %s",url)
            return links

        except Exception as e:
            logger.error("Erro ao obter links para a URL:%s, error:%s", url, e)
            return []

        finally:
            await page.close()"""
    
    """async def get_links(self, url: str) -> list[str]:
        page = await self._context.new_page()
        try:
            # 1. Navegação
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 2. Seletor baseado no seu HTML (data-cy é o mais seguro)
            # Ele busca o link <a> que está dentro do item de lista do imóvel
            seletor_zap = 'li[data-cy="rp-property-cd"] a[href*="/imovel/"]'
            
            await asyncio.sleep(random.uniform(1, 3))
            
            # 3. Scroll para carregar (Zap é chato com lazy loading)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await asyncio.sleep(1)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

            # 4. Espera o seletor aparecer
            await page.wait_for_selector(seletor_zap, timeout=20000, state="attached")

            # 5. Extração dos links
            links = await page.locator(seletor_zap).evaluate_all(
                "nodes => nodes.map(n => n.href)"
            )
            
            # Limpeza: remove duplicados e lixo
            links_unicos = list(set([l for l in links if l]))
            
            logger.info(f"Sucesso: {len(links_unicos)} imóveis encontrados em Joinville.")
            return links_unicos

        except Exception as e:
            logger.error(f"Erro ao obter links no Zap: {e}")
            return []
        finally:
            await page.close()"""
    
    async def get_links(self, url: str, retries=3) -> list[str]:
        for i in range(retries):
            page = await self._context.new_page()
            try:
                # 1. Navegação menos exigente
                await page.goto(url, wait_until="commit", timeout=40000)
                
                # Espera manual curta em vez de networkidle
                await asyncio.sleep(random.uniform(0.5, 2))

                # 2. Scroll (Zap só renderiza com isso)
                await page.mouse.wheel(0, 1500)
                await asyncio.sleep(0.5)

                seletor = 'a.olx-core-surface[href*="/imovel/"]'
                # Busca links existentes, mesmo que não estejam visíveis
                links = await page.locator(seletor).evaluate_all(
                    "nodes => nodes.map(n => n.href)"
                )

                if links:
                    logger.info("Links encontrados para a URL %s", url)
                    return list(set(links))
                
                logger.warning(f"Tentativa {i+1}: Nenhum link encontrado na {url}")

            except Exception as e:
                logger.error(f"Tentativa {i+1} falhou para {url}: {e}")
            finally:
                await page.close()
            
            # Se falhou, espera um tempo maior antes de tentar de novo
            await asyncio.sleep(random.uniform(10, 20))
        
        return []


if __name__ == "__main__":
    

    async def main():
        paginas = 30
        
        for pagina in range(1, paginas + 1):
            link = f"https://www.vivareal.com.br/venda/santa-catarina/joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&pagina={pagina}"
            print(f"Raspando página {pagina}: {link}")
            
            async with VivaRealScraperLinksAsync(headless=True) as scanner:
                links = await scanner.get_links(link)
                print(f"Total de links na página {pagina}: {len(links)}")
                if links:
                    print(f"Primeiro link da página {pagina}: {links[0]}")
                else:
                    print(f"Nenhum link encontrado na página {pagina}.")
    
    
    asyncio.run(main())
    
    

    