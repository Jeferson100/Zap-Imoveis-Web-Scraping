import asyncio
import sys
from pathlib import Path
import time
import os

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).parent.parent.parent))

from unificando_dados import consolidar_jsons, consolidar_parquet

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR    = Path(__file__).parent.parent.parent.parent 

cidade = os.getenv("CIDADE_PASTA")

bairro = os.getenv("BAIRRO")

PASTA_DADOS = BASE_DIR / 'dados' / cidade  / bairro

PASTA_DADOS.mkdir(parents=True, exist_ok=True)

logger.info(f"Diretório de dados: {PASTA_DADOS}")

#consolidar_parquet('vivareal', cidade, PASTA_DADOS)

logger.info(f"Dados consolidados para Viva Real.")

consolidar_parquet('chave_mao', cidade, PASTA_DADOS, bairro)

logger.info(f"Dados consolidados para Chave na Mão.")

#consolidar_parquet('zap', cidade, PASTA_DADOS)

logger.info(f"Dados consolidados para Zap.")

#consolidar_jsons('olx', cidade, PASTA_DADOS)

#logger.info(f"Dados consolidados para Olx.")

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")