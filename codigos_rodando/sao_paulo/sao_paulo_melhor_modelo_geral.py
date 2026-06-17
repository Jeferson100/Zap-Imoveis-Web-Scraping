from pathlib import Path
import logging
import warnings
import os
from datetime import datetime
from dotenv import load_dotenv

from melhor_modelo_geral import treinar_melhor_modelo_geral

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")
bairro = os.getenv("BAIRRO")
cidade_nome = os.getenv("LOCALIZAZAO_COMPLETA", "Sao Paulo, Sao Paulo, Brasil")
MES_REF = os.getenv("MES_REF", datetime.now().strftime("%Y-%m"))

logger = logging.getLogger(__name__)
logger.info("Iniciando treinamento do melhor modelo geral para %s/%s (ref: %s)", cidade, bairro, MES_REF)

BASE_DIR = Path(__file__).parent.parent.parent
PASTA_DADOS = BASE_DIR / 'dados' / cidade / bairro
PASTA_DADOS.mkdir(parents=True, exist_ok=True)

prefixo = f"{cidade}_{bairro}"

pipe = treinar_melhor_modelo_geral(
    cidade=prefixo,
    cidade_nome=cidade_nome,
    mes_ref=MES_REF,
    pasta_dados=PASTA_DADOS,
    experimento=f"imoveis-{cidade}-{bairro}-valor",
)
