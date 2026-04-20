import re
from playwright.sync_api import Playwright, sync_playwright, BrowserContext
from playwright_stealth import Stealth
from dataclasses import dataclass, field
from typing import Optional, List
import logging
import time

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


class ChavesNaMaoScraper:
    """
    Scraper para imóveis do site chavesnamao.com.br
    """
    MAX_RETRIES = 3
    RETRY_DELAY = 2 

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

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
        self._page = self._context.new_page()
        return self

    def __exit__(self, *args):
        self._browser.close()
        self._playwright.stop()

    def _get_text(self, seletor: str, timeout: int = 5000) -> str | None:
        try:
            return self._page.locator(seletor).first.inner_text(timeout=timeout).strip()
        except Exception:
            return None

    def _get_attr(self, seletor: str, atributo: str, timeout: int = 5000) -> str | None:
        try:
            return self._page.locator(seletor).first.get_attribute(atributo, timeout=timeout)
        except Exception:
            return None

    def _limpar_valor(self, valor: str | None) -> str:
        if valor is None:
            return "0"
        if "-" in valor or "—" in valor:
            return "0"
        return "".join(filter(str.isdigit, valor))

    def get_titulo(self) -> str | None:
        return self._get_text('h1.styles_typography__xG9rg')

    def get_valor(self) -> str | None:
        valor_raw = self._get_text('span.style_clamp__m7txb')
        if valor_raw:
            return valor_raw.replace('R$', '').replace('.', '').strip()
        return None

    def get_metragem(self) -> str | None:
        return self._get_text('b.row.spacing:has-text("m²")')

    def get_quartos(self) -> str | None:
        valor = self._get_text("b:has(svg path[d^='M112.867 767.316'])")
        return valor.strip() if valor else None

    def get_banheiros(self) -> str | None:
        valor = self._get_text('p[aria-label="Banheiros"] b')
        if valor:
            return "".join(filter(str.isdigit, valor))
        return None

    def get_garagens(self) -> str | None:
        valor = self._get_text("p[aria-label='Garagens'] b")
        return valor.strip() if valor else None

    def get_descricao(self) -> str | None:
        return self._get_text('p[aria-label="descrição"]')

    def get_data_referencia(self) -> dict:
        return {
            'data_texto': self._get_text('time'),
        }

    def _extrair_referencia(self) -> str:
        texto = self._get_text('p:has(time)')
        if texto and 'Ref:' in texto:
            return texto.split('Ref:')[1].strip()
        return "N/A"

    def get_endereco(self) -> str | None:
        return self._get_text('b:has-text("Joinville"), b:has-text("SC")')

    def get_condominio_iptu(self) -> dict:
        return {
            'condominio': self._limpar_valor(self._get_text('p:has-text("Condomínio") + p')),
            'iptu':       self._limpar_valor(self._get_text('p:has-text("IPTU") + p')),
        }

    def get_fotos(self) -> list[str]:
        try:
            self._page.locator('#tablink-media').click()
            self._page.wait_for_selector('ul.galleryContainer', timeout=10000)
            return self._page.locator('ul.galleryContainer img').evaluate_all(
                "imgs => imgs.map(img => img.src || img.dataset.src)"
            )
        except Exception as e:
            logger.debug("Erro ao capturar fotos: %s", e)
            return []

    def get_mapa(self) -> str | None:
        try:
            self._page.locator('#tablink-map').click()
            self._page.wait_for_selector('iframe[src*="maps"]', timeout=15000)
            return self._get_attr('iframe[src*="maps"]', 'src')
        except Exception as e:
            logger.debug("Erro ao capturar mapa: %s", e)
            return None

    def get_tipo_imovel(self) -> str | None:
        return self._get_text('span.style_realtyType__TTt5s')

    def _extrair_dados_da_pagina(self) -> dict:
        """
        Coleta todos os dados de um imóvel.
        Retorna dict com todos os campos disponíveis.
        """
        cond_iptu = self.get_condominio_iptu()
        
        dados = DadosImovel(
            url=url,
            titulo=self.get_titulo(),
            metragem=self.get_metragem(),
            valor_venda=self.get_valor(),
            quartos=self.get_quartos(),
            banheiros=self.get_banheiros(),
            vagas=self.get_garagens(),
            endereco=self.get_endereco(),
            descricao=self.get_descricao(),
            condominio=cond_iptu['condominio'],
            iptu=cond_iptu['iptu'],
            caracteristicas=[],
            fotos=self.get_fotos(),
            link_maps=self.get_mapa(),
        )
        
        return dados
    
    def extrair_chave_mao(self, url: str) -> dict:
        for tentativa in range(1, self.MAX_RETRIES + 1):
            try:
                
                if self._page.is_closed():
                    self._page = self._context.new_page()

                logger.info("Tentativa %d/%d — %s", tentativa, self.MAX_RETRIES, url)
                
                # Usamos 'domcontentloaded' e um timeout maior para sites lentos
                self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                
                # Pequena espera manual ou scroll para garantir que os dados renderizem
                self._page.wait_for_timeout(2000) 
                
                dados = self._extrair_dados_da_pagina()
                logger.info("Dados extraídos com sucesso")
                return dados

            except Exception as e:
                logger.warning("Erro na tentativa %d: %s", tentativa, e)
                if tentativa < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY * tentativa)
                else:
                    logger.error("Todas as tentativas falharam para: %s", url)
                    return DadosImovel(url=url)

            finally:
                self._page.close()

# Uso
if __name__ == "__main__":
    url = "https://www.chavesnamao.com.br/imovel/apartamento-a-venda-2-quartos-com-garagem-sc-joinville-atiradores-54m2-RS369900/id-34276107/"
    import json
    with ChavesNaMaoScraper(headless=True) as scraper:
        dados = scraper.extrair_chave_mao(url)
        print(dados)
    