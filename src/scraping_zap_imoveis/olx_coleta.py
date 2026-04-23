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

    async def _get_item_data(self, url, semaphore):
        async with semaphore:
            try:
                async with OLXScraperAsync(headless=True) as scraper:
                    return await scraper.extrair_anuncio(url)
            except Exception as e:
                logger.error(f"Erro ao extrair {url}: {e}")
                return None
    
            
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
                if len(resultados) % 100 == 0:
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