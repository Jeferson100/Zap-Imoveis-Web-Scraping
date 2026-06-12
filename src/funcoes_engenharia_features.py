import pandas as pd

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


def engenharia_features_completa(train, test):
    """Aplica todas as funcoes de engenharia de features."""
    train, test = criar_features_bairro(train, test)
    train, test = criar_razoes(train, test)
    train, test = extrair_novo_lancamento(train, test)
    train, test = extrair_tem_elevador(train, test)
    return train, test
