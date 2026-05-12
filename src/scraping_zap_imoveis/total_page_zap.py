from playwright.async_api import async_playwright
from playwright_stealth import Stealth
import logging
import warnings
import asyncio
import re
import math

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)

class TotalPageZap:
    def __init__(self, headless=True):
        self.headless = headless
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    async def get_total_pages(self, url: str, imoveis_por_pagina: int = 30) -> int:
        """
        Acessa a URL do Zap, captura o total de imóveis e calcula o número de páginas.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()
    
            try:
                logger.info(f"Acessando Zap para calcular páginas: {url[:50]}...")
                
                # 'networkidle' é essencial aqui para esperar o contador renderizar
                await page.goto(url, wait_until="networkidle", timeout=60000)

                # Seletor baseado no data-cy (mais estável no Zap)
                locator_total = page.locator('[data-cy="rp-searchTitle-txt"]')
                
                # Espera o texto aparecer
                await locator_total.wait_for(state="visible", timeout=20000)
                
                texto_total = await locator_total.inner_text()
                
                # Limpeza: remove pontos e vírgulas para não quebrar o Regex
                # Ex: "1.288 Imóveis..." -> "1288 Imóveis..."
                texto_limpo = texto_total.replace('.', '').replace(',', '')
                numeros = re.findall(r'\d+', texto_limpo)
                
                if numeros:
                    total_imoveis = int(numeros[0])
                    
                    # O Zap costuma carregar 24 por padrão, mas pode variar
                    total_paginas = math.ceil(total_imoveis / imoveis_por_pagina)
                    
                    logger.info(f"Detectado: {total_imoveis} imóveis -> {total_paginas} páginas.")
                    
                    # O Zap tem um hard limit de 100 páginas na interface web
                    return min(total_paginas, 100)
                
                logger.warning("Nenhum número encontrado no título. Retornando padrão 1.")
                return 1

            except Exception as e:
                logger.error(f"Erro ao capturar total de páginas: {e}")
                return 1 # Retorno seguro para não quebrar o loop principal
            finally:
                await browser.close()

# --- EXEMPLO DE USO ---
if __name__ == "__main__":
    # Sua URL de Joinville com filtros de área
    URL_TESTE = "https://www.zapimoveis.com.br/aluguel/imoveis/sc+joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&areaMaxima=100&areaMinima=10"
    
    scraper_total = TotalPageZap(headless=True)
    total = asyncio.run(scraper_total.get_total_pages(URL_TESTE))
    
    print(f"\n>>> Total de páginas para processar: {total}")