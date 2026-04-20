import re
from playwright.sync_api import Playwright, sync_playwright, expect
from playwright_stealth import Stealth

#https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg=90

from playwright.sync_api import Playwright, sync_playwright
import re

from playwright.sync_api import Playwright, sync_playwright

def run(playwright: Playwright) -> None:
    # Lançando o navegador
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    page = context.new_page()
    page.goto(
        #"https://sc.olx.com.br/norte-de-santa-catarina/imoveis/casa-com-2-dormitorios-sendo-2-suites-e-2-vagas-de-garagem-em-joinville-sc-1481632088?lis=listing_1001", 
        #"https://sp.olx.com.br/sao-paulo-e-regiao/imoveis/sao-paulo-padrao-consolacao-1327005839",
        #'https://sc.olx.com.br/norte-de-santa-catarina/imoveis/casa-joinville-aventureiro-1488985390',
        #"https://sp.olx.com.br/sao-paulo-e-regiao/imoveis/sao-paulo-padrao-bela-vista-1483710570",
        "https://sp.olx.com.br/sao-paulo-e-regiao/imoveis/sao-paulo-padrao-bela-vista-994788219",
              wait_until="domcontentloaded", 
              timeout=60000)
    
    seletor_preco = 'span.typo-title-large'
    # Espera o preço aparecer na tela
    page.wait_for_selector(seletor_preco, timeout=10000)
    
    
    def _get_preco_olx(page):
        # Lista de seletores da OLX por ordem de prioridade
        seletores_olx = [
            'h2[data-testid="ad-price"]',    # O seletor mais oficial e estável da OLX
            'span[class*="ad-price"]',       # Busca qualquer span que contenha "ad-price" na classe
            'h2.ad-price',                    # Classe genérica comum
            '.sc-1u0770-0.jovYOs'            # Seletor de classe atual (caso os outros falhem)
        ]

        for seletor in seletores_olx:
            try:
                # Espera curta para não travar o scraper se o anúncio não tiver preço
                element = page.wait_for_selector(seletor, timeout=4000, state="attached")
                if element:
                    texto = element.inner_text()
                    # Limpeza: "R$ 156.137" -> 156137
                    preco_limpo = texto.replace("R$", "").replace(".", "").replace(" ", "").strip()
                    
                    if preco_limpo.isdigit():
                        return int(preco_limpo)
                    return texto # Caso seja "Troca" ou algo assim
            except:
                continue
                
        return None
    
    preco_olx = _get_preco_olx(page)
    print(f"Preço OLX: {preco_olx}")
        
    # Captura o texto bruto (ex: "R$ 430.000")
    preco_raw = page.locator(seletor_preco).first.inner_text()
    
    print(f"Valor do imóvel no Vila Nova: R$ {preco_raw}")
    
    seletor_desc = 'span.typo-body-medium[style*="word-break: break-word"]'
    
    
        # 1. Espera o elemento estar visível (timeout curto de 5s para não travar o loop)
    locator = page.locator(seletor_desc).first
    locator.wait_for(state="visible", timeout=5000)
        
        # 2. Captura o texto mantendo as quebras de linha (white-space: break-spaces)
    descricao_raw = locator.inner_text()
    
    #print(f"Descrição: {descricao_raw.strip()}")
    
    
    # Seletor focado no span com a cor neutra de destaque e fonte semibold
    seletor_data = 'span.typo-caption.text-neutral-100.font-semibold'
    

    # Espera o elemento carregar (timeout de 5s para ser ágil)
    locator = page.locator(seletor_data).first
    
    locator.wait_for(state="visible", timeout=5000)
        
    data_raw = locator.inner_text()
    
    print(f"Data: {data_raw.strip()}")
    # Output: Data: 2023-05-01
    
    container_quartos = page.locator('div:has(> span:has-text("Quartos"))')
    valor_locator = container_quartos.locator('span, a').last
    valor_locator.wait_for(state="attached", timeout=5000)
    
    texto_raw = valor_locator.inner_text()
    
    print(f"Quantidade de quartos: {texto_raw.strip()}")
    # Output: Quantidade de quartos: 2
    
    seletor = 'span:has-text("Área útil"), span:has-text("Área construída"), span:has-text("Tamanho")'    
    locator = page.locator(f'{seletor}').locator('xpath=../span[2]')
    locator.wait_for(state="attached", timeout=5000)
    metragem = locator.inner_text()
    print(f"Metragem: {metragem.strip()}")
    
    
    ## Busca o span com texto "Banheiros" e pega o próximo span com o número
    banheiros = page.locator("span:has-text('Banheiros') + span").inner_text()
    print(f"Quantidade de banheiros: {banheiros.strip()}")
    # Output: Quantidade de banheiros: 1

    
    
    garagens = page.locator("span:has-text('Vagas na garagem') + span").inner_text()
    print(f"Vagas na garagem: {garagens.strip()}")
    # Output: Vagas na garagem: 1
    
    # Classe do div pai do valor do condomínio
    condominio = page.locator(".cBvagp span:last-child").first.inner_text(timeout=3000)
    print(condominio)
    
    
    iptu = page.locator("span:text-is('IPTU') + div span:last-child").inner_text(timeout=3000)
    print(f"IPTU: {iptu.strip()}")
    
    """bairro = page.locator(".DCCug span.font-semibold").first.inner_text(timeout=3000)
    
    cidade = page.locator(".DCCug span.text-neutral-110").inner_text(timeout=3000)

    print(f"Bairro: {bairro.strip()}")   # Nova Brasília
    print(f"Cidade: {cidade.strip()}")   # Joinville, SC, 89214505"""

        
        
    
    # Fechando o navegador
    context.close()
    browser.close()
    


with sync_playwright() as playwright:
    run(playwright)