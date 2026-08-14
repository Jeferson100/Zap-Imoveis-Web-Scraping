import asyncio
import sys
from pathlib import Path
import time
import os

from dotenv import load_dotenv

sys.path.append(str(Path(__file__).parent.parent))

from unificando_dados import consolidar_jsons, consolidar_parquet

import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

load_dotenv()

BASE_DIR    = Path(__file__).parent.parent.parent  

cidade = os.getenv("CIDADE_PASTA")

PASTA_DADOS = BASE_DIR / 'dados' / cidade

PASTA_DADOS.mkdir(parents=True, exist_ok=True)

logger.info(f"Diretório de dados: {PASTA_DADOS}")

consolidar_parquet('aluguel_chave_mao', cidade, PASTA_DADOS)

logger.info(f"Dados consolidados para Chave na Mão aluguel.")

consolidar_parquet('aluguel_vivareal', cidade, PASTA_DADOS)

logger.info(f"Dados consolidados para Viva Real aluguel.")

consolidar_parquet('aluguel_zap', cidade, PASTA_DADOS)

logger.info(f"Dados consolidados para Zap aluguel.")

consolidar_jsons('aluguel_olx', cidade, PASTA_DADOS)

logger.info(f"Dados consolidados para Olx aluguel.")

logger.info(f"Arquivos consolidados em: {PASTA_DADOS}")