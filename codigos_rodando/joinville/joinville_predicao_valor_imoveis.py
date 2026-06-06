from pathlib import Path
import pandas as pd
from criando_indices_individuais import CriandoIndicesIndividuais
import os
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split
import logging
import warnings
from  mlflow_manager import MLflowManager
import asyncio

import sys
#sys.path.append(str(Path(__file__).parent.parent))

from teste_incremental_features import TesteIncrementalFeatures
from teste_incremental_features_async import TesteIncrementalFeaturesAsync


load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

cidade = os.getenv("CIDADE_PASTA")

#BASE_DIR = Path.cwd().parent

PASTA_DADOS  = Path(__file__).parent.parent.parent / 'dados'/ cidade

dados = pd.read_parquet(PASTA_DADOS / f'{cidade}_com_ind_local_2026-05.parquet')

localizacao_completa = os.getenv("LOCALIZAZAO_COMPLETA")

indices = CriandoIndicesIndividuais(cidade=localizacao_completa)

dados = indices.calcular_indices(imoveis_df=dados)

TARGET = "valor_imovel"

df_modelo = dados.copy()

df_modelo = df_modelo[
    (df_modelo["metragem"] > 10)
    #& (df_modelo[TARGET] >= 50_000)
    #& (df_modelo[TARGET] <= 25_000_000)
    & ((df_modelo["tipo_imovel"] == "casa") | (df_modelo["preco_por_m2"] >= 100))
    & ((df_modelo["tipo_imovel"] == "apartamento") | (df_modelo["preco_por_m2"] >= 100))
].copy()

train, test = train_test_split(
    df_modelo, test_size=0.25, random_state=42
)

train, val_teste = train_test_split(
    df_modelo, test_size=0.25, random_state=42
)

val, test = train_test_split(
    val_teste, test_size=0.4, random_state=42
)

logger.info(f"Amostras para treino: {len(train):,} | teste: {len(test):,} | validação: {len(val):,}")

# 4. Engenharia de features de localização
print('\n4. ENGENHARIA DE FEATURES DE LOCALIZAÇÃO')
print('-' * 80)

# Estatísticas por bairro
bairro_stats = train.groupby('bairro').agg({
    'preco_por_m2': ['mean', 'median', 'count'],
    'valor_imovel': ['mean', 'median']
}).fillna(0)

## metro_quadrado_bairro_mean

train['metro_quadrado_bairro_mean'] = train['bairro'].map(
    bairro_stats[('preco_por_m2', 'mean')]
)

val['metro_quadrado_bairro_mean'] = val['bairro'].map(
    bairro_stats[('preco_por_m2', 'mean')]
)

test['metro_quadrado_bairro_mean'] = test['bairro'].map(
    bairro_stats[('preco_por_m2', 'mean')]
)

## metro_quadrado_bairro_median

train['metro_quadrado_bairro_median'] = train['bairro'].map(
    bairro_stats[('preco_por_m2', 'median')]
)
val['metro_quadrado_bairro_median'] = val['bairro'].map(
    bairro_stats[('preco_por_m2', 'median')]    
)
test['metro_quadrado_bairro_median'] = test['bairro'].map(
    bairro_stats[('preco_por_m2', 'median')]
)

## valor_bairro_mean
train['valor_bairro_mean'] = train['bairro'].map(
    bairro_stats[('valor_imovel', 'mean')]
)
val['valor_bairro_mean'] = val['bairro'].map(
    bairro_stats[('valor_imovel', 'mean')]
)
test['valor_bairro_mean'] = test['bairro'].map(
    bairro_stats[('valor_imovel', 'mean')]
)   

# Criar ranking de bairros por preço
bairro_rank = train.groupby('bairro')['preco_por_m2'].median().rank()

train['bairro_rank'] = train['bairro'].map(bairro_rank)
val['bairro_rank'] = val['bairro'].map(bairro_rank)
test['bairro_rank'] = test['bairro'].map(bairro_rank)

# Razões
train['quartos_por_metro'] = train['quartos'] / (train['metragem'] + 1)
val['quartos_por_metro'] = val['quartos'] / (val['metragem'] + 1)
test['quartos_por_metro'] = test['quartos'] / (test['metragem'] + 1)

train['vagas_por_metro'] = train['vagas'] / (train['metragem'] + 1)
val['vagas_por_metro'] = val['vagas'] / (val['metragem'] + 1)
test['vagas_por_metro'] = test['vagas'] / (test['metragem'] + 1)

train['banheiros_por_quarto'] = train['banheiros'] / (train['quartos'] + 1)
val['banheiros_por_quarto'] = val['banheiros'] / (val['quartos'] + 1)
test['banheiros_por_quarto'] = test['banheiros'] / (test['quartos'] + 1)

train['condominio_por_metro'] = train['condominio'] / (train['metragem'] + 1)
val['condominio_por_metro'] = val['condominio'] / (val['metragem'] + 1)
test['condominio_por_metro'] = test['condominio'] / (test['metragem'] + 1)

CATEGORICAL_FEATURES = ['tipo_imovel', 'bairro']
NUMERIC_FEATURES = ['metragem', 'quartos', 'banheiros', 'vagas', 'score_escola_privada', 
                    'score_escola_publica', 'score_hospitais', 'score_mercado',
                    'score_farmacia', 'score_parque', 'score_seguranca', 'score_educacao',
                    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
                    'valor_bairro_mean', 'bairro_rank',
                    'quartos_por_metro', 'vagas_por_metro', 'banheiros_por_quarto',
                    'lat', 'lng']

TARGET = 'valor_imovel'

X_train = train[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
y_train = train[TARGET]

X_val = val[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
y_val = val[TARGET]

X_test = test[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
y_test = test[TARGET]

logger.info(f"Amostras para treino: {X_train.shape} | teste: {X_test.shape} | validação: {X_val.shape}")

mlf = MLflowManager(
    nome_experimento=f"imoveis-{cidade}-valor",
    databricks_workspace_path=f"/Workspace/Users/sehnemjeferson@gmail.com/imoveis-{cidade}-valor",
)

mlf.conectar()

CATEGORICAL_FEATURES = ['tipo_imovel', 'bairro']

NUMERIC_FEATURES = ['metragem', 'quartos', 'banheiros', 'vagas', 'score_escola_privada', 
                    'score_escola_publica', 'score_hospitais', 'score_mercado',
                    'score_farmacia', 'score_parque', 'score_seguranca', 'score_educacao',
                    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
                    'valor_bairro_mean', 'bairro_rank',
                    'quartos_por_metro', 'vagas_por_metro', 'banheiros_por_quarto',
                    'lat', 'lng']

TARGET = 'valor_imovel'

FEATURES_TESTADAS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

"""teste = TesteIncrementalFeatures(experimento_mlflow=f"imoveis-{cidade}-valor")

df_resultados = teste.testar_tratamentos_modelos_incrementais(
    train=train, test=test, target_col=TARGET,
    features_testadas=FEATURES_TESTADAS,
    categorical_features=CATEGORICAL_FEATURES,
    n_trials_optuna=5,
    otimizar_mlp=True,
)"""

async def main():
    teste = TesteIncrementalFeaturesAsync(experimento_mlflow="imoveis-joinville-valor")
    df = await teste.testar_tratamentos_modelos_incrementais_async(
        train=train, test=test, target_col=TARGET,
        features_testadas=FEATURES_TESTADAS,
        categorical_features=CATEGORICAL_FEATURES,
        n_trials_optuna=5,
        otimizar_mlp=True,
        max_concurrent=3,
    )
    return df

df = asyncio.run(main())