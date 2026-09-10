import os
import sys
import re
import json
import unicodedata
import logging
import asyncio
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import joblib
from dotenv import load_dotenv
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

sys.path.append(str(Path(__file__).parent.parent.parent / 'src'))
from funcoes_limpando_dados_imoveis import (
    limpar_metragem,
    limpar_valor_venda,
    limpar_valor_condominio,
    limpar_banheiros,
    limpar_quartos,
    limpar_vagas,
    limpar_idade,
    converter_para_data,
    classificar_tipo_imovel,
    reclassificar_outros,
    limpa_endereco_apply_imovelweb,
    preencher_todas_coordenadas,
    geocodificar_dataframe,
)
from preprocessador import PreprocessadorFactory, Avaliador
from otimizador_optuna import FactoryModelos, OtimizadorOptuna

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ── Configuração ──────────────────────────────────────────────────────
cidade = os.getenv("CIDADE_PASTA")
MES_REF = os.getenv("MES_REF") or datetime.now().strftime("%Y-%m")
PASTA_DADOS = Path(__file__).parent.parent.parent / 'dados' / cidade
TARGET = "idade"
N_TRIALS = 80
N_FOLDS = 5

cidade_limpeza = os.getenv("CIDADE_LIMPEZA")
cidade_localizacao = os.getenv("CIDADE_LOCALIZACAO")
estado_limpeza = os.getenv("ESTADO_LIMPEZA")
estado_localizacao = os.getenv("ESTADO_LOCALIZACAO")
BATCH = int(os.getenv("BATCH_LIMPEZA", "100"))

MAPA_BAIRROS = {
    'pirabeiraba': ['pirabeiraba', 'dona francisca', 'distrito industrial norte'],
    'distrito industrial': ['distrito industrial', 'zona industrial'],
    'area rural': ['area rural', 'rural'],
    'vila nova': ['vila nova'],
    's/b': ['localizacao'],
}

NUMERIC_FEATURES = [
    "metragem", "quartos", "vagas",
    "valor_imovel", "condominio",
    "preco_por_m2", "dias_publicacao",
]

CATEGORICAL_FEATURES = ["bairro", "tipo_imovel"]

CARAC_COMUM_FLAGS = [
    "elevador", "piscina", "churrasqueira_parrilla",
    "playground", "fitness_sala_de_ginastica",
]

CARAC_PRIVADA_FLAGS = [
    "varanda", "lavanderia", "piscina", "ar_condicionado",
]


def _normalizar_item(item):
    return (
        item.lower()
        .replace(" ", "_")
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
    )


def processar_flags(lista, prefixo, flags):
    if not isinstance(lista, list) or len(lista) == 0:
        return {f"{prefixo}_{f}": 0 for f in flags}
    itens_norm = [_normalizar_item(i) for i in lista]
    return {f"{prefixo}_{f}": 1 if f in itens_norm else 0 for f in flags}


# ── Funções auxiliares ────────────────────────────────────────────────
def normalizar_bairros(bairro, mapeamento):
    if not isinstance(bairro, str):
        return bairro
    b = bairro.strip().lower()
    if re.match(r'^\d+$', b) or b in ("s/n", "s/b", ""):
        return "s/b"
    b_norm = unicodedata.normalize('NFD', b).encode('ascii', 'ignore').decode('utf-8')
    for nome_correto, variacoes in mapeamento.items():
        if any(v in b_norm for v in variacoes):
            return nome_correto
    if "bairro" in b:
        b = b.split("bairro")[-1].strip(" ,.-")
        if b:
            return b
    return bairro


async def limpar_dados_idade(
    pasta_dados,
    name_arquivo_imovelweb,
    cidade_limpeza='joinville',
    cidade_localizacao='Joinville',
    estado_limpeza='sc',
    estado_localizacao='SC',
    MAPA_BAIRROS=None,
    batch=100,
    pais='Brasil',
):
    logger.info("Iniciando limpeza de dados para preditor de idade...")

    arquivos = list(pasta_dados.glob(name_arquivo_imovelweb))
    if not arquivos:
        logger.warning("Nenhum arquivo imovelweb encontrado: %s", name_arquivo_imovelweb)
        return pd.DataFrame()

    arquivo_ref = max(arquivos, key=lambda f: f.stem.split('_')[-1])
    logger.info("Arquivo imovelweb: %s", arquivo_ref.name)

    pd_data = pd.read_parquet(arquivo_ref)

    pd_data['fonte'] = 'imovelweb'
    endereco_limpo = pd_data['endereco'].apply(
        lambda x: limpa_endereco_apply_imovelweb(x, cidade_limpeza, estado_limpeza)
    )
    overlap = set(pd_data.columns) & set(endereco_limpo.columns)
    if overlap:
        pd_data = pd_data.drop(columns=list(overlap))
    if 'uf' in pd_data.columns and 'estado' in endereco_limpo.columns:
        pd_data = pd_data.drop(columns=['uf'])
    pd_data = pd.concat([pd_data, endereco_limpo], axis=1)
    if pd_data.columns.duplicated().any():
        pd_data = pd_data.loc[:, ~pd_data.columns.duplicated(keep='last')]

    logger.info("Dados imovelweb: %d linhas", len(pd_data))

    pd_data = pd_data[pd_data['cidade'].isin([cidade_limpeza])]
    logger.info("Após filtro cidade: %d linhas", len(pd_data))

    if pd_data.empty:
        logger.warning("Nenhum registro para a cidade %s", cidade_limpeza)
        return pd.DataFrame()

    pd_data = pd_data.drop_duplicates(subset=['url'])
    pd_data = pd_data[pd_data['valor_imovel'].notna()]
    pd_data = pd_data.dropna(thresh=10)
    logger.info("Após remover duplicatas e nulos: %d linhas", len(pd_data))

    pd_data = pd_data[pd_data['estado'] == estado_limpeza]
    logger.info("Após filtro estado: %d linhas", len(pd_data))

    pd_data['metragem'] = pd_data['metragem'].apply(limpar_metragem)
    logger.info("Metragem limpa")

    try:
        pd_data['valor_venda'] = pd_data['valor_venda'].apply(limpar_valor_venda)
    except Exception:
        pd_data['valor_imovel'] = pd_data['valor_imovel'].apply(limpar_valor_venda)
    logger.info("Valor imóvel limpo")

    pd_data['condominio'] = pd_data['condominio'].apply(limpar_valor_condominio)
    logger.info("Condomínio limpo")

    pd_data['data_criacao'] = pd_data['data_criacao'].apply(converter_para_data)
    pd_data['dias_publicacao'] = (
        pd.to_datetime(datetime.now().strftime('%Y-%m-%d'))
        - pd.to_datetime(pd_data['data_criacao'], format='%d/%m/%Y', errors='coerce')
    ).dt.days
    logger.info("Data de publicação limpa")

    pd_data['banheiros'] = pd_data['banheiros'].apply(limpar_banheiros)
    pd_data['quartos'] = pd_data['quartos'].apply(limpar_quartos)
    pd_data['vagas'] = pd_data['vagas'].apply(limpar_vagas)
    logger.info("Banheiros, quartos, vagas limpos")

    if 'idade' in pd_data.columns:
        pd_data['idade'] = pd_data['idade'].apply(limpar_idade)
        logger.info("Idade limpa")
    else:
        pd_data['idade'] = pd.NA
        logger.info("Coluna idade criada como pd.NA")

    pd_data['tipo_imovel'] = pd_data['titulo'].apply(classificar_tipo_imovel)
    mask = pd_data['tipo_imovel'] == 'outros'
    pd_data.loc[mask, 'tipo_imovel'] = (
        pd_data.loc[mask, 'descricao'].apply(reclassificar_outros)
    )
    logger.info("Tipo de imóvel classificado")

    cache_path = pasta_dados.parent / "geocode_cache.parquet"
    pd_data, timeout_ocorrido = await preencher_todas_coordenadas(
        pd_data, batch_size=batch, cidade=cidade_localizacao,
        estado=estado_localizacao, pais=pais, cache_path=cache_path,
    )
    logger.info("Geocodificação concluída")

    pd_data['preco_por_m2'] = pd_data['valor_imovel'] / pd_data['metragem']
    logger.info("preco_por_m2 criado")

    def classificar_dentro_bairro(grupo):
        p25 = grupo["preco_por_m2"].quantile(0.25)
        p50 = grupo["preco_por_m2"].quantile(0.50)
        p75 = grupo["preco_por_m2"].quantile(0.75)

        def faixa(val):
            if val <= p25:
                return "barato"
            elif val <= p50:
                return "medio_baixo"
            elif val <= p75:
                return "medio_alto"
            else:
                return "alto_padrao"

        grupo = grupo.copy()
        grupo["faixa"] = grupo["preco_por_m2"].apply(faixa)
        grupo["p25_bairro"] = p25
        grupo["p50_bairro"] = p50
        grupo["p75_bairro"] = p75
        return grupo

    faixas = pd_data.groupby(["bairro", "tipo_imovel"], group_keys=False).apply(classificar_dentro_bairro)
    pd_data = pd.concat([pd_data, faixas[['faixa', 'p25_bairro', 'p50_bairro', 'p75_bairro']]], axis=1)

    pd_data["desvio_mediana"] = round(
        (pd_data["preco_por_m2"] - pd_data["p50_bairro"]) / pd_data["p50_bairro"], 2
    )
    logger.info("Faixas de preço por bairro criadas")

    if MAPA_BAIRROS:
        pd_data['bairro'] = pd_data['bairro'].apply(normalizar_bairros, args=(MAPA_BAIRROS,))

    for col in ('lat', 'lng'):
        if col in pd_data.columns:
            pd_data[col] = pd.to_numeric(pd_data[col], errors='coerce')

    pd_data = pd_data.groupby('bairro').filter(lambda x: len(x) > 1)

    logger.info("Limpeza concluída: %d linhas, %d colunas", len(pd_data), len(pd_data.columns))
    return pd_data


class _TrialStub:
    def __init__(self, params):
        self.params = params
        self.number = 0

    def suggest_float(self, name, *args, **kwargs):
        return self.params.get(name, args[0])

    def suggest_int(self, name, *args, **kwargs):
        return self.params.get(name, args[0])

    def suggest_categorical(self, name, *args, **kwargs):
        return self.params.get(name, args[0][0] if args else None)


# ══════════════════════════════════════════════════════════════════════
logger.info("=" * 60)
logger.info("INICIANDO TREINAMENTO PREDITOR DE IDADE")
logger.info("Cidade: %s | Mês ref: %s", cidade, MES_REF)
logger.info("=" * 60)

# ── 1. Verificar dado bruto ───────────────────────────────────────────
ARQUIVO_DADOS = PASTA_DADOS / f"{cidade}_imovelweb_{MES_REF}.parquet"
logger.info("[ETAPA 1/11] Verificando arquivo bruto: %s", ARQUIVO_DADOS.name)

if not ARQUIVO_DADOS.exists():
    logger.warning("Arquivo bruto não encontrado para %s. Pulando treinamento.", MES_REF)
    sys.exit(0)

logger.info("✓ Arquivo bruto encontrado")

# ── 2. Limpar dados ──────────────────────────────────────────────────
logger.info("[ETAPA 2/11] Limpando dados com limpar_dados_idade()...")
df = asyncio.run(limpar_dados_idade(
    pasta_dados=PASTA_DADOS,
    name_arquivo_imovelweb=f'{cidade}_imovelweb_*.parquet',
    cidade_limpeza=cidade_limpeza,
    cidade_localizacao=cidade_localizacao,
    estado_limpeza=estado_limpeza,
    estado_localizacao=estado_localizacao,
    MAPA_BAIRROS=MAPA_BAIRROS,
    batch=BATCH,
))

if df.empty:
    logger.warning("Nenhum dado limpo gerado. Pulando treinamento.")
    sys.exit(0)

logger.info("✓ Dados limpos: %d linhas", len(df))

# ── 3. Filtrar idade válida ───────────────────────────────────────────
logger.info("[ETAPA 3/11] Filtrando idade válida...")
df = df.dropna(subset=[TARGET])
df[TARGET] = df[TARGET].astype(float)
logger.info("Registros com idade válida: %d", len(df))

if len(df) < 50:
    logger.warning("Dados insuficientes: %d registros. Mínimo: 50. Pulando.", len(df))
    sys.exit(0)

logger.info("✓ Dados suficientes para treino")

# ── 4. Preparar features ─────────────────────────────────────────────
logger.info("[ETAPA 4/11] Preparando features...")
numeric_features = [f for f in NUMERIC_FEATURES if f in df.columns]
categorical_features = [f for f in CATEGORICAL_FEATURES if f in df.columns]

for col in numeric_features:
    df[col] = pd.to_numeric(df[col], errors="coerce")

if "bairro" in df.columns:
    df["bairro"] = df["bairro"].fillna("desconhecido").astype(str)

df["quartos_por_metro"] = df.get("quartos", 0) / df["metragem"].replace(0, np.nan)
df["vagas_por_metro"] = df.get("vagas", 0) / df["metragem"].replace(0, np.nan)
numeric_features += ["quartos_por_metro", "vagas_por_metro"]

df["n_carac_comum"] = df["caracteristicas_comum"].apply(lambda x: len(x) if isinstance(x, list) else 0)
df["n_carac_privada"] = df["caracteristicas_privativa"].apply(lambda x: len(x) if isinstance(x, list) else 0)
numeric_features += ["n_carac_comum", "n_carac_privada"]

for idx, row in df.iterrows():
    for flag, val in processar_flags(row.get("caracteristicas_comum", []), "comum", CARAC_COMUM_FLAGS).items():
        df.at[idx, flag] = val
    for flag, val in processar_flags(row.get("caracteristicas_privativa", []), "priv", CARAC_PRIVADA_FLAGS).items():
        df.at[idx, flag] = val

for prefixo, flags in [("comum", CARAC_COMUM_FLAGS), ("priv", CARAC_PRIVADA_FLAGS)]:
    for f in flags:
        col = f"{prefixo}_{f}"
        if col in df.columns:
            df[col] = df[col].astype(int)
            numeric_features.append(col)

logger.info("Features numéricas (%d): %s", len(numeric_features), numeric_features)
logger.info("Features categóricas (%d): %s", len(categorical_features), categorical_features)

# ── 5. Split train/test ──────────────────────────────────────────────
logger.info("[ETAPA 5/11] Dividindo train/test (80/20)...")
all_features = numeric_features + categorical_features
X = df[all_features].copy()
y = df[TARGET].copy()

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
logger.info("Train: %d | Test: %d", len(X_train), len(X_test))
logger.info("Target stats: mean=%.2f, std=%.2f, min=%.0f, max=%.0f",
            y.mean(), y.std(), y.min(), y.max())

# ── 6. Criar pré-processador ─────────────────────────────────────────
logger.info("[ETAPA 6/11] Criando pré-processador...")
CATEGORICAL_MAX_CATEGORIES = {"bairro": 10, "tipo_imovel": 4}
preprocessador = PreprocessadorFactory(
    numeric_features=numeric_features,
    categorical_features=categorical_features,
    categorical_max_categories=CATEGORICAL_MAX_CATEGORIES,
).criar()
logger.info("✓ Pré-processador criado")

# ── 7. Otimizar com Optuna ──────────────────────────────────────────
logger.info("[ETAPA 7/11] Iniciando otimização Optuna (%d trials, %d folds)...", N_TRIALS, N_FOLDS)

factory = FactoryModelos(random_state=42)
modelos_candidatos = {
    "ridge": factory.ridge,
    "random_forest": factory.random_forest,
    "gradient_boosting": factory.gradient_boosting,
    "lightgbm": factory.lightgbm,
    "catboost": factory.catboost,
    "hist_gb": factory.hist_gb,
}

logger.info("Modelos candidatos: %s", list(modelos_candidatos.keys()))

otimizador = OtimizadorOptuna(
    preprocessador=preprocessador,
    X=X_train, y=y_train,
    mlflow_manager=None,
    n_trials=N_TRIALS, n_folds=N_FOLDS,
    random_state=42,
)
melhores_params, estudos = otimizador.otimizar_varios(modelos_candidatos, log_trials=False)
logger.info("✓ Otimização concluída")

# ── 8. Selecionar melhor modelo ──────────────────────────────────────
logger.info("[ETAPA 8/11] Selecionando melhor modelo...")
melhor_nome = min(melhores_params, key=lambda k: estudos[k].best_value if estudos[k] else float("inf"))
melhor_rmse = estudos[melhor_nome].best_value if estudos[melhor_nome] else float("inf")
melhor_params = melhores_params[melhor_nome]
logger.info("Melhor modelo: %s | RMSE CV: %.2f", melhor_nome, melhor_rmse)
logger.info("Hiperparâmetros: %s", melhor_params)

# ── 9. Treinar modelo final ────────────────────────────────────────
logger.info("[ETAPA 9/11] Treinando modelo final com todos os dados...")
modelo_fn = getattr(factory, melhor_nome)
pipeline_final = Pipeline([
    ("preprocessador", PreprocessadorFactory(
        numeric_features=numeric_features,
        categorical_features=categorical_features,
        categorical_max_categories=CATEGORICAL_MAX_CATEGORIES,
    ).criar()),
    ("modelo", modelo_fn(_TrialStub(melhor_params))),
])
pipeline_final.fit(X, y)
logger.info("✓ Modelo treinado com %d amostras", len(X))

# ── 10. Avaliar ──────────────────────────────────────────────────────
logger.info("[ETAPA 10/11] Avaliando no conjunto de teste...")
y_pred = pipeline_final.predict(X_test)
metricas_teste = Avaliador.metricas("TestIdade", y_test.values, y_pred)

# ── 11. Salvar modelo + metadados ───────────────────────────────────
logger.info("[ETAPA 11/11] Salvando modelo e metadados...")
ARQUIVO_MODELO = PASTA_DADOS / f"{cidade}_preditor_idade_{MES_REF}.joblib"
ARQUIVO_METADADOS = PASTA_DADOS / f"{cidade}_preditor_idade_{MES_REF}.json"

logger.info("Salvando modelo: %s", ARQUIVO_MODELO.name)
joblib.dump(pipeline_final, ARQUIVO_MODELO)
logger.info("✓ Modelo salvo")

logger.info("Salvando metadados: %s", ARQUIVO_METADADOS.name)
metadados = {
    "modelo": melhor_nome,
    "params": melhor_params,
    "features_numericas": numeric_features,
    "features_categoricas": categorical_features,
    "metricas_cv": {"rmse": float(melhor_rmse), "n_folds": N_FOLDS, "n_trials": N_TRIALS},
    "metricas_teste": metricas_teste,
    "n_amostras": len(X),
    "data_treino": datetime.now().isoformat(),
    "arquivo_dados": str(ARQUIVO_DADOS),
}

with open(ARQUIVO_METADADOS, "w", encoding="utf-8") as f:
    json.dump(metadados, f, indent=2, ensure_ascii=False)
logger.info("✓ Metadados salvos")

# ── Resumo final ─────────────────────────────────────────────────────
logger.info("=" * 60)
logger.info("TREINAMENTO CONCLUÍDO COM SUCESSO")
logger.info("Modelo: %s", ARQUIVO_MODELO.name)
logger.info("Metadados: %s", ARQUIVO_METADADOS.name)
logger.info("RMSE teste: %.2f anos", metricas_teste['rmse'])
logger.info("MAE teste: %.2f anos", metricas_teste['mae'])
logger.info("R² teste: %.3f", metricas_teste['r2'])
logger.info("=" * 60)
