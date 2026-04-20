from pathlib import Path
import pandas as pd
import asyncio
from funcoes_limpando_dados_imoveis import main_example, fetch_osm_data_async, calculate_surroundings_index_v3_async
from tqdm import tqdm
import time
import logging
import warnings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

start_time = time.time()

def criando_indice_cidades_2(pd_data, max_concurrent):

    primeira_index = 0

    segundo_index = 20

    pulando = 20

    resultado = []

    #pd_data = pd_data.head(100)

    for j in tqdm(range(round(pd_data.shape[0]/pulando) +1)):

        pd_100 = pd_data.iloc[primeira_index:segundo_index, :]

        location = [{"name": i['rua'] + " - " + i['bairro'], "lat": i['lat'], "lng": i['lng']} for i in pd_100.to_dict('records')]
        
        response = asyncio.run(main_example(location, max_concurrent=max_concurrent))
        
        df_results = pd.DataFrame(response)
        
        df_results['url'] = pd_100['url']
        
        df_results['index'] = pd_100.index
        
        if not df_results.dropna(how='all').empty:
            colunas_alvo = ['name', 'score', 'url', 'index']
            resultado.append(df_results[colunas_alvo])
        
        #resultado.append(df_results[['name', 'score', 'url', 'index']])
        
        primeira_index += pulando
        segundo_index += pulando

    resultado_final = pd.concat(resultado, ignore_index=True)

    end_final = time.time()

    logger.info(f"Tempo de execução: {end_final - start_time}")

    pd_data['score'] = resultado_final['score'].values
    
    return pd_data

async def criando_indice_cidades_async(pd_data: pd.DataFrame, max_concurrent: int = 5, batch_size: int = 20) -> pd.DataFrame:
    """
    Calcula o índice de entorno para cada imóvel no dataframe de forma assíncrona.
    
    Args:
        pd_data:        DataFrame com colunas 'rua', 'bairro', 'lat', 'lng', 'url'
        max_concurrent: Máximo de requisições OSM simultâneas
        batch_size:     Quantidade de imóveis por batch
    
    Returns:
        DataFrame original com coluna 'score' adicionada
    """
    df = pd_data.copy()
    df['score'] = None

    batches = [df.iloc[i:i+batch_size] for i in range(0, len(df), batch_size)]

    # ✅ Semáforo controla quantas requisições rodam ao mesmo tempo
    semaforo = asyncio.Semaphore(max_concurrent)

    start_time = time.time()
    erros = 0
    com_score = 0

    async def processar_imovel(row):
        nonlocal erros, com_score

        async with semaforo:
            try:
                lat  = row['lat']
                lng  = row['lng']
                nome = f"{row['rua']} - {row['bairro']}"

                gdf = await asyncio.wait_for(
                    fetch_osm_data_async(lat, lng, radius=1000),
                    timeout=30
                )

                if gdf is None or gdf.empty:
                    logger.warning(f"⚠️ Sem dados OSM para: {nome}")
                    return row.name, None

                score, breakdown = await asyncio.wait_for(
                    calculate_surroundings_index_v3_async(gdf, lat, lng),
                    timeout=30
                )

                com_score += 1
                logger.info(f"✅ {nome} → score: {score}")
                return row.name, score

            except asyncio.TimeoutError:
                logger.warning(f"⏱️ Timeout em {row.name}")
                erros += 1
                return row.name, None

            except Exception as e:
                logger.error(f"❌ Erro em {row.name}: {e}")
                erros += 1
                return row.name, None

            finally:
                # ✅ Pausa entre requisições para não sobrecarregar o OSM
                await asyncio.sleep(1.5)

    for i, batch in enumerate(tqdm(batches, desc="Calculando índice de entorno")):

        batch_valido = batch.dropna(subset=['lat', 'lng'])
        if batch_valido.empty:
            logger.warning(f"Batch {i} sem coordenadas válidas — pulando")
            continue

        # ✅ Processa o batch inteiro em paralelo respeitando o semáforo
        tasks = [processar_imovel(row) for _, row in batch_valido.iterrows()]
        resultados = await asyncio.gather(*tasks, return_exceptions=False)

        for idx, score in resultados:
            if score is not None:
                df.loc[idx, 'score'] = score

        # ✅ Pausa entre batches
        logger.info(f"⏸️ Pausa entre batches...")
        await asyncio.sleep(5)

    elapsed = time.time() - start_time
    total   = len(df)
    logger.info(f"Concluído em {elapsed:.1f}s | {com_score}/{total} com score | {erros} erros")

    return df

def criando_indice_cidades(pd_data, max_concurrent):
    start_time = time.time()
    logger.info(f"Iniciando cálculo de índice para {len(pd_data)} imóveis...")

    # 1. Prepara todos os dados de uma vez (sem loops manuais)
    # Criamos a lista de dicionários que o main_example espera
    locations = [
        {"name": f"{row['rua']} - {row['bairro']}", "lat": row['lat'], "lng": row['lng']} 
        for _, row in pd_data.iterrows()
    ]

    # 2. Roda TUDO em um único loop de eventos
    # O semáforo dentro do main_example vai controlar para não travar o OSM
    response = asyncio.run(main_example(locations, max_concurrent=max_concurrent))

    # 3. Processa os resultados
    df_results = pd.DataFrame(response)
    
    # Garante que os índices batam (caso haja falhas no OSM)
    # Se main_example retornar na mesma ordem, podemos apenas atribuir
    if len(df_results) == len(pd_data):
        pd_data['score'] = df_results['score'].values
        # Se quiser o breakdown (detalhes por categoria), pode salvar também:
        # pd_data['breakdown'] = df_results['breakdown'].values
    else:
        logger.warning("Diferença no número de resultados retornados. Verifique falhas nas tasks.")

    end_final = time.time()
    logger.info(f"Tempo de execução total: {end_final - start_time:.2f} segundos")
    
    return pd_data