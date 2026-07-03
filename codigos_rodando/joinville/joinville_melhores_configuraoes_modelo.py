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
from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES


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
INCLUIR_TOPICOS = os.getenv("INCLUIR_TOPICOS", "True").lower() == "true"

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
        (dados["metragem"] > 20)
        & (
            ~dados["tipo_imovel"].isin(["casa", "apartamento"])
            | (
                (dados["preco_por_m2"] >= 100)
                & (dados["metragem"] <= 1000)
            )
        )
    ].copy()
    df_modelo = df_modelo[df_modelo['tipo_imovel'].isin(['apartamento', 'casa'])]
    df_modelo = df_modelo[df_modelo['valor_imovel'] < 15000000]
    df_modelo = df_modelo.dropna(subset=["valor_imovel"])
    train, test = train_test_split(df_modelo, test_size=0.25, random_state=42)
    train, test = engenharia_features_completa(train, test)
    train.to_parquet(train_path, index=False)
    test.to_parquet(test_path, index=False)
    logger.info(f"Cache salvo: {train_path.name}, {test_path.name}")

logger.info(f"Amostras: treino {len(train):,} | teste {len(test):,}")

TOPICOS_PATH = PASTA_DADOS / f"{cidade}_topicos_modelo.pkl"

if INCLUIR_TOPICOS:
    from treinar_topicos import treinar_modelo_topicos
    from utils_topicos import TOPIC_COLS
    treinar_modelo_topicos(train, test, TOPICOS_PATH)
    FEATURES_TESTADAS = NUMERIC_FEATURES + CATEGORICAL_FEATURES + TOPIC_COLS
else:
    FEATURES_TESTADAS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

logger.info(f"Features: {len(FEATURES_TESTADAS)}")

mlf = MLflowManager(
    nome_experimento=f"imoveis-{cidade}-valor",
    databricks_workspace_path=f"/Workspace/Users/sehnemjeferson@gmail.com/imoveis-{cidade}-valor",
)

mlf.conectar()

DELETAR_RUNS = True
if DELETAR_RUNS:
    from selecao_modelos_mlflow import deletar_runs_experimento
    deletar_runs_experimento(f"imoveis-{cidade}-valor", confirmacao=True)


async def main():
    teste = TesteIncrementalFeaturesAsync(
        experimento_mlflow=f"imoveis-{cidade}-valor",
        target_log=True,
    )
    df = await teste.testar_tratamentos_modelos_incrementais_async(
        train=train, test=test, target_col=TARGET,
        features_testadas=FEATURES_TESTADAS,
        categorical_features=CATEGORICAL_FEATURES,
        n_trials_optuna=N_TRIALS_OPTUNA,
        otimizar_mlp=False,
        max_concurrent=MAX_CONCURRENT,
        feature_selection="shap"
    )
    return df


if __name__ == "__main__":
    df = asyncio.run(main())
    logger.info("Treinamento concluido, buscando melhores modelos por incremento no MLflow...")

    from mlflow.tracking import MlflowClient
    from selecao_modelos_mlflow import buscar_melhores_por_incremento

    client = MlflowClient(mlf.get_tracking_uri())
    exp = client.get_experiment_by_name(mlf.nome_experimento)
    if not exp:
        exp = client.get_experiment_by_name(mlf.databricks_workspace_path)
    if not exp:
        for e in client.search_experiments():
            if mlf.nome_experimento in e.name or mlf.databricks_workspace_path in e.name:
                exp = e
                break
    if exp:
        melhores = buscar_melhores_por_incremento(client, exp.experiment_id)
        if not melhores.empty:
            parquet_path = PASTA_DADOS / f"{cidade}_melhores_por_incremento_{MES_REF}.parquet"
            melhores.to_parquet(parquet_path, index=False)
            logger.info(f"Melhores por incremento salvos ({len(melhores)} linhas): {parquet_path.name}")
            cols = ['n_features','modelo','otimizacao','tratamento','transform','scaler','imputer_num','encoder','r2','rmse','mape','rmsle']
            logger.info(f"\n{melhores[cols].head(15).to_string()}")
        else:
            logger.warning("Nenhum run com metrica r2 encontrado no MLflow")
    else:
        logger.warning(f"Experimento '{mlf.nome_experimento}' nao encontrado no MLflow")
