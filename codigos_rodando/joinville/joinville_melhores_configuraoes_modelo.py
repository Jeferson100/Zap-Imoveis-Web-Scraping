from pathlib import Path
import pandas as pd
import os
from datetime import datetime
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split
import logging
import warnings
from mlflow_manager import MLflowManager
import asyncio

from criando_indices_individuais import CriandoIndicesIndividuais
from teste_incremental_features_async import TesteIncrementalFeaturesAsync
from funcoes_engenharia_features import engenharia_features_completa


load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")
cidade_nome = os.getenv("CIDADE_NOME", "Joinville, Santa Catarina, Brasil")
MES_REF = os.getenv("MES_REF", datetime.now().strftime("%Y-%m"))
N_TRIALS_OPTUNA = int(os.getenv("N_TRIALS_OPTUNA", "15"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "20"))
TARGET = "valor_imovel"

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

PASTA_DADOS = Path(__file__).parent.parent.parent / 'dados' / cidade

train_path = PASTA_DADOS / f"{cidade}_train_{MES_REF}.parquet"
test_path  = PASTA_DADOS / f"{cidade}_test_{MES_REF}.parquet"

if train_path.exists() and test_path.exists():
    train = pd.read_parquet(train_path)
    test  = pd.read_parquet(test_path)
    logger.info(f"Cache carregado: {train_path.name}, {test_path.name}")
else:
    dados = pd.read_parquet(PASTA_DADOS / f"{cidade}_imoveis_limpo_{MES_REF}.parquet")
    if not {'descricao', 'bairro', 'metragem', 'preco_por_m2', 'tipo_imovel'}.issubset(dados.columns):
        raise KeyError("Colunas obrigatorias ausentes no parquet")
    logger.info("Calculando indices de localizacao...")
    indices = CriandoIndicesIndividuais(cidade=cidade_nome)
    dados = indices.calcular_indices(imoveis_df=dados)
    df_modelo = dados[
        (dados["metragem"] > 10)
        & (dados["tipo_imovel"].isin(["casa", "apartamento"]))
        & (dados["preco_por_m2"] >= 100)
    ].copy()
    train, test = train_test_split(df_modelo, test_size=0.25, random_state=42)
    train, test = engenharia_features_completa(train, test)
    train.to_parquet(train_path, index=False)
    test.to_parquet(test_path, index=False)
    logger.info(f"Cache salvo: {train_path.name}, {test_path.name}")

logger.info(f"Amostras: treino {len(train):,} | teste {len(test):,}")

logger.info(f"Features: {len(NUMERIC_FEATURES)} numericas + {len(CATEGORICAL_FEATURES)} categoricas")
FEATURES_TESTADAS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

mlf = MLflowManager(
    nome_experimento=f"imoveis-{cidade}-valor",
    databricks_workspace_path=f"/Workspace/Users/sehnemjeferson@gmail.com/imoveis-{cidade}-valor",
)

mlf.conectar()


async def main():
    teste = TesteIncrementalFeaturesAsync(experimento_mlflow=f"imoveis-{cidade}-valor")
    df = await teste.testar_tratamentos_modelos_incrementais_async(
        train=train, test=test, target_col=TARGET,
        features_testadas=FEATURES_TESTADAS,
        categorical_features=CATEGORICAL_FEATURES,
        n_trials_optuna=N_TRIALS_OPTUNA,
        otimizar_mlp=False,
        max_concurrent=MAX_CONCURRENT,
    )
    return df


if __name__ == "__main__":
    df = asyncio.run(main())
    