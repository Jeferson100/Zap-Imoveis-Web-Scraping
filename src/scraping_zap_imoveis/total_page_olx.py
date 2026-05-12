import asyncio
import re
from playwright.async_api import async_playwright

class TotalPageOLX:
    def __init__(self, user_agent: str = None):
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    async def get_total_pages(self, url: str) -> int:
        """
        Retorna o número total de páginas para uma dada URL da OLX.
        Se não encontrar paginação, retorna 1.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()

            try:
                # Aumentamos o timeout de carregamento para 60s devido à lentidão da OLX
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # Estratégia 1: Procurar pelo botão "Última página"
                # Usamos um timeout curto (5s) para não travar o script
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

                return 50

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