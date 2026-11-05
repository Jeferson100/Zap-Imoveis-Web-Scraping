import asyncio
from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import logging
from typing import Optional
import warnings
import random

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ANTI_DETECT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
"""

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


class ZapScraperLinksAsync:

    def __init__(self, headless: bool = True, proxy: Optional[dict] = None):
        self.headless = headless
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._context = None
        self._pw_cm = None
        self._user_agent = random.choice(USER_AGENTS)

    async def __aenter__(self):
        try:
            self._pw_cm = Stealth().use_async(async_playwright())
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            viewport_w = random.randint(1850, 1980)
            viewport_h = random.randint(1020, 1120)
            context_kwargs = dict(
                viewport={"width": viewport_w, "height": viewport_h},
                user_agent=self._user_agent,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                device_scale_factor=random.choice([1, 1.25, 1.5, 2]),
                has_touch=False,
            )
            if self.proxy:
                context_kwargs["proxy"] = self.proxy
            self._context = await self._browser.new_context(**context_kwargs)
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
                await page.add_init_script(ANTI_DETECT_JS)
                await self._navegar(page, url)
                await self._rolar(page)
                if await self._bloqueado_pelo_cloudflare(page):
                    # Contexto já marcado: nenhum reload resolve (testado). Só
                    # um browser novo passa, então falha rápido em vez de gastar
                    # 30s nos wait_for_selector.
                    raise RuntimeError("Cloudflare challenge (contexto bloqueado)")
                seletores = ['li[data-cy="rp-property-cd"] a[href*="/imovel/"]', 'a[href*="/imovel/"]']
                links = []
                for seletor in seletores:
                    try:
                        await page.wait_for_selector(seletor, timeout=10000)
                        links = await page.locator(seletor).evaluate_all("nodes => nodes.map(n => n.href)")
                        if links:
                            break
                    except Exception:
                        continue
                if links:
                    logger.info("Links encontrados para a URL %s", url)
                    return list(set(links))
                logger.warning(f"Tentativa {i+1}: Nenhum link encontrado na {url}")
            except Exception as e:
                logger.error(f"Tentativa {i+1} falhou para {url}: {e}")
            finally:
                await page.close()
            # Só vale esperar se ainda houver tentativa pela frente. Antes, com
            # retries=1, dormia 15-30s depois da única tentativa e descartava a
            # página sem nunca ler o DOM (que já estava renderizado).
            if i + 1 < retries:
                await asyncio.sleep(random.uniform(3, 6))
        return []

    async def _navegar(self, page, url: str) -> None:
        """Navega sem depender de networkidle.

        No ZAP a rede nunca fica ociosa (ads, analytics, heartbeat) e o
        networkidle estourava 60s em ~25% das páginas que já estavam
        renderizadas. O conteúdo é SSR; o wait_for_selector em get_links é
        quem garante que os cards chegaram.
        """
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            # Timeout de navegação não significa página vazia: segue para o DOM.
            logger.warning("goto lento em %s (%s); tentando ler o DOM mesmo assim", url, str(e)[:80])

    @staticmethod
    async def _bloqueado_pelo_cloudflare(page) -> bool:
        try:
            titulo = (await page.title()) or ""
        except Exception:
            return False
        return any(
            marca in titulo
            for marca in ("Attention Required", "Just a moment", "Cloudflare")
        )

    async def _rolar(self, page) -> None:
        await asyncio.sleep(random.uniform(1, 2))
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 2 / 3)")
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        except Exception as e:
            logger.debug("Scroll falhou (página ainda carregando?): %s", e)


if __name__ == "__main__":
    

    async def main():
        paginas =100
        
        for pagina in range(1, paginas + 1):
            link = f"https://www.zapimoveis.com.br/venda/?pagina={pagina}&transacao=Venda"
            print(f"Raspando página {pagina}: {link}")
            
            async with ZapScraperLinksAsync(headless=True) as scanner:
                links = await scanner.get_links(link)
                print(f"Total de links na página {pagina}: {len(links)}")
                if links:
                    print(f"Primeiro link da página {pagina}: {links[0]}")
                else:
                    print(f"Nenhum link encontrado na página {pagina}.")
        """link = "https://www.zapimoveis.com.br/venda/?pagina=2&transacao=Venda"

        async with ZapScraperLinksAsync(headless=True) as scanner:
            links = await scanner.get_links(link)
            print(f"Total de links: {len(links)}")
            print(f"Primeiro link: {links}")"""
    
    
    asyncio.run(main())
    
    

    