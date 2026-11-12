import logging
import re

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

PADRAO_NOVO_LANCAMENTO = r'''
    \bnovo\b|\bnova\b|\blan[çc]amento\b|\bpr[eé]-?lan[çc]amento\b|
    \bnovo\s+empreendimento\b|\bem\s+constru[cç][aã]o\b|
    \bprevis[aã]o\s+de\s+entrega\b|\bentrega\s+para\b|
    \bser[aá]\s+entregue\b|\bnunca\s+habitado\b|
    \brec[eé]m[- ]?entregue\b|\brec[eé]m[- ]?constru[ií]do\b
'''


def criar_features_bairro(train, test):
    """Medias/medianas do bairro + ranking."""
    bairro_stats = train.groupby('bairro').agg({
        'preco_por_m2': ['mean', 'median', 'count'],
        'valor_imovel': ['mean', 'median']
    }).fillna(0)

    train['metro_quadrado_bairro_mean'] = train['bairro'].map(
        bairro_stats[('preco_por_m2', 'mean')]
    )
    test['metro_quadrado_bairro_mean'] = test['bairro'].map(
        bairro_stats[('preco_por_m2', 'mean')]
    )

    train['metro_quadrado_bairro_median'] = train['bairro'].map(
        bairro_stats[('preco_por_m2', 'median')]
    )
    test['metro_quadrado_bairro_median'] = test['bairro'].map(
        bairro_stats[('preco_por_m2', 'median')]
    )

    train['valor_bairro_mean'] = train['bairro'].map(
        bairro_stats[('valor_imovel', 'mean')]
    )
    test['valor_bairro_mean'] = test['bairro'].map(
        bairro_stats[('valor_imovel', 'mean')]
    )

    bairro_rank = train.groupby('bairro')['preco_por_m2'].median().rank()
    train['bairro_rank'] = train['bairro'].map(bairro_rank)
    test['bairro_rank'] = test['bairro'].map(bairro_rank)

    return train, test


def criar_razoes(train, test):
    """razoes entre variaveis: quartos_por_metro, vagas_por_metro,
    banheiros_por_quarto, condominio_por_metro."""
    for num, den, nome in [
        ('quartos', 'metragem', 'quartos_por_metro'),
        ('vagas', 'metragem', 'vagas_por_metro'),
        ('banheiros', 'quartos', 'banheiros_por_quarto'),
        ('condominio', 'metragem', 'condominio_por_metro'),
    ]:
        train[nome] = train[num] / (train[den] + 1)
        test[nome] = test[num] / (test[den] + 1)
    return train, test


def extrair_novo_lancamento(train, test):
    """Extrai flag novo_lancamento da coluna descricao."""
    train['novo_lancamento'] = train['descricao'].str.contains(
        PADRAO_NOVO_LANCAMENTO, case=False, regex=True, na=False
    ).astype(int)
    test['novo_lancamento'] = test['descricao'].str.contains(
        PADRAO_NOVO_LANCAMENTO, case=False, regex=True, na=False
    ).astype(int)
    return train, test


def extrair_tem_elevador(train, test):
    """Extrai flag tem_elevador da coluna descricao."""
    train['tem_elevador'] = train['descricao'].str.contains(
        r'\belevador\b', case=False, na=False
    )
    test['tem_elevador'] = test['descricao'].str.contains(
        r'\belevador\b', case=False, na=False
    )
    return train, test


def extrair_sem_rua(train, test):
    """Flag 1 se o imovel nao tem rua (s/r)."""
    def _is_sem_rua(series):
        return (
            series.str.lower().isin(["s/r", "", "nan"]) |
            series.isna()
        ).astype(int)

    train["sem_rua"] = _is_sem_rua(train["rua"])
    test["sem_rua"] = _is_sem_rua(test["rua"])
    return train, test


def extrair_amenidades(df):
    """Extrai amenities das arrays caracteristicas_privativa/comum e caracteristicas."""
    df = df.copy()
    
    def check_arr(arr, term):
        if isinstance(arr, np.ndarray):
            return any(term in str(item).lower() for item in arr)
        return False
    
    # PRIVADAS (4)
    df['priv_churrasqueira'] = df['caracteristicas_privativa'].apply(
        lambda arr: 1 if check_arr(arr, 'churr') else 0
    )
    df['priv_varanda'] = df['caracteristicas_privativa'].apply(
        lambda arr: 1 if check_arr(arr, 'varanda') else 0
    )
    df['priv_piscina'] = df['caracteristicas_privativa'].apply(
        lambda arr: 1 if check_arr(arr, 'piscina') else 0
    )
    df['priv_closet'] = df['caracteristicas_privativa'].apply(
        lambda arr: 1 if check_arr(arr, 'closet') else 0
    )
    
    # COMUNS (7)
    df['comum_piscina'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'piscina') else 0
    )
    df['comum_elevador'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'elevador') else 0
    )
    df['comum_salao'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'salão') or check_arr(arr, 'salao') else 0
    )
    df['comum_churrasqueira'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'churr') else 0
    )
    df['comum_playground'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'playground') else 0
    )
    df['comum_academia'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'fitness') or check_arr(arr, 'academia') else 0
    )
    df['comum_spa'] = df['caracteristicas_comum'].apply(
        lambda arr: 1 if check_arr(arr, 'spa') or check_arr(arr, 'sauna') else 0
    )
    
    # SUITES - extraído de caracteristicas
    def extrair_suites(arr):
        if not isinstance(arr, np.ndarray):
            return np.nan
        for item in arr:
            s = str(item).lower()
            if 'suíte' in s or 'suite' in s:
                if '0 su' in s: return 0
                for n in range(1, 7):
                    if f'{n} su' in s: return n
        return np.nan
    
    df['suites'] = df['caracteristicas'].apply(extrair_suites)
    
    return df


def extrair_amenidades_train_test(train, test):
    """Aplica extração de amenities em train e test."""
    train = extrair_amenidades(train)
    test = extrair_amenidades(test)
    return train, test


KM_POR_GRAU = 111.0


def sanitizar_coordenadas(df, max_km=50.0):
    """Substitui coordenadas de fallback do geocoder pelo centroide do bairro.

    Medido em Joinville/2026-11: 2.896 de 23.063 imoveis (12,6%) compartilham
    apenas 10 coordenadas, todas a 400-600 km da cidade (Parana, Minas, RS,
    Brasilia). Sao fallbacks do Nominatim para endereco ambiguo, nao imoveis.

    O estrago nao e so a coordenada: `dist_centro` e todos os `score_*` de POI
    sao calculados a partir de lat/lng, entao essas 2.896 linhas recebem
    distancia e vizinhanca de outra cidade. Por isso a funcao precisa rodar
    ANTES de `CriandoIndicesIndividuais.calcular_indices`.

    O centroide da cidade e a MEDIANA (robusta aos 12,6% de outliers) e a
    reposicao usa o centroide do proprio bairro, calculado apenas com as
    coordenadas plausiveis. Nao usa o alvo, entao e livre de vazamento e
    idempotente.
    """
    if "lat" not in df.columns or "lng" not in df.columns:
        return df

    lat = pd.to_numeric(df["lat"], errors="coerce").to_numpy(dtype=float)
    lng = pd.to_numeric(df["lng"], errors="coerce").to_numpy(dtype=float)
    validos = np.isfinite(lat) & np.isfinite(lng)
    if validos.sum() < 10:
        return df

    lat0 = float(np.median(lat[validos]))
    lng0 = float(np.median(lng[validos]))
    d_km = np.hypot(
        (lat - lat0) * KM_POR_GRAU,
        (lng - lng0) * KM_POR_GRAU * np.cos(np.radians(lat0)),
    )
    ruim = ~validos | (np.isfinite(d_km) & (d_km > max_km))
    n = int(ruim.sum())
    if n == 0:
        return df

    ok = ~ruim
    lat_fix = np.full(len(df), np.nan, dtype=float)
    lng_fix = np.full(len(df), np.nan, dtype=float)
    if "bairro" in df.columns and ok.any():
        bairros = df["bairro"].astype(str).to_numpy()
        centros = (
            pd.DataFrame({"b": bairros[ok], "lat": lat[ok], "lng": lng[ok]})
            .groupby("b")[["lat", "lng"]].median()
        )
        lat_fix = pd.Series(bairros).map(centros["lat"]).to_numpy(dtype=float)
        lng_fix = pd.Series(bairros).map(centros["lng"]).to_numpy(dtype=float)

    lat[ruim] = np.where(np.isfinite(lat_fix[ruim]), lat_fix[ruim], lat0)
    lng[ruim] = np.where(np.isfinite(lng_fix[ruim]), lng_fix[ruim], lng0)
    df["lat"] = lat
    df["lng"] = lng

    logger.warning(
        "coordenadas implausiveis corrigidas: %d linha(s) a mais de %.0f km do "
        "centroide (%.3f, %.3f)", n, max_km, lat0, lng0,
    )
    return df


CLUSTER_COLS = [    "score_escola_privada", "score_escola_publica", "score_hospitais",
    "score_mercado", "score_farmacia", "score_parque",
    "score_seguranca",
]


def criar_clusters_bairro(train, test, random_state=42, save_path=None):
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    import joblib

    n = len(train)
    n_clusters = 3

    cols_existentes = [c for c in CLUSTER_COLS if c in train.columns]
    if not cols_existentes:
        train["bairro_cluster"] = 0
        test["bairro_cluster"] = 0
        return train, test

    scaler = StandardScaler()
    Xs = scaler.fit_transform(train[cols_existentes].fillna(0))

    km = KMeans(n_clusters=n_clusters, random_state=random_state, n_init="auto")
    train["bairro_cluster"] = km.fit_predict(Xs)
    test["bairro_cluster"] = km.predict(scaler.transform(test[cols_existentes].fillna(0)))

    if save_path:
        joblib.dump({"kmeans": km, "scaler": scaler}, save_path)

    return train, test


# ── Score de texto ────────────────────────────────────────────────────────────
# Versao da limpeza. Se os regex mudarem, incrementar: treino e inferencia
# precisam usar exatamente a mesma transformacao, senao a feature deriva em
# silencio.
SCORE_TEXTO_VERSAO = 1

_RE_MOEDA = re.compile(r"R\$\s*[\d\.,]*", re.IGNORECASE)
_RE_PALAVRA_PRECO = re.compile(
    r"\b(valor|pre[çc]o|reais?|mil|milh[ãa]o|milh[õo]es)\b", re.IGNORECASE
)
_RE_NUMEROS = re.compile(r"\d[\d\.,]*")


def _texto_limpo(df):
    """Titulo + descricao sem numeros, 'R$' e palavras de preco.

    24% das descricoes contem o proprio valor do imovel e 28% trazem 'R$'.
    Sem essa limpeza o modelo aprende a ler o preco escrito no anuncio em vez
    das caracteristicas do imovel (vazamento do alvo).
    """
    n = len(df)
    titulo = (
        df["titulo"].fillna("").astype(str).to_numpy()
        if "titulo" in df.columns
        else np.full(n, "", dtype=object)
    )
    descricao = (
        df["descricao"].fillna("").astype(str).to_numpy()
        if "descricao" in df.columns
        else np.full(n, "", dtype=object)
    )
    texto = pd.Series(titulo + " " + descricao, dtype="object")
    texto = texto.str.replace(_RE_MOEDA, " ", regex=True)
    texto = texto.str.replace(_RE_PALAVRA_PRECO, " ", regex=True)
    return texto.str.replace(_RE_NUMEROS, " ", regex=True)


def _ajustar_score_texto(train, alpha, max_features):
    """Ajusta TF-IDF + Ridge no treino e devolve (artefato, X, y, mascara_valida)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import Ridge

    y = np.log1p(
        pd.to_numeric(train["valor_imovel"], errors="coerce").values.astype(float)
    )
    valido = np.isfinite(y)
    if valido.sum() < 10:
        raise ValueError(
            "score_texto: treino com menos de 10 valores validos de valor_imovel"
        )

    vec = TfidfVectorizer(
        max_features=max_features, ngram_range=(1, 2), min_df=3, sublinear_tf=True,
    )
    X = vec.fit_transform(_texto_limpo(train))
    ridge = Ridge(alpha=alpha).fit(X[valido], y[valido])

    artefato = {
        "vectorizer": vec,
        "ridge": ridge,
        "alpha": alpha,
        "versao": SCORE_TEXTO_VERSAO,
        "target_transform": "log1p",
    }
    return artefato, X, y, valido


def treinar_score_texto(train, alpha=3.0, max_features=20000):
    """Ajusta o modelo de texto no treino e devolve apenas o artefato serializavel."""
    artefato, _, _, _ = _ajustar_score_texto(train, alpha, max_features)
    return artefato


def aplicar_score_texto(df, artefato):
    """Aplica um artefato ja treinado (teste, dataset completo ou anuncio novo)."""
    X = artefato["vectorizer"].transform(_texto_limpo(df))
    return artefato["ridge"].predict(X)


def criar_score_texto(train, test, alpha=3.0, random_state=42, n_splits=5,
                      max_features=20000, save_path=None):
    """Feature `score_texto`: previsao do log do preco a partir do texto.

    - treino: valor out-of-fold (KFold), para que cada imovel seja previsto por
      um modelo que nao o viu;
    - teste/inferencia: previsao do Ridge ajustado no treino inteiro.

    `save_path` (opcional) grava o artefato em joblib; sem ele nao ha como
    calcular a feature em anuncios novos.
    """
    from sklearn.model_selection import KFold
    from sklearn.linear_model import Ridge
    import joblib

    if "valor_imovel" not in train.columns or "descricao" not in train.columns:
        logger.warning(
            "score_texto nao criado: faltam 'valor_imovel' e/ou 'descricao'"
        )
        return train, test, None

    n_validos = int(
        np.isfinite(
            pd.to_numeric(train["valor_imovel"], errors="coerce").values.astype(float)
        ).sum()
    )
    if n_validos < 10:
        logger.warning(
            "score_texto nao criado: apenas %d valores validos de valor_imovel",
            n_validos,
        )
        return train, test, None

    artefato, X, y, valido = _ajustar_score_texto(train, alpha, max_features)

    n_splits = max(2, min(int(n_splits), int(valido.sum())))
    oof = np.full(X.shape[0], np.nan, dtype=float)
    for idx_fit, idx_pred in KFold(
        n_splits, shuffle=True, random_state=random_state
    ).split(X):
        mask = valido[idx_fit]
        if mask.sum() < 2:
            continue
        fold = Ridge(alpha=alpha).fit(X[idx_fit][mask], y[idx_fit][mask])
        oof[idx_pred] = fold.predict(X[idx_pred])

    train["score_texto"] = oof
    test["score_texto"] = aplicar_score_texto(test, artefato)

    # Guarda de vazamento. score_texto e uma previsao do ALVO empilhada como
    # feature; so e legitimo enquanto for out-of-fold. Se o loop acima nao rodar
    # (n_splits degenerado, indice desalinhado), entra valor in-sample, a
    # correlacao sobe e nenhuma metrica de teste avisa. OOF tem de ser
    # visivelmente PIOR que o ajuste pleno no mesmo treino.
    insample = artefato["ridge"].predict(X)
    c_oof = float(np.corrcoef(oof[valido], y[valido])[0, 1])
    c_in = float(np.corrcoef(insample[valido], y[valido])[0, 1])
    # So faz sentido acusar quando existe sinal a proteger: se o texto nao
    # explica nada (base pequena, descricoes identicas), OOF e in-sample sao
    # ambos ~0 e a guarda daria falso positivo.
    if np.isfinite(c_in) and c_in >= 0.15 and (c_in - c_oof) < 0.01:
        raise RuntimeError(
            "score_texto suspeito: OOF r=%.4f vs in-sample r=%.4f (folga esperada "
            "> 0.01). O valor in-sample vazou na coluna de treino." % (c_oof, c_in)
        )
    artefato["corr_oof"] = c_oof
    artefato["corr_insample"] = c_in
    logger.info(
        "score_texto: OOF r=%.4f | in-sample r=%.4f | folga %.4f",
        c_oof, c_in, c_in - c_oof,
    )

    if save_path:
        joblib.dump(artefato, save_path)
        logger.info("Modelo de score_texto salvo: %s", save_path)

    return train, test, artefato


def engenharia_features_completa(train, test, score_texto_path=None):
    """Aplica todas as funcoes de engenharia de features."""
    train = sanitizar_coordenadas(train)
    test = sanitizar_coordenadas(test)
    train, test = criar_features_bairro(train, test)
    train, test = criar_razoes(train, test)
    train, test = extrair_novo_lancamento(train, test)
    train, test = extrair_tem_elevador(train, test)
    train, test = extrair_sem_rua(train, test)
    train, test = extrair_amenidades_train_test(train, test)
    train, test = criar_clusters_bairro(train, test)
    train, test, _ = criar_score_texto(train, test, save_path=score_texto_path)
    return train, test
