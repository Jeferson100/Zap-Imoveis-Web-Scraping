import asyncio
import html
import json
import sys
import time
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))

from scraping_zap_imoveis.link_anuncios_imovelweb_playwright_sync_2 import ImovelWebScraperLinksSync2
from scraping_zap_imoveis.total_page_imovelweb import TotalPageImovelWeb
from scraping_zap_imoveis.extrair_dados_imovelweb_playwright_async import ImovelWebDadosImovelAsync, DadosImovelImovelWeb

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

URL_BASE = "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-menos-50-m2-pagina-{}.html"
URL_PAGINA_FIXA = "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-menos-50-m2-pagina-7.html"
URL_FALLBACK = "https://www.imovelweb.com.br/imoveis-venda-joinville-sc-menos-50-m2.html"


def get_links(url: str = URL_PAGINA_FIXA) -> list[str]:
    links: list[str] = []
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="pt-BR",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(5000)
        for attempt in range(3):
            title = page.title()
            if "Um momento" in title:
                print(f"[INFO] Cloudflare desafio detectado (tentativa {attempt+1}/3), aguardando 8000ms...")
                page.wait_for_timeout(8000)
            else:
                break
        try:
            page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
        except Exception as e:
            print(f"[WARN] Container não encontrado em {url}: {e}")
            print(f"[INFO] título: {page.title()}")
            print(f"[INFO] url atual: {page.url}")
            html_snip = page.content()[:2000]
            print(f"[DEBUG] html inicio: {html_snip[:800]}")
            fallbacks = [u for u in [URL_FALLBACK, URL_PAGINA_FIXA.replace("menos-50", "0-50")] if u != url]
            success = False
            for fb in fallbacks:
                try:
                    print(f"[INFO] Tentando fallback {fb}")
                    page.goto(fb, wait_until="domcontentloaded", timeout=90000)
                    page.wait_for_timeout(5000)
                    for att in range(3):
                        if "Um momento" in page.title():
                            page.wait_for_timeout(8000)
                        else:
                            break
                    page.wait_for_selector("div.postingsList-module__postings-container", timeout=30000)
                    print(f"[OK] Fallback funcionou: {fb}")
                    success = True
                    break
                except Exception as e2:
                    print(f"[WARN] Fallback {fb} também falhou: {e2}")
            if not success:
                raise
        container = page.locator("div.postingsList-module__postings-container").first
        container.wait_for(state="visible", timeout=15000)
        cards = container.locator("div.postingsList-module__card-container")
        total = cards.count()
        print(f"[INFO] Container: {total} cards")
        for i in range(total):
            card = cards.nth(i)
            try:
                layout = card.locator("div.postingCardLayout-module__posting-card-layout").first
                href = layout.get_attribute("data-to-posting")
                if not href:
                    href = card.locator('[data-qa="POSTING_CARD_DESCRIPTION"] a').first.get_attribute("href")
                if href:
                    href = html.unescape(href)
                    abs_url = href if href.startswith("http") else f"https://www.imovelweb.com.br{href}"
                    links.append(abs_url)
            except Exception as e:
                print(f"[WARN] card {i}: {e}")
        browser.close()
    seen = set()
    uniq = []
    for u in links:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq


async def main():
    logger.info("Iniciando coleta de links...")

    total_pages = 1
    try:
        tp = TotalPageImovelWeb(headless=True)
        total_pages = await tp.get_total_pages(URL_BASE.format(1))
        logger.info(f"Total de páginas: {total_pages}")
        total_pages = min(total_pages, 10)
    except Exception as e:
        logger.warning(f"Falha ao detectar total_pages, usando 10: {e}")
        total_pages = 10

    def _sync_collect_links() -> list[str]:
        todos: list[str] = []
        with ImovelWebScraperLinksSync2(headless=True) as scraper:
            for i in range(1, total_pages + 1):
                logger.info(f"Coletando links da página {i}/{total_pages}")
                url_pagina = URL_BASE.format(i)
                try:
                    links = scraper.get_links(url_pagina)
                except Exception as e:
                    logger.error(f"Erro ao coletar página {i}: {e}")
                    links = []
                logger.info(f"Página {i}: {len(links)} links")
                for u in links:
                    logger.info(u)
                todos.extend(links)
                if i < total_pages:
                    logger.info("Aguardando 3s antes da próxima página...")
                    time.sleep(3)
        return todos

    todos_links = await asyncio.to_thread(_sync_collect_links)

    juncao_links = list(dict.fromkeys(todos_links))
    logger.info(f"Total bruto: {len(todos_links)} | Único (dedup global): {len(juncao_links)}")

    out_dir = Path(__file__).resolve().parents[1] / "dados"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_txt = out_dir / "links_10_paginas.txt"
    out_json = out_dir / "links_10_paginas.json"
    try:
        out_txt.write_text("\n".join(juncao_links), encoding="utf-8")
        out_json.write_text(json.dumps(juncao_links, indent=4, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Salvo {out_txt} ({len(juncao_links)} links)")
        logger.info(f"Salvo {out_json} ({len(juncao_links)} links)")
    except Exception as e:
        logger.error(f"Erro ao salvar links: {e}")
        return

    if not juncao_links:
        logger.warning("Nenhum link coletado, encerrando antes da coleta de dados.")
        return

    logger.info("Iniciando coleta de dados...")
    dados_imoveis: list[DadosImovelImovelWeb] = []
    for idx, link in enumerate(juncao_links):
        logger.info(f"Coletando dados do imóvel {idx + 1}/{len(juncao_links)}: {link}")
        dados = None
        try:
            async with ImovelWebDadosImovelAsync(url=link, headless=True) as scraper:
                dados = await scraper.extrair()
            if dados:
                logger.info(f"Dados coletados: {dados.url} | {dados.titulo}")
        except Exception as e:
            logger.error(f"Erro ao coletar dados do imóvel {link}: {e}")
            dados = None
        if dados is not None:
            dados_imoveis.append(dados)
        logger.info("Aguardando 1s para a próxima coleta...")
        await asyncio.sleep(1)

    logger.info(f"Total de imóveis coletados: {len(dados_imoveis)}")
    if dados_imoveis:
        logger.info("Salvando dados em parquet...")
        try:
            import pandas as pd

            df = pd.DataFrame([d.to_dict() for d in dados_imoveis])
            out_parquet = out_dir / "imoveis_imovelweb.parquet"
            df.to_parquet(out_parquet, index=False, compression="snappy")
            logger.info(f"Dados salvos com sucesso em {out_parquet} ({len(df)} registros)")
        except Exception as e:
            logger.error(f"Erro ao salvar parquet: {e}")
            out_json_dados = out_dir / "imoveis_imovelweb.json"
            try:
                out_json_dados.write_text(json.dumps([d.to_dict() for d in dados_imoveis], indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info(f"Salvo JSON fallback em {out_json_dados}")
            except Exception as e2:
                logger.error(f"Erro também no JSON fallback: {e2}")


if __name__ == "__main__":
    asyncio.run(main())
