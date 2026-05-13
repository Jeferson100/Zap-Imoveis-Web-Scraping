from pathlib import Path
import logging
import warnings
import sys

import os
from dotenv import load_dotenv

load_dotenv()

sys.path.append(str(Path(__file__).parent.parent.parent))

from limpando_dados import limpando_dados

from unificando_dados import consolidar_jsons, consolidar_parquet

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")

cidade_limpeza      =  os.getenv("CIDADE_LIMPEZA")

cidade_localizacao  =  os.getenv("CIDADE_LOCALIZACAO")

estado_limpeza      =  os.getenv("ESTADO_LIMPEZA")

estado_localizacao  =  os.getenv("ESTADO_LOCALIZACAO")

bairro = os.getenv("BAIRRO")

filtro_bairro = os.getenv("FILTRO_BAIRRO")

BASE_DIR    = Path(__file__).parent.parent.parent.parent
 
PASTA_DADOS = BASE_DIR / 'dados' / cidade  / bairro

BATCH        =  os.getenv("BATCH_LIMPEZA")

BATCH = int(BATCH) if BATCH and BATCH.isdigit() else 100

logger.info(f"Iniciando limpeza de dados de imóveis de {cidade_limpeza}...")

logger.info(f"Pasta de dados: {PASTA_DADOS}")

logger.info(f"Os parametros de limpeza são: cidade_limpeza={cidade_limpeza}, cidade_localizacao={cidade_localizacao}, estado_limpeza={estado_limpeza}, estado_localizacao={estado_localizacao}, BATCH={BATCH}")

PASTA_DADOS.mkdir(parents=True, exist_ok=True)

logger.info(f"Diretório de dados: {PASTA_DADOS}")

consolidar_parquet('vivareal', cidade, PASTA_DADOS, bairro)

logger.info(f"Dados consolidados para Viva Real.")

consolidar_parquet('chave_mao', cidade, PASTA_DADOS, bairro)

logger.info(f"Dados consolidados para Chave na Mão.")

consolidar_parquet('zap', cidade, PASTA_DADOS, bairro)

logger.info(f"Dados consolidados para Zap.")

consolidar_jsons('olx', cidade, PASTA_DADOS, bairro)

logger.info(f"Dados consolidados para Olx.")

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")

limpando_dados(name_arquivo_zap = f'{cidade}_{bairro}_zap_*.parquet', 
               name_arquivo_vivareal = f'{cidade}_{bairro}_vivareal_*.parquet', 
               name_arquivo_chave_mao = f'{cidade}_{bairro}_chave_mao_*.parquet',
               name_arquivo_olx = f'{cidade}_{bairro}_olx_*.json',
               name_arquivo_saida = f'{cidade}_{bairro}_imoveis_limpo', 
               pasta_dados = PASTA_DADOS, 
               tipo_async = True,
               batch = BATCH, 
               cidade_limpeza=cidade_limpeza,
               cidade_localizacao=cidade_localizacao,
               estado_limpeza=estado_limpeza,
               estado_localizacao=estado_localizacao, 
               #MAPA_BAIRROS=MAPA_BAIRROS,
               filtro_bairro=filtro_bairro
               )