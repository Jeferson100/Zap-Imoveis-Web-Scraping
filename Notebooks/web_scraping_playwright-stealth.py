from playwright.sync_api import Playwright, sync_playwright
from playwright_stealth import Stealth
import json
from playwright_stealth import Stealth

class ZapScraperPlaywright:
    def __init__(self, page, url):
        self.page = page
        self.url = url

    def safe_get_text(self, selector, is_testid=False, multiple=False):
        """Auxiliar para evitar erros se o elemento não existir na página."""
        try:
            locator = self.page.get_by_test_id(selector) if is_testid else self.page.locator(selector)
            if multiple:
                return [item.strip() for item in locator.all_text_contents()]
            
            # Se houver mais de um (strict mode), pegamos o primeiro
            return locator.first.text_content(timeout=3000).strip()
        except:
            return None

    def extrair_dados(self):
        dados = {}
        
        dados['url'] = self.url
        dados['titulo'] = self.page.locator("h2.text-neutral-130.line-clamp-2").first.text_content()
        dados['valor_venda'] = self.safe_get_text(".value-item__value-highlight .value-item__value")
        dados['condominio'] = self.safe_get_text("condoFee", is_testid=True)
        dados['iptu'] = self.page.locator("div.value-item", has_text="IPTU").locator("p.value-item__value").text_content()
        
        # Se o seletor acima do IPTU falhar pelo texto, tentamos o data-testid
        if not dados['iptu']:
             dados['iptu'] = self.safe_get_text("iptu", is_testid=True)

        # Características (Usando os XPaths que você validou)
        dados['metragem'] = self.safe_get_text("p.font-secondary:has-text('m²')")
        dados['banheiros'] = self.safe_get_text("xpath=//p[text()='Banheiros']/following-sibling::div/p")
        dados['vagas'] = self.safe_get_text("xpath=//p[text()='Vagas']/following-sibling::div/p")
        dados['quartos'] = self.safe_get_text("xpath=//p[text()='Quartos']/following-sibling::div/p")
        
        # Localização e Descrição
        dados['endereco'] = self.safe_get_text("location-address", is_testid=True)
        dados['link_maps'] = self.page.locator('iframe[data-testid="map-iframe"]').get_attribute("src")
        dados['descricao'] = self.safe_get_text("description-content", is_testid=True)
        dados['data_criacao'] = self.safe_get_text("listing-created-date", is_testid=True)
        
        # Amenidades (Lista)
        dados['caracteristicas'] = self.safe_get_text('ul[data-testid="amenities-list"] li span.amenities-item-text', multiple=True)

        # Fotos (Lógica refinada)
        dados['fotos'] = self.extrair_links_imagens()
        
        return dados

    def extrair_links_imagens(self):
        links = []
        try:
            sources = self.page.locator('ul[data-testid="carousel-photos"] source[type="image/webp"]')
            for i in range(sources.count()):
                srcset = sources.nth(i).get_attribute("srcset")
                if srcset:
                    # Pega a última URL do srcset (maior resolução)
                    url = srcset.split(",")[-1].strip().split(" ")[0]
                    links.append(url)
        except:
            pass
        return links

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    page = context.new_page()
    
    url = "https://www.zapimoveis.com.br/imovel/venda-sobrados-3-quartos-com-cozinha-parque-penha-zona-leste-sao-paulo-sp-115m2-id-2815677438/?source=ranking%2Crp"
        
    page.goto(url, wait_until="domcontentloaded")
        
    scraper = ZapScraper(page, url)
        
    resultado = scraper.extrair_dados()
        
    # Exibe de forma organizada (JSON)
    print(json.dumps(resultado, indent=4, ensure_ascii=False))
        
    context.close()
    browser.close()
    return resultado

with Stealth().use_sync(sync_playwright()) as playwright:
    # Usando stealth para evitar bloqueios
    # Nota: Stealth é aplicado à page
    resultado = run(playwright)
    with open("resultado.json", "w", encoding="utf-8") as f:
        json.dump(resultado, f, indent=4, ensure_ascii=False)