import asyncio
import time
import logging
import json
import sys
from .extrair_dados_zap_imoveis_playwright_async import ZapScraperDadosImovelAsync
from .total_pagina_zap_imovel_playwright_async import ZapScraperTotalPaginaAsync
from .link_anuncios_zap_imoveis_playwright_async import ZapScraperLinksAsync
from tqdm import tqdm
import warnings
import random

warnings.filterwarnings("ignore")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

logger = logging.getLogger(__name__)

class ZapImoveisColeta:
    def __init__(self, base_url_template, headless=True, max_concurrency=5, retries=1, max_concurrency_links=1):
        self.base_url_template = base_url_template
        self.headless = headless
        self.max_concurrency = max_concurrency
        self.max_concurrency_links = max_concurrency_links
        self.retries = retries
        self.lista_dados = []
    
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    async def _get_total_pages(self):
        url_inicial = self.base_url_template.format(pagina=1)
        logger.info(f"Obtendo total de páginas para: {url_inicial}")
        async with ZapScraperTotalPaginaAsync(headless=self.headless) as scanner:
            return await scanner.get_total_pages(url_inicial)

    async def _get_links_from_page(self, page_number):
        url = self.base_url_template.format(pagina=page_number)
        async with ZapScraperLinksAsync(headless=self.headless) as scanner:
            links = await scanner.get_links(url, retries= self.retries)
            logger.info(f"Página {page_number}: {len(links)} links encontrados.")
            return links
    
    async def _get_links_from_page_smartphone(self, page_number, semaphore):
        """
        Obtém links de uma página de listagem usando concorrência controlada
        e emulação de smartphone.
        """
        async with semaphore:
            url = self.base_url_template.format(pagina=page_number)
            
            # Certifique-se de que o ZapScraperLinksAsync suporte 
            # ou já esteja configurado para modo mobile internamente.
            async with ZapScraperLinksAsync(headless=self.headless) as scanner:
                logger.info(f"Acessando listagem (Mobile Mode) - Página {page_number}")
                
                links = await scanner.get_links(url, retries=self.retries)
                
                logger.info(f"Página {page_number}: {len(links)} links encontrados.")
                
                # Pequeno delay dentro do semáforo para evitar picos de tráfego
                await asyncio.sleep(random.uniform(1.5, 3))
                
                return links

    async def _get_item_data(self, url, semaphore):
        async with semaphore:
            try:
                async with ZapScraperDadosImovelAsync(url, headless=self.headless) as scraper:
                    return await scraper.extrair()
            except Exception as e:
                logger.error(f"Erro ao extrair {url}: {e}")
                return None

    """async def run(self, output_file="resultados.json", total_pages: int = None):
        
        if total_pages is not None:
            total_paginas = total_pages
        else:
            total_paginas = await self._get_total_pages()
            
        if not total_paginas:
            logger.error("Não foi possível determinar o total de páginas.")
            return
        
        logger.info("Determinando o total de %s páginas ", total_paginas)
        
        semaphore = asyncio.Semaphore(self.max_concurrency)

        for pagina in tqdm(range(1, total_paginas + 1)):
            
            logger.info(f"--- Processando Página {pagina}/{total_paginas} ---")
            
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
        
        return self.lista_dados """
        
    
    """async def run(self, output_file="resultados.json", total_pages: int = None):
        # --- ETAPA 1: DETERMINAR PÁGINAS ---
        if total_pages is None:
            total_pages = 5
            
        if not total_pages:
            logger.error("Não foi possível determinar o total de páginas.")
            return
        
        logger.info("Iniciando coleta de links em %s páginas", total_pages)
        
        todos_os_links = []

        # --- ETAPA 2: COLETAR APENAS OS LINKS ---
        for pagina in tqdm(range(1, total_pages + 1), desc="Coletando Links"):
            logger.info(f"--- Obtendo links da Página {pagina}/{total_pages} ---")
            
            links = await self._get_links_from_page(pagina)
            
            if links:
                todos_os_links.extend(links)
                logger.info(f"Página {pagina}: {len(links)} links encontrados.")
            else:
                logger.warning(f"Página {pagina} não retornou links.")
            
            # Pequeno delay aleatório para não ser bloqueado na listagem
            await asyncio.sleep(random.uniform(1, 3))

        # Remove duplicatas de links (comum no Zap/VivaReal)
        todos_os_links = list(set(todos_os_links))
        logger.info(f"Total de links únicos coletados: {len(todos_os_links)}")

        if not todos_os_links:
            logger.error("Nenhum link foi encontrado. Encerrando.")
            return

        # --- ETAPA 3: PAUSA DE RESPIRO PARA O IP ---
        logger.info("Aguardando 30 segundos antes de iniciar a extração detalhada...")
        await asyncio.sleep(30)

        # --- ETAPA 4: EXTRAIR DADOS DE CADA LINK ---
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        # Criamos as tasks para todos os links coletados
        tasks = [self._get_item_data(link, semaphore) for link in todos_os_links]
        
        logger.info(f"Iniciando extração de dados de {len(todos_os_links)} imóveis...")
        
        # Usamos tqdm aqui também para ver o progresso da extração detalhada
        resultados = []
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Extraindo Dados"):
            res = await f
            if res:
                resultados.append(res)
                # Opcional: Salvar a cada 50 itens para não perder nada se o PC suspender
                if len(resultados) % 50 == 0:
                    self.lista_dados = resultados
                    self._save_to_json(output_file)

        self.lista_dados = resultados
        self._save_to_json(output_file)

        logger.info(f"Execução finalizada. Total de imóveis processados: {len(self.lista_dados)}")
        return self.lista_dados
    """
    
    async def run(self, output_file="resultados.json", total_pages: int = None, limite_falhas: int = 3):
        # --- ETAPA 1: DETERMINAR PÁGINAS ---
        if total_pages is None:
            total_pages = 5
            
        if not total_pages:
            logger.error("Não foi possível determinar o total de páginas.")
            return
        
        logger.info("Iniciando coleta de links em %s páginas", total_pages)
        
        logger.info("Parametros recebidos: total_pages=%s, limite_falhas=%s, max_concurrency=%s, self.retries=%s", total_pages, limite_falhas, self.max_concurrency, self.retries)
        
        todos_os_links = []
        # --- Lógica de Interrupção ---
        contador_falhas = 0

        # --- ETAPA 2: COLETAR APENAS OS LINKS ---
        for pagina in tqdm(range(1, total_pages + 1), desc="Coletando Links"):
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
            await asyncio.sleep(random.uniform(1.5, 4))

        # Remove duplicatas de links
        todos_os_links = list(set(todos_os_links))
        logger.info(f"Total de links únicos coletados: {len(todos_os_links)}")

        if not todos_os_links:
            logger.error("Nenhum link foi encontrado. Encerrando.")
            return

        # --- ETAPA 3: PAUSA DE RESPIRO PARA O IP ---
        # Se o scraper já está falhando páginas, essa pausa é obrigatória
        logger.info("Aguardando 30 segundos antes de iniciar a extração detalhada...")
        await asyncio.sleep(30)

        # --- ETAPA 4: EXTRAIR DADOS DE CADA LINK ---
        semaphore = asyncio.Semaphore(self.max_concurrency)
        tasks = [self._get_item_data(link, semaphore) for link in todos_os_links]
        
        logger.info(f"Iniciando extração de dados de {len(todos_os_links)} imóveis...")
        
        resultados = []
        for f in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Extraindo Dados"):
            res = await f
            if res:
                resultados.append(res)
                # Salvar parcial para segurança
                if len(resultados) % 50 == 0:
                    self.lista_dados = resultados
                    self._save_to_json(output_file)

        self.lista_dados = resultados
        self._save_to_json(output_file)

        logger.info(f"Execução finalizada. Total de imóveis processados: {len(self.lista_dados)}")
        return self.lista_dados


    def _save_to_json(self, filename):
        with open(filename, "w", encoding="utf-8") as f:
            json.dump([d.to_dict() for d in self.lista_dados], f, indent=4, ensure_ascii=False)
        logger.info(f"Dados salvos em {filename}")

if __name__ == "__main__":

    URL_TEMPLATE = "https://www.zapimoveis.com.br/venda/imoveis/sc+joinville/?transacao=venda&onde=%2CSanta+Catarina%2CJoinville%2C%2C%2C%2C%2Ccity%2CBR%3ESanta+Catarina%3ENULL%3EJoinville%2C-26.304376%2C-48.846374%2C&page={pagina}"

    orchestrator = ZapImoveisColeta(URL_TEMPLATE, headless=True, max_concurrency=3)
    
    asyncio.run(orchestrator.run())