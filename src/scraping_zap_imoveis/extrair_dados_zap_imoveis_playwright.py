
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List
from playwright.sync_api import Page, sync_playwright, BrowserContext
from playwright_stealth import Stealth
import warnings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")


@dataclass
class DadosImovel:
    """Estrutura de dados de um imóvel."""
    url: str
    titulo: Optional[str] = None
    metragem: Optional[str] = None
    banheiros: Optional[str] = None
    vagas: Optional[str] = None
    quartos: Optional[str] = None
    valor_venda: Optional[str] = None
    condominio: Optional[str] = None
    endereco: Optional[str] = None
    iptu: Optional[str] = None
    descricao: Optional[str] = None
    data_criacao: Optional[str] = None
    caracteristicas: List[str] = field(default_factory=list)
    fotos: List[str] = field(default_factory=list)
    link_maps: Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__


class ZapScraperDadosImovel:
    """Extrator de dados detalhados de anúncios no Zap Imóveis."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2 

    def __init__(self, url: str, headless: bool = True):
        self.url = url
        self.headless = headless


    def __enter__(self):
        self._playwright = Stealth().use_sync(sync_playwright()).__enter__()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context: BrowserContext = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()

    def _safe_get_text(
        self,
        page: Page,
        selector: str,
        is_testid: bool = False,
        multiple: bool = False,
        timeout: int = 3000,
    ) -> Optional[str] | List[str]:
        try:
            locator = (
                page.get_by_test_id(selector) if is_testid else page.locator(selector)
            )

            if multiple:
                return [t.strip() for t in locator.all_text_contents() if t.strip()]

            text = locator.first.text_content(timeout=timeout)
            return text.strip() if text else None

        except Exception as e:
            logger.debug("Elemento não encontrado [%s]: %s", selector, e)
            return [] if multiple else None

    def _extrair_iptu(self, page: Page) -> Optional[str]:
        try:
            valor = (
                page.locator("div.value-item", has_text="IPTU")
                .locator("p.value-item__value")
                .text_content(timeout=3000)
            )
            return valor.strip() if valor else None
        except Exception:
            return self._safe_get_text(page, "iptu", is_testid=True)

    def _extrair_links_imagens(self, page: Page) -> List[str]:
        links = []
        try:
            sources = page.locator(
                'ul[data-testid="carousel-photos"] source[type="image/webp"]'
            )
            for i in range(sources.count()):
                srcset = sources.nth(i).get_attribute("srcset")
                if srcset:
                    url_alta_res = srcset.split(",")[-1].strip().split(" ")[0]
                    links.append(url_alta_res)

            logger.info("Encontradas %d imagens", len(links))
        except Exception as e:
            logger.error("Erro ao extrair imagens: %s", e)

        return links

    def _extrair_link_maps(self, page: Page) -> Optional[str]:
        try:
            return page.locator('iframe[data-testid="map-iframe"]').get_attribute("src")
        except Exception as e:
            logger.debug("Erro ao extrair link maps: %s", e)
            return None

    def _extrair_dados_da_pagina(self, page: Page) -> DadosImovel:
        """Extrai todos os dados de uma página já carregada."""
        return DadosImovel(
            url=self.url,
            titulo=self._safe_get_text(page, "h2.text-neutral-130.line-clamp-2"),
            metragem=self._safe_get_text(page, "p.font-secondary:has-text('m²')"),
            banheiros=self._safe_get_text(
                page, "xpath=//p[text()='Banheiros']/following-sibling::div/p"
            ),
            vagas=self._safe_get_text(
                page, "xpath=//p[text()='Vagas']/following-sibling::div/p"
            ),
            quartos=self._safe_get_text(
                page, "xpath=//p[text()='Quartos']/following-sibling::div/p"
            ),
            valor_venda=self._safe_get_text(
                page, ".value-item__value-highlight .value-item__value"
            ),
            condominio=self._safe_get_text(page, "condoFee", is_testid=True),
            endereco=self._safe_get_text(page, "location-address", is_testid=True),
            iptu=self._extrair_iptu(page),
            descricao=self._safe_get_text(page, "description-content", is_testid=True),
            data_criacao=self._safe_get_text(
                page, "listing-created-date", is_testid=True
            ),
            caracteristicas=self._safe_get_text(
                page,
                'ul[data-testid="amenities-list"] li span.amenities-item-text',
                multiple=True,
            ),
            fotos=self._extrair_links_imagens(page),
            link_maps=self._extrair_link_maps(page),
        )

    def extrair(self) -> DadosImovel:
        """
        Acessa a URL e extrai os dados com tentativas automáticas em caso de falha.

        Returns:
            DadosImovel com os dados extraídos ou campo `erro` preenchido.
        """
        for tentativa in range(1, self.MAX_RETRIES + 1):
            page = self._context.new_page()
            try:
                logger.info("Tentativa %d/%d — %s", tentativa, self.MAX_RETRIES, self.url)
                page.goto(self.url, wait_until="domcontentloaded")
                dados = self._extrair_dados_da_pagina(page)
                logger.info("Dados extraídos com sucesso")
                return dados

            except Exception as e:
                logger.warning("Erro na tentativa %d: %s", tentativa, e)
                if tentativa < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * tentativa)
                else:
                    logger.error("Todas as tentativas falharam para: %s", self.url)
                    return DadosImovel(url=self.url)
            finally:
                page.close()

if __name__ == "__main__":
    import json

    url = (
        "https://www.zapimoveis.com.br/imovel/venda-casa-de-condominio-2-quartos-com-piscina-alphaville-nova-esplanada-votorantim-sp-226m2-id-2866295152/?source=ranking%2Crp"
    )

    with ZapScraperDadosImovel(url, headless=True) as scraper:
        dados = scraper.extrair()

    print(json.dumps(dados.to_dict(), indent=4, ensure_ascii=False))