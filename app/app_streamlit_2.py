import sys
from pathlib import Path
import re
import json
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import joblib
import unidecode

from criando_indices_individuais import CriandoIndicesIndividuais

from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
INCLUIR_TOPICOS = os.getenv("INCLUIR_TOPICOS", "false").lower() == "true"
TOPIC_COLS = ["componente_0", "componente_1", "componente_2", "componente_3"]

CIDADE_POI = {
    "sao_paulo":    "Sao Paulo, Sao Paulo, Brasil",
    "rio_janeiro":  "Rio de Janeiro, Rio de Janeiro, Brasil",
    "joinville":    "Joinville, Santa Catarina, Brasil",
    "curitiba":     "Curitiba, Parana, Brasil",
    "blumenau":     "Blumenau, Santa Catarina, Brasil",
    "balneario_camboriu": "Balneario Camboriu, Santa Catarina, Brasil",
    "balneario_picarras": "Balneario Picarras, Santa Catarina, Brasil",
    "itajai":       "Itajai, Santa Catarina, Brasil",
    "itapema":      "Itapema, Santa Catarina, Brasil",
    "itapoa":       "Itapoa, Santa Catarina, Brasil",
    "jaragua":      "Jaragua do Sul, Santa Catarina, Brasil",
    "florianopolis":"Florianopolis, Santa Catarina, Brasil",
}


def geocodificar_endereco_app(rua, numero, bairro, cidade, estado, pais="Brasil"):
    if rua and numero:
        query = f"{numero} {rua}, {bairro}, {cidade}, {estado}, {pais}"
    elif rua:
        query = f"{rua}, {bairro}, {cidade}, {estado}, {pais}"
    elif bairro:
        query = f"{bairro}, {cidade}, {estado}, {pais}"
    else:
        query = f"{cidade}, {estado}, {pais}"

    headers = {"User-Agent": "analise_imoveis_app_v1"}
    for tentativa in range(3):
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1},
                headers=headers, timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    return float(data[0]["lat"]), float(data[0]["lon"])
            elif resp.status_code in (429, 503):
                time.sleep(2 ** tentativa * 2)
                continue
        except Exception:
            time.sleep(1)
    return None, None


def carregar_modelo_e_stats(pasta, prefixo_name):
    modelos = sorted(pasta.glob(f"{prefixo_name}_modelo_geral_*.joblib"))
    if not modelos:
        st.error("Nenhum modelo encontrado. Execute o treinamento primeiro.")
        st.stop()

    modelo_path = modelos[-1]
    mes_ref = modelo_path.stem.split("_")[-1]

    stats_path = pasta / f"{prefixo_name}_bairro_stats_{mes_ref}.parquet"
    if not stats_path.exists():
        st.error(
            f"Arquivo 'bairro_stats_{mes_ref}.parquet' nao encontrado. "
            f"Treine o modelo primeiro."
        )
        st.stop()

    modelo = joblib.load(modelo_path)
    bairro_stats = pd.read_parquet(stats_path)

    try:
        ct = modelo.named_steps["preprocessador"]
        feature_names_modelo = []
        for _, _, cols in ct.transformers_:
            feature_names_modelo.extend(cols)
    except Exception:
        feature_names_modelo = ALL_FEATURES
        st.warning("Nao foi possivel extrair features do modelo — usando ALL_FEATURES")

    from intervalo_predicao import PreditorComIntervalo
    preditor_path = pasta / f"{prefixo_name}_preditor_intervalo_{mes_ref}.joblib"
    if preditor_path.exists():
        preditor = PreditorComIntervalo.load(preditor_path)
    else:
        preditor = None
        st.warning("Preditor com intervalo nao encontrado. Exibindo apenas predicao pontual.")

    # ── Carregar modelo de cluster ──
    cluster_path = pasta / f"{prefixo_name}_cluster_models_{mes_ref}.pkl"
    cluster_data = joblib.load(cluster_path) if cluster_path.exists() else {}
    km_cluster = cluster_data.get("kmeans") if cluster_data else None
    scaler_cluster = cluster_data.get("scaler") if cluster_data else None

    meta_path = pasta / f"{prefixo_name}_target_transform_{mes_ref}.json"
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
        target_transform = meta.get("target_transformer", "none")
    else:
        target_transform = "none"

    # ── Carregar modelos de topicos ──
    topicos_data = None
    if any(c.startswith("componente_") for c in feature_names_modelo):
        topicos_path = pasta / f"{prefixo_name}_topicos_modelo.pkl"
        topicos_data = joblib.load(topicos_path) if topicos_path.exists() else None

    return modelo, bairro_stats, mes_ref, preditor, feature_names_modelo, km_cluster, scaler_cluster, target_transform, topicos_data


def montar_features_predicao(metragem, quartos, banheiros, vagas,
                              tipo_imovel, bairro, novo_lancamento, tem_elevador,
                              lat, lng, bairro_stats, indices,
                              km_cluster=None, scaler_cluster=None,
                              predicao_idade=0, extras=None, rua=""):
    dados = {
        'metragem': metragem,
        'quartos': quartos,
        'banheiros': banheiros,
        'vagas': vagas,
        'lat': lat,
        'lng': lng,
        'tipo_imovel': tipo_imovel,
        'bairro': bairro,
        'novo_lancamento': int(novo_lancamento),
        'tem_elevador': bool(tem_elevador),
        'quartos_por_metro': quartos / (metragem + 1),
        'vagas_por_metro': vagas / (metragem + 1),
        'banheiros_por_quarto': banheiros / (quartos + 1),
        'predicao_idade': predicao_idade,
    }

    if bairro in bairro_stats.index:
        for col in ['metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
                     'valor_bairro_mean', 'bairro_rank']:
            dados[col] = bairro_stats.loc[bairro, col]
    else:
        for col in ['metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median',
                     'valor_bairro_mean', 'bairro_rank']:
            dados[col] = bairro_stats[col].mean()

    df = pd.DataFrame([dados])

    if indices is not None:
        try:
            df = indices.calcular_indices(df)
        except Exception as e:
            st.warning(f"Erro ao calcular POI scores: {e}. Usando medias do bairro.")
            for col in NUMERIC:
                if col.startswith("score_") and col not in df.columns:
                    if bairro in bairro_stats.index and col in bairro_stats.columns:
                        df[col] = bairro_stats.loc[bairro, col]
                    elif col in bairro_stats.columns:
                        df[col] = bairro_stats[col].mean()

    # ── Cluster intra-bairro ──
    if km_cluster is not None and scaler_cluster is not None:
        cluster_cols = ["score_escola_privada", "score_escola_publica", "score_hospitais",
                        "score_mercado", "score_farmacia", "score_parque", "score_seguranca"]
        try:
            Xs = scaler_cluster.transform(df[cluster_cols].fillna(0).values)
            df["bairro_cluster"] = int(km_cluster.predict(Xs)[0])
        except Exception:
            df["bairro_cluster"] = 0
    else:
        df["bairro_cluster"] = 0

    # Extras genéricos (amenities, suites, features futuras): valores do usuário
    # têm prioridade sobre as médias do bairro no fallback abaixo
    if extras:
        for k, v in extras.items():
            if k == 'suites':
                try:
                    df[k] = int(v) if str(v).isdigit() else 0
                except (ValueError, TypeError):
                    df[k] = 0
            elif isinstance(v, bool):
                df[k] = int(v)
            else:
                df[k] = v

    for col in ALL_FEATURES:
        if col not in df.columns:
            if bairro in bairro_stats.index and col in bairro_stats.columns:
                df[col] = bairro_stats.loc[bairro, col]
            elif col in bairro_stats.columns:
                df[col] = bairro_stats[col].mean()

    if "sem_rua" not in df.columns:
        df["sem_rua"] = 0 if (rua or "") else 1

    return df[ALL_FEATURES]


def _aplicar_topicos_descricao(descricao, topicos_data, df_pred):
    """Aplica TfidfVectorizer + NMF na descricao e adiciona componentes ao DataFrame."""
    if topicos_data is None or not descricao:
        for c in TOPIC_COLS:
            df_pred[c] = 0.0
        return

    vec = topicos_data["vectorizer"]
    nmf = topicos_data["nmf"]
    n_topics = topicos_data.get("n_topics", 4)

    RE_REMOVE = re.compile(
        r"código\s+do\s+anúncio[\s:\d\-]+|código:\s*\d+|ref\.?:?\s*\d+|"
        r"ri[\-\s]*\d+|cr[ée]ci[\-\s]*\d+|"
        r"\b(creci|whatsapp|telefone|contato|celular)\b[\s\d\-\\(\\)]+|"
        r"\d{7,}|https?\://\S+|www\.\S+",
        re.IGNORECASE,
    )

    t = RE_REMOVE.sub(" ", descricao)
    t = unidecode.unidecode(t)
    t = re.sub(r"\b\d+\b", " ", t)
    t = re.sub(r"[^a-zA-Z\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    tokens = [w for w in t.lower().split() if len(w) > 2]
    desc_limpa = " ".join(tokens)

    X = vec.transform([desc_limpa])
    W = nmf.transform(X)

    for i in range(n_topics):
        df_pred[f"componente_{i}"] = W[0, i]
    for i in range(n_topics, 4):
        df_pred[f"componente_{i}"] = 0.0


# ── Formulário dinâmico: só mostra inputs das features do modelo carregado ──
DERIVADAS_PRED = {'lat', 'lng', 'dist_centro', 'dist_centro_faixa',
    'score_escola_privada', 'score_escola_publica', 'score_hospitais',
    'score_mercado', 'score_farmacia', 'score_parque', 'score_seguranca', 'score_educacao',
    'metro_quadrado_bairro_mean', 'metro_quadrado_bairro_median', 'valor_bairro_mean',
    'bairro_rank', 'bairro_cluster', 'quartos_por_metro', 'vagas_por_metro',
    'banheiros_por_quarto', 'sem_rua', 'componente_0', 'componente_1',
    'componente_2', 'componente_3'}

# feature -> (tipo_widget, rotulo, args). Feature futura desconhecida: number genérico.
WIDGETS_PRED = {
    'metragem':       ('number', 'Metragem (m²)', dict(min_value=10, max_value=10000, value=70)),
    'quartos':        ('number', 'Quartos', dict(min_value=0, max_value=20, value=3)),
    'banheiros':      ('number', 'Banheiros', dict(min_value=0, max_value=20, value=2)),
    'vagas':          ('number', 'Vagas', dict(min_value=0, max_value=20, value=1)),
    'suites':         ('select', 'Suítes', ['Não informado', '0', '1', '2', '3', '4', '5+']),
    'tipo_imovel':    ('select', 'Tipo de imovel', ['apartamento', 'casa']),
    'bairro':         ('select_bairro', 'Bairro', None),
    'novo_lancamento':('check', 'Novo lancamento', None),
    'tem_elevador':   ('check', 'Tem elevador', None),
    'predicao_idade': ('number', 'Idade do imovel (anos)', dict(min_value=0, max_value=200, value=0)),
    'priv_churrasqueira': ('check', 'Churrasqueira (priv.)', None),
    'priv_varanda':   ('check', 'Varanda', None),
    'priv_piscina':   ('check', 'Piscina (priv.)', None),
    'priv_closet':    ('check', 'Closet', None),
    'comum_piscina':  ('check', 'Piscina (cond.)', None),
    'comum_elevador': ('check', 'Elevador (cond.)', None),
    'comum_salao':    ('check', 'Salão de festas', None),
    'comum_churrasqueira': ('check', 'Churrasqueira (cond.)', None),
    'comum_playground': ('check', 'Playground', None),
    'comum_academia': ('check', 'Academia/Fitness', None),
    'comum_spa':      ('check', 'Spa/Sauna', None),
}

GRUPO_WIDGET = {
    'metragem': 'base', 'quartos': 'base', 'banheiros': 'base', 'vagas': 'base',
    'suites': 'base', 'tipo_imovel': 'base', 'predicao_idade': 'base',
    'bairro': 'base', 'novo_lancamento': 'base', 'tem_elevador': 'base',
}


def gerar_pagina_predicao(cidade_path, prefixo_name, cidade_nome_poi):
    pasta = Path(__file__).resolve().parent.parent / 'dados' / cidade_path
    pasta.mkdir(parents=True, exist_ok=True)

    modelo, bairro_stats, mes_ref, preditor, feature_names, km_cluster, scaler_cluster, target_transform, topicos_data = carregar_modelo_e_stats(pasta, prefixo_name)

    indices = None
    try:
        indices = CriandoIndicesIndividuais(cidade=cidade_nome_poi, cache_dir=pasta)
    except Exception as e:
        st.warning(f"Nao foi possivel carregar indices de localizacao: {e}")

    st.markdown(f"### Predicao de Valor - {prefixo_name.replace('_', ' ').title()}")
    st.caption(f"Modelo: {mes_ref} | {len(bairro_stats)} bairros disponiveis")

    estado = CIDADE_POI.get(prefixo_name.split("_")[0], "").split(", ")[1] if CIDADE_POI.get(prefixo_name.split("_")[0]) else "SP"

    with st.form("form_predicao"):
        col1, col2 = st.columns(2)
        valores = {}

        def render_widget(col, feature, cfg):
            tipo, rotulo, args = cfg
            key = f"pred_{feature}"
            if tipo == 'number':
                return col.number_input(rotulo, key=key, **(args or {}))
            if tipo == 'select':
                return col.selectbox(rotulo, options=args, key=key)
            if tipo == 'select_bairro':
                return col.selectbox(rotulo, options=sorted(bairro_stats.index.tolist()), key=key)
            if tipo == 'check':
                return col.checkbox(rotulo, key=key)
            return col.number_input(rotulo or feature, key=key, value=0)

        with col1:
            rua = st.text_input("Rua (opcional)", help="Se preenchido, usado para geolocalizacao exata")
            numero = st.number_input("Numero (opcional)", 0, 99999, 0,
                                     help="Se preenchido junto com a rua, melhora a precisao da geolocalizacao")
            # Particiona as features base entre col1/col2 (cada key renderizada 1x)
            base_feats = [f for f in feature_names
                          if f not in DERIVADAS_PRED
                          and GRUPO_WIDGET.get(f, 'amen') == 'base'
                          and f != 'bairro']
            metade = (len(base_feats) + 1) // 2
            col1_feats, col2_feats = base_feats[:metade], base_feats[metade:]
            for feature in col1_feats:
                cfg = WIDGETS_PRED.get(feature)
                if cfg is None:
                    cfg = ('number', feature, dict(value=0))
                valores[feature] = render_widget(col1, feature, cfg)

        with col2:
            if 'bairro' in feature_names:
                valores['bairro'] = render_widget(col2, 'bairro', WIDGETS_PRED['bairro'])
            else:
                valores['bairro'] = sorted(bairro_stats.index.tolist())[0]
            for feature in col2_feats:
                cfg = WIDGETS_PRED.get(feature)
                if cfg is None:
                    cfg = ('number', feature, dict(value=0))
                valores[feature] = render_widget(col2, feature, cfg)

        with st.expander("Amenidades privativas / comuns (se o modelo usar)"):
            for feature in feature_names:
                if feature in DERIVADAS_PRED:
                    continue
                if GRUPO_WIDGET.get(feature, 'amen') == 'base':
                    continue
                cfg = WIDGETS_PRED.get(feature)
                if cfg is None:
                    cfg = ('number', feature, dict(value=0))
                valores[feature] = render_widget(st, feature, cfg)

        metragem = valores.get('metragem', 70)
        quartos = valores.get('quartos', 3)
        banheiros = valores.get('banheiros', 2)
        vagas = valores.get('vagas', 1)
        tipo_imovel = valores.get('tipo_imovel', 'apartamento')
        bairro = valores.get('bairro', sorted(bairro_stats.index.tolist())[0])
        novo_lancamento = bool(valores.get('novo_lancamento', False))
        tem_elevador = bool(valores.get('tem_elevador', False))
        predicao_idade = valores.get('predicao_idade', 0)
        suites_raw = valores.get('suites', 'Não informado')
        try:
            suites_val = int(suites_raw) if str(suites_raw).isdigit() else 0
        except (ValueError, TypeError):
            suites_val = 0
        extras = {k: v for k, v in valores.items()
                  if k not in ('metragem', 'quartos', 'banheiros', 'vagas',
                               'tipo_imovel', 'bairro', 'novo_lancamento',
                               'tem_elevador', 'predicao_idade')}
        if 'suites' in extras:
            extras['suites'] = suites_val

        modelo_precisa_topicos = any(c.startswith("componente_") for c in feature_names)
        if modelo_precisa_topicos:
            descricao = st.text_area("Descricao (opcional)", height=100,
                                     help="Descricao do imovel — usada para topicos NMF. Quanto mais detalhes, melhor.")
        else:
            descricao = ""

        submitted = st.form_submit_button("Prever valor", type="primary")

    if submitted:
        with st.spinner("Geocodificando endereco..."):
            cidade_nome = cidade_nome_poi.split(",")[0].strip() if cidade_nome_poi else ""
            lat, lng = geocodificar_endereco_app(rua, numero, bairro, cidade_nome, estado)

            if lat is None:
                if bairro in bairro_stats.index and 'lat_centroide' in bairro_stats.columns:
                    lat = bairro_stats.loc[bairro, 'lat_centroide']
                    lng = bairro_stats.loc[bairro, 'lng_centroide']
                    st.info("Usando centroide do bairro (endereco nao encontrado no Nominatim)")
                else:
                    st.error("Endereco nao encontrado e sem centroide disponivel.")
                    st.stop()

        with st.spinner("Calculando features e POI scores..."):
            X_pred = montar_features_predicao(
                metragem=metragem, quartos=quartos, banheiros=banheiros,
                vagas=vagas, tipo_imovel=tipo_imovel, bairro=bairro,
                novo_lancamento=novo_lancamento, tem_elevador=tem_elevador,
                lat=lat, lng=lng,
                bairro_stats=bairro_stats, indices=indices,
                km_cluster=km_cluster, scaler_cluster=scaler_cluster,
                predicao_idade=predicao_idade, extras=extras, rua=rua,
            )

        if modelo_precisa_topicos and topicos_data is not None:
            _aplicar_topicos_descricao(descricao, topicos_data, X_pred)

        for c in TOPIC_COLS:
            if c not in X_pred.columns:
                X_pred[c] = 0.0

        X_pred_filtrado = X_pred[[c for c in feature_names if c in X_pred.columns]]
        valor_pred_raw = modelo.predict(X_pred_filtrado)[0]
        valor_pred = max(np.expm1(valor_pred_raw) if target_transform == "log" else valor_pred_raw, 0)

        valor_lo = None
        valor_hi = None
        if preditor is not None:
            try:
                y_p, lo, hi = preditor.predict(X_pred_filtrado)
                if target_transform == "log":
                    lo, hi = np.expm1(lo), np.expm1(hi)
                else:
                    lo, hi = lo, hi
                valor_lo = max(lo[0], 0)
                valor_hi = max(hi[0], 0)
            except Exception as e:
                st.warning(f"Nao foi possivel calcular intervalo: {e}")

        st.divider()
        col_res1, col_res2, col_res3 = st.columns(3)
        col_res1.metric("Valor previsto", f"R$ {valor_pred:,.2f}")
        if valor_lo is not None:
            st.caption(
                f"Intervalo de 90%: "
                f"R$ {valor_lo:,.2f} ~ R$ {valor_hi:,.2f}"
            )
        col_res2.metric("Metragem", f"{metragem} m²")
        col_res3.metric("Bairro", bairro)

        st.divider()
        with st.expander("Detalhes das features utilizadas"):
            for col in feature_names:
                if col in X_pred.columns:
                    val = X_pred[col].values[0]
                    if isinstance(val, (int, float)):
                        st.text(f"{col}: {val:.4f}")
                    else:
                        st.text(f"{col}: {val}")
