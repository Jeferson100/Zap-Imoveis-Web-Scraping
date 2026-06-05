import json, uuid, copy

NOTEBOOK_PATH = r"C:\Users\jefer\Documents\Ciencia-de-dados\Preco-Imoveis\Notebooks\modelos_preco_imoveis.ipynb"

with open(NOTEBOOK_PATH, encoding="utf-8") as f:
    nb = json.load(f)

cells = nb["cells"]

# Find insertion point: before markdown cell with "Treinando o melhor modelo"
insert_idx = None
for i, c in enumerate(cells):
    src = "".join(c["source"])
    if c["cell_type"] == "markdown" and "Treinando o melhor modelo" in src:
        insert_idx = i
        break

if insert_idx is None:
    raise ValueError("Could not find insertion point")

print(f"Inserting at index {insert_idx} (current cell: {''.join(cells[insert_idx]['source'])[:60]}...)")

# ─── Markdown cell ───
md_cell = {
    "cell_type": "markdown",
    "id": str(uuid.uuid4())[:8],
    "metadata": {},
    "source": [
        "## Testando varias features, varias transformacoes e varios modelos\n",
        "\n",
        "Grade de experimentos combinando diferentes conjuntos de features, transformações e modelos.\n",
        "Target: **valor_imovel**. Todos os resultados são logados no MLflow via `treinar_pipeline_com_mlflow`.\n",
    ],
}

# ─── Code cell ───
code_source = r'''# ============================================================================
# GRADE: VARIAS FEATURES x VARIAS TRANSFORMACOES x VARIOS MODELOS
# Target: valor_imovel | Log via treinar_pipeline_com_mlflow
# ============================================================================

import warnings, time, itertools, sys
warnings.filterwarnings("ignore")

TARGET = "valor_imovel"

CATEGORICAL_FEATURES = ["tipo_imovel", "bairro"]
NUMERIC_FEATURES_BASE = [
    "metragem", "quartos", "banheiros", "vagas",
]
NUMERIC_FEATURES_SCORES = [
    "score_escola_privada", "score_escola_publica", "score_hospitais",
    "score_mercado", "score_farmacia", "score_parque", "score_seguranca",
    "score_educacao",
]
NUMERIC_FEATURES_DERIVADAS = [
    "metro_quadrado_bairro_mean", "metro_quadrado_bairro_median",
    "valor_bairro_mean", "bairro_rank",
    "quartos_por_metro", "vagas_por_metro", "banheiros_por_quarto",
]
NUMERIC_FEATURES_ALL = NUMERIC_FEATURES_BASE + NUMERIC_FEATURES_SCORES + NUMERIC_FEATURES_DERIVADAS
ALL_FEATURES = NUMERIC_FEATURES_ALL + CATEGORICAL_FEATURES

# ── Garantir que features derivadas existam no pd_joinville ──
derivadas_faltando = [f for f in NUMERIC_FEATURES_DERIVADAS if f not in pd_joinville.columns]
if derivadas_faltando:
    print(f"Criando features derivadas: {derivadas_faltando}")
    bairro_stats = pd_joinville.groupby("bairro").agg(
        metro_quadrado_bairro_mean=("metragem", "mean"),
        metro_quadrado_bairro_median=("metragem", "median"),
        valor_bairro_mean=("valor_imovel", "mean"),
    ).reset_index()
    bairro_stats["bairro_rank"] = bairro_stats["valor_bairro_mean"].rank(ascending=False)
    pd_joinville = pd_joinville.merge(bairro_stats, on="bairro", how="left", suffixes=("", "_y"))
    pd_joinville["quartos_por_metro"] = pd_joinville["quartos"] / pd_joinville["metragem"].replace(0, np.nan)
    pd_joinville["vagas_por_metro"] = pd_joinville["vagas"] / pd_joinville["metragem"].replace(0, np.nan)
    pd_joinville["banheiros_por_quarto"] = pd_joinville["banheiros"] / pd_joinville["quartos"].replace(0, np.nan)

# ── 1. CONJUNTOS DE FEATURES ──
FEATURE_SETS = {
    "apenas_basicas": NUMERIC_FEATURES_BASE + CATEGORICAL_FEATURES,
    "basicas_scores": NUMERIC_FEATURES_BASE + NUMERIC_FEATURES_SCORES + CATEGORICAL_FEATURES,
    "todas_numericas": NUMERIC_FEATURES_ALL + CATEGORICAL_FEATURES,
    "todas_sem_derivadas": NUMERIC_FEATURES_BASE + NUMERIC_FEATURES_SCORES + CATEGORICAL_FEATURES,
    "apenas_derivadas": NUMERIC_FEATURES_BASE + NUMERIC_FEATURES_DERIVADAS + CATEGORICAL_FEATURES,
}

# ── 2. PREPROCESSORS (diferentes estrategias de escala) ──
from sklearn.preprocessing import StandardScaler, RobustScaler
from functools import partial

def _replace_inf(X):
    return np.nan_to_num(np.asarray(X, dtype=np.float64), nan=np.nan, posinf=np.nan, neginf=np.nan)

def make_preprocessor(scaler_class=None, use_log=False):
    def _build():
        steps = [
            ("replace_inf", FunctionTransformer(_replace_inf, validate=False, feature_names_out="one-to-one")),
            ("imputer", SimpleImputer(strategy="median")),
        ]
        if use_log:
            steps.append(("log1p", FunctionTransformer(np.log1p, validate=False)))
        if scaler_class is not None:
            steps.append(("scaler", scaler_class()))
        numeric_pipe = Pipeline(steps)
        categorical_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="constant", fill_value="desconhecido")),
            ("ohe", OneHotEncoder(handle_unknown="ignore", max_categories=30, sparse_output=False)),
        ])
        return ColumnTransformer([
            ("num", numeric_pipe, [c for c in NUMERIC_FEATURES_ALL if c in pd_joinville.columns]),
            ("cat", categorical_pipe, CATEGORICAL_FEATURES),
        ])
    return _build

PREPROCESSORS = {
    "raw": make_preprocessor(scaler_class=None, use_log=False),
    "standard": make_preprocessor(scaler_class=StandardScaler, use_log=False),
    "robust": make_preprocessor(scaler_class=RobustScaler, use_log=False),
    "log_standard": make_preprocessor(scaler_class=StandardScaler, use_log=True),
}

# ── 3. MODELOS ──
from sklearn.linear_model import LinearRegression, Ridge, Lasso, ElasticNet
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor

MODELOS = {
    "LinearRegression": LinearRegression(),
    "Ridge": Ridge(alpha=1.0),
    "Lasso": Lasso(alpha=0.001, max_iter=10000),
    "ElasticNet": ElasticNet(alpha=0.001, l1_ratio=0.5, max_iter=10000),
    "RandomForest": RandomForestRegressor(n_estimators=200, max_depth=12, random_state=42, n_jobs=-1),
    "GradientBoosting": GradientBoostingRegressor(n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42),
}

try:
    from lightgbm import LGBMRegressor
    MODELOS["LightGBM"] = LGBMRegressor(n_estimators=200, max_depth=8, learning_rate=0.1, random_state=42, n_jobs=-1, verbose=-1)
except ImportError:
    pass

try:
    from catboost import CatBoostRegressor
    MODELOS["CatBoost"] = CatBoostRegressor(iterations=200, depth=6, learning_rate=0.1, random_seed=42, verbose=0)
except ImportError:
    pass

try:
    import xgboost as xgb
    MODELOS["XGBoost"] = xgb.XGBRegressor(n_estimators=200, max_depth=6, learning_rate=0.1, random_state=42, n_jobs=-1, verbosity=0)
except ImportError:
    pass

print(f"Feature sets: {len(FEATURE_SETS)}")
print(f"Preprocessors: {len(PREPROCESSORS)}")
print(f"Models: {len(MODELOS)}")
total = len(FEATURE_SETS) * len(PREPROCESSORS) * len(MODELOS)
print(f"Total combinations: {total}")

# ── 4. PREPARAR DADOS ──
df = pd_joinville.dropna(subset=[TARGET, "metragem"]).copy()
df = df[(df["metragem"] > 10)].copy()

# ── 5. EXECUTAR GRADE ──
resultados = []
count = 0
t_start = time.time()

for feat_name, feat_cols in FEATURE_SETS.items():
    # Filter to existing columns
    feat_available = [c for c in feat_cols if c in df.columns]
    if not feat_available:
        continue

    X_full = df[feat_available].copy()
    y_full = df[TARGET].copy()

    # Train/test split
    X_tr, X_te, y_tr, y_te = train_test_split(X_full, y_full, test_size=0.25, random_state=42)

    for pp_name, pp_fn in PREPROCESSORS.items():
        for model_name, model in MODELOS.items():
            run_name = f"grid_{feat_name}_{pp_name}_{model_name}"
            count += 1

            try:
                pipe, metrics = treinar_pipeline_com_mlflow(
                    nome=run_name,
                    estimador=model,
                    X_tr=X_tr, y_tr=y_tr,
                    X_te=X_te, y_te=y_te,
                    criar_preprocessador_fn=pp_fn,
                )
                resultados.append({
                    "features": feat_name,
                    "preprocessing": pp_name,
                    "modelo": model_name,
                    "rmse": metrics["rmse"],
                    "mae": metrics["mae"],
                    "mape": metrics["mape"],
                    "r2": metrics["r2"],
                })
            except Exception as e:
                print(f"  ERRO: {run_name} -> {e}")
                resultados.append({
                    "features": feat_name,
                    "preprocessing": pp_name,
                    "modelo": model_name,
                    "rmse": float("nan"),
                    "mae": float("nan"),
                    "mape": float("nan"),
                    "r2": float("nan"),
                })

            elapsed = time.time() - t_start
            eta = (elapsed / count) * (total - count) if count > 0 else 0
            print(f"[{count}/{total}] {run_name:55s} | R2={resultados[-1]['r2']:.4f} | {elapsed/60:.1f}min | ETA: {eta/60:.0f}min")

t_total = time.time() - t_start
print(f"\nConcluido em {t_total/60:.1f} minutos")

# ── 6. TABELA COMPARATIVA ──
df_res = pd.DataFrame(resultados)
df_ok = df_res.dropna(subset=["r2"]).copy()

print("\n" + "="*90)
print("TOP 15 COMBINACOES (R2)")
print("="*90)
top = df_ok.nlargest(15, "r2")
print(f"{'#':>3} {'Features':>22} {'Preproc':>14} {'Modelo':>20} {'R2':>8} {'MAE':>10} {'RMSE':>10}")
print("-"*90)
for i, (_, row) in enumerate(top.iterrows(), 1):
    print(f"{i:>3} {row['features']:>22} {row['preprocessing']:>14} {row['modelo']:>20} "
          f"{row['r2']:>8.4f} {row['mae']:>10,.0f} {row['rmse']:>10,.0f}")

melhor = df_ok.loc[df_ok["r2"].idxmax()]
print(f"\nMELHOR: {melhor['modelo']} | features={melhor['features']} | "
      f"preproc={melhor['preprocessing']} | R2={melhor['r2']:.4f} | MAE=R${melhor['mae']:,.0f}")

print("\n" + "="*90)
print("RESUMO POR MODELO (media R2)")
print("="*90)
print(df_ok.groupby("modelo").agg(
    r2_medio=("r2", "mean"), r2_max=("r2", "max"),
    r2_std=("r2", "std"), n=("r2", "count")
).sort_values("r2_medio", ascending=False).round(4))

print("\n" + "="*90)
print("RESUMO POR FEATURES (media R2)")
print("="*90)
print(df_ok.groupby("features").agg(
    r2_medio=("r2", "mean"), r2_max=("r2", "max"), n=("r2", "count")
).sort_values("r2_medio", ascending=False).round(4))

print("\n" + "="*90)
print("RESUMO POR PREPROCESSING (media R2)")
print("="*90)
print(df_ok.groupby("preprocessing").agg(
    r2_medio=("r2", "mean"), r2_max=("r2", "max"), n=("r2", "count")
).sort_values("r2_medio", ascending=False).round(4))
'''

code_cell = {
    "cell_type": "code",
    "execution_count": None,
    "id": str(uuid.uuid4())[:8],
    "metadata": {},
    "outputs": [],
    "source": [code_source],
}

# Insert at insert_idx (before the target cell)
cells.insert(insert_idx, md_cell)
cells.insert(insert_idx + 1, code_cell)

# Update nb['cells']
nb["cells"] = cells

# Count metadata
nb["nbformat"] = 4
nb["nbformat_minor"] = 5

with open(NOTEBOOK_PATH, "w", encoding="utf-8") as f:
    json.dump(nb, f, ensure_ascii=False, indent=1)

print(f"\nDone! Inserted 2 cells at index {insert_idx}")
print(f"Total cells now: {len(cells)}")
