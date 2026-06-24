from pathlib import Path
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv
import logging
import warnings

from selecao_modelos_mlflow import otimizar_melhores_incrementos, carregar_dados
from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES



load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

logger = logging.getLogger(__name__)

warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")

MES_REF = os.getenv("MES_REF", datetime.now().strftime("%Y-%m"))
cidade_nome = os.getenv("LOCALIZAZAO_COMPLETA", "Joinville, Santa Catarina, Brasil")

N_TRIALS = int(os.getenv("N_TRIALS_OPTUNA", "400"))
SELECTION_MODE = os.getenv("SELECTION_MODE", "combinado")
TOP_K = int(os.getenv("TOP_K", "10"))
TOP_K_MODELO = int(os.getenv("TOP_K_MODELO", "3"))

PASTA_DADOS = Path(__file__).parent.parent.parent / 'dados' / cidade

EXPERIMENTO = f"imoveis-{cidade}-valor"

logger.info(f"Carregando dados do cache {MES_REF}...")

train, test = carregar_dados(PASTA_DADOS, MES_REF, cidade, cidade_nome=cidade_nome)

logger.info(f"Iniciando otimizacao dos melhores modelos por incremento ({N_TRIALS} trials)...")

resultados = otimizar_melhores_incrementos(
    experimento_mlflow=EXPERIMENTO,
    train=train, test=test,
    numeric_features=NUMERIC_FEATURES,
    categorical_features=CATEGORICAL_FEATURES,
    n_trials=N_TRIALS,
    metrica="rmse",
    selection_mode=SELECTION_MODE,
    top_k=TOP_K,
    top_k_modelo=TOP_K_MODELO,
)

if not resultados.empty:
    parquet_path = PASTA_DADOS / f"{cidade}_otimizados_melhores_incrementos_{MES_REF}.parquet"
    resultados.to_parquet(parquet_path, index=False)
    logger.info(f"Otimizacao concluida ({len(resultados)} linhas): {parquet_path.name}")
    cols = ['n_features','modelo','tratamento','transform','scaler',
            'imputer_num','encoder',
            'r2_original','rmse_original','mape_original',
            'r2_otimizado','rmse_otimizado','mape_otimizado',
            'mae_otimizado','mdape_otimizado','rmsle_original','rmsle_otimizado','best_params']
    logger.info(f"\n{resultados[cols].to_string()}")
else:
    logger.warning("Nenhum resultado de otimizacao gerado")
