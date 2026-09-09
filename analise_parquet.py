import pandas as pd
import numpy as np

df = pd.read_parquet('dados/joinville/joinville_imovelweb_2026-09.parquet')

print('=' * 60)
print('1. NUMERO DE LINHAS E COLUNAS')
print('=' * 60)
print(f'Linhas: {df.shape[0]}')
print(f'Colunas: {df.shape[1]}')

print()
print('=' * 60)
print('2. NOMES DE TODAS AS COLUNAS')
print('=' * 60)
for i, col in enumerate(df.columns, 1):
    print(f'{i:2d}. {col}')

print()
print('=' * 60)
print('3. TIPO DE DADOS DE CADA COLUNA')
print('=' * 60)
print(df.dtypes.to_string())

print()
print('=' * 60)
print('4. ESTATISTICAS BASICAS DA COLUNA idade')
print('=' * 60)
if 'idade' in df.columns:
    print(f'Tipo original: {df["idade"].dtype}')
    print(f'Valores unicos (primeiros 20): {df["idade"].unique()[:20]}')
    print(f'Total de valores unicos: {df["idade"].nunique()}')
    print()

    # Converter para numerico, forçando erros para NaN
    idade_num = pd.to_numeric(df['idade'], errors='coerce')
    print(f'Valores convertiveis para numero: {idade_num.notna().sum()}')
    print(f'Valores que NAO sao numeros: {(idade_num.isna() & df["idade"].notna()).sum()}')
    print()

    s = idade_num.dropna()
    if len(s) > 0:
        print(f'Media:              {s.mean():.4f}')
        print(f'Mediana:            {s.median():.4f}')
        print(f'Desvio padrao:      {s.std():.4f}')
        print(f'Minimo:             {s.min():.4f}')
        print(f'Maximo:             {s.max():.4f}')
        print(f'25o percentil:      {s.quantile(0.25):.4f}')
        print(f'50o percentil:      {s.quantile(0.50):.4f}')
        print(f'75o percentil:      {s.quantile(0.75):.4f}')
        print(f'Contagem valida:    {len(s)}')

        print()
        print('=' * 60)
        print('5. VALORES NULOS NA COLUNA idade (original)')
        print('=' * 60)
        null_count = df['idade'].isnull().sum()
        null_pct = df['idade'].isnull().mean() * 100
        print(f'Nulos (original):           {null_count}')
        print(f'Percentual (original):      {null_pct:.2f}%')
        print(f'Nao-numericos (convertidos): {(idade_num.isna() & df["idade"].notna()).sum()}')
        print(f'Total invalidos:            {idade_num.isna().sum()}')
    else:
        print('Nenhum valor numerico encontrado na coluna idade.')
else:
    print('Coluna "idade" nao encontrada!')

print()
print('=' * 60)
print('6. AMOSTRA DAS PRIMEIRAS 5 LINHAS')
print('=' * 60)
print(df.head().to_string())

print()
print('=' * 60)
print('7. DISTRIBUICAO DA COLUNA idade (PERCENTIS - valores numericos)')
print('=' * 60)
if 'idade' in df.columns:
    idade_num = pd.to_numeric(df['idade'], errors='coerce')
    s = idade_num.dropna()
    if len(s) > 0:
        percentis = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
        for p in percentis:
            val = s.quantile(p)
            print(f'{p * 100:5.1f}o percentil:  {val:.4f}')
        print()
        print('Distribuicao por faixas:')
        faixas = [0, 5, 10, 20, 30, 50, 100, 200, 500]
        bins = pd.cut(s, bins=faixas, right=False)
        dist = bins.value_counts().sort_index()
        for interval, count in dist.items():
            print(f'  {interval}: {count} ({count / len(s) * 100:.1f}%)')
    else:
        print('Nenhum valor numerico para calcular distribuicao.')

print()
print('=' * 60)
print('8. COLUNAS UTILEIS PARA PREDIZER idade')
print('=' * 60)
print()
print('--- Colunas numericas (correlacao com idade numerica) ---')
idade_num = pd.to_numeric(df['idade'], errors='coerce')
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
if 'idade' in num_cols:
    num_cols.remove('idade')
for col in num_cols:
    corr = idade_num.corr(df[col])
    if not np.isnan(corr):
        print(f'  {col:40s} correlacao: {corr:+.4f}')

# Tentar correlacao com colunas que parecem numericas mas estao como object
print()
print('--- Colunas object que podem ser numericas ---')
obj_cols = df.select_dtypes(include=['object']).columns.tolist()
excluir = ['url', 'titulo', 'endereco', 'descricao', 'data_criacao',
           'caracteristicas', 'caracteristicas_privativa',
           'caracteristicas_comum', 'fotos', 'fonte', 'idade']
for col in obj_cols:
    if col not in excluir:
        converted = pd.to_numeric(df[col], errors='coerce')
        valid = converted.notna().sum()
        if valid > len(df) * 0.5:
            corr = idade_num.corr(converted)
            if not np.isnan(corr):
                print(f'  {col:40s} (num valid: {valid:5d}) correlacao: {corr:+.4f}')

print()
print('--- Colunas categoricas ---')
cat_cols = df.select_dtypes(include=['object', 'category']).columns.tolist()
for col in cat_cols:
    n_unique = df[col].nunique()
    print(f'  {col:40s} {n_unique} valores unicos')

print()
print('=' * 60)
print('INFORMACOES GERAIS DO DATAFRAME')
print('=' * 60)
print(f'Uso de memoria: {df.memory_usage(deep=True).sum() / 1024 ** 2:.2f} MB')
