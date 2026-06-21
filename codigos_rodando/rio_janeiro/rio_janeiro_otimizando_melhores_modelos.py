from pathlib import Path
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv
import logging
import warnings

from selecao_modelos_mlflow import otimizar_melhores_incrementos, carregar_dados

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")
bairro = os.getenv("BAIRRO")
cidade_nome = os.getenv("LOCALIZAZAO_COMPLETA", "Rio de Janeiro, Rio de Janeiro, Brasil")
MES_REF = datetime.now().strftime("%Y-%m")
N_TRIALS = int(os.getenv("N_TRIALS_OPTUNA", "500"))

CATEGORICAL_FEATURES = ['tipo_imovel', 'bairro', 'novo_lancamento', 'tem_elevador']

NUMERIC_FEATURES = [
    'metragem', 'quartos', 'banheiros', 'vagas',
    'score_escola_privada', 'score_escola_publica', 'score_hospitais',
    'score_mercado', 'score_farmacia', 'score_parque',
    'score_seguranca', 'score_educacao',
    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
    'valor_bairro_mean', 'bairro_rank',
    'quartos_por_metro', 'vagas_por_metro', 'banheiros_por_quarto',
    'lat', 'lng',
]

BASE_DIR = Path(__file__).parent.parent.parent
PASTA_DADOS = BASE_DIR / 'dados' / cidade / bairro

prefixo = f"{cidade}_{bairro}"
EXPERIMENTO = f"imoveis-{cidade}-{bairro}-valor"

logger.info(f"Carregando dados do cache {MES_REF}...")
train, test = carregar_dados(PASTA_DADOS, MES_REF, prefixo, cidade_nome=cidade_nome)

logger.info(f"Iniciando otimizacao dos melhores modelos por incremento ({N_TRIALS} trials)...")

resultados = otimizar_melhores_incrementos(
    experimento_mlflow=EXPERIMENTO,
    train=train, test=test,
    numeric_features=NUMERIC_FEATURES,
    categorical_features=CATEGORICAL_FEATURES,
    n_trials=N_TRIALS,
    metrica="rmse",
)

if not resultados.empty:
    parquet_path = PASTA_DADOS / f"{prefixo}_otimizados_melhores_incrementos_{MES_REF}.parquet"
    resultados.to_parquet(parquet_path, index=False)
    logger.info(f"Otimizacao concluida ({len(resultados)} linhas): {parquet_path.name}")
    cols = ['n_features','modelo','tratamento','transform','scaler',
            'imputer_num','encoder',
            'r2_original','rmse_original','mape_original',
            'r2_otimizado','rmse_otimizado','mape_otimizado',
            'mae_otimizado','mdape_otimizado','best_params']
    logger.info(f"\n{resultados[cols].to_string()}")
else:
    logger.warning("Nenhum resultado de otimizacao gerado")
