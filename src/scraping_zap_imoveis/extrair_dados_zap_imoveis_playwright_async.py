import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Optional, List
from playwright.async_api import async_playwright, Page, BrowserContext
from playwright_stealth import Stealth

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


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


class ZapScraperDadosImovelAsync:
    """Extrator assíncrono de dados detalhados de anúncios no Zap Imóveis."""

    MAX_RETRIES = 3
    RETRY_DELAY = 2  # segundos

    def __init__(self, url: str, headless: bool = True):
        self.url = url
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._pw_cm = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self):
        try:
            self._pw_cm = Stealth().use_async(async_playwright())
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(headless=self.headless)
            self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
            )
            return self
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw_cm:
                await self._pw_cm.__aexit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.error("Erro ao fechar recursos: %s", e)


    async def _safe_get_text(
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
                texts = await locator.all_text_contents()
                return [t.strip() for t in texts if t.strip()]

            text = await locator.first.text_content(timeout=timeout)
            return text.strip() if text else None

        except Exception as e:
            logger.debug("Elemento não encontrado [%s]: %s", selector, e)
            return [] if multiple else None

    async def _extrair_iptu(self, page: Page) -> Optional[str]:
        try:
            valor = await (
                page.locator("div.value-item", has_text="IPTU")
                .locator("p.value-item__value")
                .text_content(timeout=3000)
            )
            return valor.strip() if valor else None
        except Exception:
            return await self._safe_get_text(page, "iptu", is_testid=True)

    async def _extrair_links_imagens(self, page: Page) -> List[str]:
        links = []
        try:
            sources = page.locator(
                'ul[data-testid="carousel-photos"] source[type="image/webp"]'
            )
            count = await sources.count()
            for i in range(count):
                srcset = await sources.nth(i).get_attribute("srcset")
                if srcset:
                    url_alta_res = srcset.split(",")[-1].strip().split(" ")[0]
                    links.append(url_alta_res)

            logger.info("Encontradas imagens")
        except Exception as e:
            logger.error("Erro ao extrair imagens: %s", e)

        return links

    async def _extrair_link_maps(self, page: Page) -> Optional[str]:
        try:
            return await page.locator('iframe[data-testid="map-iframe"]').get_attribute("src")
        except Exception as e:
            logger.debug("Erro ao extrair link maps: %s", e)
            return None

    async def _extrair_dados_da_pagina(self, page: Page) -> DadosImovel:
        """Extrai todos os dados de uma página já carregada."""
        # Dispara todas as extrações em paralelo
        (
            titulo, metragem, banheiros, vagas, quartos,
            valor_venda, condominio, endereco, iptu,
            descricao, data_criacao, caracteristicas, fotos, link_maps
        ) = await asyncio.gather(
            self._safe_get_text(page, "h2.text-neutral-130.line-clamp-2"),
            self._safe_get_text(page, "p.font-secondary:has-text('m²')"),
            self._safe_get_text(page, "xpath=//p[text()='Banheiros']/following-sibling::div/p"),
            self._safe_get_text(page, "xpath=//p[text()='Vagas']/following-sibling::div/p"),
            self._safe_get_text(page, "xpath=//p[text()='Quartos']/following-sibling::div/p"),
            self._safe_get_text(page, ".value-item__value-highlight .value-item__value"),
            self._safe_get_text(page, "condoFee", is_testid=True),
            self._safe_get_text(page, "location-address", is_testid=True),
            self._extrair_iptu(page),
            self._safe_get_text(page, "description-content", is_testid=True),
            self._safe_get_text(page, "listing-created-date", is_testid=True),
            self._safe_get_text(
                page,
                'ul[data-testid="amenities-list"] li span.amenities-item-text',
                multiple=True,
            ),
            self._extrair_links_imagens(page),
            self._extrair_link_maps(page),
        )

        return DadosImovel(
            valor_venda=valor_venda,
            metragem=metragem,
            url=self.url,
            data_criacao=data_criacao,
            banheiros=banheiros,
            vagas=vagas,
            quartos=quartos,
            condominio=condominio,
            endereco=endereco,
            iptu=iptu,
            titulo=titulo,
            descricao=descricao,
            caracteristicas=caracteristicas,
            link_maps=link_maps,
            fotos=fotos,
        )

    async def extrair(self) -> DadosImovel:
        """
        Acessa a URL e extrai os dados com tentativas automáticas em caso de falha.

        Returns:
            DadosImovel com os dados extraídos ou campo `erro` preenchido.
        """
        for tentativa in range(1, self.MAX_RETRIES + 1):
            page = await self._context.new_page()
            try:
                logger.info("Tentativa %d/%d — %s", tentativa, self.MAX_RETRIES, self.url)
                await page.goto(self.url, wait_until="domcontentloaded")
                dados = await self._extrair_dados_da_pagina(page)
                logger.info("Dados extraídos com sucesso")
                return dados

            except Exception as e:
                logger.warning("Erro na tentativa %d: %s", tentativa, e)
                if tentativa < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY * tentativa)  # non-blocking sleep
                else:
                    logger.error("Todas as tentativas falharam para: %s", self.url)
                    return DadosImovel(url=self.url)

            finally:
                await page.close()

if __name__ == "__main__":
    async def main():
        urls = ['https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-elevador-campestre-santo-andre-sp-62m2-id-2818274726/?source=ranking%2Crp',
            'https://www.zapimoveis.com.br/imovel/venda-casa-de-condominio-2-quartos-com-piscina-alphaville-nova-esplanada-votorantim-sp-226m2-id-2866295152/?source=ranking%2Crp',
            'https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-com-jardim-butanta-zona-oeste-sao-paulo-sp-350m2-id-2763317088/?source=ranking%2Crp',
            'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-piscina-bom-retiro-sao-paulo-65m2-id-2863929162/?source=ranking%2Crp',
            'https://www.zapimoveis.com.br/imovel/venda-casa-3-quartos-redencao-manaus-198m2-id-2750221407/?source=ranking%2Crp',
            'https://www.zapimoveis.com.br/imovel/venda-apartamento-2-quartos-com-espaco-gourmet-pinheiros-sao-paulo-95m2-id-2863933126/?source=ranking%2Crp',
            'https://www.zapimoveis.com.br/imovel/venda-apartamento-3-quartos-com-piscina-cidade-moncoes-sao-paulo-98m2-id-2857696093/?source=ranking%2Crp',
        ]

        # Cria um scraper por URL e roda todos em paralelo
        async def scrape(url: str) -> DadosImovel:
            async with ZapScraperDadosImovelAsync(url, headless=True) as scraper:
                return await scraper.extrair()

        resultados = await asyncio.gather(*[scrape(url) for url in urls])

        import json
        for dados in resultados:
            print(json.dumps(dados.to_dict(), indent=4, ensure_ascii=False))

    asyncio.run(main())