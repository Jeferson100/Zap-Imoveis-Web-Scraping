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
import os
import re
import joblib
import numpy as np
import pandas as pd

CIDADES = {
    'joinville': 'Joinville',
    'balneario_camboriu': 'Balneario Camboriu',
}


def extract_trees(modelo):
    estimator = modelo.named_steps['modelo']
    # A calibracao isotonica nao e exportavel para JS. Exportar o modelo base
    # sem ela produz precos sistematicamente diferentes dos do Python (vies de
    # +4% a -6% por faixa), entao o aviso e obrigatorio e nao silencioso.
    if type(estimator).__name__ == 'CalibradorIsotonico':
        print('  AVISO: camada de calibracao isotonica NAO exportada para JS.')
        print('         O navegador usara o modelo base, sem correcao de vies.')
        estimator = getattr(estimator, 'estimador_', estimator)
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
                elif hasattr(tr, 'metodo') and hasattr(tr, 'positivas_'):
                    # TransformadorPorColuna (log/sqrt). So vale nas colunas nao
                    # negativas; as demais passam cruas. Sem isto o JS alimentaria
                    # as arvores em escala diferente da do treino — previsao
                    # silenciosamente deformada.
                    result['numeric']['transform'] = tr.metodo
                    result['numeric']['transform_cols'] = [
                        col for col, ok in zip(cols, tr.positivas_) if ok
                    ]

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

    # ── Modelo a exportar ────────────────────────────────────────────────
    # MODELO_JS_PATH permite exportar o "modelo de site" (features que o
    # navegador consegue calcular) em vez do modelo de producao completo.
    modelo_env = os.environ.get('MODELO_JS_PATH', '').strip()
    if modelo_env:
        modelo_path = Path(modelo_env)
        if not modelo_path.is_absolute():
            modelo_path = base_dir / modelo_path
        if not modelo_path.exists():
            raise SystemExit(f'MODELO_JS_PATH nao encontrado: {modelo_path}')
        print(f'  Modelo (MODELO_JS_PATH): {modelo_path.name}')
    else:
        # Preferir o modelo de site: e o unico que o navegador consegue
        # reproduzir. Sem isto, o export automatico pegaria o modelo de
        # producao (com score_texto) e falharia na allowlist do JS.
        site_modelos = sorted(pasta_dados.glob(f'{cidade}_modelo_site_*.joblib'))
        if site_modelos:
            modelo_path = site_modelos[-1]
            print(f'  Modelo de site: {modelo_path.name}')
        else:
            modelos = sorted(pasta_dados.glob(f'{cidade}_modelo_geral_*.joblib'))
            if not modelos:
                print(f'  Nenhum modelo encontrado para {cidade}')
                return
            modelo_path = modelos[-1]
            print(f'  Modelo: {modelo_path.name}')
    mes_ref = modelo_path.stem.split('_')[-1]
    if not re.fullmatch(r'\d{4}-\d{2}', mes_ref):
        # modelo_site_<cidade>_2026-11 -> ultimo token ainda e o mes
        mes_ref = re.findall(r'\d{4}-\d{2}', modelo_path.stem)[-1]

    modelo = joblib.load(modelo_path)

    try:
        ct = modelo.named_steps['preprocessador']
        feature_names = []
        for _, _, cols in ct.transformers_:
            feature_names.extend(cols)
    except Exception:
        feature_names = []

    print(f'  Features ({len(feature_names)})')

    # ── Allowlist: o navegador precisa conseguir calcular TODAS as features ──
    # score_texto e um Ridge sobre TF-IDF de 20k termos: nao ha como reproduzir
    # no JS. Exportar mesmo assim faria o formulario prever com 0 nessa coluna,
    # que e a 2a feature mais importante do modelo — previsao deformada sem aviso.
    NAO_CALCULAVEIS_EM_JS = {'score_texto'}
    bloqueadas = [f for f in feature_names if f in NAO_CALCULAVEIS_EM_JS]
    if bloqueadas:
        raise RuntimeError(
            f'{cidade}: features que o navegador nao calcula: {bloqueadas}. '
            'O site MANTEM o modelo antigo desta cidade. Gere o modelo de site '
            '(scripts/treinar_modelo_site.py) ou remova essas features do modelo.'
        )

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

    # ── Features oficiais do treino (mesmo método do app) ──
    # Ao exportar o modelo de site, o `features` tem de vir do JSON DELE: herdar
    # o da producao traria score_texto para a lista que o formulario usa, e o
    # navegador passaria a alimentar a arvore com 0 numa coluna que o modelo
    # nem tem.
    features_info = None
    eh_modelo_site = '_modelo_site_' in modelo_path.name
    if eh_modelo_site:
        site_json = pasta_dados / f'{cidade}_modelo_site_{mes_ref}.json'
        if site_json.exists():
            with open(site_json, encoding='utf-8') as f:
                features_info = json.load(f)
            features_info['fonte'] = 'modelo_site'
            # Cobertura da busca pertence ao modelo de PRODUCAO que definiu a
            # configuracao; o modelo de site herda os hiperparametros dele.
            prod_json = pasta_dados / f'{cidade}_features_modelo_{mes_ref}.json'
            if prod_json.exists():
                try:
                    prod = json.loads(prod_json.read_text(encoding='utf-8'))
                    for k in ('busca_cobertura', 'busca_completa'):
                        features_info.setdefault(k, prod.get(k))
                except Exception:
                    pass
            print(f"  Features oficiais (modelo de site): {features_info.get('n_features')}")
    if features_info is None:
        feat_path = pasta_dados / f'{cidade}_features_modelo_{mes_ref}.json'
        if feat_path.exists():
            try:
                with open(feat_path, encoding='utf-8') as f:
                    features_info = json.load(f)
                print(f"  Features oficiais: {features_info.get('n_features')} ({features_info.get('fonte', '?')})")
            except Exception as exc:
                print(f'  Aviso: falha ao ler {feat_path.name} ({exc})')
    if features_info is None:
        features_info = {'features': list(feature_names), 'fonte': 'pipeline'}

    # Coerencia obrigatoria: a lista de features do JSON tem de ser a que o
    # pipeline realmente usa. Divergencia aqui ja causou formulario prevendo com
    # zeros em features que o modelo treinado esperava.
    declaradas = set(features_info.get('features') or [])
    if declaradas and declaradas != set(feature_names):
        so_json = sorted(declaradas - set(feature_names))
        so_pipe = sorted(set(feature_names) - declaradas)
        raise SystemExit(
            f'  ERRO: features do JSON divergem do pipeline em {cidade}: '
            f'so no JSON={so_json} | so no pipeline={so_pipe}'
        )

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

    # ── Cobertura real da busca ──────────────────────────────────────────
    # Lida do estado (fonte primaria, escrita pelo treino), nao do JSON do
    # modelo, que pode estar defasado. Blocos e combinacoes sao grandezas
    # diferentes: misturar as duas foi o que produziu um "0,06%" irreal.
    cobertura_blocos = None
    cobertura_combos = None
    completa = (features_info or {}).get('busca_completa')
    estado_path = pasta_dados / f'{cidade}_{mes_ref}_busca_estado.json'
    if estado_path.exists():
        try:
            est = json.loads(estado_path.read_text(encoding='utf-8'))
            blocos = len(est.get('blocos_concluidos') or [])
            planejados = int(est.get('blocos_planejados') or 0)
            if not planejados:
                # estados gravados antes de `blocos_planejados` existir
                try:
                    from teste_incremental_features_async import (
                        TRATAMENTOS,
                        TesteIncrementalFeaturesAsync as _T,
                    )
                    planejados = len(TRATAMENTOS) * len(_T.TRANSFORM_OPCOES)
                except Exception:
                    planejados = 0
            combos = sum((est.get('incrementos') or {}).values())
            total_combos = int(est.get('total_planejado') or 0)
            cobertura_blocos = (blocos / planejados) if planejados else None
            cobertura_combos = (combos / total_combos) if total_combos else None
            completa = est.get('completa', completa)
            print(f'  Cobertura da busca: {blocos}/{planejados or "?"} blocos '
                  f'({100 * (cobertura_blocos or 0):.0f}%) | '
                  f'{combos}/{total_combos or "?"} combinacoes')
        except Exception as exc:
            print(f'  Aviso: estado da busca ilegivel ({exc})')
    if cobertura_blocos is None:
        cobertura_blocos = (features_info or {}).get('busca_cobertura')

    model_export = {
        'model_type': model_type,
        'feature_names': feature_names,
        'features_info': features_info,
        'target_transform': target_transform,
        'ensemble': trees_data,
        'preprocessor': preprocessor_data,
        # Proveniencia: qual arquivo gerou este JSON e quao completa foi a busca
        # que escolheu a configuracao. Sem isso o site mostra um numero sem dizer
        # de onde ele veio.
        'modelo_arquivo': modelo_path.name,
        'mes_ref': mes_ref,
        'busca_cobertura': cobertura_blocos,
        'busca_combos': cobertura_combos,
        'busca_completa': completa,
        'calc_em_js': NAO_CALCULAVEIS_EM_JS.isdisjoint(feature_names),
    }

    # ── Features cujo 0 e implausivel ────────────────────────────────────
    # O JS preenche feature ausente com 0. Para uma coluna cujo centro esta a
    # mais de 5 desvios do zero (ex.: lng ~ -48,8), isso manda um z-score
    # absurdo para dentro da arvore e deforma a previsao sem avisar. Nesses
    # casos o site deve dizer "indisponivel", nao inventar um numero.
    num_cfg = preprocessor_data.get('numeric', {})
    centro = num_cfg.get('scaler_center') or num_cfg.get('scaler_mean') or {}
    escala = num_cfg.get('scaler_scale') or {}
    obrigatorias = [
        col for col in feature_names
        if centro.get(col) is not None and escala.get(col)
        and abs(centro[col]) / escala[col] > 5
    ]
    model_export['features_obrigatorias'] = obrigatorias
    if obrigatorias:
        print(f'  Features obrigatorias (0 seria implausivel): {obrigatorias}')

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
        try:
            exportar_cidade(cidade, base_dir)
        except Exception as exc:
            print(f"[AVISO] Pulei modelo de {cidade}: {exc} (dados seguem normalmente)")

    print('\nConcluido!')


if __name__ == '__main__':
    main()
