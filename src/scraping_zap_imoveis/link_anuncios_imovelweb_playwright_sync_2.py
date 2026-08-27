import html
import logging
import random
import re
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

try:
    from playwright_stealth import Stealth
except Exception:
    Stealth = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DOMINIO = "https://www.imovelweb.com.br"
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
]

ANTI_DETECT_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
"""


class ImovelWebScraperLinksSync2:
    def __init__(self, headless: bool = True, proxy: Optional[dict] = None):
        self.headless = headless
        self.proxy = proxy
        self._pw_cm = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._user_agent = random.choice(USER_AGENTS)

    def __enter__(self):
        if Stealth:
            pw = sync_playwright()
            self._pw_cm = Stealth().use_sync(pw)
        else:
            pw = sync_playwright()
            self._pw_cm = pw
        self._playwright = self._pw_cm.__enter__()
        self._browser = self._playwright.chromium.launch(headless=self.headless, args=["--disable-blink-features=AutomationControlled"])
        ctx_kwargs = dict(
            viewport={"width": random.randint(1850, 1980), "height": random.randint(1020, 1120)},
            user_agent=self._user_agent,
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        if self.proxy:
            ctx_kwargs["proxy"] = self.proxy
        self._context = self._browser.new_context(**ctx_kwargs)
        try:
            self._context.add_init_script(ANTI_DETECT_JS)
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._pw_cm:
                self._pw_cm.__exit__(exc_type, exc_val, exc_tb)
        except Exception as e:
            logger.error("Erro ao fechar: %s", e)

    def get_links(self, url: str, retries: int = 3) -> list[str]:
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
                    page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                except Exception as e:
                    logger.warning("Container não encontrado em %s: %s", url, e)
                    if "pagina-" in url:
                        fb = re.sub(r"pagina-\d+\.html", "", url).rstrip("/") + ".html"
                        alt_fbs = [f for f in [fb, "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-menos-50-m2.html", "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-0-50-m2.html"] if f != url]
                        success = False
                        for alt in alt_fbs:
                            try:
                                logger.info("Tentando fallback %s", alt)
                                page.goto(alt, wait_until="domcontentloaded", timeout=90000)
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
                                logger.info("Fallback funcionou: %s", alt)
                                success = True
                                break
                            except Exception as e2:
                                logger.warning("Fallback %s também falhou: %s", alt, e2)
                        if not success:
                            page.close()
                            continue
                    else:
                        page.close()
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
                logger.warning("Tentativa %d/%d: nenhum link em %s", attempt + 1, retries, url)
            except Exception as e:
                logger.warning("Erro na tentativa %d/%d para %s: %s", attempt + 1, retries, url, e)
                if page is not None:
                    try:
                        page.close()
                    except Exception:
                        pass
                time.sleep(2 ** attempt)
        return []
