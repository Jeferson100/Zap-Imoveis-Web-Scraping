from playwright.sync_api import Playwright, sync_playwright, expect
from playwright_stealth import Stealth

with Stealth().use_sync(sync_playwright()) as playwright:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.zapimoveis.com.br/venda/?pagina=2&transacao=Venda")
    links = page.locator('.listings-wrapper a.olx-core-surface').evaluate_all(
        "nodes => nodes.map(n => n.href)"
    )

    print(links)
    context.close()
    browser.close()
    
    
def run(playwright: Playwright) -> None:
    with Stealth().use_sync(sync_playwright()) as playwright:
        
        browser = playwright.chromium.launch(headless=True)
        
        context = browser.new_context()
        
        page = context.new_page()
        
        page.goto("https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda")
        
        page.keyboard.press("End")

        ultimo_botao = page.locator('.olx-core-pagination__button').last

        ultimo_botao.wait_for(state="attached", timeout=15000)
        
        texto = ultimo_botao.inner_text()
        
        total_paginas = int(texto.replace('.', '').strip())
        
        context.close()
        
        browser.close()
        
        return total_paginas
