"""O dedup entre portais tem que manter a linha do imovelweb.

`idade` so existe no imovelweb (0% em chave_mao/olx/viva_real/zap). O pipeline concatena
os frames com o imovelweb por ultimo e usava `drop_duplicates(keep='first')`, entao em toda
duplicata entre portais a linha descartada era a unica com `idade`. Estes testes travam o
contrato do desempate.
"""

import pandas as pd

from funcoes_limpando_dados_imoveis import (
    FONTE_PRIORITARIA_DEDUP,
    deduplicar_manter_fonte_prioritaria,
)

CHAVES = ['valor_imovel', 'rua', 'bairro', 'metragem', 'quartos',
          'preco_por_m2', 'banheiros', 'lat', 'lng']


def _base():
    """Ordem real do pipeline: zap primeiro, imovelweb por ultimo."""
    dup = dict(valor_imovel=500000, rua='a', bairro='atiradores', metragem=100.0,
               quartos=2, preco_por_m2=5000.0, banheiros=1, lat=-26.28, lng=-48.83)
    unico = dict(valor_imovel=300000, rua='b', bairro='centro', metragem=60.0,
                 quartos=1, preco_por_m2=5000.0, banheiros=1, lat=-26.30, lng=-48.85)
    return pd.DataFrame([
        {**dup, 'fonte': 'zap_imoveis', 'idade': pd.NA, 'url': 'zap/1'},
        {**unico, 'fonte': 'olx', 'idade': pd.NA, 'url': 'olx/9'},
        {**dup, 'fonte': 'imovelweb', 'idade': 32.0, 'url': 'imovelweb/7'},
    ])


def test_imovelweb_sobrevive_e_idade_fica():
    """O bug: o keep='first' antigo entregava a base sem nenhum rotulo de idade."""
    df = _base()
    antigo = df.drop_duplicates(subset=CHAVES, keep='first').reset_index(drop=True)
    assert antigo['idade'].isna().all()

    novo = deduplicar_manter_fonte_prioritaria(df, CHAVES)
    assert len(novo) == len(antigo)
    assert set(novo['fonte']) == {'imovelweb', 'olx'}
    assert float(novo.loc[novo['idade'].notna(), 'idade'].iloc[0]) == 32.0


def test_grupo_permanece_na_posicao_da_primeira_ocorrencia():
    """Contagem e ordem identicas ao comportamento antigo: so o membro muda."""
    df = _base()
    antigo = df.drop_duplicates(subset=CHAVES, keep='first').reset_index(drop=True)
    novo = deduplicar_manter_fonte_prioritaria(df, CHAVES)
    assert len(novo) == len(antigo) == 2
    assert novo['rua'].tolist() == antigo['rua'].tolist()  # 'a', 'b'


def test_sem_coluna_fonte_comportamento_antigo():
    df = _base().drop(columns=['fonte'])
    novo = deduplicar_manter_fonte_prioritaria(df, CHAVES)
    antigo = df.drop_duplicates(subset=CHAVES, keep='first').reset_index(drop=True)
    assert novo.equals(antigo)


def test_linhas_unicas_nao_mudam():
    dup = dict(valor_imovel=500000, rua='a', bairro='atiradores', metragem=100.0,
               quartos=2, preco_por_m2=5000.0, banheiros=1, lat=-26.28, lng=-48.83)
    linhas = [{**dict(valor_imovel=300000 + i, rua=f'u{i}', bairro='centro',
                      metragem=60.0 + i, quartos=1, preco_por_m2=5000.0, banheiros=1,
                      lat=-26.3, lng=-48.85),
               'fonte': 'zap_imoveis', 'idade': pd.NA, 'url': f'zap/u{i}'} for i in range(4)]
    linhas.insert(2, {**dup, 'fonte': 'olx', 'idade': pd.NA, 'url': 'olx/dup1'})
    linhas.append({**dup, 'fonte': 'imovelweb', 'idade': 41.0, 'url': 'imovelweb/dup2'})
    df = pd.DataFrame(linhas)

    antigo = df.drop_duplicates(subset=CHAVES, keep='first').reset_index(drop=True)
    novo = deduplicar_manter_fonte_prioritaria(df, CHAVES)

    assert len(novo) == len(antigo) == 5
    assert antigo['idade'].isna().all()
    assert int(novo['idade'].notna().sum()) == 1
    assert float(novo.loc[novo['idade'].notna(), 'idade'].iloc[0]) == 41.0
    assert int(novo.index[novo['idade'].notna()][0]) == 2  # 1a ocorrencia do grupo
    assert (novo.loc[novo['rua'].str.startswith('u'), 'url'].tolist()
            == antigo.loc[antigo['rua'].str.startswith('u'), 'url'].tolist())


def test_empate_dentro_da_fonte_prioritaria():
    df = pd.concat([_base(), _base().tail(1)], ignore_index=True)
    novo = deduplicar_manter_fonte_prioritaria(df, CHAVES)
    assert len(novo) == 2
    assert int((novo['fonte'] == FONTE_PRIORITARIA_DEDUP).sum()) == 1


def test_chave_vazia_e_dataframe_vazio():
    df = _base()
    assert len(deduplicar_manter_fonte_prioritaria(df, [])) == 3
    assert len(deduplicar_manter_fonte_prioritaria(df, ['url'])) == 3
    assert len(deduplicar_manter_fonte_prioritaria(df.iloc[0:0], CHAVES)) == 0
