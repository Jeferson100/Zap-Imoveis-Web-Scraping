import asyncio
import base64
import logging
import random
import re
from dataclasses import dataclass, field
from typing import List, Optional

from playwright.async_api import async_playwright, Page, BrowserContext
try:
    from playwright_stealth import Stealth
except Exception:
    Stealth = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ANTI_DETECT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
"""

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

EXTRACTOR_AVISO_JS = """
() => {
    const scripts = Array.from(document.querySelectorAll('script'));
    const script = scripts.find(s => s.textContent && s.textContent.includes('const avisoInfo'));
    if (!script) return null;
    const texto = script.textContent;
    const chave = 'const avisoInfo';
    const inicio = texto.indexOf(chave) + chave.length;
    const objeto = texto.slice(inicio);
    const abre = objeto.indexOf('{');
    if (abre === -1) return null;
    let profundidade = 0;
    let i = abre;
    let fechado = false;
    for (; i < objeto.length; i++) {
        const c = objeto[i];
        if (c === '{') profundidade += 1;
        else if (c === '}') {
            profundidade -= 1;
            if (profundidade === 0) { fechado = true; break; }
        }
    }
    if (!fechado) return null;
    const literal = objeto.slice(abre, i + 1);
    return Function('"use strict"; return (' + literal + ')')();
}
"""


@dataclass
class DadosImovelImovelWeb:
    url: str
    titulo: Optional[str] = None
    metragem: Optional[str] = None
    metragem_total: Optional[str] = None
    metragem_util: Optional[str] = None
    quartos: Optional[str] = None
    suites: Optional[str] = None
    banheiros: Optional[str] = None
    vagas: Optional[str] = None
    idade: Optional[str] = None
    valor_imovel: Optional[str] = None
    condominio: Optional[str] = None
    endereco: Optional[str] = None
    bairro: Optional[str] = None
    cidade: Optional[str] = None
    uf: Optional[str] = None
    descricao: Optional[str] = None
    data_criacao: Optional[str] = None
    caracteristicas: List[str] = field(default_factory=list)
    caracteristicas_privativa: List[str] = field(default_factory=list)
    caracteristicas_comum: List[str] = field(default_factory=list)
    fotos: List[str] = field(default_factory=list)
    lat: Optional[str] = None
    lng: Optional[str] = None
    fonte: str = field(default="imovelweb")

    def to_dict(self) -> dict:
        return self.__dict__


def _feature(main_features, codigo):
    item = (main_features or {}).get(codigo) or {}
    return item.get("value")


def _decodificar_coordenada(valor):
    if not valor:
        return None
    try:
        return base64.b64decode(valor).decode("utf-8")
    except Exception:
        return valor


def _limpar_descricao(texto):
    if not texto:
        return None
    return re.sub(r"<[^>]+>", "", texto).strip()


class ImovelWebDadosImovelAsync:

    MAX_RETRIES = 3
    RETRY_DELAY = 2

    def __init__(self, url: str, headless: bool = True, proxy: Optional[dict] = None):
        self.url = url
        self.headless = headless
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._pw_cm = None
        self._context: Optional[BrowserContext] = None
        self._user_agent = random.choice(USER_AGENTS)

    async def __aenter__(self):
        try:
            if Stealth:
                self._pw_cm = Stealth().use_async(async_playwright())
            else:
                self._pw_cm = async_playwright()
            self._playwright = await self._pw_cm.__aenter__()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            viewport_w = random.randint(1850, 1980)
            viewport_h = random.randint(1020, 1120)
            context_kwargs = dict(
                viewport={"width": viewport_w, "height": viewport_h},
                user_agent=self._user_agent,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                device_scale_factor=random.choice([1, 1.25, 1.5, 2]),
                has_touch=False,
            )
            if self.proxy:
                context_kwargs["proxy"] = self.proxy
            self._context = await self._browser.new_context(**context_kwargs)
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

    async def _mapear_aviso(self, aviso: dict) -> DadosImovelImovelWeb:
        main_features = aviso.get("mainFeatures") or {}

        location = aviso.get("location") or {}
        parent = location.get("parent") or {}
        avo = parent.get("parent") or {}
        uf = avo.get("acronym")

        rua = (aviso.get("address") or {}).get("name")
        bairro = location.get("name")
        cidade = parent.get("name")

        endereco = ", ".join(
            p for p in [rua.rstrip(",") if rua else None, bairro, cidade] if p
        )
        if endereco and uf:
            endereco = f"{endereco} - {uf}"

        total = _feature(main_features, "CFT100")
        util = _feature(main_features, "CFT101")
        metragem_total = f"{total} m²" if total else None
        metragem_util = f"{util} m²" if util else None
        metragem = metragem_total or metragem_util
        condominio = aviso.get("expenses")
        if condominio == "0":
            condominio = None

        caracteristicas, priv, comum = [], [], []
        for grupo_nome, grupo in (aviso.get("generalFeatures") or {}).items():
            for item in (grupo or {}).values():
                label = item.get("label")
                valor = item.get("value")
                entry = f"{label}: {valor}" if valor not in (None, "") else label
                caracteristicas.append(entry)
                nome_norm = grupo_nome.strip().lower()
                if "privativa" in nome_norm:
                    priv.append(entry)
                elif "comuns" in nome_norm or "comum" in nome_norm:
                    comum.append(entry)

        fotos = [
            foto.get("url1200x1200")
            for foto in (aviso.get("pictures") or [])
            if foto.get("url1200x1200")
        ]

        return DadosImovelImovelWeb(
            url=self.url,
            titulo=aviso.get("postingTitle") or aviso.get("generatedTitle"),
            metragem=metragem,
            metragem_total=metragem_total,
            metragem_util=metragem_util,
            quartos=_feature(main_features, "CFT2"),
            suites=_feature(main_features, "CFT4"),
            banheiros=_feature(main_features, "CFT3"),
            vagas=_feature(main_features, "CFT7"),
            idade=_feature(main_features, "CFT5"),
            valor_imovel=aviso.get("price"),
            condominio=condominio,
            endereco=endereco,
            bairro=bairro,
            cidade=cidade,
            uf=uf,
            descricao=_limpar_descricao(aviso.get("description")),
            data_criacao=aviso.get("publicationDateFormatted"),
            caracteristicas=caracteristicas,
            caracteristicas_privativa=priv,
            caracteristicas_comum=comum,
            fotos=fotos,
            lat=_decodificar_coordenada(aviso.get("mapLat")),
            lng=_decodificar_coordenada(aviso.get("mapLng")),
        )

    async def _extrair_fallback(self, page: Page) -> DadosImovelImovelWeb:
        titulo = await page.title()
        match_valor = re.search(r"R\$\s*[\d.]+", titulo)
        tot = re.search(r"(\d[\d.,]*)\s*m²\s*tot", titulo, re.IGNORECASE)
        util = re.search(r"(\d[\d.,]*)\s*m²\s*útil", titulo, re.IGNORECASE)
        generic = re.search(r"(\d[\d.,]*)\s*m2", titulo, re.IGNORECASE)
        metragem_total = f"{tot.group(1)} m²" if tot else (f"{generic.group(1)} m²" if generic else None)
        metragem_util = f"{util.group(1)} m²" if util else None
        metragem = metragem_total or metragem_util
        return DadosImovelImovelWeb(
            url=self.url,
            titulo=titulo,
            valor_imovel=match_valor.group(0) if match_valor else None,
            metragem=metragem,
            metragem_total=metragem_total,
            metragem_util=metragem_util,
        )

    async def _extrair_dados_da_pagina(self, page: Page) -> DadosImovelImovelWeb:
        aviso = await page.evaluate(EXTRACTOR_AVISO_JS)
        if not aviso:
            logger.warning("avisoInfo não encontrado em %s. Usando fallback.", self.url)
            return await self._extrair_fallback(page)
        return await self._mapear_aviso(aviso)

    async def extrair(self) -> DadosImovelImovelWeb:
        for tentativa in range(1, self.MAX_RETRIES + 1):
            page = await self._context.new_page()
            try:
                await page.add_init_script(ANTI_DETECT_JS)
                logger.info("Tentativa %d/%d — %s", tentativa, self.MAX_RETRIES, self.url)
                await page.goto(self.url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(random.uniform(1, 2))
                dados = await self._extrair_dados_da_pagina(page)
                logger.info("Dados extraídos com sucesso")
                return dados
            except Exception as e:
                logger.warning("Erro na tentativa %d: %s", tentativa, e)
                if tentativa < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAY * tentativa)
                else:
                    logger.error("Todas as tentativas falharam para: %s", self.url)
                    return DadosImovelImovelWeb(url=self.url)
            finally:
                await page.close()