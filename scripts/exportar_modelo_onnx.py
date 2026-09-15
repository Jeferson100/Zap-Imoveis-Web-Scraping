"""
Exporta o pipeline sklearn para ONNX + dados auxiliares (bairro_stats, cluster, etc.)
para uso no site estatico via onnxruntime-web.

Uso:
    python scripts/exportar_modelo_onnx.py joinville
    python scripts/exportar_modelo_onnx.py todas
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

import json
import joblib
import numpy as np
import pandas as pd

CIDADES = {
    'joinville': 'Joinville',
    'balneario_camboriu': 'Balneario Camboriu',
}

FEATURES_NUMERICAS = [
    "metragem", "quartos", "banheiros", "vagas",
    "score_escola_privada", "score_escola_publica", "score_hospitais",
    "score_mercado", "score_farmacia", "score_parque",
    "score_seguranca", "score_educacao",
    "metro_quadrado_bairro_mean", "metro_quadrado_bairro_median",
    "valor_bairro_mean", "bairro_rank",
    "quartos_por_metro", "vagas_por_metro", "banheiros_por_quarto",
    "dist_centro", "sem_rua",
    "lat", "lng", "predicao_idade",
]

FEATURES_CATEGORICAS = [
    "tipo_imovel", "bairro", "novo_lancamento", "tem_elevador",
    "dist_centro_faixa", "bairro_cluster",
]


def exportar_cidade(cidade, base_dir):
    pasta_dados = base_dir / 'dados' / cidade
    pasta_saida = base_dir / 'site_estatico' / 'data'
    pasta_saida.mkdir(parents=True, exist_ok=True)

    print(f'\n=== {cidade.upper()} ===')

    modelos = sorted(pasta_dados.glob(f'{cidade}_modelo_geral_*.joblib'))
    if not modelos:
        print(f'  Nenhum modelo encontrado para {cidade}')
        return
    modelo_path = modelos[-1]
    mes_ref = modelo_path.stem.split('_')[-1]
    print(f'  Modelo: {modelo_path.name}')

    modelo = joblib.load(modelo_path)

    try:
        ct = modelo.named_steps["preprocessador"]
        feature_names = []
        for _, _, cols in ct.transformers_:
            feature_names.extend(cols)
    except Exception:
        feature_names = FEATURES_NUMERICAS + FEATURES_CATEGORICAS
    print(f'  Features do modelo ({len(feature_names)}): {feature_names}')

    precisa_topicos = any(c.startswith("componente_") for c in feature_names)

    n_features = len(feature_names)
    initial_types = []
    for f in feature_names:
        if f in FEATURES_CATEGORICAS:
            initial_types.append((f, StringTensorType([None, 1])))
        else:
            initial_types.append((f, FloatTensorType([None, 1])))

    onnx_model = convert_sklearn(modelo, initial_types=initial_types)
    onnx_path = pasta_saida / f'modelo_{cidade}.onnx'
    with open(onnx_path, 'wb') as f:
        f.write(onnx_model.SerializeToString())
    print(f'  Salvo: {onnx_path.name} ({onnx_path.stat().st_size / 1024:.0f} KB)')

    stats_path = pasta_dados / f'{cidade}_bairro_stats_{mes_ref}.parquet'
    if stats_path.exists():
        bairro_stats = pd.read_parquet(stats_path)
        stats_dict = {}
        for bairro in bairro_stats.index:
            stats_dict[bairro] = {}
            for col in bairro_stats.columns:
                val = bairro_stats.loc[bairro, col]
                if isinstance(val, (np.floating, float)):
                    stats_dict[bairro][col] = round(float(val), 4)
                elif isinstance(val, (np.integer, int)):
                    stats_dict[bairro][col] = int(val)
                else:
                    stats_dict[bairro][col] = str(val)
        with open(pasta_saida / f'bairro_stats_{cidade}.json', 'w', encoding='utf-8') as f:
            json.dump(stats_dict, f, ensure_ascii=False, indent=2)
        print(f'  Bairro stats: {len(stats_dict)} bairros')

    cluster_path = pasta_dados / f'{cidade}_cluster_models_{mes_ref}.pkl'
    if cluster_path.exists():
        cluster_data = joblib.load(cluster_path)
        km = cluster_data.get("kmeans")
        scaler = cluster_data.get("scaler")
        if km and scaler:
            cluster_export = {
                "centroids": km.cluster_centers_.tolist(),
                "scaler_mean": scaler.mean_.tolist(),
                "scaler_scale": scaler.scale_.tolist(),
                "n_clusters": km.n_clusters,
            }
            with open(pasta_saida / f'cluster_{cidade}.json', 'w') as f:
                json.dump(cluster_export, f, indent=2)
            print(f'  Cluster: {km.n_clusters} centroids exportados')

    meta_path = pasta_dados / f'{cidade}_target_transform_{mes_ref}.json'
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        with open(pasta_saida / f'target_transform_{cidade}.json', 'w') as f:
            json.dump(meta, f)
        print(f'  Target transform: {meta.get("target_transformer", "none")}')

    if precisa_topicos:
        topicos_path = pasta_dados / f'{cidade}_topicos_modelo.pkl'
        if topicos_path.exists():
            topicos_data = joblib.load(topicos_path)
            vec = topicos_data["vectorizer"]
            nmf = topicos_data["nmf"]
            topic_export = {
                "vocabulary": {k: int(v) for k, v in vec.vocabulary_.items()},
                "idf": vec.idf_.tolist(),
                "nmf_components": nmf.components_.tolist(),
                "n_topics": topicos_data.get("n_topics", 4),
                "max_features": vec.max_features,
                "ngram_range": list(vec.ngram_range),
            }
            with open(pasta_saida / f'topicos_{cidade}.json', 'w', encoding='utf-8') as f:
                json.dump(topic_export, f, ensure_ascii=False)
            print(f'  Topicos: {len(vec.vocabulary_)} vocab, {topic_export["n_topics"]} components')

    try:
        ct = modelo.named_steps["preprocessador"]
        imputer_defaults = {}
        for name, trans, cols in ct.transformers_:
            if name.startswith("num"):
                pipe_steps = trans.named_steps
                if "imputer" in pipe_steps:
                    stats = pipe_steps["imputer"].statistics_
                    for col, val in zip(cols, stats):
                        imputer_defaults[col] = round(float(val), 4)
            elif name.startswith("cat"):
                pipe_steps = trans.named_steps
                if "ohe" in pipe_steps:
                    ohe = pipe_steps["ohe"]
                    categories = {}
                    for i, col in enumerate(cols):
                        cats = ohe.categories_[i].tolist() if i < len(ohe.categories_) else []
                        categories[col] = [str(c) for c in cats]
                    with open(pasta_saida / f'encoder_categories_{cidade}.json', 'w', encoding='utf-8') as f:
                        json.dump(categories, f, ensure_ascii=False, indent=2)
        with open(pasta_saida / f'imputer_defaults_{cidade}.json', 'w') as f:
            json.dump(imputer_defaults, f, indent=2)
        print(f'  Imputer defaults: {len(imputer_defaults)} features')
    except Exception as e:
        print(f'  Aviso: Nao foi possivel extrair imputer defaults: {e}')

    config = {
        "features_numericas": [f for f in feature_names if f in FEATURES_NUMERICAS],
        "features_categoricas": [f for f in feature_names if f in FEATURES_CATEGORICAS],
        "features_tematicas": [f for f in feature_names if f.startswith("componente_")],
        "todas_features": feature_names,
    }
    with open(pasta_saida / f'feature_config_{cidade}.json', 'w') as f:
        json.dump(config, f, indent=2)
    print(f'  Feature config exportado')


def main():
    base_dir = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1 and sys.argv[1] == 'todas':
        cidades = list(CIDADES.keys())
    elif len(sys.argv) > 1 and sys.argv[1] in CIDADES:
        cidades = [sys.argv[1]]
    else:
        print(f'Uso: python {sys.argv[0]} <cidade|todas>')
        print(f'Cidades disponiveis: {", ".join(CIDADES.keys())}')
        return

    for cidade in cidades:
        exportar_cidade(cidade, base_dir)

    print('\nConcluido!')


if __name__ == '__main__':
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType, StringTensorType
    main()
