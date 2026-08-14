import re
from playwright.sync_api import Playwright, sync_playwright, expect
from playwright_stealth import Stealth

#https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg=90

from playwright.sync_api import Playwright, sync_playwright
import re

from playwright.sync_api import Playwright, sync_playwright

"""def run(playwright: Playwright) -> None:
    # Lançando o navegador
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    page = context.new_page()
    
    page.goto("https://www.chavesnamao.com.br/imovel/apartamento-a-venda-3-quartos-com-garagem-sp-sao-paulo-brooklin-RS3090000/id-40215019/")

    try:
        titulo = page.locator('h1.styles_typography__xG9rg').inner_text()
        print(f"Titulo: {titulo}")
        
        elemento = page.locator('b.row.spacing:has-text("m²")')
        
        # Localiza o elemento pela classe específica do span
        valor_raw = page.locator('span.style_clamp__m7txb').inner_text()
        
        valor_limpo = valor_raw.replace('R$', '').replace('.', '').strip()
        
        print(f"Valor numérico: {valor_limpo}")
        
        elemento = page.locator('b.row.spacing:has-text("m²")')
        
        texto_metragem = elemento.last.inner_text()
        
        print(f"Metragem capturada: {texto_metragem}")
        
        quartos = page.locator("b:has(svg path[d^='M112.867 767.316'])").first.inner_text(timeout=5000)
        print(f"Quartos: {quartos.strip()}")
        
        banheiros_raw = page.locator('p[aria-label="Banheiros"] b').inner_text()
    
        qtd_banheiros = "".join(filter(str.isdigit, banheiros_raw))
    
        print(f"Quantidade de banheiros: {qtd_banheiros}")
        

        garagem = page.locator("p[aria-label='Garagens'] b").first.inner_text(timeout=5000)
        
        print(f"Garagem: {garagem.strip()}")  # '1'
        

        descricao_elemento = page.locator('p[aria-label="descrição"]')
        
        # Extrai o texto (o Playwright já lida com os <br> transformando em quebras de linha)
        texto_descricao = descricao_elemento.inner_text().strip()
        
        print("--- Descrição do Imóvel ---")
        print(texto_descricao)
        
        # 1. Captura a data técnica (formato ISO: 2026-02-14 07:31:42)
        # É melhor para organizar por ordem cronológica depois
        data_iso = page.locator('time').get_attribute('datetime')
        
        # 2. Captura a data formatada para exibição (14/02/2026 às 07:31h)
        data_texto = page.locator('time').inner_text()
        
        # 3. Captura a Referência (Ref)
        # Buscamos o parágrafo pai e limpamos o texto para pegar o que vem após "Ref:"
        texto_completo = page.locator('p:has(time)').inner_text()
        referencia = texto_completo.split('Ref:')[1].strip() if 'Ref:' in texto_completo else "N/A"

        print(f"Atualizado em (ISO): {data_iso}")
        print(f"Referência do Imóvel: {referencia}")
        
        #seletor_endereco = 'b:has-text("Joinville"), b:has-text("SC")'
        
        #seletor_endereco = 'h2[class*="styles_text-title-lg"]:has-text("SP"), h2[class*="styles_text-title-lg"]:has-text("SC")'
        seletor_endereco = 'h2[class*="styles_text-title-lg"].column, h2[class*="styles_text-title-lg"] b'
    
        # O .inner_text() vai limpar os comentários e retornar:
        # "Rua Joaquim Girardi, 611, Vila Nova, Joinville/SC"
        endereco_completo = page.locator(seletor_endereco).first.inner_text().strip()
        
        print(f"Endereço: {endereco_completo}")
        
        condo_elemento = page.locator('p:has-text("Condomínio") + p')
        valor_condo = condo_elemento.inner_text().strip()

        # Captura o IPTU procurando o parágrafo que contém o texto "IPTU"
        # e pegando o próximo elemento irmão
        iptu_elemento = page.locator('p:has-text("IPTU") + p')
        valor_iptu = iptu_elemento.inner_text().strip()

        # Tratamento para casos de "R$ -" ou "R$ --" (converter para 0 ou N/A)
        def limpar_valor(valor):
            if "-" in valor or "—" in valor:
                return "0"
            return "".join(filter(str.isdigit, valor))

        print(f"Condomínio: {valor_condo} (Limpo: {limpar_valor(valor_condo)})")
        print(f"IPTU: {valor_iptu} (Limpo: {limpar_valor(valor_iptu)})")
        
        # 1. Localiza o botão pelo ID e clica nele
        # O seletor '#' busca por ID no CSS
        botao_fotos = page.locator('#tablink-media')
        
        print("Clicando no botão de fotos...")
        botao_fotos.click()

        # 2. Agora que clicamos, esperamos a galeria aparecer
        # Usamos o seletor da galeria que você mandou antes
        page.wait_for_selector('ul.galleryContainer', timeout=10000)
        
        # 3. Agora sim, pegamos os links das imagens
        fotos = page.locator('ul.galleryContainer img').evaluate_all(
            "imgs => imgs.map(img => img.src || img.dataset.src)"
        )

        print(f"Sucesso! {len(fotos)} fotos carregadas após o clique.")
        print(f"Primeira foto: {fotos[0]}")
        
        page.locator('#tablink-map').click()

        # 2. Espera o iframe do Google Maps carregar
        # Usamos o seletor 'iframe' e verificamos se ele contém 'maps' no src
        page.wait_for_selector('iframe[src*="maps"]', timeout=15000)

        # 3. Captura o link (SRC) do iframe
        link_mapa = page.locator('iframe[src*="maps"]').get_attribute('src')
        
        print(f"Link do mapa capturado: {link_mapa}")
              
    except Exception as e:
        print(f"Erro ao localizar metragem: {e}")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)"""
    
import asyncio
import sys
from pathlib import Path
    
sys.path.append(str(Path(__file__).parent.parent))

from scraping_zap_imoveis import ChavesMaoColeta

output_file = "chaves_mao_alugueis.parquet"
    
#URL_TEMPLATE_NEW = "https://www.chavesnamao.com.br/imoveis-para-alugar/sc-joinville/?pg=1"

URL_TEMPLATE_NEW = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg=1"
    
orchestrator = ChavesMaoColeta(URL_TEMPLATE_NEW, 
                                headless=True,
                                max_concurrency=3)

resultado = asyncio.run(orchestrator.run(
        output_file=str(output_file),
        total_pages=1
    ))
    
