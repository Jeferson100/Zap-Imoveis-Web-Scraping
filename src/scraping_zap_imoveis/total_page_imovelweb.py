import asyncio
import logging
import math
import random
import re
import warnings

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


class TotalPageImovelWeb:
    def __init__(self, headless=True):
        self.headless = headless
        self._user_agent = random.choice(USER_AGENTS)

    async def get_total_pages(self, url: str, imoveis_por_pagina: int = 30) -> int:
        if Stealth:
            pw_cm = Stealth().use_async(async_playwright())
        else:
            pw_cm = async_playwright()
        async with pw_cm as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']
            )
            viewport_w = random.randint(1850, 1980)
            viewport_h = random.randint(1020, 1120)
            context = await browser.new_context(
                viewport={"width": viewport_w, "height": viewport_h},
                user_agent=self._user_agent,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                device_scale_factor=random.choice([1, 1.25, 1.5, 2]),
                has_touch=False,
            )
            page = await context.new_page()
            await page.add_init_script(ANTI_DETECT_JS)

            try:
                logger.info(f"Acessando ImovelWeb para calcular páginas: {url[:60]}...")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await asyncio.sleep(random.uniform(2, 4))

                total_pages = await page.evaluate(
                    """
                    () => {
                        const s = window.__PRELOADED_STATE__;
                        try {
                            const p = s.listStore.paging;
                            return p.totalPages || Math.ceil(p.totalItems / 30) || null;
                        } catch (e) { return null; }
                    }
                    """
                )
                if not total_pages:
                    try:
                        texto = await page.locator('h1.postingsTitle-module__title').inner_text(timeout=10000)
                        numeros = re.findall(r'\d+', texto.replace('.', '').replace(',', ''))
                        if numeros:
                            total_pages = math.ceil(int(numeros[0]) / imoveis_por_pagina)
                    except Exception:
                        pass

                total_pages = int(total_pages) if total_pages else 50
                logger.info(f"Detectado: {total_pages} páginas.")
                return min(total_pages, 200)

            except Exception as e:
                logger.error(f"Erro ao capturar total de páginas: {e}")
                return 50
            finally:
                await browser.close()