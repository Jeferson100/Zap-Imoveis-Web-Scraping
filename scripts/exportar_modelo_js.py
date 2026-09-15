"""
Extrai parametros do modelo sklearn (GradientBoosting + preprocessador) como JSON
para inferencia direta em JavaScript, sem necessidade de onnxruntime.

Uso:
    python scripts/exportar_modelo_js.py todas
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


def extract_trees(modelo):
    estimator = modelo.named_steps['modelo']
    name = type(estimator).__name__

    if name == 'GradientBoostingRegressor':
        trees = []
        for est in estimator.estimators_.ravel():
            t = est.tree_
            trees.append({
                'n_nodes': t.node_count,
                'children_left': t.children_left.tolist(),
                'children_right': t.children_right.tolist(),
                'feature': t.feature.tolist(),
                'threshold': t.threshold.tolist(),
                'value': t.value.ravel().tolist(),
            })
        return {
            'type': 'gradient_boosting',
            'n_estimators': len(trees),
            'learning_rate': float(estimator.learning_rate),
            'init': float(estimator.init_.predict(np.zeros((1, 1)))[0]) if hasattr(estimator.init_, 'predict') else float(estimator.init_),
            'trees': trees,
        }
    elif name == 'DecisionTreeRegressor':
        t = estimator.tree_
        return {
            'type': 'decision_tree',
            'n_nodes': t.node_count,
            'children_left': t.children_left.tolist(),
            'children_right': t.children_right.tolist(),
            'feature': t.feature.tolist(),
            'threshold': t.threshold.tolist(),
            'value': t.value.ravel().tolist(),
        }
    else:
        raise ValueError(f'Tipo de modelo nao suportado: {name}')


def extract_preprocessor(modelo):
    ct = modelo.named_steps['preprocessador']
    result = {'numeric': {}, 'categorical': {}}

    for name, trans, cols in ct.transformers_:
        if name.startswith('num'):
            pipe_steps = trans.named_steps
            if 'imputer' in pipe_steps:
                result['numeric']['imputer_median'] = {
                    col: round(float(val), 6)
                    for col, val in zip(cols, pipe_steps['imputer'].statistics_)
                }
            if 'scaler' in pipe_steps:
                scaler = pipe_steps['scaler']
                if hasattr(scaler, 'center_'):
                    result['numeric']['scaler_center'] = {
                        col: round(float(val), 6)
                        for col, val in zip(cols, scaler.center_)
                    }
                elif hasattr(scaler, 'mean_'):
                    result['numeric']['scaler_mean'] = {
                        col: round(float(val), 6)
                        for col, val in zip(cols, scaler.mean_)
                    }
                result['numeric']['scaler_scale'] = {
                    col: round(float(val), 6)
                    for col, val in zip(cols, scaler.scale_)
                }
            if 'transform' in pipe_steps:
                tr = pipe_steps['transform']
                if hasattr(tr, 'lambdas_'):
                    result['numeric']['yeo_lambdas'] = {
                        col: round(float(val), 6)
                        for col, val in zip(cols, tr.lambdas_)
                    }
                    result['numeric']['yeo_method'] = 'yeo-johnson'
                    if hasattr(tr, '_scaler') and hasattr(tr._scaler, 'mean_'):
                        result['numeric']['yj_standardize_mean'] = {
                            col: round(float(val), 6)
                            for col, val in zip(cols, tr._scaler.mean_)
                        }
                        result['numeric']['yj_standardize_scale'] = {
                            col: round(float(val), 6)
                            for col, val in zip(cols, tr._scaler.scale_)
                        }
                elif hasattr(tr, 'power_'):
                    result['numeric']['boxcox_lambdas'] = {
                        col: round(float(val), 6)
                        for col, val in zip(cols, tr.power_)
                    }
                    result['numeric']['boxcox_method'] = 'box-cox'

        elif name.startswith('cat'):
            pipe_steps = trans.named_steps
            if 'ohe' in pipe_steps:
                ohe = pipe_steps['ohe']
                categories = {}
                for i, col in enumerate(cols):
                    cats = ohe.categories_[i].tolist() if i < len(ohe.categories_) else []
                    categories[col] = [str(int(c)) if isinstance(c, (bool, np.bool_)) else str(c) for c in cats]
                result['categorical']['categories'] = categories

    return result


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
        ct = modelo.named_steps['preprocessador']
        feature_names = []
        for _, _, cols in ct.transformers_:
            feature_names.extend(cols)
    except Exception:
        feature_names = []

    print(f'  Features ({len(feature_names)})')

    model_type = type(modelo.named_steps['modelo']).__name__
    print(f'  Tipo do modelo: {model_type}')

    trees_data = extract_trees(modelo)
    preprocessor_data = extract_preprocessor(modelo)

    meta_path = pasta_dados / f'{cidade}_target_transform_{mes_ref}.json'
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        target_transform = meta.get('target_transformer', 'none')
    else:
        target_transform = 'none'

    precisa_topicos = any(c.startswith('componente_') for c in feature_names)
    topic_data = None
    if precisa_topicos:
        topicos_path = pasta_dados / f'{cidade}_topicos_modelo.pkl'
        if topicos_path.exists():
            topicos_data = joblib.load(topicos_path)
            vec = topicos_data['vectorizer']
            nmf = topicos_data['nmf']
            topic_data = {
                'vocabulary': {k: int(v) for k, v in vec.vocabulary_.items()},
                'idf': [round(float(x), 6) for x in vec.idf_.tolist()],
                'nmf_components': [[round(float(x), 6) for x in row] for row in nmf.components_.tolist()],
                'n_topics': topicos_data.get('n_topics', 4),
                'max_features': vec.max_features,
                'ngram_range': list(vec.ngram_range),
            }
            print(f'  Topicos: {len(vec.vocabulary_)} vocab')

    model_export = {
        'model_type': model_type,
        'feature_names': feature_names,
        'target_transform': target_transform,
        'ensemble': trees_data,
        'preprocessor': preprocessor_data,
    }

    if topic_data:
        model_export['topics'] = topic_data

    with open(pasta_saida / f'modelo_{cidade}.json', 'w', encoding='utf-8') as f:
        json.dump(model_export, f, ensure_ascii=False)
    print(f'  Salvo: modelo_{cidade}.json')

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
        km = cluster_data.get('kmeans')
        scaler = cluster_data.get('scaler')
        if km and scaler:
            cluster_export = {
                'centroids': km.cluster_centers_.tolist(),
                'scaler_mean': scaler.mean_.tolist(),
                'scaler_scale': scaler.scale_.tolist(),
                'n_clusters': km.n_clusters,
            }
            with open(pasta_saida / f'cluster_{cidade}.json', 'w') as f:
                json.dump(cluster_export, f, indent=2)
            print(f'  Cluster: {km.n_clusters} centroids')


def main():
    base_dir = Path(__file__).resolve().parent.parent

    if len(sys.argv) > 1 and sys.argv[1] == 'todas':
        cidades = list(CIDADES.keys())
    elif len(sys.argv) > 1 and sys.argv[1] in CIDADES:
        cidades = [sys.argv[1]]
    else:
        print(f'Uso: python {sys.argv[0]} <cidade|todas>')
        return

    for cidade in cidades:
        exportar_cidade(cidade, base_dir)

    print('\nConcluido!')


if __name__ == '__main__':
    main()
