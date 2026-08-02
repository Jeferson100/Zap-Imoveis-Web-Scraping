import asyncio
import re
import logging
from playwright.async_api import async_playwright


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class TotalPageOLX:
    MAX_RETRIES = 3

    def __init__(self, user_agent: str = None):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    # ---------------------------------------------------------------
    # Método público: tenta curl_cffi primeiro, cai para Playwright.
    # ---------------------------------------------------------------
    async def get_total_pages(self, url: str) -> int:
        """Retorna o número total de páginas para uma dada URL da OLX."""
        total = await self._get_total_pages_curl(url)
        if total is not None:
            logger.info("Total de páginas obtido via curl_cffi: %s", total)
            return total

        logger.warning("curl_cffi falhou para %s. Caindo para Playwright.", url)
        return await self._get_total_pages_playwright(url)

    # -- Modo primário: curl_cffi -----------------------------------
    async def _get_total_pages_curl(self, url: str):
        return await asyncio.to_thread(self._get_total_pages_curl_sync, url)

    def _get_total_pages_curl_sync(self, url: str):
        """Executa a leitura síncrona via curl_cffi (num thread)."""
        try:
            from curl_cffi import requests as cr
        except ImportError:
            logger.error("curl_cffi não está instalado. Usando fallback.")
            return None

        for tentativa in range(1, self.MAX_RETRIES + 1):
            try:
                resp = cr.get(url, impersonate="chrome", timeout=60000)
                if resp.status_code != 200:
                    logger.warning("curl_cffi retornou status %s (tentativa %s)", resp.status_code, tentativa)
                    continue

                html = resp.text

                # Estratégia 1: link "Última página"
                m = re.search(r'href="([^"]*[?&]o=\d+[^"]*)"[^>]*>[^<]*Última', html) \
                    or re.search(r'Última[^<]*<a[^>]*href="([^"]*[?&]o=\d+[^"]*)"', html) \
                    or re.search(r'href="([^"]*[?&]amp;o=\d+[^"]*)"[^>]*>[^<]*Última', html) \
                    or re.search(r'Última[^<]*<a[^>]*href="([^"]*[?&]amp;o=\d+[^"]*)"', html)
                if m:
                    match = re.search(r'[?&]o=(\d+)', m.group(1)) or re.search(r'[?&]amp;o=(\d+)', m.group(1))
                    if match:
                        return int(match.group(1))

                # Estratégia 2: maior número entre links de paginação
                # Considera tanto "o=" quanto "o=" com escape HTML (&amp;)
                o_vals = [int(n) for n in re.findall(r'[?&]o=(\d+)|[?&]amp;o=(\d+)', html)
                          for n in n if n]
                if o_vals:
                    return max(o_vals)

                return 1

            except Exception as e:
                logger.warning("curl_cffi erro na tentativa %s: %s", tentativa, e)
            return None

    # -- Fallback: Playwright (implementação original) ----------------
    async def _get_total_pages_playwright(self, url: str) -> int:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()

            try:
                # Aumentamos o timeout de carregamento para 60s devido à lentidão da OLX
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Estratégia 1: Procurar pelo botão "Última página"
                # Usamos um tempo curto (5s) para não travar o script
                last_page_button = page.get_by_role("link", name="Última página")

                try:
                    href = await last_page_button.get_attribute("href", timeout=5000)
                    if href:
                        match = re.search(r'[?&]o=(\d+)', href)
                        if match:
                            total = int(match.group(1))
                            return total
                except Exception:
                    # Se não achou o botão "Última página", tentamos a Estratégia 2
                    pass

                # Estratégia 2: Pegar o maior número da lista de paginação comum
                # Isso resolve casos onde a busca tem poucas páginas (ex: 3 ou 4)
                pagination_items = await page.locator('a[data-lurker-detail="pagination_page"]').all_text_contents()

                if not pagination_items:
                    # Seletor alternativo caso a OLX mude as classes
                    pagination_items = await page.locator('ul.olx-pagination a').all_text_contents()

                if pagination_items:
                    numeros = [int(n) for n in pagination_items if n.isdigit()]
                    if numeros:
                        return max(numeros)

                return 1

            except Exception as e:
                print(f"Erro ao obter total de páginas: {e}")
                return 50
            finally:
                await browser.close()

# --- Exemplo de uso no seu Notebook ou Script ---
if __name__ == "__main__":
    async def main():
        url_teste = "https://www.olx.com.br/imoveis/venda/estado-sp/sao-paulo-e-regiao/zona-oeste/pinheiros?se=40"
        
        scraper_paginas = TotalPageOLX()
        total = await scraper_paginas.get_total_pages(url_teste)
        
        print(f"Resultado final: {total} páginas.")

    asyncio.run(main())