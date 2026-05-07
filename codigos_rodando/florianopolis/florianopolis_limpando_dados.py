from pathlib import Path
import logging
import warnings
import sys

import os
from dotenv import load_dotenv

load_dotenv()

sys.path.append(str(Path(__file__).parent.parent))

from limpando_dados import limpando_dados

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")

cidade_limpeza      =  os.getenv("CIDADE_LIMPEZA")

cidade_localizacao  =  os.getenv("CIDADE_LOCALIZACAO")

estado_limpeza      =  os.getenv("ESTADO_LIMPEZA")

estado_localizacao  =  os.getenv("ESTADO_LOCALIZACAO")

PASTA_DADOS  = Path(__file__).parent.parent.parent / 'dados'/ cidade

BATCH        =  os.getenv("BATCH_LIMPEZA")

BATCH = int(BATCH) if BATCH and BATCH.isdigit() else 100

logger.info(f"Iniciando limpeza de dados de imóveis de {cidade}...")

logger.info(f"Pasta de dados: {PASTA_DADOS}")

PASTA_DADOS.mkdir(parents=True, exist_ok=True)

logger.info(f"Os parametros de limpeza são: cidade_limpeza={cidade_limpeza}, cidade_localizacao={cidade_localizacao}, estado_limpeza={estado_limpeza}, estado_localizacao={estado_localizacao}, BATCH={BATCH}")

MAPA_BAIRROS = {
        'jurere internacional': ['jurere internacional', 'forte'],
        'jurere': ['jurere tradicional', 'jurere'],
        'ingleses': ['praia dos ingleses', 'ingleses norte', 'sc 403 km 1', 'ingleses'],
        'pantano do sul': ['acores', 'pantano do sul', 'praia da solidao'],
        'estreito': ['canto', 'balneario do estreito'],
        'centro': ['centro', 'beira mar','monte cristo', 'campinas'],
        'lagoa da conceicao': ['porto da lagoa', 'canto da lagoa','costa da lagoa', 'lagoa'],
        'ribeirao da ilha' : ['portal do ribeirao', 'ribeirao da ilha', 'alto ribeirao'],
        'itacorubi' : ['parque sao jorge', 'itacorubi'],
        'canasvieiras' : ['canajure'],
        'barra da lagoa' : ['praia mole'],
        'vargem grande': ['vargem pequena', 'vargem do bom jesus', 'real parque'],
        'rio vermelho': ['sao joao do rio vermelho', 'moenda', 'muquem', 'rio vermelho', 'praia mocambique'],
        'corrego grande' : ['jardim anchieta'],
        'jose mendes' : ['prainha'],
        'balneario' : ['ponta do leal'],
        'ponta das canas' : ['praia da lagoinha', 'lagoinha do norte'],
        'coqueiros' : ['coqueiros'],
        'joao paulo' : ['joao paulo'],
        'agronomica' :['morro da cruz'],
        'tapera da base' : ['tapera']
    }


limpando_dados(name_arquivo_zap = f'{cidade}_zap_*.parquet', 
               name_arquivo_vivareal = f'{cidade}_vivareal_*.parquet', 
               name_arquivo_chave_mao = f'{cidade}_chave_mao_*.parquet',
               #name_arquivo_olx = f'{cidade}_olx_*.json',
               name_arquivo_saida = f'{cidade}_imoveis_limpo', 
               pasta_dados = PASTA_DADOS, 
               tipo_async = True,
               batch = BATCH, 
               cidade_limpeza=cidade_limpeza,
               cidade_localizacao=cidade_localizacao,
               estado_limpeza=estado_limpeza,
               estado_localizacao=estado_localizacao,
               MAPA_BAIRROS=MAPA_BAIRROS)