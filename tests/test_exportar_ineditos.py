"""Testes do recorte de anúncios inéditos da página de Joinville."""

import importlib.util
import json
from pathlib import Path

import pandas as pd

CAMINHO_MODULO = Path(__file__).resolve().parents[1] / 'scripts' / 'exportar_dados.py'
_especificacao = importlib.util.spec_from_file_location('exportar_dados', CAMINHO_MODULO)
exportar_dados = importlib.util.module_from_spec(_especificacao)
_especificacao.loader.exec_module(exportar_dados)


def _preparar(tmp_path, urls_anteriores=None):
    pasta = tmp_path / 'dados' / 'joinville'
    pasta.mkdir(parents=True)
    if urls_anteriores is not None:
        pd.DataFrame({'url': urls_anteriores}).to_parquet(
            pasta / 'joinville_imoveis_limpo_2026-10.parquet'
        )
    return tmp_path


def _config(base):
    caminho = base / 'site_estatico' / 'data' / 'config_ineditos.json'
    with caminho.open(encoding='utf-8') as arquivo:
        return json.load(arquivo)['joinville']


def test_chave_anuncio_ignora_parametros_de_rastreamento():
    chave = exportar_dados._chave_anuncio
    assert chave('https://www.zapimoveis.com.br/imovel/x-id-2918356410/?source=ranking') == '2918356410'
    assert chave('https://www.vivareal.com.br/imovel/y-id-2916785037/?source=x') == '2916785037'
    assert chave('https://www.chavesnamao.com.br/imovel/casa/id-46256535/') == '46256535'
    assert chave('https://www.imovelweb.com.br/propriedades/casa-3045269885.html?n_src=x') == '3045269885'
    assert chave('https://sc.olx.com.br/imoveis/apartamento-1048020198') == '1048020198'
    assert chave(None) is None


def test_ineditos_compara_por_id_e_nao_por_url(tmp_path):
    base = _preparar(
        tmp_path,
        [
            'https://www.zapimoveis.com.br/imovel/a-id-111/?source=ranking',
            'https://www.zapimoveis.com.br/imovel/b-id-222/?source=ranking',
        ],
    )
    urls = [
        # Mesmo anúncio do mês anterior, só mudou o parâmetro de rastreamento.
        'https://www.zapimoveis.com.br/imovel/a-id-111/?source=outro',
        'https://www.zapimoveis.com.br/imovel/c-id-333/?source=ranking',
        'https://www.zapimoveis.com.br/imovel/d-id-444/?source=ranking',
    ]
    df = pd.DataFrame({'url': urls})

    exportar_dados.exportar_ineditos('joinville', base, df, df.copy(), '2026-11')

    cfg = _config(base)
    assert cfg['mes_atual'] == '2026-11'
    assert cfg['mes_anterior'] == '2026-10'
    assert cfg['total'] == 2
    assert cfg['total_base'] == 3

    dados = base / 'site_estatico' / 'data'
    conteudo = (dados / 'dados_ineditos_joinville.js').read_text(encoding='utf-8')
    assert 'window.DADOS_INEDITOS["joinville"]' in conteudo
    assert '-id-111' not in conteudo
    assert '-id-333' in conteudo
    registros = json.loads((dados / 'imoveis_ineditos_joinville.json').read_text(encoding='utf-8'))
    assert [r['url'] for r in registros] == urls[1:]


def test_sem_mes_anterior_gera_lista_vazia(tmp_path):
    base = _preparar(tmp_path)

    exportar_dados.exportar_ineditos(
        'joinville', base, pd.DataFrame({'url': ['https://x-id-1/']}), pd.DataFrame({'url': ['https://x-id-1/']}), '2026-11'
    )

    cfg = _config(base)
    assert cfg['mes_anterior'] == ''
    assert cfg['total'] == 0


def test_outras_cidades_nao_geram_artefatos(tmp_path):
    base = _preparar(tmp_path)
    resultado = exportar_dados.exportar_ineditos(
        'blumenau', base, pd.DataFrame({'url': []}), pd.DataFrame({'url': []}), '2026-11'
    )
    assert resultado is None
    assert not (base / 'site_estatico' / 'data' / 'config_ineditos.json').exists()
