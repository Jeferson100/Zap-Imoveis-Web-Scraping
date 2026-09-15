import os
import pandas as pd
import numpy as np
import json
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
}

dados_todas_cidades = {}
stats_todas_cidades = {}
dados_aluguel_cidades = {}
cidades_com_aluguel = []


def _carregar_sao_paulo(base_dir):
    """Carrega todos os bairros de São Paulo de subdiretórios."""
    pasta = base_dir / 'dados' / 'sao_paulo'
    subpastas = [d for d in pasta.iterdir() if d.is_dir()]
    if not subpastas:
        print('  Nenhum bairro encontrado em sao_paulo/.')
        return None, None

    dfs = []
    data_ref = ''
    for subpasta in sorted(subpastas):
        bairro = subpasta.name
        arquivos = list(subpasta.glob(f'sao_paulo_{bairro}_imoveis_limpo_*.parquet'))
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
        print('  Nenhum dado encontrado para São Paulo.')
        return None, None

    df = pd.concat(dfs, ignore_index=True)
    print(f'  Total: {len(df)} imóveis de {len(dfs)} bairros ({data_ref})')
    return df, data_ref


def exportar_cidade(cidade, base_dir):
    if cidade == 'sao_paulo':
        df, data_ref = _carregar_sao_paulo(base_dir)
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
