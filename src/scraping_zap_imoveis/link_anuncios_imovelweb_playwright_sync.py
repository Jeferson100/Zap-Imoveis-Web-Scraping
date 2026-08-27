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

from playwright.sync_api import sync_playwright
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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
]

LISTINGS_SELECTOR = "div[data-to-posting]"
DOMINIO = "https://www.imovelweb.com.br"


class ImovelWebScraperLinksSync:
    def __init__(self, headless: bool = True, proxy: Optional[dict] = None):
        self.headless = headless
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._context = None
        self._user_agent = random.choice(USER_AGENTS)

    def __enter__(self):
        try:
            if Stealth:
                pw = sync_playwright()
                self._pw_cm = Stealth().use_sync(pw)
            else:
                pw = sync_playwright()
                self._pw_cm = pw
            self._playwright = self._pw_cm.__enter__()
            self._browser = self._playwright.chromium.launch(
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
            self._context = self._browser.new_context(**context_kwargs)
            self._context.add_init_script(ANTI_DETECT_JS)
            return self
        except Exception as e:
            logger.error("Erro ao inicializar navegador: %s", e)
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw_cm:
                self._pw_cm.__exit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.error("Erro ao fechar recursos: %s", e)

    def _wait_for_listings(self, page, timeout_sec: float = 90.0) -> bool:
        """Aguarda o carregamento dos cards da listagem."""
        deadline = time.monotonic() + timeout_sec
        count = 0

        while time.monotonic() < deadline:
            count += 1
            try:
                page.wait_for_selector(LISTINGS_SELECTOR, timeout=5000)
                return True
            except Exception:
                time.sleep(0.5)

        return False

    def _scroll_page(self, page) -> None:
        """Faz scroll na página para carregar mais conteúdos."""
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_load_state("networkidle")
        time.sleep(random.uniform(1, 2))

    def get_links(self, url: str, retries: int = 3) -> list[str]:
        """Coleta links de anúncios de uma página do ImovelWeb.

        Adaptado de Notebooks/imovelweb_links_pagina.py (funciona: 30 links):
        escopa 1º div.postingsList-module__postings-container -> 30x card-container
        e lê data-to-posting (fallback a[href]), html.unescape, dedup preservando ordem.
        """
        for attempt in range(retries):
            page = None
            try:
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(5000)
                for cf in range(3):
                    try:
                        title = page.title()
                    except Exception:
                        title = ""
                    if "Um momento" in title:
                        logger.info("Cloudflare desafio detectado (tentativa %d/3), aguardando 8000ms...", cf + 1)
                        page.wait_for_timeout(8000)
                    else:
                        break
                try:
                    ok = self._handle_cloudflare(page)
                except Exception:
                    ok = True
                if not ok:
                    logger.warning("Cloudflare não resolvido; pulando tentativa.")
                    page.close()
                    page = None
                    continue
                try:
                    page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                except Exception as e:
                    logger.warning("Container não encontrado em %s: %s", url, e)
                    if "pagina-" in url:
                        fallback = re.sub(r"pagina-\d+\.html", "", url).rstrip("/") + ".html" if "pagina-" in url else None
                        alt_fallbacks = [f for f in [fallback, "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-menos-50-m2.html"] if f and f != url]
                        success = False
                        for fb in alt_fallbacks:
                            try:
                                logger.info("Tentando fallback %s", fb)
                                page.goto(fb, wait_until="domcontentloaded", timeout=90000)
                                page.wait_for_timeout(5000)
                                for att in range(3):
                                    try:
                                        t = page.title()
                                    except Exception:
                                        t = ""
                                    if "Um momento" in t:
                                        page.wait_for_timeout(8000)
                                    else:
                                        break
                                page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                                logger.info("Fallback funcionou: %s", fb)
                                success = True
                                break
                            except Exception as e2:
                                logger.warning("Fallback %s também falhou: %s", fb, e2)
                        if not success:
                            page.close()
                            page = None
                            continue
                    else:
                        page.close()
                        page = None
                        continue
                container = page.locator("div.postingsList-module__postings-container").first
                try:
                    container.wait_for(state="visible", timeout=15000)
                except Exception:
                    pass
                cards = container.locator("div.postingsList-module__card-container")
                total = cards.count()
                logger.info("Container: %d cards em %s", total, url)
                links: list[str] = []
                for idx in range(total):
                    card = cards.nth(idx)
                    try:
                        layout = card.locator("div.postingCardLayout-module__posting-card-layout").first
                        href = layout.get_attribute("data-to-posting")
                        if not href:
                            href = card.locator('[data-qa="POSTING_CARD_DESCRIPTION"] a').first.get_attribute("href")
                        if href:
                            href = html.unescape(href)
                            abs_url = href if href.startswith("http") else f"{DOMINIO}{href}"
                            links.append(abs_url)
                    except Exception as e:
                        logger.warning("card %d: %s", idx, e)
                page.close()
                page = None
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
                logger.warning("Erro na tentativa %d/%d para %s: %s", attempt + 1, retries, url, e)
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                time.sleep(2 ** attempt)
        return []

    def get_listings_data(self, url: str, retries: int = 3) -> list[dict]:
        """Extrai os dados de todos os cards dentro de
        `div.postingsList-module__postings-container` na página de listagem.

        Retorna lista de dicts com campos brutos e alguns campos normalizados:
        - url, title, price_raw, price (float or None), area_raw, area_m2 (float or None),
          bedrooms_raw, bedrooms (int or None), bathrooms_raw, bathrooms (int or None), address, description
        """
        # helpers locais de parsing
        def _parse_price(text: Optional[str]) -> Optional[float]:
            if not text:
                return None
            s = re.sub(r"[^0-9,\.]", "", text)
            if not s:
                return None
            if s.count(',') == 1 and s.count('.') > 0:
                s = s.replace('.', '').replace(',', '.')
            else:
                s = s.replace(',', '.')
            try:
                return float(s)
            except Exception:
                return None

        def _parse_int(text: Optional[str]) -> Optional[int]:
            if not text:
                return None
            m = re.search(r"(\d+)", text)
            if not m:
                return None
            try:
                return int(m.group(1))
            except Exception:
                return None

        def _parse_area(text: Optional[str]) -> Optional[float]:
            if not text:
                return None
            m = re.search(r"(\d+[\.,]?\d*)\s*(m2|m²|m)", text, flags=re.I)
            if m:
                return float(m.group(1).replace(',', '.'))
            # fallback to any number
            m2 = re.search(r"(\d+[\.,]?\d*)", text)
            if m2:
                return float(m2.group(1).replace(',', '.'))
            return None

        # tentativa de extração
        for i in range(retries):
            try:
                page = self._context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)

                try:
                    ok = self._handle_cloudflare(page)
                except Exception:
                    ok = True
                if not ok:
                    logger.warning("Cloudflare não resolvido; pulando tentativa.")
                    page.close()
                    continue

                # aguardar container principal (várias páginas usam essa classe)
                try:
                    page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                except Exception:
                    # fallback para cards individuais
                    if not self._wait_for_listings(page):
                        logger.warning("Listagens não encontradas na página: %s", url)
                        page.close()
                        continue

                # scroll para carregar lazy-load
                self._scroll_page(page)

                # extrair dados via evaluate_all para minimizar roundtrips
                script = '''(nodes => nodes.map(card => {
                    try{
                        const container = card.closest('div.postingsList-module__postings-container') || card.parentElement;
                        const title = card.querySelector('h2')?.innerText || card.querySelector('.posting-title')?.innerText || null;
                        const price = card.querySelector('.price')?.innerText || card.querySelector('.valor')?.innerText || null;
                        const area = card.querySelector('.metragem')?.innerText || card.querySelector('.area')?.innerText || null;
                        const bedrooms = card.querySelector('.quartos')?.innerText || card.querySelector('.rooms')?.innerText || null;
                        const bathrooms = card.querySelector('.banheiros')?.innerText || card.querySelector('.bathrooms')?.innerText || null;
                        const address = card.querySelector('.address')?.innerText || card.querySelector('.location')?.innerText || null;
                        const desc = card.querySelector('.description')?.innerText || null;
                        const dataHref = card.getAttribute('data-to-posting') || card.getAttribute('data-href') || null;
                        let url = null;
                        if(dataHref){
                            url = dataHref.startsWith('/') ? `${'" + DOMINIO + "'}${dataHref}` : (dataHref.startsWith('http') ? dataHref : null);
                        } else {
                            const a = card.querySelector('a'); if(a) url = a.href;
                        }
                        return {title, price, area, bedrooms, bathrooms, address, description: desc, url};
                    }catch(e){ return null }
                }))'''

                # localizar cards dentro do container
                cards = page.locator('div.postingsList-module__postings-container').locator(LISTINGS_SELECTOR)
                raw = []
                try:
                    raw = cards.evaluate_all(script)
                except Exception:
                    # fallback: avaliar diretamente em LISTINGS_SELECTOR
                    try:
                        raw = page.locator(LISTINGS_SELECTOR).evaluate_all(script)
                    except Exception as e:
                        logger.warning('Falha ao avaliar script de extração: %s', e)

                results = []
                for item in (raw or []):
                    if not item:
                        continue
                    price_raw = item.get('price')
                    area_raw = item.get('area')
                    bedrooms_raw = item.get('bedrooms')
                    bathrooms_raw = item.get('bathrooms')
                    address = item.get('address')
                    description = item.get('description')
                    title = item.get('title')
                    u = item.get('url')

                    # normalizações
                    price = _parse_price(price_raw)
                    area_m2 = _parse_area(area_raw)
                    bedrooms = _parse_int(bedrooms_raw)
                    bathrooms = _parse_int(bathrooms_raw)

                    results.append({
                        'url': u,
                        'title': title,
                        'price_raw': price_raw,
                        'price': price,
                        'area_raw': area_raw,
                        'area_m2': area_m2,
                        'bedrooms_raw': bedrooms_raw,
                        'bedrooms': bedrooms,
                        'bathrooms_raw': bathrooms_raw,
                        'bathrooms': bathrooms,
                        'address': address,
                        'description': description,
                    })

                page.close()
                return results

            except Exception as e:
                logger.warning("Erro na tentativa %d/%d para %s: %s", i + 1, retries, url, e)
                time.sleep(2 ** i)

        return []

    def _handle_cloudflare(self, page) -> bool:
        """Detecta challenge Cloudflare e tenta resolver (auto-click ou pausa para intervenção manual)."""
        try:
            content = page.content()
        except Exception:
            content = ""

        if any(s in content for s in ("Executando verificação de segurança", "Confirm", "Cloudflare", "Confirme que é humano")):
            logger.warning("Cloudflare challenge detectado na página.")
            if not self.headless:
                logger.info("Modo não-headless: aguarde resolver o challenge no navegador; pressione Enter aqui quando concluir.")
                try:
                    input("Depois de resolver o challenge, pressione Enter...")
                except Exception:
                    pass
                time.sleep(2)
                return True

            # tentativa automática em headless: procurar checkbox dentro de iframes e clicar
            try:
                for frame in page.frames:
                    try:
                        checkbox = frame.query_selector("input[type=checkbox]")
                        if checkbox:
                            checkbox.click()
                            time.sleep(3)
                            logger.info("Tentativa automática: clique em checkbox realizada.")
                            return True
                    except Exception:
                        continue
            except Exception:
                pass

            logger.warning("Falha ao resolver Cloudflare automaticamente em headless.")
            return False

        return True