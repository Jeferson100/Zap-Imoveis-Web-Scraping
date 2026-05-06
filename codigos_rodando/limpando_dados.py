import pandas as pd
import warnings
import logging
import asyncio
from funcoes_limpando_dados_imoveis import (limpar_valor_iptu,
                                            limpar_banheiros, 
                                            limpar_metragem, 
                                            limpar_vagas,  
                                            #limpa_endereco_apply, 
                                            limpar_valor_condominio, 
                                            converter_para_data, 
                                            classificar_tipo_imovel, 
                                            reclassificar_outros, 
                                            preencher_todas_coordenadas,
                                            main_example, 
                                            limpar_valor_venda, 
                                            limpar_quartos, 
                                            pirabeiraba_dona_francisca, 
                                            geocodificar_dataframe,
                                            limpa_endereco_apply_zap, 
                                            limpa_endereco_apply_chave_mao, 
                                            limpa_endereco_apply_olx,)
import time
from datetime import datetime
import json
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

start_time = time.time()

async def limpando_dados_cidades(pd_data, batch, cidade_limpeza = 'joinville', estado_limpeza = 'sc', cidade_localizacao = 'Joinville', estado_localizacao = 'SC',  tipo_async=True,  pais='Brasil'): 
       
    logger.info("Iniciando o processo de limpeza de dados de imóveis...")    
    
    pd_data = pd_data.drop_duplicates(subset=['url'])

    pd_data = pd_data[pd_data['valor_imovel'].notna()]

    pd_data_sem_nulos = pd_data.dropna(thresh=10)

    logger.info(f"Removendo linhas com muitos valores faltantes. Registros restantes: {pd_data_sem_nulos.shape}")

    #endereco_dividido = pd_data_sem_nulos['endereco'].apply(limpa_endereco_apply)

    #pd_data_endereco_dividido = pd.concat([pd_data_sem_nulos, endereco_dividido], axis=1).drop('endereco', axis=1)

    #pd_data_endereco_dividido['bairro'] = pd_data_endereco_dividido['bairro'].apply(pirabeiraba_dona_francisca)

    #logger.info("Coluna 'endereco' dividida em 'rua', 'bairro', 'cidade' e 'estado'...")
    
    pd_data_estado = pd_data_sem_nulos.copy()

    pd_data_estado = pd_data_estado[pd_data_estado['estado'] == estado_limpeza]

    logger.info(f"Removendo linhas com estado diferente de {estado_limpeza}. Registros restantes: {pd_data_estado.shape}")

    pd_data_metragem = pd_data_estado.copy()

    pd_data_metragem['metragem'] = pd_data_metragem['metragem'].apply(limpar_metragem)

    logger.info(f"Coluna 'metragem' limpa. Registros restantes: {pd_data_metragem.shape}")

    pd_data_valor_imovel = pd_data_metragem.copy()

    try:
        pd_data_valor_imovel['valor_venda'] = pd_data_valor_imovel['valor_venda'].apply(limpar_valor_venda)
    except:
        pd_data_valor_imovel['valor_imovel'] = pd_data_valor_imovel['valor_imovel'].apply(limpar_valor_venda)


    logger.info(f"Coluna 'valor_venda' limpa. Registros restantes: {pd_data_valor_imovel.shape}")

    pd_data_valor_condominio = pd_data_valor_imovel.copy()

    pd_data_valor_condominio['condominio'] = pd_data_valor_condominio['condominio'].apply(limpar_valor_condominio)

    logger.info(f"Coluna 'condominio' limpa. Registros restantes: {pd_data_valor_condominio.shape}")

    pd_data_valor_iptu = pd_data_valor_condominio.copy()

    pd_data_valor_iptu['iptu'] = pd_data_valor_iptu['iptu'].apply(limpar_valor_iptu)
    

    logger.info(f"Coluna 'iptu' limpa. Registros restantes: {pd_data_valor_iptu.shape}")

    pd_data_ano_publicacao = pd_data_valor_iptu.copy()

    pd_data_ano_publicacao['data_criacao'] = pd_data_ano_publicacao['data_criacao'].apply(converter_para_data)

    pd_data_ano_publicacao['dias_publicacao'] = (pd.to_datetime(datetime.now().strftime('%Y-%m-%d')) - pd.to_datetime(pd_data_ano_publicacao['data_criacao'], format='%d/%m/%Y')).dt.days
    
    logger.info(f"Coluna 'data_criacao' limpa. Registros restantes: {pd_data_ano_publicacao.shape}")

    pd_data_banheiros = pd_data_ano_publicacao.copy()
    
    pd_data_banheiros['banheiros'] = pd_data_banheiros['banheiros'].apply(limpar_banheiros)

    logger.info(f"Coluna 'banheiros' limpa. Registros restantes: {pd_data_banheiros.shape}")

    pd_data_quartos = pd_data_banheiros.copy()

    pd_data_quartos['quartos'] = pd_data_quartos['quartos'].apply(limpar_quartos)

    logger.info(f"Coluna 'quartos' limpa. Registros restantes: {pd_data_quartos.shape}")

    pd_data_garagem = pd_data_quartos.copy()

    #pd_data_garagem['vagas'] = pd_data_garagem['vagas'].replace('--', 0).astype('int64')

    pd_data_garagem['vagas'] = pd_data_garagem['vagas'].apply(limpar_vagas)

    logger.info(f"Coluna 'vagas' limpa. Registros restantes: {pd_data_garagem.shape}")

    pd_data_tipo_imovel = pd_data_garagem.copy()

    pd_data_tipo_imovel['tipo_imovel'] = pd_data_tipo_imovel['titulo'].apply(classificar_tipo_imovel)

    mask = pd_data_tipo_imovel['tipo_imovel'] == 'outros'

    pd_data_tipo_imovel.loc[mask, 'tipo_imovel'] = (
        pd_data_tipo_imovel.loc[mask, 'descricao']
        .apply(reclassificar_outros)
    )

    logger.info(f"Coluna 'tipo_imovel' classificada. Registros restantes: {pd_data_tipo_imovel.shape}")

    pd_data_long_lat = pd_data_tipo_imovel.copy()
    
    if tipo_async:
        pd_data_lat_log_completo = await preencher_todas_coordenadas(pd_data_long_lat, batch_size=batch, cidade=cidade_localizacao, estado=estado_localizacao, pais=pais)
    else:
        pd_data_lat_log_completo = geocodificar_dataframe(pd_data_long_lat, cidade=cidade_localizacao, estado=estado_localizacao, pais=pais)

    logger.info(f"Todas as coordenadas preenchidas. Registros restantes: {pd_data_lat_log_completo.shape}")

    pd_data_lat_log_completo['preco_por_m2'] = pd_data_lat_log_completo['valor_imovel'] / pd_data_lat_log_completo['metragem']

    logger.info(f'Coluna "preco_por_m2" criada. Registros restantes: {pd_data_lat_log_completo.shape}')

    def classificar_dentro_bairro(grupo):
        p25 = grupo["preco_por_m2"].quantile(0.25)
        p50 = grupo["preco_por_m2"].quantile(0.50)
        p75 = grupo["preco_por_m2"].quantile(0.75)
        
        def faixa(val):
            if val <= p25:
                return "barato"
            elif val <= p50:
                return "medio_baixo"
            if val <= p75:
                return "medio_alto"
            else:
                return "alto_padrao"

        grupo = grupo.copy()
        grupo["faixa"]       = grupo["preco_por_m2"].apply(faixa)
        grupo["p25_bairro"]  = p25
        grupo["p50_bairro"]  = p50
        grupo["p75_bairro"]  = p75
        return grupo

    pd_data_range_bairro_tipo_imovel = pd_data_lat_log_completo.groupby(["bairro", "tipo_imovel"], group_keys=False, ).apply(classificar_dentro_bairro)

    pd_data_range_bairro_tipo_imovel = pd.concat([pd_data_lat_log_completo, pd_data_range_bairro_tipo_imovel[['faixa', 'p25_bairro', 'p50_bairro', 'p75_bairro']]], axis=1)

    logger.info(f"Criando Faixas de preço por bairro e tipo de imóvel classificadas. Registros restantes: {pd_data_range_bairro_tipo_imovel.shape}")

    pd_data_range_bairro_tipo_imovel["desvio_mediana"] = round((pd_data_range_bairro_tipo_imovel["preco_por_m2"] - pd_data_range_bairro_tipo_imovel["p50_bairro"]) / pd_data_range_bairro_tipo_imovel["p50_bairro"],2)

    logger.info(f"Coluna 'desvio_mediana' criada. Registros restantes: {pd_data_range_bairro_tipo_imovel.shape}")
    
    return pd_data_range_bairro_tipo_imovel

def carregar_json(pasta_dados: Path, glob_pattern: str) -> tuple[pd.DataFrame, Path | None]:
    """
    Busca o arquivo mais recente pelo padrão e retorna um DataFrame.
    Retorna DataFrame vazio se não encontrar nenhum arquivo.
    """
    arquivos = list(pasta_dados.glob(glob_pattern))

    if not arquivos:
        logger.warning(f"Nenhum arquivo encontrado para o padrão: {glob_pattern}")
        return pd.DataFrame(), None

    arquivo = max(arquivos, key=lambda f: f.stem.split('_')[-1])
    
    logger.info(f"Arquivo encontrado: {arquivo.name}")

    try:
        with open(arquivo, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return pd.DataFrame(data), arquivo

    except Exception as e:
        logger.error(f"Erro ao carregar {arquivo.name}: {e}")
        return pd.DataFrame(), arquivo

def carregar_parquet(pasta_dados: Path, glob_pattern: str) -> tuple[pd.DataFrame, Path | None]:
    """
    Busca o arquivo .parquet mais recente pelo padrão e retorna um DataFrame.
    Retorna DataFrame vazio se não encontrar nenhum arquivo.
    """
    # Se o padrão ainda estiver como .json, trocamos para .parquet
    if '.json' in glob_pattern:
        glob_pattern = glob_pattern.replace('.json', '.parquet')

    arquivos = list(pasta_dados.glob(glob_pattern))

    if not arquivos:
        logger.warning(f"Nenhum arquivo encontrado para o padrão: {glob_pattern}")
        return pd.DataFrame(), None

    # Mantém sua lógica de pegar o arquivo com a data mais recente no nome
    try:
        arquivo = max(arquivos, key=lambda f: f.stem.split('_')[-1])
    except Exception:
        # Fallback caso o nome do arquivo não siga o padrão de data
        arquivo = max(arquivos, key=lambda f: f.stat().st_mtime)
    
    logger.info(f"Arquivo Parquet encontrado: {arquivo.name}")

    try:
        # O pandas lê o Parquet diretamente do caminho (Path ou str)
        # Não é necessário usar 'with open' pois o formato é binário
        df = pd.read_parquet(arquivo)
        return df, arquivo

    except Exception as e:
        logger.error(f"Erro ao carregar {arquivo.name}: {e}")
        return pd.DataFrame(), arquivo

def deletar_arquivo(arquivo: Path | None):
    if arquivo and arquivo.exists():
        arquivo.unlink()
        logger.info(f"Arquivo deletado: {arquivo.name}")
        
"""def normalizar_bairro(bairro_raw, MAPA_BAIRROS):
    key = str(bairro_raw).strip().lower()
    normalizado = MAPA_BAIRROS.get(key)
    
    if normalizado is None:
        print(f"⚠️ Bairro sem mapeamento: '{bairro_raw}'")
        return str(bairro_raw).strip()  # mantém original
    
    return normalizado"""

def normalizar_bairros(bairro, mapeamento):
    if not isinstance(bairro, str):
        return bairro
        
    bairro_low = bairro.lower()
    
    for nome_correto, variacoes in mapeamento.items():
        # Verifica se qualquer uma das variações está contida no nome original
        if any(v in bairro_low for v in variacoes):
            return nome_correto
            
    return bairro 
        
def limpando_dados(
         name_arquivo_saida: str,
         pasta_dados : Path,
         name_arquivo_zap : str = None, 
         name_arquivo_vivareal: str = None, 
         name_arquivo_chave_mao: str = None,
         name_arquivo_olx: str = None, 
         batch: int = 1,
         tipo_async: bool = False,
         cidade_localizacao: str = 'Joinville', 
         cidade_limpeza: str = 'joinville',
         estado_limpeza: str = 'sc', 
         estado_localizacao: str = 'SC',
         pais: str = 'Brasil', 
         MAPA_BAIRROS: dict = None,
         MAPA_CIDADES: str = None,):
    
    logger.info(f"Iniciando limpeza de dados de imóveis de {cidade_limpeza}...")
    
    logger.info(f"Pasta de dados: {pasta_dados}")

    pasta_dados.mkdir(parents=True, exist_ok=True)

    if name_arquivo_zap is not None:
        df_zap, arquivo_zap      = carregar_parquet(pasta_dados, name_arquivo_zap)
        if not df_zap.empty:
            df_zap['fonte'] = 'zap_imoveis'
        df_zap_endereco_limpo = df_zap['endereco'].apply(lambda x: limpa_endereco_apply_zap(x, cidade_limpeza, estado_limpeza))
        df_zap_endereco =  pd.concat([df_zap, df_zap_endereco_limpo], axis=1)
        logger.info(f"Quantidade de dados ZAP: {len(df_zap)}")

        
    if name_arquivo_vivareal is not None:
        df_vivareal, arquivo_vivareal = carregar_parquet(pasta_dados, name_arquivo_vivareal)
        if not df_vivareal.empty:
            df_vivareal['fonte'] = 'viva_real'
        df_vivareal_endereco_limpo = df_vivareal['endereco'].apply(lambda x: limpa_endereco_apply_zap(x, cidade_limpeza, estado_limpeza))
        df_vivareal_endereco =  pd.concat([df_vivareal, df_vivareal_endereco_limpo], axis=1)
        logger.info(f"Quantidade de dados Vivareal: {len(df_vivareal)}")
    
    if name_arquivo_chave_mao is not None:
        df_chave_mao, arquivo_chave_mao = carregar_parquet(pasta_dados, name_arquivo_chave_mao)
        if not df_chave_mao.empty:
            df_chave_mao['fonte'] = 'chave_mao'
        df_chave_mao_endereco_limpo = df_chave_mao['endereco'].apply(lambda x: limpa_endereco_apply_chave_mao(x, cidade_limpeza, estado_limpeza))
        df_chave_mao_endereco =  pd.concat([df_chave_mao, df_chave_mao_endereco_limpo], axis=1)
        logger.info(f"Quantidade de dados Chave Mao: {len(df_chave_mao)}")
    
    if name_arquivo_olx is not None:
        df_olx, arquivo_olx = carregar_json(pasta_dados,name_arquivo_olx)
        if not df_olx.empty:
            df_olx['fonte'] = 'olx'
        df_olx_endereco_limpo = df_olx['endereco'].apply(lambda x: limpa_endereco_apply_olx(x, cidade_limpeza, estado_limpeza))
        df_olx_endereco =  pd.concat([df_olx, df_olx_endereco_limpo], axis=1)
        logger.info(f"Quantidade de dados OLX: {len(df_olx)}")
    else:
        logger.info("Arquivo de OLX não encontrado.")

    if df_zap.empty and df_vivareal.empty and df_chave_mao.empty and df_olx.empty:
        logger.error("Nenhum dado encontrado em nenhuma das fontes — abortando.")
        return
    #df_zap_endereco_limpo = df_zap['endereco'].apply(lambda x: limpa_endereco_apply_zap(x, cidade_limpeza, estado_limpeza))
    #df_vivareal_endereco_limpo = df_vivareal['endereco'].apply(lambda x: limpa_endereco_apply_zap(x, cidade_limpeza, estado_limpeza))
    #df_chave_mao_endereco_limpo = df_chave_mao['endereco'].apply(lambda x: limpa_endereco_apply_chave_mao(x, cidade_limpeza, estado_limpeza))
    #df_olx_endereco_limpo = df_olx['endereco'].apply(lambda x: limpa_endereco_apply_olx(x, cidade_limpeza, estado_limpeza))
    
    #df_zap_endereco =  pd.concat([df_zap, df_zap_endereco_limpo], axis=1)
    #df_vivareal_endereco =  pd.concat([df_vivareal, df_vivareal_endereco_limpo], axis=1)
    #df_chave_mao_endereco =  pd.concat([df_chave_mao, df_chave_mao_endereco_limpo], axis=1)
    #df_olx_endereco =  pd.concat([df_olx, df_olx_endereco_limpo], axis=1)

    df = pd.concat([
                    df_zap_endereco if name_arquivo_zap is not None else pd.DataFrame(), 
                    df_vivareal_endereco if name_arquivo_vivareal is not None else pd.DataFrame(),
                    df_chave_mao_endereco if name_arquivo_chave_mao is not None else pd.DataFrame(),
                    df_olx_endereco if name_arquivo_olx is not None else pd.DataFrame()], 
                   axis=0, ignore_index=True)
    
    #logger.info(f"Total de registros carregados: {len(df)} (zap: {len(df_zap)} | vivareal: {len(df_vivareal)} | chave_mao: {len(df_chave_mao)} | olx: {len(df_olx)})")
    
    logger.info(f"Filtrando por cidade: {cidade_limpeza}...")
    
    df_cidade = df[df['cidade'].isin([cidade_limpeza])]
    
    logger.info(f"Registros após filtro de cidade: {len(df_cidade)} | Registros removidos: {len(df) - len(df_cidade)}")
    
    # Limpeza
    df_limpo = asyncio.run(limpando_dados_cidades(df_cidade, 
                                        batch = batch, 
                                        cidade_limpeza= cidade_limpeza, 
                                        cidade_localizacao= cidade_localizacao,
                                        tipo_async=tipo_async,
                                        estado_limpeza= estado_limpeza,
                                        estado_localizacao= estado_localizacao, 
                                        pais= pais
                                        ))

    # Remove duplicatas
    colunas_dedup = ['valor_imovel', 'rua', 'bairro', 'metragem', 'quartos', 'preco_por_m2', 'banheiros', 'lat', 'lng']
    
    colunas_dedup = [c for c in colunas_dedup if c in df_limpo.columns]  

    antes = len(df_limpo)
    
    df_limpo = df_limpo.drop_duplicates(subset=colunas_dedup, keep='first').reset_index(drop=True)
    
    logger.info(f"Duplicatas removidas: {antes - len(df_limpo)} | Registros finais: {len(df_limpo)}")
    
    if MAPA_BAIRROS:
        df_limpo['bairro'] = df_limpo['bairro'].apply(normalizar_bairros, args=(MAPA_BAIRROS,))
        
    if MAPA_CIDADES:
        df_limpo.loc[df_limpo['cidade'].str.contains(MAPA_CIDADES, na=False), 'cidade'] = cidade_limpeza

    logger.info(f"Coluna 'bairro' corrigida...")
    
    df_limpo = df_limpo.groupby('bairro').filter(lambda x: len(x) > 1)

    arquivo_ref = arquivo_zap or arquivo_vivareal
    
    data_ref    = arquivo_ref.stem.split('_')[-1]
    
    caminho_saida = pasta_dados / f'{name_arquivo_saida}_{data_ref}.parquet'
    
    #df_limpo.to_csv(caminho_saida, index=False, encoding='utf-8')
    
    df_limpo.to_parquet(caminho_saida, index=False, compression='snappy')
    
    logger.info(f"Arquivo salvo: {caminho_saida.name}")

    if not df_limpo.empty:
        
        total_registros = len(df_limpo)
        
        nulos_lat = df_limpo['lat'].isna().sum() + (df_limpo['lat'] == '').sum()
        
        porcentagem_vazio = (nulos_lat / total_registros) * 100
        
        logger.info(f"Validação de Latitude: {nulos_lat}/{total_registros} ({porcentagem_vazio:.2f}% vazios)")

        # 2. Só deleta se a metade (50%) ou mais da coluna ESTIVER preenchida
        if porcentagem_vazio < 50:
            logger.info("✅ Dados de localização validados. Procedendo com a deleção dos arquivos temporários.")
            
            deletar_arquivo(arquivo_zap)
            deletar_arquivo(arquivo_vivareal)
            deletar_arquivo(arquivo_chave_mao)
            deletar_arquivo(arquivo_olx)
        else:
            logger.warning("⚠️ ALERTA: Mais de 50% da coluna 'lat' está vazia!")
            logger.warning("Os arquivos originais foram MANTIDOS para conferência.")
    else:
        logger.error("❌ DataFrame limpo está vazio. Operação de deleção abortada.")
    
    logger.info("Processo de limpeza de dados concluído.")
    
    

def criar_area_ranges(inicio_total: int, fim_total: int, regras_intervalo: list):
    """
    Cria dicionário de ranges seguindo a lógica: inicio = fim_anterior + 1.
    
    regras_intervalo: Lista de tuplas (ate_qual_area, tamanho_do_passo)
    Ex: [(100, 5), (500, 50)] -> Ate 100m² pula de 5 em 5. Ate 500m² pula de 50 em 50.
    """
    ranges = {}
    atual = inicio_total
    
    # Ordena as regras pelo limite de área para garantir a lógica
    regras_intervalo.sort(key=lambda x: x[0])
    
    for limite, passo in regras_intervalo:
        while atual <= limite and atual < fim_total:
            inicio = atual
            fim = atual + passo
            
            # Garante que não ultrapasse o limite atual da regra nem o fim total
            if fim > limite:
                fim = limite
            if fim > fim_total:
                fim = fim_total
                
            ranges[str(inicio)] = str(fim)
            
            # Regra: Próximo inicio = fim anterior + 1
            atual = fim + 1
            
    # Caso o fim_total seja muito grande (o "infinito" da busca)
    # Adicionamos o último range manualmente se ainda não chegamos lá
    if atual <= fim_total:
        ranges[str(atual)] = str(fim_total)
        
    return ranges


