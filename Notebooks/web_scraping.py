import re
from playwright.sync_api import Playwright, sync_playwright, expect
from playwright_stealth import Stealth

"""def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.zapimoveis.com.br/imovel/venda-cobertura-3-quartos-com-cozinha-paraiso-santo-andre-sp-134m2-id-2866886768/?source=ranking%2Crp")
    
    #print(page.title())
    #titulo_imovel = page.locator("h2.text-neutral-130.line-clamp-2").first.text_content()
    # Procura h1 ou h2 que tenha a classe neutral-130
    titulo_imovel = page.locator("h1.text-neutral-130, h2.text-neutral-130").first.text_content()
    
    print(titulo_imovel.strip())

    metragem = page.locator("p.font-secondary").get_by_text("m²").first.text_content()
    print(metragem)

    # Localiza o container de Banheiros e pega o valor numérico
    # Busca o parágrafo 'Banheiros', vai para o próximo elemento (div) e pega o <p> interno
    banheiros = page.locator("xpath=//p[text()='Banheiros']/following-sibling::div/p").text_content()
    
    print(banheiros.strip())
    
    # Procura o texto 'Vagas', desce para a div seguinte e pega o parágrafo
    vagas = page.locator("xpath=//p[text()='Vagas']/following-sibling::div/p").text_content()
    print(vagas.strip())
    
    # Procura o <p> com texto 'Quartos' e pega o <p> que é 'sobrinho' dele (dentro da mesma estrutura)
    quartos = page.locator("xpath=//p[text()='Quartos']/following-sibling::div/p").text_content()
    print(quartos.strip())
    
    valor_venda = page.locator(".value-item__value-highlight .value-item__value").text_content()
    print(valor_venda.strip())
    
    condominio_raw = page.get_by_test_id("condoFee").text_content()
    print(condominio_raw.strip())
    
    # Captura o texto completo: "Rua Nova Cruz, 236 - Parque Penha, São Paulo - SP"
    endereco_raw = page.get_by_test_id("location-address").text_content()
    print(endereco_raw.strip())
    
    link_google_maps = page.locator('iframe[data-testid="map-iframe"]').get_attribute("src")
    
    print(link_google_maps)
    
    # Localiza o container que contém o texto 'IPTU' e busca o valor dentro dele
    valor_iptu = page.locator("div.value-item", has_text="IPTU").locator("p.value-item__value").text_content()
    print(valor_iptu.strip())
    
    # Busca todos os textos dentro da lista de amenidades
    amenities = page.locator('ul[data-testid="amenities-list"] li span.amenities-item-text').all_text_contents()

    # Limpando espaços extras
    amenities_limpas = [item.strip() for item in amenities]
    print(amenities_limpas)

    # 3. Agora pega o conteúdo completo
    descricao = page.get_by_test_id("description-content").first.text_content()
    print(descricao)
    
    # Captura: "Anúncio criado em 21 de junho de 2025, atualizado há 12 horas."
    data_raw = page.get_by_test_id("listing-created-date").first.text_content()
    print(data_raw.strip())
    
    def extrair_links_imagens(page):
        links = []
        # Localiza todas as fontes de imagem dentro do carrossel
        sources = page.locator('ul[data-testid="carousel-photos"] source[type="image/webp"]')
        
        count = sources.count()
        for i in range(count):
            srcset = sources.nth(i).get_attribute("srcset")
            if srcset:
                # O srcset contém várias URLs separadas por vírgula. 
                # A última costuma ser a de maior resolução (1080w)
                lista_urls = srcset.split(",")
                url_alta_res = lista_urls[-1].strip().split(" ")[0]
                links.append(url_alta_res)
                
        return links
    
    

    # Uso
    fotos = extrair_links_imagens(page)
    print(f"Encontradas {len(fotos)} imagens.")
    #print(fotos) # Exibe o link da primeira foto

            
    context.close()
    browser.close()


with Stealth().use_sync(sync_playwright()) as playwright:
    run(playwright)
        """
        
import asyncio
import re
from playwright.async_api import async_playwright

import math
from playwright.async_api import async_playwright


import asyncio
import re
import math
from playwright.async_api import async_playwright

async def get_total_pages_by_count(url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Contexto com User-Agent para evitar bloqueios
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # O Zap exige um tempo para carregar os dados dinâmicos
            await page.goto(url, wait_until="networkidle", timeout=60000)

            # ESTRATÉGIA: Usar o atributo 'data-cy' que você postou no HTML
            # Este é o seletor mais forte disponível
            locator_total = page.locator('[data-cy="rp-searchTitle-txt"]')
            
            # Espera o elemento ficar visível
            await locator_total.wait_for(state="visible", timeout=15000)
            
            texto_total = await locator_total.inner_text()
            print(f"Texto capturado: {texto_total}") # Debug
            
            # Limpa o texto: remove pontos de milhar e pega apenas os números
            # "288 Imóveis para alugar..." -> 288
            numeros = re.findall(r'\d+', texto_total.replace('.', '').replace(',', ''))
            
            print(f"Total de imóveis: {numeros[0]}")
            
            if numeros:
                total_imoveis = int(numeros[0])
                
                # Cálculo de páginas (Zap costuma usar 24 anúncios por página)
                imoveis_por_pagina = 30 
                total_paginas = math.ceil(total_imoveis / imoveis_por_pagina)
                
                print(f"Total de imóveis: {total_imoveis} -> Páginas: {total_paginas}")
                return min(total_paginas, 100)
            
            return 50

        except Exception as e:
            print(f"Erro na captura: {e}")
            return 1
        finally:
            await browser.close()

if __name__ == "__main__":
    # Teste com a URL de Joinville
    url = "https://www.zapimoveis.com.br/aluguel/imoveis/sc+joinville/?onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&areaMaxima=100&areaMinima=10"
    total = asyncio.run(get_total_pages_by_count(url))
    print(f"Resultado Final: {total}")