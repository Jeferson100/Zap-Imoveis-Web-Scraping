"""
TESTE ABRANGENTE: Multiplas Features x Multiplas Transformacoes x Multiplos Modelos

Executa todas as combinacoes possiveis entre:
  - Conjuntos de features (basicas, com engenharia, com localizacao, etc.)
  - Tratamentos de dados (raw, standard, robust, sem outliers, log target)
  - Modelos (Linear, Ridge, Lasso, ElasticNet, RandomForest, GBM, LightGBM, CatBoost, SVR, MLP)

Uso:
    uv run python scripts/testar_combinacoes.py
"""

import json
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# === ML/DL imports ===
from sklearn.linear_model import LinearRegression, Ridge, Lasso, ElasticNet
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.preprocessing import StandardScaler, RobustScaler, MinMaxScaler, FunctionTransformer
from sklearn.model_selection import cross_val_score, KFold
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer

try:
    from lightgbm import LGBMRegressor
except ImportError:
    LGBMRegressor = None

try:
    from catboost import CatBoostRegressor
except ImportError:
    CatBoostRegressor = None

try:
    import xgboost as xgb
    XGBRegressor = xgb.XGBRegressor
except ImportError:
    XGBRegressor = None

try:
    import keras
    from keras import layers
except ImportError:
    keras = None

# ============================================================
# 1. CARREGAMENTO DOS DADOS
# ============================================================

BASE_DIR = Path(__file__).parent.parent
PASTA_DADOS = BASE_DIR / "dados" / "joinville"


def carregar_dados() -> pd.DataFrame:
    arquivos = sorted(PASTA_DADOS.glob("joinville_com_ind_local_*.parquet"))
    if not arquivos:
        arquivos = sorted(PASTA_DADOS.glob("joinville_imoveis_limpo_*.parquet"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo parquet encontrado em {PASTA_DADOS}")
    caminho = arquivos[-1]
    print(f"Carregando: {caminho.name}")
    df = pd.read_parquet(caminho)
    print(f"Shape: {df.shape}")
    return df


# ============================================================
# 2. ENGENHARIA DE FEATURES
# ============================================================

def criar_features(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = df_raw.copy()

    # Conversao de tipos
    for col in df.columns:
        if df[col].dtype == "object":
            try:
                df[col] = pd.to_numeric(df[col], errors="ignore")
            except:
                pass

    # Preencher nulos em colunas numericas uteis
    for col in ["condominio", "iptu", "vagas"]:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    # Log do target (preco / m2)
    if "preco_por_m2" in df.columns:
        df["log_preco_por_m2"] = np.log1p(df["preco_por_m2"])

    if "valor_imovel" in df.columns:
        df["log_valor_imovel"] = np.log1p(df["valor_imovel"])

    # Estatisticas por bairro (target encoding suave)
    if "bairro" in df.columns and "preco_por_m2" in df.columns:
        bairro_stats = df.groupby("bairro")["preco_por_m2"].agg(["mean", "median", "std"]).fillna(0)
        df["preco_m2_bairro_mean"] = df["bairro"].map(bairro_stats["mean"])
        df["preco_m2_bairro_median"] = df["bairro"].map(bairro_stats["median"])

        bairro_rank = df.groupby("bairro")["preco_por_m2"].median().rank()
        df["bairro_rank"] = df["bairro"].map(bairro_rank)

    # Derivadas
    df["quartos_por_metro"] = df["quartos"] / (df["metragem"] + 1)
    df["vagas_por_metro"] = df["vagas"] / (df["metragem"] + 1)
    df["banheiros_por_quarto"] = df["banheiros"] / (df["quartos"] + 1)
    df["condominio_por_metro"] = df["condominio"] / (df["metragem"] + 1)
    df["valor_mensal_total"] = df["condominio"].fillna(0) + df["iptu"].fillna(0)
    df["tem_condominio"] = (df["condominio"] > 0).astype(int)

    # Interacao area x quartos
    df["area_por_quarto"] = df["metragem"] / (df["quartos"] + 1)

    return df


# ============================================================
# 3. DEFINICAO DOS CONJUNTOS DE FEATURES
# ============================================================

def get_feature_sets(df: pd.DataFrame) -> Dict[str, List[str]]:
    """Retorna dicionario nome -> lista de colunas."""
    
    cols_numeric = df.select_dtypes(include=[np.number]).columns.tolist()
    cols_excluir = [
        "valor_imovel", "preco_por_m2", "log_valor_imovel", "log_preco_por_m2",
        "lat", "lng", "p25_bairro", "p50_bairro", "p75_bairro", "desvio_mediana",
        "dias_publicacao",
    ]
    cols_numeric = [c for c in cols_numeric if c not in cols_excluir]

    sets = {}

    # S1 - features basicas do imovel
    s1 = [c for c in ["metragem", "quartos", "banheiros", "vagas"] if c in cols_numeric]
    if s1:
        sets["basicas"] = s1

    # S2 - basicas + condominio/iptu
    s2 = s1 + [c for c in ["condominio", "iptu", "tem_condominio", "valor_mensal_total"] if c in cols_numeric]
    sets["basicas_financeiro"] = s2

    # S3 - S2 + scores de localizacao
    score_cols = [c for c in cols_numeric if "score" in c.lower()]
    s3 = s2 + score_cols
    sets["basicas_financeiro_local"] = s3

    # S4 - S3 + features derivadas (razoes)
    razao_cols = [c for c in cols_numeric if "por_metro" in c or "por_quarto" in c or "area_por" in c]
    s4 = s3 + razao_cols
    sets["todas_numericas"] = s4

    # S5 - S4 + bairro encoding
    bairro_cols = [c for c in cols_numeric if "bairro" in c.lower()]
    s5 = s4 + bairro_cols
    sets["todas_com_bairro_encoding"] = s5

    return sets


# ============================================================
# 4. DEFINICAO DOS TRATAMENTOS
# ============================================================

def get_treatments() -> Dict[str, Dict]:
    return {
        "raw": {
            "descricao": "Sem normalizacao",
        },
        "standard": {
            "descricao": "StandardScaler",
            "scaler": StandardScaler(),
        },
        "robust": {
            "descricao": "RobustScaler",
            "scaler": RobustScaler(),
        },
        "minmax": {
            "descricao": "MinMaxScaler",
            "scaler": MinMaxScaler(),
        },
    }


# ============================================================
# 5. DEFINICAO DOS MODELOS
# ============================================================

def get_models() -> Dict[str, Any]:
    modelos = {
        "LinearRegression": LinearRegression(),
        "Ridge": Ridge(alpha=1.0),
        "Lasso": Lasso(alpha=0.001, max_iter=10000),
        "ElasticNet": ElasticNet(alpha=0.001, l1_ratio=0.5, max_iter=10000),
    }

    modelos["RandomForest"] = RandomForestRegressor(
        n_estimators=100, max_depth=12, random_state=42, n_jobs=-1
    )
    modelos["GradientBoosting"] = GradientBoostingRegressor(
        n_estimators=100, max_depth=5, learning_rate=0.1, random_state=42
    )

    if LGBMRegressor is not None:
        modelos["LightGBM"] = LGBMRegressor(
            n_estimators=100, max_depth=8, learning_rate=0.1,
            random_state=42, n_jobs=-1, verbose=-1,
        )

    if CatBoostRegressor is not None:
        modelos["CatBoost"] = CatBoostRegressor(
            iterations=100, depth=6, learning_rate=0.1,
            random_seed=42, verbose=0,
        )

    if XGBRegressor is not None:
        modelos["XGBoost"] = XGBRegressor(
            n_estimators=100, max_depth=6, learning_rate=0.1,
            random_state=42, n_jobs=-1, verbosity=0,
        )

    if keras is not None:
        modelos["MLP_Keras"] = "keras"

    return modelos


# ============================================================
# 6. PREPARACAO DOS DADOS PARA CADA TESTE
# ============================================================

def preparar_dados(
    df: pd.DataFrame,
    feature_cols: List[str],
    target_col: str,
    tratamento: str,
    trat_config: Dict,
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], int]:
    """Prepara X, y aplicando limpeza e opcionalmente scaling."""

    cols_validas = [c for c in feature_cols if c in df.columns]
    if not cols_validas:
        return None, None, 0

    X = df[cols_validas].copy()
    y = df[target_col].copy()

    # Forcar numerico
    X = X.apply(pd.to_numeric, errors="coerce")
    y = pd.to_numeric(y, errors="coerce")

    # Inf -> NaN
    X = X.replace([np.inf, -np.inf], np.nan)
    y = y.replace([np.inf, -np.inf], np.nan)

    # Remover linhas com NaN
    mask = X.notna().all(axis=1) & y.notna()
    X = X[mask]
    y = y[mask]

    # Remover valores extremos no target
    limite = y.quantile(0.99)
    mask_fim = y < limite
    X = X[mask_fim]
    y = y[mask_fim]

    if len(X) < 50:
        return None, None, 0

    n_samples = len(X)

    # Aplicar scaler se configurado
    scaler = trat_config.get("scaler")
    if scaler is not None:
        scaler = scaler.__class__()  # fresh copy
        X = pd.DataFrame(scaler.fit_transform(X), columns=X.columns, index=X.index)

    return X.values, y.values, n_samples


# ============================================================
# 7. EXECUTOR DE TESTES
# ============================================================

def executar_testes(
    df: pd.DataFrame,
    feature_sets: Dict[str, List[str]],
    tratamentos: Dict[str, Dict],
    modelos: Dict[str, Any],
    target_col: str = "preco_por_m2",
    cv_folds: int = 3,
) -> pd.DataFrame:
    """Percorre todas as combinacoes e retorna DataFrame com resultados."""

    resultados = []
    total = len(feature_sets) * len(tratamentos) * len(modelos)
    atual = 0
    cv = KFold(n_splits=cv_folds, shuffle=True, random_state=42)

    print(f"\n{'='*70}")
    print(f"Total de combinacoes: {total}")
    print(f"Target: {target_col}")
    print(f"{'='*70}\n")

    for feat_nome, feat_cols in feature_sets.items():
        for trat_nome, trat_conf in tratamentos.items():
            X, y, n = preparar_dados(df, feat_cols, target_col, trat_nome, trat_conf)

            if X is None:
                for mod_nome in modelos:
                    atual += 1
                    resultados.append({
                        "features": feat_nome,
                        "tratamento": trat_nome,
                        "modelo": mod_nome,
                        "r2": np.nan,
                        "mae": np.nan,
                        "rmse": np.nan,
                        "n_amostras": 0,
                        "erro": "dados insuficientes",
                    })
                continue

            for mod_nome, modelo in modelos.items():
                atual += 1
                t0 = time.time()

                if mod_nome == "MLP_Keras" and keras is not None:
                    # MLP com Keras - usa pipeline com scaler interno
                    resultado = _testar_keras(X, y, cv, feat_nome, trat_nome)
                    resultados.append(resultado)
                else:
                    resultado = _testar_sklearn(modelo, X, y, cv, feat_nome, trat_nome, mod_nome)
                    resultados.append(resultado)

                elapsed = time.time() - t0
                r2_str = f"{resultado['r2']:.4f}" if not np.isnan(resultado["r2"]) else "ERRO"
                sys.stdout.write(
                    f"\r[{atual}/{total}] {feat_nome:>28} | {trat_nome:>10} | {mod_nome:>20} | "
                    f"R2={r2_str} | n={resultado['n_amostras']:>5} | {elapsed:.1f}s   "
                )
                sys.stdout.flush()

    print(f"\n\n{'='*70}")
    print(f"Testes concluidos: {len(resultados)} combinacoes")
    print(f"{'='*70}")

    df_res = pd.DataFrame(resultados)
    return df_res


def _testar_sklearn(modelo, X, y, cv, feat_nome, trat_nome, mod_nome=None):
    try:
        scores_r2 = cross_val_score(modelo, X, y, cv=cv, scoring="r2", n_jobs=-1)
        scores_mae = cross_val_score(modelo, X, y, cv=cv, scoring="neg_mean_absolute_error", n_jobs=-1)
        scores_rmse = cross_val_score(modelo, X, y, cv=cv, scoring="neg_root_mean_squared_error", n_jobs=-1)
        return {
            "features": feat_nome,
            "tratamento": trat_nome,
            "modelo": modelo.__class__.__name__,
            "r2": scores_r2.mean(),
            "mae": -scores_mae.mean(),
            "rmse": -scores_rmse.mean(),
            "n_amostras": len(X),
            "erro": "",
        }
    except Exception as e:
        return {
            "features": feat_nome,
            "tratamento": trat_nome,
            "modelo": modelo.__class__.__name__ if hasattr(modelo, "__class__") else str(modelo),
            "r2": np.nan,
            "mae": np.nan,
            "rmse": np.nan,
            "n_amostras": len(X),
            "erro": str(e)[:100],
        }


def _testar_keras(X, y, cv, feat_nome, trat_nome):
    try:
        from sklearn.preprocessing import StandardScaler as SKStandardScaler
        r2_scores, mae_scores, rmse_scores = [], [], []
        n_amostras = len(X)

        for train_idx, test_idx in cv.split(X):
            X_tr, X_te = X[train_idx], X[test_idx]
            y_tr, y_te = y[train_idx], y[test_idx]

            scaler = SKStandardScaler()
            X_tr_s = scaler.fit_transform(X_tr)
            X_te_s = scaler.transform(X_te)

            model = keras.Sequential([
                layers.Input(shape=(X_tr_s.shape[1],)),
                layers.Dense(64, activation="relu"),
                layers.Dropout(0.2),
                layers.Dense(32, activation="relu"),
                layers.Dense(1),
            ])
            model.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse", metrics=["mae"])
            model.fit(X_tr_s, y_tr, validation_data=(X_te_s, y_te),
                      epochs=50, batch_size=64, verbose=0,
                      callbacks=[keras.callbacks.EarlyStopping(monitor="val_loss", patience=5, restore_best_weights=True)])

            pred = model.predict(X_te_s, verbose=0).ravel()
            r2_scores.append(1 - np.sum((y_te - pred) ** 2) / np.sum((y_te - y_te.mean()) ** 2))
            mae_scores.append(np.mean(np.abs(y_te - pred)))
            rmse_scores.append(np.sqrt(np.mean((y_te - pred) ** 2)))

        return {
            "features": feat_nome,
            "tratamento": trat_nome,
            "modelo": "MLP_Keras",
            "r2": np.mean(r2_scores),
            "mae": np.mean(mae_scores),
            "rmse": np.mean(rmse_scores),
            "n_amostras": n_amostras,
            "erro": "",
        }
    except Exception as e:
        return {
            "features": feat_nome,
            "tratamento": trat_nome,
            "modelo": "MLP_Keras",
            "r2": np.nan,
            "mae": np.nan,
            "rmse": np.nan,
            "n_amostras": len(X) if "X" in dir() else 0,
            "erro": str(e)[:100],
        }


# ============================================================
# 8. RELATORIO
# ============================================================

def gerar_relatorio(df_res: pd.DataFrame):
    print(f"\n{'='*80}")
    print("RELATORIO FINAL - TESTE ABRANGENTE")
    print(f"{'='*80}")

    # Remover falhas
    df_ok = df_res.dropna(subset=["r2"]).copy()
    df_ok = df_ok[df_ok["r2"].notna() & (df_ok["erro"] == "")]
    if df_ok.empty:
        print("\nNenhum teste obteve sucesso. Verifique os dados.")
        return df_res

    print(f"\nTestes com sucesso: {len(df_ok)} / {len(df_res)}")

    # Top 15
    top15 = df_ok.nlargest(15, "r2")
    linha_sep = "-" * 80
    print(f"\n{linha_sep}")
    print("TOP 15 COMBINACOES (por R2)")
    print(linha_sep)
    print(f"{'#':>3} {'Features':>28} {'Tratamento':>12} {'Modelo':>22} {'R2':>8} {'MAE':>10} {'RMSE':>10} {'n':>6}")
    print(linha_sep)
    for i, (_, row) in enumerate(top15.iterrows(), 1):
        print(f"{i:>3} {row['features']:>28} {row['tratamento']:>12} {row['modelo']:>22} "
              f"{row['r2']:>8.4f} {row['mae']:>10.0f} {row['rmse']:>10.0f} {int(row['n_amostras']):>6}")

    # Melhor modelo
    print(f"\n{linha_sep}")
    print("MELHOR COMBINACAO:")
    print(f"  Features:    {best['features']}")
    print(f"  Tratamento:  {best['tratamento']}")
    print(f"  Modelo:      {best['modelo']}")
    print(f"  R2:          {best['r2']:.4f}")
    print(f"  MAE:         R$ {best['mae']:,.0f}")
    print(f"  RMSE:        R$ {best['rmse']:,.0f}")
    print(f"  Amostras:    {int(best['n_amostras'])}")

    # Resumo por modelo
    print(f"\n{linha_sep}")
    print("RESUMO POR MODELO (media R2)")
    print(linha_sep)
    resumo_modelo = df_ok.groupby("modelo").agg(
        r2_medio=("r2", "mean"),
        r2_max=("r2", "max"),
        r2_std=("r2", "std"),
        n_testes=("r2", "count"),
    ).sort_values("r2_medio", ascending=False)
    print(f"{'Modelo':>22} {'R2_medio':>10} {'R2_max':>8} {'R2_std':>8} {'Testes':>7}")
    print(linha_sep)
    for modelo, row in resumo_modelo.iterrows():
        print(f"{modelo:>22} {row['r2_medio']:>10.4f} {row['r2_max']:>8.4f} {row['r2_std']:>8.4f} {int(row['n_testes']):>7}")

    # Resumo por features
    print(f"\n{linha_sep}")
    print("RESUMO POR CONJUNTO DE FEATURES (media R2)")
    print(linha_sep)
    resumo_feat = df_ok.groupby("features").agg(
        r2_medio=("r2", "mean"),
        r2_max=("r2", "max"),
        n_testes=("r2", "count"),
    ).sort_values("r2_medio", ascending=False)
    for feat, row in resumo_feat.iterrows():
        print(f"{feat:>28}  R2_medio={row['r2_medio']:.4f}  R2_max={row['r2_max']:.4f}  testes={int(row['n_testes'])}")

    # Resumo por tratamento
    print(f"\n{linha_sep}")
    print("RESUMO POR TRATAMENTO (media R2)")
    print(linha_sep)
    resumo_trat = df_ok.groupby("tratamento").agg(
        r2_medio=("r2", "mean"),
        r2_max=("r2", "max"),
        n_testes=("r2", "count"),
    ).sort_values("r2_medio", ascending=False)
    for trat, row in resumo_trat.iterrows():
        print(f"{trat:>12}  R2_medio={row['r2_medio']:.4f}  R2_max={row['r2_max']:.4f}  testes={int(row['n_testes'])}")

    return df_res


# ============================================================
# 9. MAIN
# ============================================================

def main():
    print("=" * 70)
    print("TESTE ABRANGENTE: FEATURES x TRATAMENTOS x MODELOS")
    print("=" * 70)

    # Carregar
    df_raw = carregar_dados()

    # Engenharia
    print("\nCriando features derivadas...")
    df = criar_features(df_raw)
    print(f"Dataset final: {df.shape}")
    print(f"Colunas numericas: {len(df.select_dtypes(include=[np.number]).columns)}")

    # Target
    target = "preco_por_m2"
    if target not in df.columns:
        target = "valor_imovel"
    print(f"Target: {target}")

    # Feature sets
    feature_sets = get_feature_sets(df)
    print(f"\nConjuntos de features: {len(feature_sets)}")
    for nome, cols in feature_sets.items():
        print(f"  {nome:>30}: {len(cols)} features -> {cols}")

    # Tratamentos
    tratamentos = get_treatments()
    print(f"\nTratamentos: {len(tratamentos)}")
    for nome, conf in tratamentos.items():
        print(f"  {nome:>12}: {conf['descricao']}")

    # Modelos
    modelos = get_models()
    print(f"\nModelos: {len(modelos)}")
    for nome in modelos:
        print(f"  {nome}")

    # Executar
    t_total = time.time()
    df_resultados = executar_testes(df, feature_sets, tratamentos, modelos, target)
    t_total = time.time() - t_total
    print(f"\nTempo total: {t_total / 60:.1f} min")

    # Relatorio
    gerar_relatorio(df_resultados)

    # Salvar
    caminho_res = BASE_DIR / "scripts" / "resultados_combinacoes.csv"
    df_resultados.to_csv(caminho_res, index=False)
    print(f"\nResultados salvos em: {caminho_res}")

    return df_resultados


if __name__ == "__main__":
    main()
