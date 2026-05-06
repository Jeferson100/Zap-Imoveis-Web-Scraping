from app_streamlit import gerar_pagina_analise_imoveis

import pandas as pd
import streamlit as st
from pathlib import Path
import re

cidade_nome = 'Florianopolis'

prefixo_name = 'florianopolis'

cidade_path = 'florianopolis'

BASE_DIR = Path.cwd().parent

pasta = BASE_DIR / 'dados' / cidade_path

arquivos = list(pasta.glob(f'{prefixo_name}_imoveis_limpo_*.parquet'))

mais_recentes_por_fonte = {}

for arquivo in arquivos:
    partes = arquivo.stem.split('_')
    portal = partes[-2]
    data = partes[-1]
    
    if portal not in mais_recentes_por_fonte:
        mais_recentes_por_fonte[portal] = arquivo
    else:
        # Compara as datas (string YYYY-MM funciona bem com comparação direta)
        data_atual = mais_recentes_por_fonte[portal].stem.split('_')[-1]
        if data > data_atual:
            mais_recentes_por_fonte[portal] = arquivo

# 3. Agora lemos apenas os selecionados
dfs = []
for portal, caminho in mais_recentes_por_fonte.items():
    try:
        df_temp = pd.read_parquet(caminho)
        dfs.append(df_temp)
        #st.info(f"Carregado {portal} mais recente: {caminho.name}")
        print(f"Carregado {portal} mais recente: {caminho.name}") # Altera
    except Exception as e:
        #st.error(f"Erro ao ler {caminho.name}: {e}")
        print(f"Erro ao ler {caminho.name}:)")

if dfs:
    df = pd.concat(dfs, ignore_index=True)
else:
    #st.warning("Nenhum arquivo encontrado.")
    print("Nenhum arquivo encontrado.")

colunas_dedup = ['valor_imovel', 'rua', 'bairro', 'metragem', 'quartos', 'preco_por_m2', 'banheiros', 'lat', 'lng']
    
colunas_dedup = [c for c in colunas_dedup if c in df.columns]  

antes = len(df)
    
df_limpo = df.drop_duplicates(subset=colunas_dedup, keep='first').reset_index(drop=True)

data_mais_recente = mais_recentes_por_fonte['zap'].stem.split('_')[-1]

gerar_pagina_analise_imoveis(cidade_path, cidade_nome, prefixo_name, df_limpo, data_mais_recente)