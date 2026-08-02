import asyncio
import logging
import random
import re
import time
from playwright.async_api import async_playwright, BrowserContext
try:
    from playwright_stealth import Stealth
    _STEALTH_OK = True
except Exception:
    _STEALTH_OK = False
from typing import Optional, List


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class OLXScraperLinksAsync:
    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._pw_cm = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        # O navegador só é iniciado sob demanda (_ensure_browser) no fallback Playwright.
        self._playwright = None
        self._browser = None
        self._pw_cm = None
        self._context: Optional[BrowserContext] = None
        return self

    async def _ensure_browser(self):
        """Inicia o navegador Playwright apenas quando necessário (fallback)."""
        if self._browser is not None:
            return
        try:
            # O Stealth ajuda a evitar a detecção de bot da OLX
            pw = async_playwright()
            if _STEALTH_OK:
                self._pw_cm = Stealth().use_async(pw)
            else:
                self._pw_cm = pw
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                )
            )
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    # ---------------------------------------------------------------
    # Método público: tenta curl_cffi primeiro, cai para Playwright.
    # ---------------------------------------------------------------
    async def get_links(self, url: str, retries=3) -> List[str]:
        """Extrai links de anúncios da OLX (modo primário: curl_cffi)."""
        links = await self._get_links_curl(url, retries=retries)
        if links:
            logger.info("Links obtidos via curl_cffi para %s: %d", url, len(links))
            return links

        logger.warning("curl_cffi falhou para %s. Caindo para Playwright.", url)
        return await self._get_links_playwright(url, retries=retries)

    # -- Modo primário: curl_cffi -----------------------------------
    async def _get_links_curl(self, url: str, retries: int = 3) -> List[str]:
        return await asyncio.to_thread(self._get_links_curl_sync, url, retries)

    def _get_links_curl_sync(self, url: str, retries: int = 3) -> List[str]:
        """Executa a listagem síncrona via curl_cffi (num thread)."""
        try:
            from curl_cffi import requests as cr
        except ImportError:
            logger.error("curl_cffi não está instalado. Usando fallback.")
            return []

        for tentativa in range(1, retries + 1):
            try:
                resp = cr.get(url, impersonate="chrome", timeout=30000)
                if resp.status_code != 200:
                    logger.warning("curl_cffi retornou status %s (tentativa %s)", resp.status_code, tentativa)
                    continue

                html = resp.text

                # Extrai os links dos cards de anúncio (data-testid="adcard-link")
                links = re.findall(
                    r'<a[^>]*data-testid="adcard-link"[^>]*href="([^"]+)"',
                    html,
                )

                # Filtra apenas links de anúncios (remove links de publicidade externa se houver)
                # Geralmente links da OLX contêm o padrão de ID numérico no final
                links_validos = list(set([l for l in links if "olx.com.br" in l and "-" in l]))

                if links_validos:
                    logger.info("Links encontrados (curl_cffi) para a URL %s", url)
                    return list(set(links_validos))

                logger.warning(f"curl_cffi tentativa {tentativa}: Nenhum link encontrado na {url}")

            except Exception as e:
                logger.error(f"curl_cffi tentativa {tentativa} falhou para {url}: {e}")

            # Pequena espera antes de tentar de novo
            time.sleep(random.uniform(1.5, 4.0))

        return []

    # -- Fallback: Playwright (implementação original) ----------------
    async def _get_links_playwright(self, url: str, retries=3) -> List[str]:
        """Extrai links de anúncios da OLX usando seletores data-testid."""
        await self._ensure_browser()

        for i in range(retries):
            page = await self._context.new_page()

            try:
                logger.info(f"Acessando listagem OLX: {url}")
                # OLX pode ser pesada, wait_until="domcontentloaded" é uma boa escolha
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                # 1. Espera o seletor específico dos links de anúncios da OLX
                # O data-testid="adcard-link" é o mais estável na estrutura atual
                seletor_link = 'a[data-testid="adcard-link"]'
                await page.wait_for_selector(seletor_link, timeout=10000)

                # 2. Scroll suave para garantir que o lazy loading carregue os cards debaixo
                await page.evaluate("window.scrollBy(0, 800)")
                await asyncio.sleep(0.4)

                # 3. Extração dos links via evaluate_all para performance
                links = await page.locator(seletor_link).evaluate_all(
                    "elements => elements.map(el => el.href)"
                )

                # Filtra apenas links de anúncios (remove links de publicidade externa se houver)
                # Geralmente links da OLX contêm o padrão de ID numérico no final
                links_validos = list(set([l for l in links if "olx.com.br" in l and "-" in l]))

                if links_validos:
                    logger.info("Links encontrados para a URL %s", url)
                    return list(set(links_validos))

                logger.warning(f"Tentativa {i+1}: Nenhum link encontrado na {url}")

            except Exception as e:
                logger.error(f"Tentativa {i+1} falhou para {url}: {e}")
            finally:
                await page.close()

                # Se falhou, espera um tempo maior antes de tentar de novo
            await asyncio.sleep(random.uniform(1.5, 4.0))

        return []

if __name__ == "__main__":
    async def main():
        import time
        # Exemplo focado em Joinville (ajuste conforme sua busca)
        url_olx = "https://www.olx.com.br/imoveis/venda/estado-sc/norte-de-santa-catarina/joinville?q=casa&o=100"
        
        start = time.time()
        
        async with OLXScraperLinksAsync(headless=True) as scanner:
            links = await scanner.get_links(url_olx)
            
            print(f"Links encontrados: {len(links)}")
            print(f"Primeiro link: {links}")
        end = time.time()
        print(f"Tempo total: {end - start:.2f} segundos")
    asyncio.run(main())