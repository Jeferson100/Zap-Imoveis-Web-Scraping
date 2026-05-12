import asyncio
import re
import math
import logging
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TotalPageChavesNaMao:
    def __init__(self, headless=True):
        self.headless = headless
        self.user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )

    async def get_total_pages(self, url: str, imoveis_por_pagina: int = 15) -> int:
        """
        Acessa o Chaves na Mão, captura o total de imóveis no h1 e calcula as páginas.
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            context = await browser.new_context(user_agent=self.user_agent)
            page = await context.new_page()
    
            
            try:
                logger.info(f"Acessando Chaves na Mão: {url[:50]}...")
                
                # Chaves na Mão costuma ser rápido, mas 'networkidle' garante os cards
                await page.goto(url, wait_until="networkidle", timeout=60000)

                # Seletor baseado na classe que você enviou (pegando o strong dentro do h1)
                # O seletor 'h1.styles_text-display__QLmNz strong' foca exatamente no '222'
                locator_total = page.locator('h1[class*="styles_text-display"] strong')
                
                await locator_total.wait_for(state="visible", timeout=20000)
                texto_total = await locator_total.inner_text()
                
                # Limpeza de caracteres não numéricos (pontos de milhar, etc)
                texto_limpo = texto_total.replace('.', '').replace(',', '')
                numeros = re.findall(r'\d+', texto_limpo)
                
                if numeros:
                    total_imoveis = int(numeros[0])
                    
                    # O Chaves na Mão geralmente exibe entre 24 e 36 imóveis. 
                    # Verifique quantos aparecem na sua busca e ajuste o parâmetro.
                    total_paginas = math.ceil(total_imoveis / imoveis_por_pagina)
                    
                    logger.info(f"Detectado: {total_imoveis} imóveis -> {total_paginas} páginas.")
                    
                    # Limite de segurança (portais costumam travar após 100 páginas)
                    return min(total_paginas, 100)
                
                return 100

            except Exception as e:
                logger.error(f"Erro no Chaves na Mão: {e}")
                return 100
            finally:
                await browser.close()

# --- EXEMPLO DE USO ---
if __name__ == "__main__":
    # Exemplo de URL de Joinville no Chaves na Mão
    URL_CHAVES = "https://www.chavesnamao.com.br/imoveis/sc-joinville/?filtro=amin:10,amax:40"
    
    scraper = TotalPageChavesNaMao(headless=True)
    total = asyncio.run(scraper.get_total_pages(URL_CHAVES))
    
    print(f"\n>>> Total de páginas Chaves na Mão: {total}")