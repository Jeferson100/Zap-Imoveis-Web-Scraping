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
bairro = os.getenv("BAIRRO")
cidade_nome = os.getenv("LOCALIZAZAO_COMPLETA", "Rio de Janeiro, Rio de Janeiro, Brasil")
MES_REF = datetime.now().strftime("%Y-%m")
N_TRIALS_OPTUNA = int(os.getenv("N_TRIALS_OPTUNA", "15"))
MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "20"))
FEATURE_SELECTION = os.getenv("FEATURE_SELECTION", "sequential")
TARGET = "valor_imovel"

CATEGORICAL_FEATURES = ['tipo_imovel', 'bairro', 'novo_lancamento', 'tem_elevador', 'dist_centro_faixa']

NUMERIC_FEATURES = [
    'metragem', 'quartos', 'banheiros', 'vagas',
    'score_escola_privada', 'score_escola_publica', 'score_hospitais',
    'score_mercado', 'score_farmacia', 'score_parque',
    'score_seguranca', 'score_educacao',
    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
    'valor_bairro_mean', 'bairro_rank',
    'quartos_por_metro', 'vagas_por_metro', 'banheiros_por_quarto',
    'dist_centro',
    'lat', 'lng',
]

BASE_DIR = Path(__file__).parent.parent.parent
PASTA_DADOS = BASE_DIR / 'dados' / cidade / bairro
PASTA_DADOS.mkdir(parents=True, exist_ok=True)

prefixo = f"{cidade}_{bairro}"

train_path = PASTA_DADOS / f"{prefixo}_train_{MES_REF}.parquet"
test_path  = PASTA_DADOS / f"{prefixo}_test_{MES_REF}.parquet"

if train_path.exists() and test_path.exists():
    train = pd.read_parquet(train_path)
    test  = pd.read_parquet(test_path)
    logger.info(f"Cache carregado: {train_path.name}, {test_path.name}")
else:
    caminho_consolidado = PASTA_DADOS / f"{prefixo}_imoveis_limpo_{MES_REF}.parquet"
    if caminho_consolidado.exists():
        dados = pd.read_parquet(caminho_consolidado)
        logger.info(f"Consolidado: {caminho_consolidado.name} ({len(dados):,} linhas)")
    else:
        padrao = f"{prefixo}_imoveis_limpo_*_{MES_REF}.parquet"
        arquivos = sorted(PASTA_DADOS.glob(padrao))
        if not arquivos:
            raise FileNotFoundError(
                f"Nenhum arquivo imoveis_limpo para {cidade}/{bairro} em {PASTA_DADOS}"
            )
        dfs = [pd.read_parquet(a) for a in arquivos]
        dados = pd.concat(dfs, ignore_index=True)
        logger.info(f"Concatenados {len(arquivos)} fontes: {len(dados):,} linhas")

    if not {'descricao', 'bairro', 'metragem', 'preco_por_m2', 'tipo_imovel'}.issubset(dados.columns):
        raise KeyError("Colunas obrigatorias ausentes no parquet")

    logger.info("Calculando indices de localizacao...")
    indices = CriandoIndicesIndividuais(cidade=cidade_nome, cache_dir=PASTA_DADOS)
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

EXPERIMENTO = f"imoveis-{cidade}-{bairro}-valor"
mlf = MLflowManager(
    nome_experimento=EXPERIMENTO,
    databricks_workspace_path=f"/Workspace/Users/sehnemjeferson@gmail.com/{EXPERIMENTO}",
)
mlf.conectar()

DELETAR_RUNS = True
if DELETAR_RUNS:
    from selecao_modelos_mlflow import deletar_runs_experimento
    deletar_runs_experimento(EXPERIMENTO, confirmacao=True)


async def main():
    teste = TesteIncrementalFeaturesAsync(experimento_mlflow=EXPERIMENTO)
    df = await teste.        testar_tratamentos_modelos_incrementais_async(
        train=train, test=test, target_col=TARGET,
        features_testadas=FEATURES_TESTADAS,
        categorical_features=CATEGORICAL_FEATURES,
        n_trials_optuna=N_TRIALS_OPTUNA,
        otimizar_mlp=False,
        max_concurrent=MAX_CONCURRENT,
        feature_selection="shap",
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
            parquet_path = PASTA_DADOS / f"{prefixo}_melhores_por_incremento_{MES_REF}.parquet"
            melhores.to_parquet(parquet_path, index=False)
            logger.info(f"Melhores por incremento salvos ({len(melhores)} linhas): {parquet_path.name}")
            cols = ['n_features','modelo','otimizacao','tratamento','transform','scaler','imputer_num','encoder','r2','rmse','mape']
            logger.info(f"\n{melhores[cols].head(15).to_string()}")
        else:
            logger.warning("Nenhum run com metrica r2 encontrado no MLflow")
    else:
        logger.warning(f"Experimento '{EXPERIMENTO}' nao encontrado no MLflow")
