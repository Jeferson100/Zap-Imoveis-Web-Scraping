import os
import pandas as pd
import numpy as np
import json
import re
from pathlib import Path


CIDADES = {
    'joinville': 'Joinville',
    'florianopolis': 'Florianópolis',
    'blumenau': 'Blumenau',
    'balneario_camboriu': 'Balneário Camboriú',
    'balneario_picaras': 'Balneário Picarras',
    'itajai': 'Itajaí',
    'itapema': 'Itapema',
    'itapoa': 'Itapoá',
    'jaragua': 'Jaraguá do Sul',
    'curitiba': 'Curitiba',
    'sao_paulo': 'São Paulo',
    'rio_janeiro': 'Rio de Janeiro',
}

dados_todas_cidades = {}
stats_todas_cidades = {}
dados_aluguel_cidades = {}
cidades_com_aluguel = []


def _chave_anuncio(url):
    """Chave estável do anúncio, sem parâmetros de rastreamento da URL.

    Cada portal expõe o ID de um jeito diferente. Quando não há ID reconhecido,
    a própria URL normalizada é usada como chave.
    """
    if not isinstance(url, str):
        return None

    limpa = url.split('?', 1)[0].split('#', 1)[0].rstrip('/')
    for padrao in (r'-id-(\d+)', r'/id-(\d+)', r'-(\d+)\.html', r'-(\d+)$'):
        encontrado = re.search(padrao, limpa, re.IGNORECASE)
        if encontrado:
            return encontrado.group(1)
    return limpa.lower()


def exportar_ineditos(cidade, base_dir, df, df_export, mes_atual):
    """Exporta os anúncios que não existiam no snapshot do mês anterior.

    A comparação é por ID do anúncio (não por idade do imóvel nem por dias de
    publicação), e só é feita para Joinville, cidade da página de inéditos.
    """
    if cidade != 'joinville':
        return None

    meses = []
    pasta_dados = base_dir / 'dados' / cidade
    for arquivo in pasta_dados.glob(f'{cidade}_imoveis_limpo_*.parquet'):
        encontrado = re.search(r'(\d{4}-\d{2})$', arquivo.stem)
        if encontrado and encontrado.group(1) < mes_atual:
            meses.append((encontrado.group(1), arquivo))

    mes_anterior = None
    chaves_anteriores = set()
    tem_anterior = False
    if meses:
        mes_anterior, arquivo_anterior = max(meses, key=lambda par: par[0])
        try:
            anterior = pd.read_parquet(arquivo_anterior, columns=['url'])
        except Exception as exc:
            print(f'  Aviso: nao foi possivel ler {arquivo_anterior.name}: {exc}')
            mes_anterior = None
        else:
            chaves_anteriores = set(anterior['url'].map(_chave_anuncio).dropna())
            tem_anterior = True

    if tem_anterior:
        chaves_atuais = df['url'].map(_chave_anuncio)
        ineditos = ~chaves_atuais.isin(chaves_anteriores)
        dados_ineditos = df_export.loc[ineditos].to_dict(orient='records')
    else:
        # Sem snapshot anterior não há como saber o que é inédito: melhor
        # entregar lista vazia do que marcar tudo como novo.
        dados_ineditos = []

    pasta_saida = base_dir / 'site_estatico' / 'data'
    pasta_saida.mkdir(parents=True, exist_ok=True)

    with open(pasta_saida / 'imoveis_ineditos_joinville.json', 'w', encoding='utf-8') as f:
        json.dump(dados_ineditos, f, ensure_ascii=False, default=str)

    js = 'window.DADOS_INEDITOS = window.DADOS_INEDITOS || {};\n'
    js += 'window.DADOS_INEDITOS["joinville"] = '
    js += json.dumps(dados_ineditos, ensure_ascii=False, default=str, separators=(',', ':'))
    js += ';\n'
    with open(pasta_saida / 'dados_ineditos_joinville.js', 'w', encoding='utf-8') as f:
        f.write(js)

    config = {
        'joinville': {
            'mes_atual': mes_atual,
            'mes_anterior': mes_anterior or '',
            'total': len(dados_ineditos),
            'total_base': len(df_export),
        }
    }
    with open(pasta_saida / 'config_ineditos.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f'  Ineditos: {len(dados_ineditos)} anuncios ({mes_anterior or "sem mes anterior"} -> {mes_atual})')
    return dados_ineditos


def _carregar_por_bairros(base_dir, cidade, rotulo):
    """Carrega todos os bairros de subdiretórios (São Paulo, Rio de Janeiro)."""
    pasta = base_dir / 'dados' / cidade
    subpastas = [d for d in pasta.iterdir() if d.is_dir()]
    if not subpastas:
        print(f'  Nenhum bairro encontrado em {cidade}/.')
        return None, None

    dfs = []
    data_ref = ''
    for subpasta in sorted(subpastas):
        bairro = subpasta.name
        arquivos = list(subpasta.glob(f'{cidade}_{bairro}_imoveis_limpo_*.parquet'))
        if not arquivos:
            continue
        arq = max(arquivos, key=lambda f: f.stem.split('_')[-1])
        data_ref = arq.stem.split('_')[-1]
        print(f'  Carregando {bairro}: {arq.name}...')
        df = pd.read_parquet(arq)
        if 'bairro' not in df.columns or df['bairro'].isna().all():
            df['bairro'] = bairro.replace('-', ' ').title()
        dfs.append(df)

    if not dfs:
        print(f'  Nenhum dado encontrado para {rotulo}.')
        return None, None

    df = pd.concat(dfs, ignore_index=True)
    print(f'  Total: {len(df)} imóveis de {len(dfs)} bairros ({data_ref})')
    return df, data_ref


def exportar_cidade(cidade, base_dir):
    if cidade in ('sao_paulo', 'rio_janeiro'):
        df, data_ref = _carregar_por_bairros(
            base_dir, cidade,
            rotulo='São Paulo' if cidade == 'sao_paulo' else 'Rio de Janeiro',
        )
        if df is None:
            return None, None
    else:
        pasta_dados = base_dir / 'dados' / cidade
        if not pasta_dados.exists():
            print(f'  Pasta {pasta_dados} não encontrada. Pulando.')
            return None, None

        arquivos = list(pasta_dados.glob(f'{cidade}_imoveis_limpo_*.parquet'))
        if not arquivos:
            print(f'  Nenhum parquet encontrado para {cidade}. Pulando.')
            return None, None

        arquivo = max(arquivos, key=lambda f: f.stem.split('_')[-1])
        data_ref = arquivo.stem.split('_')[-1]
        print(f'  Carregando {arquivo.name}...')
        df = pd.read_parquet(arquivo)

    cols_base = [
        'url', 'titulo', 'bairro', 'rua', 'tipo_imovel', 'fonte',
        'metragem', 'quartos', 'banheiros', 'vagas',
        'valor_imovel', 'preco_por_m2', 'dias_publicacao',
        'lat', 'lng', 'faixa', 'desvio_mediana',
    ]
    cols_extra = [
        'valor_predito', 'valor_predito_lo', 'valor_predito_hi',
        'predicao_idade', 'faixa_pred_idade',
        'score_potencial_flip', 'potencial_house_flip',
    ]

    cols = [c for c in cols_base + cols_extra if c in df.columns]

    df_export = df[cols].copy()

    if 'preco_por_m2' in df_export.columns:
        df_export['preco_por_m2'] = (
            df_export['preco_por_m2']
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
        )
        df_export['preco_por_m2'] = df_export['preco_por_m2'].astype(int)

    if 'desvio_mediana' in df_export.columns:
        df_export['desvio_mediana'] = (
            df_export['desvio_mediana']
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
            .round(2)
        )

    for c in ['lat', 'lng']:
        if c in df_export.columns:
            df_export[c] = pd.to_numeric(df_export[c], errors='coerce')

    for c in df_export.columns:
        if df_export[c].dtype.name == 'category':
            df_export[c] = df_export[c].astype(str)

    df_export = df_export.where(pd.notnull(df_export), '')

    data = df_export.to_dict(orient='records')

    pasta_saida = base_dir / 'site_estatico' / 'data'
    pasta_saida.mkdir(parents=True, exist_ok=True)

    with open(pasta_saida / f'imoveis_{cidade}.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, default=str)

    if cidade == 'joinville':
        exportar_ineditos(cidade, base_dir, df, df_export, data_ref)

    stats_cols = {}
    if 'preco_por_m2' in df.columns:
        stats_cols['mediana_ppm2'] = ('preco_por_m2', 'median')
        stats_cols['media_ppm2'] = ('preco_por_m2', 'mean')
    if 'metragem' in df.columns:
        stats_cols['mediana_metragem'] = ('metragem', 'median')
        stats_cols['media_metragem'] = ('metragem', 'mean')
    if 'valor_imovel' in df.columns:
        stats_cols['mediana_valor'] = ('valor_imovel', 'median')

    stats_cols['n_registros'] = ('preco_por_m2', 'count') if 'preco_por_m2' in df.columns else (df.columns[0], 'count')

    stats = df.groupby('bairro').agg(**stats_cols).round(2).reset_index()
    stats = stats.where(pd.notnull(stats), 0)

    stats.to_json(
        pasta_saida / f'bairro_stats_{cidade}.json',
        orient='records',
        force_ascii=False,
    )

    print(f'  Exportados {len(data)} imóveis e {len(stats)} bairros ({data_ref})')
    return data, stats.to_dict(orient='records')


def exportar_aluguel_cidade(cidade, base_dir):
    pasta_dados = base_dir / 'dados' / cidade
    if not pasta_dados.exists():
        return None

    arquivos = list(pasta_dados.glob(f'{cidade}_aluguel_imoveis_limpo_*.parquet'))
    if not arquivos:
        return None

    arquivo = max(arquivos, key=lambda f: f.stem.split('_')[-1])
    data_ref = arquivo.stem.split('_')[-1]
    print(f'  Carregando aluguel: {arquivo.name}...')
    df = pd.read_parquet(arquivo)

    cols_base = [
        'url', 'titulo', 'bairro', 'rua', 'tipo_imovel', 'fonte',
        'metragem', 'quartos', 'banheiros', 'vagas',
        'valor_imovel', 'preco_por_m2', 'dias_publicacao',
        'lat', 'lng', 'faixa', 'desvio_mediana',
    ]
    cols_extra = [
        'condominio', 'iptu',
    ]

    cols = [c for c in cols_base + cols_extra if c in df.columns]
    df_export = df[cols].copy()

    if 'preco_por_m2' in df_export.columns:
        df_export['preco_por_m2'] = (
            df_export['preco_por_m2']
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
        )
        df_export['preco_por_m2'] = df_export['preco_por_m2'].astype(int)

    if 'desvio_mediana' in df_export.columns:
        df_export['desvio_mediana'] = (
            df_export['desvio_mediana']
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0)
            .round(2)
        )

    for c in ['lat', 'lng']:
        if c in df_export.columns:
            df_export[c] = pd.to_numeric(df_export[c], errors='coerce')

    for c in df_export.columns:
        if df_export[c].dtype.name == 'category':
            df_export[c] = df_export[c].astype(str)

    df_export = df_export.where(pd.notnull(df_export), '')
    data = df_export.to_dict(orient='records')

    pasta_saida = base_dir / 'site_estatico' / 'data'
    pasta_saida.mkdir(parents=True, exist_ok=True)

    with open(pasta_saida / f'imoveis_aluguel_{cidade}.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, default=str)

    print(f'  Exportados {len(data)} imóveis de aluguel ({data_ref})')
    return data


def gerar_dados_js(base_dir):
    pasta_saida = base_dir / 'site_estatico' / 'data'
    pasta_saida.mkdir(parents=True, exist_ok=True)

    for cidade, data in dados_todas_cidades.items():
        js = f'window.DADOS_IMOVEIS = window.DADOS_IMOVEIS || {{}};\n'
        js += f'window.DADOS_IMOVEIS["{cidade}"] = '
        js += json.dumps(data, ensure_ascii=False, default=str, separators=(',', ':'))
        js += ';\n'

        with open(pasta_saida / f'dados_{cidade}.js', 'w', encoding='utf-8') as f:
            f.write(js)

        print(f'  Gerado dados_{cidade}.js ({len(data)} imóveis)')

    for cidade, stats in stats_todas_cidades.items():
        js = f'window.DADOS_STATS = window.DADOS_STATS || {{}};\n'
        js += f'window.DADOS_STATS["{cidade}"] = '
        js += json.dumps(stats, ensure_ascii=False, default=str, separators=(',', ':'))
        js += ';\n'

        with open(pasta_saida / f'stats_{cidade}.js', 'w', encoding='utf-8') as f:
            f.write(js)

    total_imoveis = sum(len(v) for v in dados_todas_cidades.values())
    print(f'\nGerados arquivos JS para {total_imoveis} imóveis de {len(dados_todas_cidades)} cidades')

    for cidade, data in dados_aluguel_cidades.items():
        js = f'window.DADOS_ALUGUEL = window.DADOS_ALUGUEL || {{}};\n'
        js += f'window.DADOS_ALUGUEL["{cidade}"] = '
        js += json.dumps(data, ensure_ascii=False, default=str, separators=(',', ':'))
        js += ';\n'

        with open(pasta_saida / f'dados_aluguel_{cidade}.js', 'w', encoding='utf-8') as f:
            f.write(js)

        print(f'  Gerado dados_aluguel_{cidade}.js ({len(data)} imóveis)')

    if cidades_com_aluguel:
        config = {'cidades': cidades_com_aluguel}
        with open(pasta_saida / 'config_aluguel.json', 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False)
        print(f'  Gerado config_aluguel.json ({len(cidades_com_aluguel)} cidades com aluguel)')


def main():
    base_dir = Path(__file__).resolve().parent.parent

    print('Cidades disponíveis:')
    for cid, nome in CIDADES.items():
        pasta = base_dir / 'dados' / cid
        tem_dados = pasta.exists() and any(pasta.glob(f'{cid}_imoveis_limpo_*.parquet'))
        status = 'OK' if tem_dados else '--'
        print(f'  [{status}] {nome} ({cid})')

    print()
    escolha = os.environ.get('CIDADE_EXPORTAR', 'todas').strip().lower()

    if escolha == 'todas':
        cidades_exportar = list(CIDADES.keys())
    elif escolha in CIDADES:
        cidades_exportar = [escolha]
    else:
        print(f'Cidade "{escolha}" não encontrada.')
        return

    for cidade in cidades_exportar:
        print(f'\nExportando {CIDADES.get(cidade, cidade)}...')
        data, stats = exportar_cidade(cidade, base_dir)
        if data is not None:
            dados_todas_cidades[cidade] = data
        if stats is not None:
            stats_todas_cidades[cidade] = stats

        aluguel = exportar_aluguel_cidade(cidade, base_dir)
        if aluguel is not None:
            dados_aluguel_cidades[cidade] = aluguel
            cidades_com_aluguel.append(cidade)

    gerar_dados_js(base_dir)
    print('\nConcluído!')


if __name__ == '__main__':
    main()
