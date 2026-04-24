import asyncio
import logging
import json
import warnings
from .extrair_dados_olx_playwright_async import OLXScraperAsync
from .link_anuncios_olx_playwright_async import OLXScraperLinksAsync
from tqdm.asyncio import tqdm  # Versão assíncrona do tqdm
import sys
import random
import pandas as pd

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class OLXColeta:
    def __init__(self, base_url_template, headless=True, max_concurrency=5, retries=1, termos_para_ignorar_links: list = None):
        self.base_url_template = base_url_template
        self.headless = headless
        self.max_concurrency = max_concurrency
        self.lista_dados = []
        self.retries = retries
        self.termos_para_ignorar_links = termos_para_ignorar_links
    
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    async def _get_links_from_page(self, page_number):
        url = self.base_url_template.format(pagina=page_number)
        async with OLXScraperLinksAsync(headless=self.headless) as scanner:
            links = await scanner.get_links(url, retries= self.retries)
            logger.info(f"Página {page_number}: {len(links)} links encontrados.")
            return links

    async def _coletar_links_em_lotes(self, total_pages: int, limite_falhas: int, concorrencia_paginas: int):
        todos_os_links = []
        contador_falhas = 0
        pagina_atual = 1

        while pagina_atual <= total_pages:
            paginas_lote = list(range(pagina_atual, min(pagina_atual + concorrencia_paginas, total_pages + 1)))
            tarefas = [self._get_links_from_page(pagina) for pagina in paginas_lote]
            resultados_lote = await asyncio.gather(*tarefas, return_exceptions=True)

            for pagina, links in zip(paginas_lote, resultados_lote):
                if isinstance(links, Exception):
                    logger.warning(f"Página {pagina} falhou com exceção: {links}")
                    links = []

                if links:
                    todos_os_links.extend(links)
                    contador_falhas = 0
                else:
                    contador_falhas += 1
                    logger.warning(f"Página {pagina} não retornou links. Falhas consecutivas: {contador_falhas}")

                if contador_falhas >= limite_falhas:
                    logger.error(f"Interrompendo: {limite_falhas} páginas seguidas sem links.")
                    return todos_os_links

            pagina_atual += concorrencia_paginas
            await asyncio.sleep(random.uniform(0.2, 1.0))

        return todos_os_links

    async def _worker_extracao(self, worker_id: int, fila_urls: asyncio.Queue, resultados: list):
        async with OLXScraperAsync(headless=self.headless) as scraper:
            while True:
                url = await fila_urls.get()
                if url is None:
                    fila_urls.task_done()
                    break

                try:
                    dado = await scraper.extrair_anuncio(url)
                    if dado:
                        resultados.append(dado)
                except Exception as e:
                    logger.error(f"Worker {worker_id} falhou ao extrair {url}: {e}")
                finally:
                    fila_urls.task_done()
    
            
    async def run(
        self,
        output_file="resultados.json",
        total_pages: int = None,
        limite_falhas: int = 3,
        concorrencia_paginas: int = 3,
        cooldown_seconds: int = 0,
    ):
        # --- ETAPA 1: DETERMINAR PÁGINAS ---
        if total_pages is None:
            total_pages = 5
            
        if not total_pages:
            logger.error("Não foi possível determinar o total de páginas.")
            return
        
        logger.info("Iniciando coleta de links em %s páginas", total_pages)
        
        logger.info("Parametros recebidos: total_pages=%s, limite_falhas=%s, max_concurrency=%s, self.retries=%s", total_pages, limite_falhas, self.max_concurrency, self.retries)

        todos_os_links = await self._coletar_links_em_lotes(
            total_pages=total_pages,
            limite_falhas=limite_falhas,
            concorrencia_paginas=concorrencia_paginas,
        )

        # Remove duplicatas de links
        todos_os_links = list(set(todos_os_links))
        logger.info(f"Total de links únicos coletados: {len(todos_os_links)}")
        
        if self.termos_para_ignorar_links:
            logger.info(f"Ignorando links contendo os termos: {self.termos_para_ignorar_links}")
            len_before = len(todos_os_links)
            todos_os_links = [
                link for link in todos_os_links
                if not any(termo in link.lower() for termo in self.termos_para_ignorar_links)
            ]
            len_after = len(todos_os_links)
            logger.info(f"Links ignorados: {len_before - len_after}")

        if not todos_os_links:
            logger.error("Nenhum link foi encontrado. Encerrando.")
            return

        # --- ETAPA 3: PAUSA DE RESPIRO PARA O IP ---
        if cooldown_seconds > 0:
            logger.info("Aguardando %s segundos antes de iniciar a extração detalhada...", cooldown_seconds)
            await asyncio.sleep(cooldown_seconds)

        # --- ETAPA 4: EXTRAIR DADOS DE CADA LINK ---
        logger.info(f"Iniciando extração de dados de {len(todos_os_links)} imóveis...")

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
                self._save_to_json(output_file)
                ultimo_salvamento = len(resultados)
            await asyncio.sleep(0.5)

        await fila_urls.join()
        await asyncio.gather(*workers, return_exceptions=True)
        progresso.n = len(todos_os_links)
        progresso.refresh()
        progresso.close()

        self.lista_dados = resultados
        
        self._save_to_json(output_file)

        logger.info(f"Execução finalizada. Total de imóveis processados: {len(self.lista_dados)}")
        return self.lista_dados
     

    def _save_to_json(self, filename):
        if not self.lista_dados:
            logger.warning("Nenhum dado coletado para salvar.")
            return

        with open(filename, "w", encoding="utf-8") as f:
            # Garante que salve como lista de dicts
            data_to_save = [d.to_dict() if hasattr(d, 'to_dict') else d for d in self.lista_dados]
            json.dump(data_to_save, f, indent=4, ensure_ascii=False)
        logger.info(f"Dados salvos em {filename}. Total: {len(self.lista_dados)} imóveis.")
    
    def _save_to_parquet(self, filename):
        # 1. Converte a lista de objetos para uma lista de dicionários
        dados_dict = [d.to_dict() for d in self.lista_dados]
        
        if not dados_dict:
            logger.warning("Nenhum dado para salvar.")
            return

        # 2. Cria um DataFrame do Pandas
        df = pd.DataFrame(dados_dict)
        
        # 3. Garante que o nome do arquivo termine em .parquet
        if not filename.endswith('.parquet'):
            filename = filename.rsplit('.', 1)[0] + '.parquet'

        # 4. Salva em Parquet com compressão snappy (equilíbrio entre velocidade e tamanho)
        df.to_parquet(filename, index=False, compression='snappy')
        
        logger.info(f"Dados compactados salvos com sucesso em {filename}")

if __name__ == "__main__":
    URL_TEMPLATE = "https://www.olx.com.br/imoveis/venda/estado-sc/norte-de-santa-catarina/joinville?q=casa&o={pagina}"

    # Instancia o orquestrador
    orchestrator = OLXColeta(URL_TEMPLATE, headless=True, max_concurrency=5)
    
    # Roda o loop de eventos
    try:
        resultado = asyncio.run(orchestrator.run(total_pages=5))
        print(f"\n--- Coleta Finalizada! ---")
        print(f"Total processado: {len(resultado)} imóveis em Joinville.")
    except KeyboardInterrupt:
        logger.info("Processo interrompido pelo usuário.")