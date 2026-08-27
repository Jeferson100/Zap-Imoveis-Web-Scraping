from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import time
import warnings
from typing import Optional
from urllib.parse import urlsplit
from pathlib import Path
import hashlib

from playwright.async_api import async_playwright
try:
    from playwright_stealth import Stealth
except Exception:
    Stealth = None

warnings.filterwarnings("ignore")

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

LISTINGS_SELECTOR = "div[data-to-posting]"
DOMINIO = "https://www.imovelweb.com.br"

EXTRACTOR_LISTAGEM_JS = """
() => {
    const DOMINIO = "https://www.imovelweb.com.br";
    const container = document.querySelector('div.postingsList-module__postings-container');
    if (!container) return null;
    
    const cards = container.querySelectorAll('div[data-to-posting]');
    return Array.from(cards).map(card => {
        const link = card.getAttribute('data-to-posting');
        return {
            url: link ? DOMINIO + link : null,
            titulo: card.querySelector('.posting-title')?.innerText.trim() || '',
            metragem: card.querySelector('.metragem')?.innerText.trim() || '',
            quartos: card.querySelector('.quartos')?.innerText.trim() || '',
            banheiros: card.querySelector('.banheiros')?.innerText.trim() || '',
            vaga: card.querySelector('.vagas')?.innerText.trim() || '',
            preco: card.querySelector('.price')?.innerText.trim() || '',
        };
    });
}
"""


class ImovelWebScraperLinksAsync:

    def __init__(self, headless: bool = True, proxy: Optional[dict] = None):
        self.headless = headless
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._context = None
        self._pw_cm = None
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
            await self._context.add_init_script(ANTI_DETECT_JS)
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

    async def _wait_for_listings(self, page, timeout_sec: float = 90.0) -> bool:
        """Aguarda o carregamento dos cards da listagem."""
        deadline = time.monotonic() + timeout_sec
        count = 0

        while time.monotonic() < deadline:
            count = await page.locator(LISTINGS_SELECTOR).count()
            if count > 0:
                return True
            await asyncio.sleep(random.uniform(2, 5))

        return False

    async def _scroll_page(self, page) -> None:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight * 2 / 3)")
        await asyncio.sleep(random.uniform(0.5, 1.5))
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    def _parse_links(self, caminhos: list[str | None]) -> list[str]:
        links = []
        for caminho in caminhos:
            if not caminho:
                continue
            so_path = urlsplit(caminho).path
            if so_path.startswith('/propriedades/'):
                links.append(DOMINIO + so_path)
        return list(set(links))

    async def get_links(self, url: str, retries: int = 3) -> list[str]:
        """Adaptado de Notebooks/imovelweb_links_pagina.py (sync, 30 links):
        container postingsList-module__postings-container + data-to-posting + html.unescape.
        """
        for attempt in range(retries):
            page = await self._context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=90000)
                await asyncio.sleep(5)
                for cf in range(3):
                    try:
                        title = await page.title()
                    except Exception:
                        title = ""
                    if "Um momento" in title:
                        logger.info("Cloudflare desafio detectado (tentativa %d/3), aguardando 8000ms...", cf + 1)
                        await asyncio.sleep(8)
                    else:
                        break
                try:
                    ok = await self._handle_cloudflare(page)
                except Exception:
                    ok = True
                if not ok:
                    logger.warning("Cloudflare não resolvido; pulando tentativa.")
                    await page.close()
                    continue
                try:
                    await page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                except Exception as e:
                    logger.warning("Container não encontrado em %s: %s", url, e)
                    if "pagina-" in url:
                        fb = re.sub(r"pagina-\d+\.html", "", url).rstrip("/") + ".html"
                        alt_fbs = [f for f in [fb, "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-menos-50-m2.html"] if f != url]
                        success = False
                        for alt in alt_fbs:
                            try:
                                logger.info("Tentando fallback %s", alt)
                                await page.goto(alt, wait_until="domcontentloaded", timeout=90000)
                                await asyncio.sleep(5)
                                for att in range(3):
                                    try:
                                        t = await page.title()
                                    except Exception:
                                        t = ""
                                    if "Um momento" in t:
                                        await asyncio.sleep(8)
                                    else:
                                        break
                                await page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                                success = True
                                break
                            except Exception as e2:
                                logger.warning("Fallback %s também falhou: %s", alt, e2)
                        if not success:
                            await page.close()
                            continue
                    else:
                        await page.close()
                        continue
                container = page.locator("div.postingsList-module__postings-container").first
                try:
                    await container.wait_for(state="visible", timeout=15000)
                except Exception:
                    pass
                cards = container.locator("div.postingsList-module__card-container")
                total = await cards.count()
                logger.info("Container: %d cards em %s", total, url)
                links: list[str] = []
                for idx in range(total):
                    card = cards.nth(idx)
                    try:
                        layout = card.locator("div.postingCardLayout-module__posting-card-layout").first
                        href = await layout.get_attribute("data-to-posting")
                        if not href:
                            href = await card.locator('[data-qa="POSTING_CARD_DESCRIPTION"] a').first.get_attribute("href")
                        if href:
                            href = html.unescape(href)
                            abs_url = href if href.startswith("http") else f"{DOMINIO}{href}"
                            links.append(abs_url)
                    except Exception as e:
                        logger.warning("card %d: %s", idx, e)
                await page.close()
                seen = set()
                uniq: list[str] = []
                for u in links:
                    if u not in seen:
                        seen.add(u)
                        uniq.append(u)
                if uniq:
                    logger.info("Links encontrados para %s (%d)", url, len(uniq))
                    return uniq
                logger.warning("Tentativa %d/%d: nenhum link encontrado em %s", attempt + 1, retries, url)
            except Exception as e:
                logger.error("Tentativa %d/%d falhou para %s: %s", attempt + 1, retries, url, e)
                try:
                    debug_dir = Path("debug/htmls")
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    content = await page.content()
                    fname = debug_dir / f"{hashlib.sha1(url.encode()).hexdigest()}_error_attempt{attempt+1}.html"
                    fname.write_text(content, encoding="utf-8")
                    logger.info("Saved debug HTML on exception to %s", fname)
                except Exception:
                    pass
                try:
                    await page.close()
                except Exception:
                    pass
            if attempt < retries - 1:
                await asyncio.sleep(random.uniform(5, 10))
        return []

    async def get_dados_das_listagens(self, url: str, retries: int = 3) -> list[DadosImovelImovelWeb]:
        """Extrai dados diretamente da página de listagem, sem coletar links."""
        from .extrair_dados_imovelweb_playwright_async import DadosImovelImovelWeb

        for i in range(retries):
            page = await self._context.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # detectar e tentar resolver challenge Cloudflare
                try:
                    ok = await self._handle_cloudflare(page)
                except Exception:
                    ok = True
                if not ok:
                    logger.warning("Cloudflare não resolvido; pulando tentativa.")
                    await page.close()
                    continue

                if not await self._wait_for_listings(page):
                    logger.warning(
                        "Tentativa %d/%d: listagem não carregou em %s",
                        i + 1, retries, url,
                    )
                    await page.close()
                    continue

                await self._scroll_page(page)

                # pequena pausa extra para garantir que os cards estejam totalmente renderizados
                await asyncio.sleep(random.uniform(3, 6))

                # Extrair dados usando o JavaScript evaluator
                dados = await page.evaluate(EXTRACTOR_LISTAGEM_JS)

                if dados:
                    # Converter para objetos DadosImovelImovelWeb
                    resultados = []
                    for dado in dados:
                        if not dado.get('url'):
                            continue
                        resultados.append(DadosImovelImovelWeb(
                            url=dado['url'],
                            titulo=dado.get('titulo'),
                            metragem=dado.get('metragem'),
                            quartos=dado.get('quartos'),
                            banheiros=dado.get('banheiros'),
                            vagas=dado.get('vaga'),
                            valor_imovel=dado.get('preco'),
                            fonte="imovelweb",
                        ))
                    logger.info("Dados extraídos da listagem %s (%d imóveis)", url, len(resultados))
                    return resultados

                await page.close()
                continue

            except Exception as e:
                logger.error("Tentativa %d/%d falhou para %s: %s", i + 1, retries, url, e)
                try:
                    # tenta salvar conteúdo de página para diagnóstico
                    debug_dir = Path("debug/htmls")
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    content = await page.content()
                    fname = debug_dir / f"{hashlib.sha1(url.encode()).hexdigest()}_error_attempt{i+1}.html"
                    fname.write_text(content, encoding="utf-8")
                    logger.info("Saved debug HTML on exception to %s", fname)
                except Exception:
                    pass
            finally:
                await page.close()

            if i < retries - 1:
                await asyncio.sleep(random.uniform(5, 10))

        return []

    async def _handle_cloudflare(self, page) -> bool:
        """Detecta challenge Cloudflare e tenta resolver (auto-click em iframe ou pausa para intervenção manual)."""
        try:
            content = await page.content()
        except Exception:
            content = ""

        if any(s in content for s in ("Executando verificação de segurança", "Confirm", "Cloudflare", "Confirme que é humano")):
            logger.warning("Cloudflare challenge detectado na página.")
            # se estivermos em modo visível, aguarda intervenção manual
            if not self.headless:
                logger.info("Modo não-headless: aguarde resolver o challenge no navegador; pressione Enter aqui quando concluir.")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, input, "Depois de resolver o challenge, pressione Enter...")
                await asyncio.sleep(2)
                return True

            # tentativa automática: procurar checkbox dentro de iframes e clicar
            try:
                for frame in page.frames:
                    try:
                        checkbox = await frame.query_selector("input[type=checkbox]")
                        if checkbox:
                            await checkbox.click()
                            await asyncio.sleep(3)
                            logger.info("Tentativa automática: clique em checkbox realizada.")
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            logger.warning("Falha ao resolver Cloudflare automaticamente em headless.")
            return False

        return True
