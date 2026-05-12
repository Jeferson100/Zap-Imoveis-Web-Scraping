import asyncio
import logging
import json
import warnings
from .extrair_dados_chave_mao_playwright_async import ChavesNaMaoScraperAsync
from .link_anuncios_chave_mao_playwright_async import ChaveMaoScraperLinksAsync
from .total_page_chaves import TotalPageChavesNaMao
from tqdm.asyncio import tqdm  # Versão assíncrona do tqdm
import random
import sys
import pandas as pd

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ChavesMaoColeta:
    def __init__(self, base_url_template, headless=True, max_concurrency=5, retries=1, item_timeout=120):
        self.base_url_template = base_url_template
        self.headless = headless
        self.max_concurrency = max_concurrency
        self.lista_dados = []
        self.retries = retries
        self.item_timeout = item_timeout
    
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    async def _total_pages(self):
        """Usa a classe TotalPageOLX para detectar o limite real de páginas"""
        try:
            url_primeira_pag = self.base_url_template.format(pagina=1)
            
            scraper_paginas = TotalPageChavesNaMao()
            total = await scraper_paginas.get_total_pages(url_primeira_pag)
            
            logger.info(f"Total de páginas detectado automaticamente: {total}")
            return total
        except Exception as e:
            logger.error(f"Erro ao extrair total de páginas: {e}")
            logger.info("Retornando total de páginas padrão: 50.")
            return 100

    async def _get_links_from_page(self, page_number):
        url = self.base_url_template.format(pagina=page_number)
        async with ChaveMaoScraperLinksAsync(headless=self.headless) as scanner:
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


    async def _get_item_data(self, url, semaphore):
        async with semaphore:
            try:
                async with ChavesNaMaoScraperAsync(headless=self.headless) as scraper:
                    return await asyncio.wait_for(
                        scraper.extrair_chave_mao(url),
                        timeout=self.item_timeout
                    )
            except asyncio.TimeoutError:
                logger.error("Timeout ao extrair %s após %ss", url, self.item_timeout)
                return None
            except Exception as e:
                logger.error(f"Erro ao extrair {url}: {e}")
                return None

    """async def run(self, output_file="resultados.json", total_pages: int = None):
    
        logger.info("Determinando o total de %s páginas ", total_pages)
        
        semaphore = asyncio.Semaphore(self.max_concurrency)

        for pagina in tqdm(range(1, total_pages + 1)):
            
            logger.info(f"--- Processando Página {pagina}/{total_pages} ---")
            
            links = await self._get_links_from_page(pagina)
            
            if not links:
                logger.warning("Página %s não retornou links, pulando.", pagina)
                continue

            tasks = [self._get_item_data(link, semaphore) for link in links]
            
            resultados_pagina = await asyncio.gather(*tasks)
            
            valid_results = [r for r in resultados_pagina if r is not None]
            
            self.lista_dados.extend(valid_results)
            
            logger.info("Página %s finalizada. %s imóveis processados.", pagina, len(valid_results))

        self._save_to_json(output_file)
    
        logger.info("Execução finalizada. Total de imóveis coletados: %s", len(self.lista_dados))
        
        return self.lista_dados"""
    
    async def run(self, output_file="resultados.json", total_pages: int = None, limite_falhas: int = 1):
        # --- ETAPA 1: DETERMINAR PÁGINAS ---
        if total_pages is None:
            logger.info("Total de páginas não definido. Iniciando detecção automática...")
            total_pages = await self._total_pages()
            
        if not total_pages:
            logger.error("Não foi possível determinar o total de páginas.")
            return
        
        logger.info("Iniciando coleta de links em %s páginas", total_pages)
        
        logger.info("Parametros recebidos: total_pages=%s, limite_falhas=%s, max_concurrency=%s, self.retries=%s", total_pages, limite_falhas, self.max_concurrency, self.retries)

        todos_os_links = []
        # --- Lógica de Interrupção ---
        contador_falhas = 0

        # --- ETAPA 2: COLETAR APENAS OS LINKS ---
        """for pagina in tqdm(range(1, total_pages + 1), desc="Coletando Links"):
            logger.info(f"--- Obtendo links da Página {pagina}/{total_pages} ---")
            
            links = await self._get_links_from_page(pagina)
            
            if links:
                todos_os_links.extend(links)
                logger.info(f"Página {pagina}: {len(links)} links encontrados.")
                contador_falhas = 0  # Reseta o contador porque encontrou dados
            else:
                contador_falhas += 1
                logger.warning(f"Página {pagina} não retornou links. Falhas consecutivas: {contador_falhas}")

            # Verifica se deve parar a coleta de links
            if contador_falhas >= limite_falhas:
                logger.error(f"Interrompendo: {limite_falhas} páginas seguidas sem links. Iniciando extração do que foi coletado.")
                break
            
            # Pequeno delay aleatório para não ser bloqueado na listagem
            await asyncio.sleep(random.uniform(1.5, 4))"""
            
        todos_os_links = await self._coletar_links_em_lotes(
            total_pages=total_pages,
            limite_falhas=limite_falhas,
            concorrencia_paginas=self.max_concurrency,
        )

        # Remove duplicatas de links
        todos_os_links = list(set(todos_os_links))
        logger.info(f"Total de links únicos coletados: {len(todos_os_links)}")

        if not todos_os_links:
            logger.error("Nenhum link foi encontrado. Encerrando.")
            return

        logger.info("Aguardando 30 segundos antes de iniciar a extração detalhada...")
        
        await asyncio.sleep(30)

        # --- ETAPA 4: EXTRAIR DADOS DE CADA LINK ---
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        logger.info(f"Iniciando extração de dados de {len(todos_os_links)} imóveis...")
        
        resultados = []
        
        lote_size = max(self.max_concurrency * 10, self.max_concurrency)
        
        logger.info(f"Processando em lotes de {lote_size} para otimizar a extração com concorrência de {self.max_concurrency}.")

        for inicio in tqdm(range(0, len(todos_os_links), lote_size), desc="Processando Lotes"):
            lote = todos_os_links[inicio:inicio + lote_size]
            logger.info(
                "Processando lote %s-%s de %s links",
                inicio + 1,
                min(inicio + lote_size, len(todos_os_links)),
                len(todos_os_links),
            )

            tasks = [self._get_item_data(link, semaphore) for link in lote]

            #for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Extraindo Dados"):
            for f in asyncio.as_completed(tasks):
                res = await f
                if res:
                    resultados.append(res)
                    # Salvar parcial para segurança
                    if len(resultados) % 100 == 0:
                        self.lista_dados = resultados
                        self._save_to_parquet(output_file)
            
            #logger.info(f"Lote {inicio + 1}-{min(inicio + lote_size, len(todos_os_links))} finalizado. Total de imóveis processados até agora: {len(resultados)}")

        self.lista_dados = resultados
        self._save_to_parquet(output_file)

        logger.info(f"Execução finalizada. Total de imóveis processados: {len(self.lista_dados)}")
        return self.lista_dados


    def _save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump([d.to_dict() for d in self.lista_dados], f, indent=4, ensure_ascii=False)
        logger.info(f"Dados salvos em {filename}")

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
        #dados_dict = [d.to_dict() for d in self.lista_dados]

        dados_dict = [d.to_dict() if hasattr(d, "to_dict") else d for d in self.lista_dados]
        
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
    URL_TEMPLATE = "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg={pagina}"

    # Instancia o orquestrador
    orchestrator = ChavesMaoColeta(URL_TEMPLATE, headless=True, max_concurrency=5)
    
    # Roda o loop de eventos
    try:
        resultado = asyncio.run(orchestrator.run(total_pages=1))
        print(f"\n--- Coleta Finalizada! ---")
        print(f"Total processado: {len(resultado)} imóveis em Joinville.")
    except KeyboardInterrupt:
        logger.info("Processo interrompido pelo usuário.")