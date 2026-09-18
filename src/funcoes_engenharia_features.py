import pandas as pd
import numpy as np

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


CLUSTER_COLS = [
    "score_escola_privada", "score_escola_publica", "score_hospitais",
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


def engenharia_features_completa(train, test):
    """Aplica todas as funcoes de engenharia de features."""
    train, test = criar_features_bairro(train, test)
    train, test = criar_razoes(train, test)
    train, test = extrair_novo_lancamento(train, test)
    train, test = extrair_tem_elevador(train, test)
    train, test = extrair_sem_rua(train, test)
    train, test = extrair_amenidades_train_test(train, test)
    train, test = criar_clusters_bairro(train, test)
    return train, test
