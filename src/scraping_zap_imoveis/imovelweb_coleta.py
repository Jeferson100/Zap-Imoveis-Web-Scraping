from __future__ import annotations

import asyncio
import html
import logging
import random
import re
import sys
import time
import warnings
from pathlib import Path

import pandas as pd
from tqdm.asyncio import tqdm

from .extrair_dados_imovelweb_playwright_async import DadosImovelImovelWeb, ImovelWebDadosImovelAsync
from .link_anuncios_imovelweb_playwright_sync_2 import ImovelWebScraperLinksSync2
from .total_page_imovelweb import TotalPageImovelWeb

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class ImovelWebColeta:
    def __init__(self, base_url_template, headless=True, max_concurrency=5, retries=3,
                 modo: str = 'sincrono', modo_coleta: str = 'links',
                 termos_para_ignorar_links: list = None):
        self.base_url_template = base_url_template
        self.headless = headless
        self.max_concurrency = max_concurrency
        self.lista_dados = []
        self.retries = retries
        self.termos_para_ignorar_links = termos_para_ignorar_links
        self.modo_coleta = modo_coleta

        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    async def _total_pages(self):
        try:
            tp = TotalPageImovelWeb(headless=self.headless)
            total = await tp.get_total_pages(self.base_url_template.format(pagina=1))
            logger.info(f"Total de páginas detectado automaticamente: {total}")
            return total
        except Exception as e:
            logger.error(f"Erro ao extrair total de páginas: {e}")
            return 20

    async def _coletar_links(self, total_pages: int, limite_falhas: int) -> list[str]:
        """Coleta links via versão 2 - reuso único de browser como em Notebooks/imovelweb_links_pagina.py (rápido, sem falha)."""
        def _sync_collect_all() -> list[str]:
            todos: list[str] = []
            cnt_falhas = 0
            with ImovelWebScraperLinksSync2(headless=self.headless) as scanner:
                for pagina in range(1, total_pages + 1):
                    url = self.base_url_template.format(pagina=pagina)
                    try:
                        links = scanner.get_links(url, retries=self.retries)
                    except Exception as e:
                        logger.error(f"Erro ao coletar página {pagina}: {e}")
                        links = []
                    logger.info("Página %s: %s links encontrados.", pagina, len(links))
                    if links:
                        todos.extend(links)
                        cnt_falhas = 0
                    else:
                        cnt_falhas += 1
                        logger.warning("Página %s não retornou links. Falhas consecutivas: %s", pagina, cnt_falhas)
                        if cnt_falhas >= limite_falhas:
                            logger.error("Interrompendo: %s páginas seguidas sem links.", limite_falhas)
                            break
                    if pagina < total_pages:
                        time.sleep(3)
            return todos

        todos_os_links = await asyncio.to_thread(_sync_collect_all)
        return list(dict.fromkeys(todos_os_links))

    async def _coletar_dados_diretos(self, total_pages: int, limite_falhas: int) -> list[DadosImovelImovelWeb]:
        """Coleta dados link a link como em Notebooks/imovelweb_links_pagina.py (async with correto + dados=None)."""
        links = await self._coletar_links(total_pages, limite_falhas)
        if not links:
            logger.warning("Nenhum link para extrair dados diretos.")
            return []
        todos_os_dados: list[DadosImovelImovelWeb] = []
        cnt_falhas = 0
        for idx, link in enumerate(links):
            logger.info(f"Coletando dados do imóvel {idx + 1}/{len(links)}: {link}")
            dados = None
            try:
                async with ImovelWebDadosImovelAsync(url=link, headless=self.headless) as scraper:
                    dados = await scraper.extrair()
                if dados:
                    logger.info(f"Dados coletados: {dados.url} | {dados.titulo}")
            except Exception as e:
                logger.error(f"Erro ao coletar dados do imóvel {link}: {e}")
                dados = None
            if dados is not None:
                todos_os_dados.append(dados)
                cnt_falhas = 0
            else:
                cnt_falhas += 1
                if cnt_falhas >= limite_falhas:
                    logger.error("Muitas falhas consecutivas em dados, interrompendo.")
                    break
            await asyncio.sleep(1)
        return todos_os_dados

    async def _worker_extracao(self, worker_id, fila_urls, resultados):
        while True:
            url = await fila_urls.get()
            if url is None:
                fila_urls.task_done()
                break
            dados = None
            try:
                async with ImovelWebDadosImovelAsync(url, headless=self.headless) as scraper:
                    dados = await scraper.extrair()
                if dados is not None:
                    resultados.append(dados)
            except Exception as e:
                logger.error(f"Worker {worker_id} falhou ao extrair {url}: {e}")
            finally:
                fila_urls.task_done()

    async def run(self, output_file="resultados.parquet", total_pages: int = None,
                  limite_falhas: int = 3, cooldown_seconds: int = 30,
                  modo_coleta: str = 'links'):
        if total_pages is None:
            logger.info("Total de páginas não definido. Iniciando detecção automática...")
            total_pages = await self._total_pages()

        if not total_pages:
            logger.error("Não foi possível determinar o total de páginas.")
            return

        logger.info("Iniciando coleta %s em %s páginas", modo_coleta, total_pages)

        if modo_coleta == 'dados_directos':
            todos_os_dados = await self._coletar_dados_diretos(
                total_pages=total_pages,
                limite_falhas=limite_falhas,
            )
            self.lista_dados = todos_os_dados
            self._save_to_parquet(output_file)
            logger.info(f"Execução finalizada. Total de imóveis processados: {len(self.lista_dados)}")
            return

        todos_os_links = await self._coletar_links(
            total_pages=total_pages,
            limite_falhas=limite_falhas,
        )

        todos_os_links = list(dict.fromkeys(todos_os_links))
        logger.info(f"Total de links únicos coletados: {len(todos_os_links)}")

        if self.termos_para_ignorar_links:
            len_before = len(todos_os_links)
            todos_os_links = [
                link for link in todos_os_links
                if not any(termo in link.lower() for termo in self.termos_para_ignorar_links)
            ]
            logger.info(f"Links ignorados: {len_before - len(todos_os_links)}")

        if not todos_os_links:
            logger.error("Nenhum link foi encontrado. Encerrando.")
            return

        if cooldown_seconds > 0:
            logger.info("Aguardando %s segundos antes de iniciar a extração detalhada...", cooldown_seconds)
            await asyncio.sleep(cooldown_seconds)

        fila_urls: asyncio.Queue = asyncio.Queue()
        for link in todos_os_links:
            fila_urls.put_nowait(link)
        for _ in range(self.max_concurrency):
            fila_urls.put_nowait(None)

        resultados = []
        workers = [
            asyncio.create_task(self._worker_extracao(worker_id=i + 1, fila_urls=fila_urls, resultados=resultados))
            for i in range(self.max_concurrency)
        ]
        progresso = tqdm(total=len(todos_os_links), desc="Extraindo Dados")
        ultimo_salvamento = 0

        while any(not worker.done() for worker in workers):
            restante = fila_urls.qsize() - self.max_concurrency
            processados = max(0, len(todos_os_links) - max(0, restante))
            progresso.n = processados
            progresso.refresh()
            if len(resultados) - ultimo_salvamento >= 100:
                self.lista_dados = resultados.copy()
                self._save_to_parquet(output_file)
                ultimo_salvamento = len(resultados)
            await asyncio.sleep(0.5)

        await fila_urls.join()
        await asyncio.gather(*workers, return_exceptions=True)
        progresso.n = len(todos_os_links)
        progresso.refresh()
        progresso.close()

        self.lista_dados = resultados
        self._save_to_parquet(output_file)

        logger.info(f"Execução finalizada. Total de imóveis processados: {len(self.lista_dados)}")

    def _save_to_parquet(self, filename):
        if not self.lista_dados:
            logger.warning("Nenhum dado coletado para salvar.")
            return

        if not filename.endswith('.parquet'):
            filename = filename.rsplit('.', 1)[0] + '.parquet'

        dados_dict = [d.to_dict() for d in self.lista_dados]
        df = pd.DataFrame(dados_dict)
        df.to_parquet(filename, index=False, compression='snappy')
        logger.info(f"Dados compactados salvos com sucesso em {filename}. Total: {len(df)} imóveis.")
