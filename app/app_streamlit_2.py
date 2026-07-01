import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import joblib

from criando_indices_individuais import CriandoIndicesIndividuais

from config_features import NUMERIC_FEATURES, CATEGORICAL_FEATURES

ALL_FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

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

    return modelo, bairro_stats, mes_ref, preditor, feature_names_modelo, km_cluster, scaler_cluster, target_transform


def montar_features_predicao(metragem, quartos, banheiros, vagas,
                              tipo_imovel, bairro, novo_lancamento, tem_elevador,
                              lat, lng, bairro_stats, indices,
                              km_cluster=None, scaler_cluster=None):
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
            dados["bairro_cluster"] = int(km_cluster.predict(Xs)[0])
        except Exception:
            dados["bairro_cluster"] = 0
    else:
        dados["bairro_cluster"] = 0

    for col in ALL_FEATURES:
        if col not in df.columns:
            if bairro in bairro_stats.index and col in bairro_stats.columns:
                df[col] = bairro_stats.loc[bairro, col]
            elif col in bairro_stats.columns:
                df[col] = bairro_stats[col].mean()

    return df[ALL_FEATURES]


def gerar_pagina_predicao(cidade_path, prefixo_name, cidade_nome_poi):
    pasta = Path(__file__).resolve().parent.parent / 'dados' / cidade_path
    pasta.mkdir(parents=True, exist_ok=True)

    modelo, bairro_stats, mes_ref, preditor, feature_names, km_cluster, scaler_cluster, target_transform = carregar_modelo_e_stats(pasta, prefixo_name)

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

        with col1:
            rua = st.text_input("Rua (opcional)", help="Se preenchido, usado para geolocalizacao exata")
            numero = st.number_input("Numero (opcional)", 0, 99999, 0,
                                     help="Se preenchido junto com a rua, melhora a precisao da geolocalizacao")
            metragem = st.number_input("Metragem (m²)", 10, 10000, 70)
            quartos = st.number_input("Quartos", 1, 20, 3)
            banheiros = st.number_input("Banheiros", 1, 20, 2)

        with col2:
            vagas = st.number_input("Vagas", 0, 20, 1)
            tipo_imovel = st.selectbox("Tipo de imovel", ["apartamento", "casa"])
            bairro = st.selectbox("Bairro", sorted(bairro_stats.index.tolist()))
            novo_lancamento = st.checkbox("Novo lancamento")
            tem_elevador = st.checkbox("Tem elevador")

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
            )

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
            cols_importantes = ['lat', 'lng', 'valor_bairro_mean',
                                'metro_quadrado_bairro_mean', 'bairro_rank']
            for col in cols_importantes:
                if col in X_pred.columns:
                    st.text(f"{col}: {X_pred[col].values[0]:.4f}")

            st.text(f"Quartos por metro: {X_pred['quartos_por_metro'].values[0]:.4f}")
            st.text(f"Vagas por metro: {X_pred['vagas_por_metro'].values[0]:.4f}")
            st.text(f"Banheiros por quarto: {X_pred['banheiros_por_quarto'].values[0]:.4f}")

            for col in X_pred.columns:
                if col.startswith("score_"):
                    st.text(f"{col}: {X_pred[col].values[0]:.4f}")
