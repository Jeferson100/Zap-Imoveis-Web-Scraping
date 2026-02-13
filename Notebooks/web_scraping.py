import re
from playwright.sync_api import Playwright, sync_playwright, expect
from playwright_stealth import Stealth

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.zapimoveis.com.br/imovel/venda-cobertura-3-quartos-com-cozinha-paraiso-santo-andre-sp-134m2-id-2866886768/?source=ranking%2Crp")
    
    #print(page.title())
    titulo_imovel = page.locator("h2.text-neutral-130.line-clamp-2").first.text_content()
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