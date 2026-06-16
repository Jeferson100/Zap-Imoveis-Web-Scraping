from pathlib import Path
import logging
import warnings
import os
from dotenv import load_dotenv

from melhor_modelo_geral import treinar_melhor_modelo_geral


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")
cidade_nome = os.getenv("LOCALIZAZAO_COMPLETA", "Itapoa, Santa Catarina, Brasil")
MES_REF = os.getenv("MES_REF", "2026-06")

logger = logging.getLogger(__name__)
logger.info("Iniciando treinamento do melhor modelo geral para %s (ref: %s)", cidade, MES_REF)

pipe = treinar_melhor_modelo_geral(
    cidade=cidade,
    cidade_nome=cidade_nome,
    mes_ref=MES_REF,
)
