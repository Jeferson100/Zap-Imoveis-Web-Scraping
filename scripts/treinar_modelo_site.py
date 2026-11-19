"""Treina o modelo que vai para o site estatico.

Motivo: o modelo de producao usa `score_texto` — um Ridge sobre TF-IDF de ate
20 mil termos — que o navegador nao consegue calcular. O exportador JS passa a
recusar esses modelos (allowlist), entao o site precisa de um modelo proprio,
restrito a features computaveis em JavaScript.

Este modelo NAO substitui o de producao. Ele existe para que a tabela e o
formulario do site mostrem numeros coerentes entre si e honestos sobre o que o
navegador consegue reproduzir.

Uso:
    python scripts/treinar_modelo_site.py --cidade joinville --mes 2026-11
Saidas:
    dados/<cidade>/<cidade>_modelo_site_<mes>.joblib
    dados/<cidade>/<cidade>_modelo_site_<mes>.json   (metricas + features)
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "src"))

from config_features import CATEGORICAL_FEATURES, NUMERIC_FEATURES  # noqa: E402
from preprocessador import PreprocessadorFactory  # noqa: E402
from utils_topicos import TOPIC_COLS, aplicar_topicos  # noqa: E402

# Unicas features que o navegador nao calcula. O modelo de site nao pode te-las.
NAO_CALCULAVEIS_EM_JS = {"score_texto"}

PARAMS_PADRAO = dict(
    n_estimators=150, max_depth=8, learning_rate=0.09,
    subsample=0.75, min_samples_leaf=5,
)


def carregar(cidade, mes, pasta):
    tr = pasta / f"{cidade}_train_{mes}.parquet"
    te = pasta / f"{cidade}_test_{mes}.parquet"
    if not (tr.exists() and te.exists()):
        raise FileNotFoundError(
            f"Cache ausente: {tr.name} / {te.name}. Rode o Treinamento da cidade primeiro."
        )
    return pd.read_parquet(tr), pd.read_parquet(te)


def treinar_site(cidade, mes, pasta):
    """Treina e salva o modelo do site.

    Usado tanto pela CLI quanto por `melhor_modelo_geral`, que o chama logo
    depois de gravar o modelo de producao — assim o site nunca fica preso a um
    mes anterior por esquecimento.
    """
    train, test = carregar(cidade, mes, pasta)
    print(f"cache: treino {len(train):,} | teste {len(test):,}")

    # Topicos: o site sabe calcula-los (vocabulario + idf + NMF vao no JSON).
    topicos_path = pasta / f"{cidade}_topicos_modelo.pkl"
    if topicos_path.exists():
        topicos = joblib.load(topicos_path)
        aplicar_topicos(train, topicos)
        aplicar_topicos(test, topicos)
        print(f"topicos aplicados ({len(TOPIC_COLS)} componentes)")
    else:
        print("AVISO: sem modelo de topicos; componentes ficam 0")

    # ── allowlist: tudo que o JS calcula ────────────────────────────────
    numericas = [c for c in NUMERIC_FEATURES if c not in NAO_CALCULAVEIS_EM_JS]
    numericas += [c for c in TOPIC_COLS if c not in numericas]
    categoricas = list(CATEGORICAL_FEATURES)
    existentes = set(train.columns) & set(test.columns)
    num = [c for c in numericas if c in existentes]
    cat = [c for c in categoricas if c in existentes]
    removidas = [c for c in NUMERIC_FEATURES if c in NAO_CALCULAVEIS_EM_JS]
    print(f"features: {len(num)} numericas + {len(cat)} categoricas")
    print(f"excluidas por nao serem calculaveis em JS: {removidas}")

    # ── hiperparametros: os da producao, se forem GradientBoosting ──────
    params = dict(PARAMS_PADRAO)
    feat_json = pasta / f"{cidade}_features_modelo_{mes}.json"
    if feat_json.exists():
        try:
            info = json.loads(feat_json.read_text(encoding="utf-8"))
            if str(info.get("modelo", "")).lower().startswith("gradient"):
                params.update(info.get("best_params") or {})
                print(f"params herdados da producao: {params}")
        except Exception as exc:
            print(f"AVISO: nao li {feat_json.name} ({exc}); usando defaults")

    # transform=None de proposito: sem log/sqrt o caminho do JS e identico ao
    # do Python por construcao, e GradientBoosting nao precisa dessa compressao.
    pp = PreprocessadorFactory(numeric_features=num, categorical_features=cat).criar(
        scaler=StandardScaler(),
        imputer_num=SimpleImputer(strategy="median"),
        encoder=OneHotEncoder(handle_unknown="ignore"),
        transform=None,
    )
    modelo = GradientBoostingRegressor(random_state=42, **params)
    pipe = Pipeline([("preprocessador", pp), ("modelo", modelo)])

    ytr = np.log1p(pd.to_numeric(train["valor_imovel"], errors="coerce").values)
    yte = pd.to_numeric(test["valor_imovel"], errors="coerce").values
    pipe.fit(train[num + cat], ytr)
    pred = np.expm1(pipe.predict(test[num + cat]))

    ape = np.abs(pred - yte) / yte
    met = {
        "r2": float(r2_score(yte, pred)),
        "rmse": float(np.sqrt(np.mean((pred - yte) ** 2))),
        "mae": float(mean_absolute_error(yte, pred)),
        "mdape": float(100 * np.median(ape)),
        "mape": float(100 * ape.mean()),
        "n_teste": int(len(yte)),
    }
    print(
        f"\nmodelo de site: R2 {met['r2']:.4f} | RMSE R$ {met['rmse']:,.0f} | "
        f"MAE R$ {met['mae']:,.0f} | MdAPE {met['mdape']:.2f}%"
    )
    if feat_json.exists():
        try:
            prod = json.loads(feat_json.read_text(encoding="utf-8"))
            print(
                f"producao (registrado): R2 {prod.get('r2_otimizado'):.4f} | "
                f"RMSE R$ {prod.get('rmse_otimizado'):,.0f} "
                f"— diferenca de R2 {met['r2'] - prod.get('r2_otimizado', 0):+.4f}"
            )
        except Exception:
            pass

    modelo_path = pasta / f"{cidade}_modelo_site_{mes}.joblib"
    joblib.dump(pipe, modelo_path, compress=3)
    info_path = pasta / f"{cidade}_modelo_site_{mes}.json"
    info_path.write_text(
        json.dumps(
            {
                "tipo": "modelo_site",
                "cidade": cidade,
                "mes_ref": mes,
                "features_numericas": num,
                "features_categoricas": cat,
                "features": num + cat,
                "n_features": len(num) + len(cat),
                "excluidas_nao_calculaveis_em_js": removidas,
                "target_transform": "log",
                "best_params": params,
                "metricas_holdout": met,
                # O predicao.js le features_info.r2_otimizado (mesma chave do
                # JSON de producao). Sem o alias a legenda do resultado mostrava
                # so o mes, sem o R2.
                "r2_otimizado": met["r2"],
                "rmse_otimizado": met["rmse"],
                "data_treino": datetime.now().isoformat(),
                "topico_modelo": topicos_path.name if topicos_path.exists() else None,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nsalvo: {modelo_path.name}")
    print(f"salvo: {info_path.name}")

    # A limpeza fica aqui, junto de quem cria o arquivo, em vez de duplicar a
    # responsabilidade no bloco 9b do melhor_modelo_geral. Mantem 2 meses
    # (1,2 MB cada) para permitir comparacao entre versoes.
    meses = sorted({
        p.stem.rsplit("_", 1)[-1]
        for p in pasta.glob(f"{cidade}_modelo_site_*.joblib")
    })
    for antigo in meses[:-2]:
        for ext in ("joblib", "json"):
            velho = pasta / f"{cidade}_modelo_site_{antigo}.{ext}"
            if velho.exists():
                velho.unlink()
                print(f"modelo de site anterior removido: {velho.name}")

    return {"joblib": str(modelo_path), "json": str(info_path), "metricas": met}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cidade", default="joinville")
    ap.add_argument("--mes", required=True, help="AAAA-MM")
    ap.add_argument("--dados", default="dados")
    args = ap.parse_args(argv)
    treinar_site(args.cidade, args.mes, Path(args.dados) / args.cidade)
    return 0


if __name__ == "__main__":
    sys.exit(main())
