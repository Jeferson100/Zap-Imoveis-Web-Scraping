import osmnx as ox
import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
from pathlib import Path


class CriandoIndicesIndividuais:

    def __init__(self, cidade, cache_dir=None):
        self.cidade = cidade
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.pois = {}

    # ========================
    # CARREGAMENTO DE POIs
    # ========================

    def carregar_pois(self, forcar_download=False):
        cache_path = self._caminho_cache() if self.cache_dir else None

        if cache_path and cache_path.exists() and not forcar_download:
            self.pois = self._carregar_cache(cache_path)
            return self.pois

        print("Baixando dados de POIs do OpenStreetMap...")
        self.pois = {}

        downloads = [
            ("hospital",  {"amenity": "hospital"}),
            ("mercado",   {"shop": ["supermarket", "convenience"]}),
            ("farmacia",  {"amenity": "pharmacy"}),
            ("parque",    {"leisure": ["park", "garden"], "landuse": "recreation_ground"}),
            ("escola",    {"amenity": ["school", "college", "university"]}),
            ("policia",   {"amenity": ["police", "fire_station", "courthouse"]}),
        ]

        for nome, tags in downloads:
            print(f"  -> {nome}...")
            self.pois[nome] = ox.features_from_place(self.cidade, tags)
            self._extrair_coordenadas(self.pois[nome])

        self._processar_escolas()

        if cache_path:
            self._salvar_cache(cache_path)

        print(f"{len(self.pois)} categorias de POIs carregadas.")
        return self.pois

    def _caminho_cache(self):
        nome_arquivo = f"pois_{self.cidade.lower().replace(' ', '_').replace(',', '')}.parquet"
        return self.cache_dir / nome_arquivo if self.cache_dir else None

    def _salvar_cache(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        dados = {}
        for nome, gdf in self.pois.items():
            gdf_serializavel = gdf.copy()
            if "geometry" in gdf_serializavel.columns:
                gdf_serializavel["geometry"] = gdf_serializavel["geometry"].astype(str)
            dados[nome] = gdf_serializavel
        pd.to_pickle(dados, path)
        print(f"  POIs salvos em cache: {path}")

    def _carregar_cache(self, path):
        print(f"  Carregando POIs do cache: {path}")
        dados = pd.read_pickle(path)
        for nome, df in dados.items():
            dados[nome] = df
        return dados

    # ========================
    # PROCESSAMENTO DE ESCOLAS
    # ========================

    @staticmethod
    def _classificar_escola(row):
        nome = str(row.get("name", "")).lower()
        padroes_publicos = [
            "municipal", "estadual", "federal", "instituto federal",
            "colégio estadual", "escola municipal",
            "cmei", "emei", "emef", "eef", "eeef",
            "universidade federal", "universidade estadual",
            "ifpr", "ifsp", "ifsc", "ifrs"
        ]
        for p in padroes_publicos:
            if p in nome:
                return "publica"
        return "privada"

    def _processar_escolas(self):
        escolas = self.pois["escola"].copy()
        escolas["tipo_escola"] = escolas.apply(self._classificar_escola, axis=1)
        self.pois["escolas_publicas"] = escolas[escolas["tipo_escola"] == "publica"].copy()
        self.pois["escolas_privadas"] = escolas[escolas["tipo_escola"] == "privada"].copy()
        del self.pois["escola"]

    @staticmethod
    def _extrair_coordenadas(gdf):
        centroids = gdf.geometry.centroid
        gdf["lon"] = centroids.x
        gdf["lat"] = centroids.y
        return gdf

    # ========================
    # FEATURES DE DISTANCIA / CONTAGEM
    # ========================

    def adicionar_features_poi(self, imoveis_df, poi_df, prefix, radius_metros):
        poi_limpo = poi_df.dropna(subset=["lat", "lon"])

        if poi_limpo.empty:
            imoveis_df[f"dist_{prefix}_mais_proximo"] = np.nan
            for r in radius_metros:
                imoveis_df[f"qtd_{prefix}_{r}m"] = 0
            return imoveis_df

        imoveis_coords = np.radians(imoveis_df[["lat", "lng"]].fillna(0).values)
        poi_coords = np.radians(poi_limpo[["lat", "lon"]].values)

        tree = BallTree(poi_coords, metric="haversine")

        dist, _ = tree.query(imoveis_coords, k=1)
        imoveis_df[f"dist_{prefix}_mais_proximo"] = dist[:, 0] * 6371000

        for r in radius_metros:
            qtd = tree.query_radius(imoveis_coords, r=r / 6371000, count_only=True)
            imoveis_df[f"qtd_{prefix}_{r}m"] = qtd

        return imoveis_df

    # ========================
    # CALCULO DE SCORES
    # ========================

    @staticmethod
    def calcular_scores(df):
        scores = pd.DataFrame(index=df.index)

        scores["score_escola_privada"] = (
            1.2 * np.exp(-df["dist_escolas_privadas_mais_proximo"] / 600)
            + 0.6 * df["qtd_escolas_privadas_500m"]
        )
        scores["score_escola_publica"] = (
            0.6 * np.exp(-df["dist_escolas_publicas_mais_proximo"] / 600)
            + 0.2 * df["qtd_escolas_publicas_500m"]
        )
        scores["score_hospitais"] = (
            0.8 * np.exp(-df["dist_hospital_mais_proximo"] / 1200)
            + 0.4 * df["qtd_hospital_1000m"]
        )
        scores["score_mercado"] = (
            1.0 * np.exp(-df["dist_mercado_mais_proximo"] / 400)
            + 0.4 * df["qtd_mercado_500m"]
        )
        scores["score_farmacia"] = (
            0.6 * np.exp(-df["dist_farmacia_mais_proximo"] / 300)
            + 0.2 * df["qtd_farmacia_300m"]
        )
        scores["score_parque"] = (
            1.2 * np.exp(-df["dist_parque_mais_proximo"] / 1200)
            + 0.8 * df["qtd_parque_1000m"]
        )
        scores["score_seguranca"] = (
            1.0 * np.exp(-df["dist_policia_mais_proximo"] / 1500)
            + 0.3 * df["qtd_policia_500m"]
        )
        scores["score_educacao"] = (
            scores["score_escola_privada"]
            - 0.2 * scores["score_escola_publica"]
        )

        return scores

    # ========================
    # DISTANCIA DO CENTRO
    # ========================

    def _adicionar_distancia_centro(self, df):
        try:
            centro = ox.geocoder.geocode(self.cidade)
            lat_centro, lng_centro = centro[0], centro[1]
        except Exception:
            lat_centro = df["lat"].median()
            lng_centro = df["lng"].median()

        coords = np.radians(df[["lat", "lng"]].fillna(0).values)
        centro_rad = np.radians([[lat_centro, lng_centro]])

        tree = BallTree(centro_rad, metric="haversine")
        dist, _ = tree.query(coords, k=1)
        df["dist_centro"] = dist[:, 0] * 6371

        bins = [0, 5, 10, 15, float("inf")]
        labels = ["centro", "proximo", "distante", "longe"]
        df["dist_centro_faixa"] = pd.cut(
            df["dist_centro"], bins=bins, labels=labels, right=True, include_lowest=True
        )
        return df

    # ========================
    # METODO PRINCIPAL
    # ========================

    def calcular_indices(self, imoveis_df):
        if not self.pois:
            self.carregar_pois()

        df = imoveis_df.copy()

        configuracao = {
            "escolas_privadas": [500],
            "escolas_publicas": [500],
            "hospital": [1000],
            "mercado": [500],
            "farmacia": [300],
            "parque": [1000],
            "policia": [500],
        }

        for nome, raios in configuracao.items():
            df = self.adicionar_features_poi(df, self.pois[nome], nome, raios)

        scores = self.calcular_scores(df)
        for col in scores.columns:
            df[col] = scores[col]

        df = self._adicionar_distancia_centro(df)

        return df
