import time
import logging
import warnings
import pandas as pd
from pathlib import Path

import os
from dotenv import load_dotenv

load_dotenv()

import sys

sys.path.append(str(Path(__file__).parent.parent.parent))

from criando_indice import criando_indice_cidades

from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

start_time = time.time()

bairro = os.getenv("BAIRRO")

cidade = os.getenv("CIDADE_PASTA")

BASE_DIR    = Path(__file__).parent.parent.parent.parent
 
PASTA_DADOS = BASE_DIR / 'dados' / cidade  / bairro

arquivo_mais_recente = max(PASTA_DADOS.glob(f'{cidade}_{bairro}_imoveis_limpo_*.parquet'), key=lambda f: f.stem.split('_')[-1])

data_mais_recente = arquivo_mais_recente.stem.split('_')[-1]

output_file   = PASTA_DADOS / f'{cidade}_{bairro}_imoveis_com_ind_local_{data_mais_recente}.parquet'  

pd_data = pd.read_parquet(arquivo_mais_recente)

#max_concurrent= os.getenv("MAX_CONCURRENCY_LOCALIZACAO")

max_concurrent=int(os.getenv("MAX_CONCURRENCY", "100"))

pd_data_com_indice = criando_indice_cidades(pd_data, max_concurrent) 

pd_data_com_indice.to_parquet(output_file, index=False)

logger.info(f"Arquivo {output_file.name} criado com sucesso!")

if arquivo_mais_recente.exists():
    arquivo_mais_recente.unlink()
    logger.info(f"Arquivo {arquivo_mais_recente.name} deletado com sucesso!")