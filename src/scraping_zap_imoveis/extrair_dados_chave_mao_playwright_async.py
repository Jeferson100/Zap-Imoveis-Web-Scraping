import asyncio
import re
import logging
from playwright.async_api import async_playwright, BrowserContext, Page
from playwright_stealth import Stealth
from dataclasses import dataclass, field
from typing import Optional, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@dataclass
class DadosImovel:
    """Estrutura de dados de um imóvel."""
    url: str
    titulo: Optional[str] = None
    metragem: Optional[str] = None
    metragem_total: Optional[str] = None
    metragem_util: Optional[str] = None
    banheiros: Optional[str] = None
    vagas: Optional[str] = None
    quartos: Optional[str] = None
    valor_imovel: Optional[str] = None
    condominio: Optional[str] = None
    endereco: Optional[str] = None
    iptu: Optional[str] = None
    descricao: Optional[str] = None
    data_criacao: Optional[str] = None
    caracteristicas: List[str] = field(default_factory=list)
    caracteristicas_privativa: List[str] = field(default_factory=list)
    caracteristicas_comum: List[str] = field(default_factory=list)
    fotos: List[str] = field(default_factory=list)
    link_maps: Optional[str] = None

    def to_dict(self) -> dict:
        return self.__dict__
    

class ChavesNaMaoScraperAsync:
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # segundos
    def __init__(self,headless: bool = True):
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
            self._context = await self._browser.new_context(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ))
            self._page = await self._context.new_page()
            return self
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _get_text(self, seletor: str, timeout: int = 5000) -> str | None:
        try:
            element = self._page.locator(seletor).first
            text = await element.inner_text(timeout=timeout)
            return text.strip()
        except Exception:
            return None

    async def _get_attr(self, seletor: str, atributo: str, timeout: int = 5000) -> str | None:
        try:
            return await self._page.locator(seletor).first.get_attribute(atributo, timeout=timeout)
        except Exception:
            return None

    def _limpar_valor(self, valor: str | None) -> str:
        if not valor or any(x in valor for x in ["-", "—", "Consulte"]):
            return "0"
        return "".join(filter(str.isdigit, valor))

    def _normalizar_valor_monetario(self, valor: str | None) -> str | None:
        if not valor:
            return None
        v = str(valor).strip()
        v = re.sub(r"[^\d.,]", "", v)
        if not v:
            return None
        if "," in v and "." in v:
            v = v.replace(".", "").replace(",", ".")
        elif "," in v:
            v = v.replace(",", ".")
        elif "." in v:
            partes = v.split(".")
            if len(partes[-1]) == 3 and len(partes) > 1:
                v = v.replace(".", "")
        try:
            return str(int(float(v)))
        except Exception:
            return re.sub(r"[^0-9]", "", v) or None

    async def _extrair_valor_imovel(self) -> str | None:
        try:
            scripts = await self._page.locator('script[type="application/ld+json"]').all_inner_texts()
            for script in scripts:
                if not script:
                    continue
                match = re.search(r'"price"\s*:\s*"?([\d.,]+)"?', script, re.I)
                if match:
                    return self._normalizar_valor_monetario(match.group(1))
                match = re.search(r'"rawPrice"\s*:\s*"?([\d.,]+)"?', script, re.I)
                if match:
                    return self._normalizar_valor_monetario(match.group(1))
                match = re.search(r'"price"\s*:\s*"([^"]+)"', script, re.I)
                if match:
                    return self._normalizar_valor_monetario(match.group(1))
        except Exception:
            pass

        try:
            body_text = await self._page.locator('body').inner_text()
            padroes = [
                r'(?i)(?:preço|valor do imóvel|valor)\s*[:\-]?\s*R\$\s*([\d\.\,]+)',
                r'(?i)aluguel\s*[:\-]?\s*R\$\s*([\d\.\,]+)\s*(?:/mês)?',
                r'(?i)aluguel\s*\+\s*condomínio\s*R\$\s*([\d\.\,]+)',
            ]
            for padrao in padroes:
                match = re.search(padrao, body_text)
                if match:
                    return self._normalizar_valor_monetario(match.group(1))
        except Exception:
            pass

        valor_raw = await self._get_text('span.style_clamp__m7txb')
        if valor_raw:
            return self._normalizar_valor_monetario(valor_raw)

        return None

    async def _extrair_metragens(self) -> tuple[Optional[str], Optional[str]]:
        total = util = None
        try:
            html = await self._page.content()
            m = re.search(r'"area"\s*:\s*\{\s*"total"\s*:\s*"(?P<tot>[^"]+)"[^}]*"useful"\s*:\s*"(?P<util>[^"]+)"', html)
            if m:
                tot, ut = m.group("tot"), m.group("util")
                total = None if tot in ("$undefined", "") else tot
                util = None if ut in ("$undefined", "") else ut
        except Exception:
            pass
        if not total:
            t = await self._get_text('p[aria-label="area-total"] b')
            if t:
                total = re.sub(r"[^\d.,]", "", t) or None
        if not util:
            u = await self._get_text('p[aria-label="area-util"] b')
            if u:
                util = re.sub(r"[^\d.,]", "", u) or None
        if not total and not util:
            g = await self._get_text('b.row.spacing:has-text("m²")')
            if g:
                total = re.sub(r"[^\d.,]", "", g) or None
        metragem_total = f"{total} m²" if total else None
        metragem_util = f"{util} m²" if util else None
        return metragem_total, metragem_util

    async def _extrair_caracteristicas(self) -> tuple[List[str], List[str]]:
        priv, comum = [], []
        try:
            html = await self._page.content()
            m_priv = re.search(r'"privativeItems"\s*:\s*\[(.*?)\]', html, re.S)
            if m_priv:
                priv = re.findall(r'"name"\s*:\s*"([^"]+)"', m_priv.group(1))
            m_com = re.search(r'"commonItems"\s*:\s*\[(.*?)\]', html, re.S)
            if m_com:
                comum = re.findall(r'"name"\s*:\s*"([^"]+)"', m_com.group(1))
        except Exception:
            pass
        if not priv and not comum:
            try:
                if await self._page.locator('div.style_optionalItemsContainer__7e5rw').count() > 0:
                    spans = await self._page.locator('div.style_optionalItemsContainer__7e5rw span').all()
                    for sp in spans:
                        titulo = (await sp.locator('b').inner_text()).strip().lower() if await sp.locator('b').count() > 0 else ""
                        itens = await sp.locator('ul li p.styles_text-body-sm-medium__FWa10').all_inner_texts()
                        itens = [i.strip() for i in itens if i.strip()]
                        if "privativa" in titulo:
                            priv = itens
                        elif "comum" in titulo:
                            comum = itens
            except Exception:
                pass
        return [p.strip() for p in priv if p.strip()], [c.strip() for c in comum if c.strip()]

    async def _extrair_dados_da_pagina(self, url: str) -> DadosImovel:
        condo_raw = await self._get_text('p:has-text("Condomínio") + p')
        iptu_raw = await self._get_text('p:has-text("IPTU") + p')

        valor_limpo = await self._extrair_valor_imovel()
        metragem_total, metragem_util = await self._extrair_metragens()
        metragem = metragem_total or metragem_util
        priv, comum = await self._extrair_caracteristicas()

        return DadosImovel(
            url=url,
            titulo=await self._get_text('h1.styles_typography__xG9rg'),
            metragem=metragem,
            metragem_total=metragem_total,
            metragem_util=metragem_util,
            valor_imovel=valor_limpo,
            quartos=await self._get_text("b:has(svg path[d^='M112.867 767.316'])"),
            banheiros=self._limpar_valor(await self._get_text('p[aria-label="Banheiros"] b')),
            vagas=await self._get_text("p[aria-label='Garagens'] b"),
            endereco=await self._get_text('h2[class*="styles_text-title-lg"].column, h2[class*="styles_text-title-lg"] b'),
            descricao=await self._get_text('p[aria-label="descrição"]'),
            condominio=self._limpar_valor(condo_raw),
            iptu=self._limpar_valor(iptu_raw),
            caracteristicas=[],
            caracteristicas_privativa=priv,
            caracteristicas_comum=comum,
            fotos=await self._get_fotos(),
            link_maps=await self._get_mapa(),
        )

    async def _get_fotos(self) -> list[str]:
        try:
            await self._page.locator('#tablink-media').click()
            await self._page.wait_for_selector('ul.galleryContainer', timeout=5000)
            return await self._page.locator('ul.galleryContainer img').evaluate_all(
                "imgs => imgs.map(img => img.src || img.dataset.src)"
            )
        except Exception:
            return []

    async def _get_mapa(self) -> str | None:
        try:
            await self._page.locator('#tablink-map').click()
            await self._page.wait_for_selector('iframe[src*="maps"]', timeout=5000)
            return await self._get_attr('iframe[src*="maps"]', 'src')
        except Exception:
            return None

    async def extrair_chave_mao(self, url: str) -> dict:
        for tentativa in range(1, self.MAX_RETRIES + 1):
            try:
                if self._page.is_closed():
                    self._page = await self._context.new_page()

                logger.info(f"Tentativa {tentativa}/{self.MAX_RETRIES} — {url}")
                
                await self._page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await self._page.wait_for_timeout(2000) 
                
                dados = await self._extrair_dados_da_pagina(url)
                logger.info("Dados extraídos com sucesso")
                return dados.to_dict()

            except Exception as e:
                logger.warning(f"Erro na tentativa {tentativa}: {e}")
                if tentativa < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY * tentativa)
                else:
                    logger.error(f"Falha total: {url}")
                    return DadosImovel(url=url).to_dict()



if __name__ == "__main__":
    # Exemplo de uso assíncrono
    async def main():
        url = "https://www.chavesnamao.com.br/imovel/apartamento-a-venda-2-quartos-com-garagem-sc-joinville-atiradores-54m2-RS369900/id-34276107/"
        #url = "https://www.chavesnamao.com.br/imovel/apartamento-a-venda-3-quartos-com-garagem-sp-sao-paulo-brooklin-RS3090000/id-40215019/"
        async with ChavesNaMaoScraperAsync(headless=True) as scraper:
            dados = await scraper.extrair_chave_mao(url)
            print(dados)
    
    asyncio.run(main())