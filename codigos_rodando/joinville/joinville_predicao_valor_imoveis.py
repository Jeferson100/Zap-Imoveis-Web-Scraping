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
import mlflow.data
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


logger.info(f"Amostras para treino: {len(train):,} | teste: {len(test):,}")

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

test['metro_quadrado_bairro_mean'] = test['bairro'].map(
    bairro_stats[('preco_por_m2', 'mean')]
)

## metro_quadrado_bairro_median

train['metro_quadrado_bairro_median'] = train['bairro'].map(
    bairro_stats[('preco_por_m2', 'median')]
)
test['metro_quadrado_bairro_median'] = test['bairro'].map(
    bairro_stats[('preco_por_m2', 'median')]
)

## valor_bairro_mean
train['valor_bairro_mean'] = train['bairro'].map(
    bairro_stats[('valor_imovel', 'mean')]
)

test['valor_bairro_mean'] = test['bairro'].map(
    bairro_stats[('valor_imovel', 'mean')]
)   

# Criar ranking de bairros por preço
bairro_rank = train.groupby('bairro')['preco_por_m2'].median().rank()

train['bairro_rank'] = train['bairro'].map(bairro_rank)
test['bairro_rank'] = test['bairro'].map(bairro_rank)

# Razões
train['quartos_por_metro'] = train['quartos'] / (train['metragem'] + 1)
test['quartos_por_metro'] = test['quartos'] / (test['metragem'] + 1)

train['vagas_por_metro'] = train['vagas'] / (train['metragem'] + 1)
test['vagas_por_metro'] = test['vagas'] / (test['metragem'] + 1)

train['banheiros_por_quarto'] = train['banheiros'] / (train['quartos'] + 1)
test['banheiros_por_quarto'] = test['banheiros'] / (test['quartos'] + 1)

train['condominio_por_metro'] = train['condominio'] / (train['metragem'] + 1)
test['condominio_por_metro'] = test['condominio'] / (test['metragem'] + 1)


padrao_novo_lancamento = r'''
\bnovo\b|
\bnova\b|
\blan[çc]amento\b|
\bpr[eé]-?lan[çc]amento\b|
\bnovo\s+empreendimento\b|
\bem\s+constru[cç][aã]o\b|
\bprevis[aã]o\s+de\s+entrega\b|
\bentrega\s+para\b|
\bser[aá]\s+entregue\b|
\bnunca\s+habitado\b|
\brec[eé]m[- ]?entregue\b|
\brec[eé]m[- ]?constru[ií]do\b
'''

train['novo_lancamento'] = (
    train['descricao']
    .str.contains(
        padrao_novo_lancamento,
        case=False,
        regex=True,
        na=False
    )
    .astype(int)
)
test['novo_lancamento'] = (
    test['descricao']
    .str.contains(
        padrao_novo_lancamento,
        case=False,
        regex=True,
        na=False
    )
    .astype(int)
)

train['tem_elevador'] = train['descricao'].str.contains(
    r'\belevador\b',
    case=False,
    na=False
)
test['tem_elevador'] = test['descricao'].str.contains(
    r'\belevador\b',
    case=False,
    na=False
)



CATEGORICAL_FEATURES = ['tipo_imovel', 'bairro', 'novo_lancamento', 'tem_elevador']
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

X_test = test[NUMERIC_FEATURES + CATEGORICAL_FEATURES]
y_test = test[TARGET]

logger.info(f"Amostras para treino: {X_train.shape} | teste: {X_test.shape}")

mlf = MLflowManager(
    nome_experimento=f"imoveis-{cidade}-valor",
    databricks_workspace_path=f"/Workspace/Users/sehnemjeferson@gmail.com/imoveis-{cidade}-valor",
)

mlf.conectar()

CATEGORICAL_FEATURES = ['tipo_imovel', 'bairro', 'novo_lancamento', 'tem_elevador']

NUMERIC_FEATURES = ['metragem', 'quartos', 'banheiros', 'vagas', 'score_escola_privada', 
                    'score_escola_publica', 'score_hospitais', 'score_mercado',
                    'score_farmacia', 'score_parque', 'score_seguranca', 'score_educacao',
                    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
                    'valor_bairro_mean', 'bairro_rank',
                    'quartos_por_metro', 'vagas_por_metro', 'banheiros_por_quarto',
                    'lat', 'lng']

TARGET = 'valor_imovel'

FEATURES_TESTADAS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

async def main():
    teste = TesteIncrementalFeaturesAsync(experimento_mlflow="imoveis-joinville-valor")
    df = await teste.testar_tratamentos_modelos_incrementais_async(
        train=train, test=test, target_col=TARGET,
        features_testadas=FEATURES_TESTADAS,
        categorical_features=CATEGORICAL_FEATURES,
        n_trials_optuna=5,
        otimizar_mlp=True,
        max_concurrent=20,
        #feature_selection = "random",
    )
    return df

df = asyncio.run(main())