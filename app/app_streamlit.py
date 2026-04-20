import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import numpy as np
from pathlib import Path
import numpy as np
from scipy.stats import pearsonr, spearmanr

def gerar_pagina_analise_imoveis(cidade_pth, cidade_nome, prefixo_arquivo):
    """
    Função para gerar automaticamente a estrutura da página de análise.
    cidade_nome: Ex: "Joinville"
    prefixo_arquivo: Ex: "zap_imoveis_joinville"
    """
    st.set_page_config(page_title=f"Análise de Imóveis {cidade_nome}", layout="wide")

    st.markdown("""
        <style>
        [data-testid="stMetricValue"] {
            font-size: 1.8rem;
            color: #1f77b4;
        }
        </style>
        """, unsafe_allow_html=True)

    BASE_DIR = Path(__file__).resolve().parent.parent

    pasta = BASE_DIR / 'dados' / cidade_pth
    
    try:

        #arquivos = list(pasta.glob(f'{prefixo_arquivo}_com_ind_local_*.csv'))
        arquivos = list(pasta.glob(f'{prefixo_arquivo}_imoveis_limpo_*.parquet'))
            
        arquivo_mais_recente = max(arquivos, key=lambda f: f.stem.split('_')[-1])
        
    except:
        #arquivos = list(pasta.glob(f'{prefixo_arquivo}_imoveis_limpo_*.csv'))
        arquivos = list(pasta.glob(f'{prefixo_arquivo}_imoveis_limpo_*.parquet'))
        
        print(arquivos)
            
        arquivo_mais_recente = max(arquivos, key=lambda f: f.stem.split('_')[-1])
    
    data_mais_recente = arquivo_mais_recente.stem.split('_')[-1]
            
    key_df = f"df_{cidade_nome.lower()}"
    
    if key_df not in st.session_state:
        #st.session_state[key_df] = pd.read_csv(arquivo_mais_recente)
        st.session_state[key_df] = pd.read_parquet(arquivo_mais_recente)
        
    df = st.session_state[key_df]

    superior = df['preco_por_m2'].quantile(0.996)

    df['preco_por_m2'] = df['preco_por_m2'].replace([np.inf, -np.inf], np.nan)
    
    mediana = df['preco_por_m2'].median()
    preco_metro_median = int(mediana) if pd.notna(mediana) else 0

    #preco_metro_median= df['preco_por_m2'].median().astype(int)

    df['preco_por_m2'] = df['preco_por_m2'].fillna(preco_metro_median).astype(int)

    df["desvio_mediana"] = round((df["preco_por_m2"] - df["p50_bairro"]) / df["p50_bairro"],2) 

    if pd.isna(superior):
        print("ERRO: O valor superior é NaN. Verifique se a coluna preco_por_m2 tem números válidos.")
    else:
        df = df[df['preco_por_m2'] < superior].astype({'preco_por_m2': int})
        
    df = df.rename(columns={'score': 'indice_localizacao'})

    st.title(f'🏠 Análise de Imóveis {cidade_nome} - Zap Imóveis')

    st.subheader(f'Atualizado em: {data_mais_recente}')

    st.sidebar.header('Filtros')

    bairros_opcoes = sorted(df['bairro'].unique().tolist())

    bairro_selecionado = st.sidebar.multiselect('Selecione o bairro:', bairros_opcoes, default=[])

    tipos_opcoes = sorted(df['tipo_imovel'].unique().tolist())

    tipo_selecionado = st.sidebar.multiselect('Tipo de imóvel:', tipos_opcoes)

    faixas_opcoes = sorted(df['faixa'].unique().tolist())

    faixas_selecionado = st.sidebar.multiselect(
        "Padrão do imóvel no bairro (preço/m²):",
        faixas_opcoes,
        help="""
        Classificação baseada na distribuição de preço por m² 
        dentro do mesmo bairro e tipo de imóvel.

        A divisão é feita por quartis:
        • Barato → até o 25º percentil  
        • Medio_baixo→ entre 25º e 50º  
        • Medio_alto→ entre 50º e 75º  
        • Alto_padrão → acima do 75º percentil
        """
        )

    rua_opcoes = sorted(df['rua'].unique().tolist())

    rua_selecionada = st.sidebar.multiselect(
        "Selecione a rua:",
        rua_opcoes,
        )
    
    fonte_opcoes = sorted(df['fonte'].unique().tolist())

    fonte_selecionada = st.sidebar.multiselect(
        "Selecione a fonte:",
        fonte_opcoes,
        )

    preco_min, preco_max = st.sidebar.slider(
        'Nivel de preço por metro quadrado(R$):',
        min_value=int(df['preco_por_m2'].min()),
        max_value=int(df['preco_por_m2'].max()),
        value=(int(df['preco_por_m2'].min()), int(df['preco_por_m2'].max()))
    )

    # Filtro de quartos
    quartos_min, quartos_max = st.sidebar.slider(
        'Número de quartos:',
        min_value=int(df['quartos'].min()),
        max_value=int(df['quartos'].max()),
        value=(int(df['quartos'].min()), int(df['quartos'].max()))
    )

    # Filtro de metragem
    area_min, area_max = st.sidebar.slider(
        'Metragem (m²):',
        min_value=int(df['metragem'].min()),
        max_value=int(df['metragem'].max()),
        value=(int(df['metragem'].min()), int(df['metragem'].max()))
    )

    desvio_mediana_min, desvio_mediana_max = st.sidebar.slider(
        'Desvio do preço por m² em relação ao preço mediano do bairro:',
        min_value=int(df['desvio_mediana'].min()),
        max_value=int(df['desvio_mediana'].max()),
        value=(int(df['desvio_mediana'].min()), int(df['desvio_mediana'].max()))
    )

    vaga_garagem_min, vaga_garagem_max  = st.sidebar.slider(
        'Vagas de Garagens:',
        min_value=int(df['vagas'].min()),
        max_value=int(df['vagas'].max()),
        value=(int(df['vagas'].min()), int(df['vagas'].max()))
    )

    # Aplicar filtros
    df_filtrado = df.copy()
    if bairro_selecionado:
        df_filtrado = df_filtrado[df_filtrado['bairro'].isin(bairro_selecionado)]
    if tipo_selecionado:
        df_filtrado = df_filtrado[df_filtrado['tipo_imovel'].isin(tipo_selecionado)]
    if faixas_selecionado:
        df_filtrado = df_filtrado[df_filtrado['faixa'].isin(faixas_selecionado)]
    if rua_selecionada:
        df_filtrado = df_filtrado[df_filtrado['rua'].isin(rua_selecionada)]
    if fonte_selecionada:
        df_filtrado = df_filtrado[df_filtrado['fonte'].isin(fonte_selecionada)]
    df_filtrado = df_filtrado[
        (df_filtrado['preco_por_m2'] >= preco_min) &
        (df_filtrado['preco_por_m2'] <= preco_max) &
        (df_filtrado['quartos'] >= quartos_min) &
        (df_filtrado['quartos'] <= quartos_max) &
        (df_filtrado['metragem'] >= area_min) &
        (df_filtrado['metragem'] <= area_max) &
        (df_filtrado['desvio_mediana'] >= desvio_mediana_min) &
        (df_filtrado['desvio_mediana'] <= desvio_mediana_max) &
        (df_filtrado['vagas'] >= vaga_garagem_min) &
        (df_filtrado['vagas'] <= vaga_garagem_max)
    ]

    col_principal1, col_principal2 = st.columns([1.2,1.8])

    with col_principal1:
        
        if not df_filtrado.empty:
            with st.container(border=True):
                
                st.subheader("🏠 Resumo do Mercado Selecionado")
            
                col_total = st.columns([1, 1, 1])
                with col_total[1]: # Centraliza a métrica principal
                    st.metric(
                        label='📦 Total de Imovéis', 
                        value=f"{len(df_filtrado):,}".replace(",", "."), 
                        help="Total de imóveis após os filtros aplicados"
                    )
                
                st.divider()
                
                c1, c2, c3 = st.columns(3)

                with c1:
                    st.markdown("##### 📍 Preço por m²")
                    st.metric('Médio', f"R$ {df_filtrado['preco_por_m2'].mean():,.0f}".replace(",", "."), 
                            help="Média aritmética de todos os imóveis")
                    st.metric('Mediano', f"R$ {df_filtrado['preco_por_m2'].median():,.0f}".replace(",", "."), 
                            help="Valor central (remove distorções de preços extremos)")

                with c2:
                    st.markdown("##### 💰 Valor do Imovel")
                    st.metric('Médio', f"R$ {df_filtrado['valor_imovel'].mean():,.0f}".replace(",", "."))
                    st.metric('Mediano', f"R$ {df_filtrado['valor_imovel'].median():,.0f}".replace(",", "."))

                with c3:
                    st.markdown("##### 📐 Dimensões")
                    st.metric('Área Média', f"{df_filtrado['metragem'].mean():.0f} m²")
                    st.metric('Área Mediana', f"{df_filtrado['metragem'].median():.0f} m²")

            # Estilo CSS opcional para deixar os números das métricas com cores mais vibrantes
            st.markdown("""
                <style>
                [data-testid="stMetricValue"] {
                    font-size: 1.6rem;
                    color: #1f77b4;
                }
                [data-testid="stMetricLabel"] {
                    font-weight: bold;
                }
                </style>
                """, unsafe_allow_html=True)
                
        else:
            st.write('Nenhum imóvel encontrado com os filtros aplicados.')

    with col_principal2:
        st.subheader('📈 Preço/m² por bairro')
        
        if not df_filtrado.empty:
            
            df_bairros_sem_sb = df_filtrado[df_filtrado['bairro'] != 's/b']
            
            df_bairros = df_bairros_sem_sb.groupby('bairro')['preco_por_m2'].agg(['mean', 'median']).reset_index()
            
            # Ordenar pelos bairros com maior média para o gráfico ficar bonito
            df_bairros = df_bairros.sort_values('median', ascending=False) 

            # 2. Criar o gráfico de barras comparativo
            import plotly.graph_objects as go

            fig = go.Figure()

            # Adicionar barra de Média
            fig.add_trace(go.Bar(
                x=df_bairros['bairro'],
                y=round(df_bairros['mean']),
                name='Média',
                marker_color='#636EFA'
            ))

            # Adicionar barra de Mediana
            fig.add_trace(go.Bar(
                x=df_bairros['bairro'],
                y=df_bairros['median'],
                name='Mediana',
                marker_color='#EF553B'
            ))

            # Configurações de Layout
            fig.update_layout(
                title='Comparativo de Preço/m² por Bairro',
                xaxis_title='Bairro',
                yaxis_title='Preço por m² (R$)',
                barmode='group', 
                xaxis_tickangle=-45,
                legend_title="Métrica"
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.write('Dados insuficientes para gráfico.')

    st.markdown("---")

    st.subheader('📋 Lista de Imóveis')

    if not df_filtrado.empty:
        # 1. Selecionar e ordenar colunas para uma leitura lógica
        cols_to_show = [
            'url', 'titulo', 'bairro', 'valor_imovel', 'preco_por_m2', 'desvio_mediana', 'faixa',
            'metragem', 'fonte','tipo_imovel', 'quartos', 'banheiros', 'vagas', 'dias_publicacao',
        ]
        
        # 2. Configuração avançada de colunas
        st.data_editor(
            df_filtrado[cols_to_show].reset_index(drop=True),
            use_container_width=True,
            hide_index=True,
            column_config={
                "url": st.column_config.LinkColumn("Link", display_text="Abrir 🔗"),
                "titulo": st.column_config.TextColumn("Título do Anúncio", width="medium"),
                "valor_imovel": st.column_config.NumberColumn("Preço Total", format="R$ %d"),
                "preco_por_m2": st.column_config.ProgressColumn(
                    "Preço/m²",
                    help="Relação de preço por metro quadrado",
                    format="R$ %d",
                    min_value=int(df_filtrado['preco_por_m2'].min()),
                    max_value=int(df_filtrado['preco_por_m2'].max()),
                ),
                "desvio_mediana": st.column_config.NumberColumn("Desvio da mediana do bairro", format=" %0.2f", help="Diferença entre o preço do imóvel e a mediana do bairro"),
                "faixa": st.column_config.TextColumn("Faixa de Preço", width="medium"),
                "metragem": st.column_config.NumberColumn("Área", format="%d m²"),
                "fonte": st.column_config.TextColumn("Fonte", width="medium"),
                "quartos": "Quartos🛏️",
                "banheiros": "Banheiros🚿",
                "vagas": "Garagem🚗",
                "dias_publicacao": st.column_config.NumberColumn("Anunciado há", format="%d dias"),
                "bairro": "📍 Bairro"
            },
            disabled=cols_to_show # Deixa a tabela apenas para leitura, mas com visual de editor
        )
    else:
        st.info('Nenhum imóvel encontrado com os filtros atuais.')

    st.markdown("---")

    col3, col4 = st.columns([1, 1])

    with col3:
        if not df_filtrado.empty and df_filtrado['tipo_imovel'].nunique() > 1:
            df_filtrado_diferenca = df.copy()
            if faixas_selecionado:
                df_filtrado_diferenca = df_filtrado[df_filtrado['faixa'].isin(faixas_selecionado)]
            
            try:
            
                df_agregado_pivot = (df_filtrado.groupby(['bairro', 'tipo_imovel'])['preco_por_m2'].aggregate(['mean', 'median'])).pivot_table(
                index='bairro',
                columns=['tipo_imovel'])
                
                diferenca_mediana_geral = round((df_agregado_pivot['median']['apartamento'] - df_agregado_pivot['median']['casa']) * 100 / df_agregado_pivot['mean']['casa'], 3)
                
                df_diff = diferenca_mediana_geral.reset_index()
                df_diff.columns = ['bairro', 'diferenca_percentual']
                
                df_diff = df_diff.dropna().sort_values('diferenca_percentual', ascending=True)
                
                st.subheader('📈 Diferença Percentual: Apartamento vs Casa')
            
                fig_diff = px.bar(
                    df_diff,
                    x='diferenca_percentual',
                    y='bairro',
                    orientation='h',
                    title='Diferença % da Mediana (Apartamento vs Casa)',
                    labels={'diferenca_percentual': 'Diferença (%)', 'bairro': 'Bairro'},
                    color='diferenca_percentual',
                    color_continuous_scale='RdBu_r', # Escala de cor que destaca positivos e negativos
                    #height=max(400, len(df_diff) * 20) # Ajusta a altura baseado no número de bairros
                    height=800
                )

                # Adicionando uma linha vertical no zero para referência
                fig_diff.add_vline(x=0, line_dash="dash", line_color="black")

                st.plotly_chart(fig_diff, use_container_width=True)
                
                st.info("""
                    **Como ler este gráfico:** * **Valores Positivos:** Apartamentos são mais caros que casas (por m²) neste bairro.  
                    * **Valores Negativos:** Casas são mais caras que apartamentos (por m²) neste bairro.
                """)
            except KeyError as e:
                st.warning(f"Não foi possível calcular a diferença: O tipo de imóvel {e} não está presente no filtro atual.")
        else:
            st.write('Dados insuficientes.')

    with col4:
        st.subheader('🏠 Composição do Portfólio (Tipo de Imóvel)')
        if not df_filtrado.empty:
            
            prop_imoveis = (df_filtrado['tipo_imovel'].value_counts(normalize=True) * 100).reset_index()
            
            prop_imoveis.columns = ['tipo_imovel', 'porcentagem']
            
            fig_barras = px.bar(
                prop_imoveis,
                x='porcentagem',
                y='tipo_imovel',
                orientation='h',
                text='porcentagem', # Adiciona o valor escrito na barra
                title='Participação por Tipo de Imóvel (%)',
                labels={'porcentagem': 'Participação no Mercado (%)', 'tipo_imovel': 'Tipo de Imóvel'},
                color='tipo_imovel',
                color_discrete_sequence=px.colors.qualitative.Safe,
                height=600
            )

            # 3. Melhorando a estética e o texto das barras
            fig_barras.update_traces(
                texttemplate='%{text:.1f}%', # Formata para uma casa decimal com símbolo de %
                textposition='outside',       # Coloca o texto fora da barra para não cortar
                cliponaxis=False              # Garante que o texto não seja cortado na borda
            )

            fig_barras.update_layout(
                xaxis_title="Porcentagem (%)",
                yaxis_title=None,
                showlegend=False,
                height=350,
                margin=dict(l=0, r=50, t=50, b=0),
                yaxis={'categoryorder':'total ascending'} # Garante a ordem do maior para o menor
            )

            # 4. Ajustando o limite do eixo X para o texto não sumir
            fig_barras.update_xaxes(range=[0, prop_imoveis['porcentagem'].max() * 1.15])

            st.plotly_chart(fig_barras, use_container_width=True)

            # 4. Texto explicativo opcional
            maior_tipo = prop_imoveis.iloc[0]['tipo_imovel']
            valor_max = prop_imoveis.iloc[0]['porcentagem']
            st.info(f"O mercado é dominado por **{maior_tipo}**, representando **{valor_max:.1f}%** dos imóveis.")
        else:
            st.info('Dados insuficientes para análise comparativa por bairro.')
            
        st.subheader('📈 Distribuição de Preços por m2')

        if not df_filtrado.empty:
            # Criando um histograma mais robusto
            
            centro_lat = df_filtrado['lat'].mean()
            centro_lon = df_filtrado['lng'].mean()
            fig = px.histogram(
                df_filtrado, 
                x='preco_por_m2', 
                nbins=50, 
                title='Distribuição de Preços por m²',
                color='tipo_imovel',        
                #marginal='box',             
                opacity=0.7,                
                barmode='overlay',          
                labels={'preco_por_m2': 'Preço por m²', 'tipo_imovel': 'Tipo', 'count': 'Frequência'},
                color_discrete_sequence=px.colors.qualitative.Prism
            )

            # Melhorando o layout e eixos
            fig.update_layout(
                xaxis_title='Preço por m² (R$)',
                yaxis_title='Quantidade de Imóveis',
                hovermode='x unified',       # Mostra todos os valores ao passar o mouse em um ponto do eixo X
                bargap=0.05,                 # Pequeno espaço entre as barras
                #legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1) # Legenda no topo
            )
            fig.update_layout(
            map=dict(
                center=dict(lat=centro_lat, lon=centro_lon),
                style='open-street-map' # Garante que o estilo seja carregado corretamente
            ),
            margin={"r":0,"t":0,"l":0,"b":0} # Remove bordas brancas inúteis
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Sem dados para gerar o histograma.")
            
    st.markdown("---")

    st.subheader('🗺️ Localização dos Imóveis')
    if not df_filtrado.empty and 'lat' in df_filtrado.columns and 'lng' in df_filtrado.columns:
        df_map = df_filtrado.dropna(subset=['lat', 'lng']).copy()
        df_map['lat'] = pd.to_numeric(df_map['lat'], errors='coerce')
        df_map['lng'] = pd.to_numeric(df_map['lng'], errors='coerce')
        df_map = df_map.dropna(subset=['lat', 'lng'])
        st.write(f"Número de imóveis com coordenadas válidas: {len(df_map)}")
        if len(df_map) > 0:
            fig_map = px.scatter_map(df_map, lat='lat', lon='lng', color='preco_por_m2',
                                    hover_name='titulo', hover_data=['preco_por_m2', 'metragem', 'quartos', 'bairro'],
                                    zoom=10, height=800, 
                                    color_continuous_scale='Spectral'
                                    #color_continuous_scale='Turbo',
                                    )
            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.write('Coordenadas não disponíveis para os imóveis filtrados.')
    else:
        st.write('Mapa não disponível.')

    st.markdown("---")

        
    if not df_filtrado.empty:
            # 1. Calcular a ordem dos bairros pela mediana para o gráfico ficar organizado
        ordem_bairros = df_filtrado.groupby('bairro')['preco_por_m2'].median().sort_values(ascending=False).index
                
        st.subheader('📈 Dispersão de Preços por m² por Bairro')

        fig3 = px.box(
                    df_filtrado, 
                    y='preco_por_m2',          # Bairro no eixo Y (horizontal)
                    x='bairro',    # Preço no eixo X
                    color='bairro',      # Uma cor para cada bairro
                    title='Dispersão de Preços por m² por Bairro',
                    category_orders={'bairro': ordem_bairros}, # Aplica a ordenação
                    points='outliers',   # Mostra apenas pontos que são outliers
                    labels={'indice_localizacao': 'Índice de Localização', 'preco_por_m2': 'Preço por m² (R$)'},
                    #orientation='v',
                    
                )

                # 3. Melhorar o layout
        fig3.update_layout(
                    showlegend=False,              # Esconde a legenda (já que o nome está no eixo Y)
                    xaxis_title='Bairros',
                    yaxis_title=None,              # Remove o título "Bairro" para ganhar espaço
                    height=max(500, len(df_filtrado['bairro'].unique()) * 15), # Altura dinâmica
                    margin=dict(l=20, r=20, t=40, b=20)
                )

                # 4. Adicionar linhas de grade mais suaves
        fig3.update_xaxes(showgrid=True, gridwidth=1, gridcolor='LightGray')

        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info('Dados insuficientes para análise comparativa por bairro.')   
        
    st.markdown("---")
    
    st.subheader('Análise: Índice de Localização vs Preço por m² (Sem Outliers | Escala Linear)')

    def remover_outliers(df, colunas):
        mascara = pd.Series(True, index=df.index)
        for col in colunas:
            Q1  = df[col].quantile(0.25)
            Q3  = df[col].quantile(0.75)
            IQR = Q3 - Q1
            mascara &= df[col].between(Q1 - 1.5 * IQR, Q3 + 1.5 * IQR)
        return df[mascara]
    
    pd_data_indice_localizacao = df_filtrado.copy()

    pd_data_indice_localizacao_sem_sr = pd_data_indice_localizacao[pd_data_indice_localizacao['rua'] != 's/r']
    
    if 'indice_localizacao' in pd_data_indice_localizacao_sem_sr:
        
        df_limpo = pd_data_indice_localizacao_sem_sr.dropna(subset=['indice_localizacao', 'preco_por_m2'])

        df_sem_outliers = remover_outliers(df_limpo, ['indice_localizacao', 'preco_por_m2'])
        
        df_sem_outliers = df_sem_outliers[df_sem_outliers['indice_localizacao'] != 0]
    
    else:
        df_limpo = pd_data_indice_localizacao_sem_sr.dropna(subset=[ 'preco_por_m2'])

        df_sem_outliers = remover_outliers(df_limpo, ['preco_por_m2'])
    
    try:
        if not df_sem_outliers.empty and len(df_sem_outliers['rua'].unique()) > 1:
            col_7, col_8= st.columns(2)
            with col_7:
                # 1. Cálculos Estatísticos
                r_p, _ = pearsonr(df_sem_outliers['indice_localizacao'], df_sem_outliers['preco_por_m2'])
                r_s, _ = spearmanr(df_sem_outliers['indice_localizacao'], df_sem_outliers['preco_por_m2'])

                # Cálculo da Linha de Tendência Manual (para maior controle)
                z = np.polyfit(df_sem_outliers['indice_localizacao'], df_sem_outliers['preco_por_m2'], 1)
                p = np.poly1d(z)
                x_range = np.linspace(df_sem_outliers['indice_localizacao'].min(), df_sem_outliers['indice_localizacao'].max(), 100)

                # 2. Criação do Gráfico Base com Plotly Express
                fig = px.scatter(
                    df_sem_outliers, 
                    x='indice_localizacao', 
                    y='preco_por_m2',
                    color='tipo_imovel',
                    #hover_data=['bairro'],
                    opacity=0.6,
                    title='<b>Índice de Localização vs Preço por m²</b><br><sup>Por Tipo de Imóvel (sem outliers)</sup>',
                    labels={'indice_localizacao': 'Índice de Localização', 'preco_por_m2': 'Preço por m² (R$)'},
                    template='plotly_white',
                    height=700,
                    color_discrete_sequence=px.colors.qualitative.Bold#px.colors.qualitative.Safe
                    
                )

                # 3. Adicionando a Linha de Tendência
                fig.add_trace(go.Scatter(
                    x=x_range, y=p(x_range),
                    mode='lines',
                    line=dict(color='black', dash='dash', width=3),
                    name='Tendência Linear'
                ))

                # 5. Adicionando a Caixa de Texto com Correlações
                fig.add_annotation(
                    xref="paper", yref="paper",
                    x=0.02, y=0.98,
                    text=(f"<b>Pearson:</b> r = {r_p:.3f}<br>"
                        f"<b>Spearman:</b> r = {r_s:.3f}<br>"
                        f"<b>N:</b> {len(df_sem_outliers):,}"),
                    showarrow=False,
                    align="left",
                    bgcolor="rgba(255, 255, 255, 0.85)",
                    bordercolor="gray",
                    borderwidth=1,
                    borderpad=4
                )

                # 6. Refinamentos de Layout e Formatação
                fig.update_layout(
                    height=700,
                    legend_title_text='Tipo',
                    hovermode='closest',
                )

                fig.update_yaxes(tickprefix="R$", tickformat=",.0f")
                
                st.plotly_chart(fig, use_container_width=True)

            with col_8:
            
                cores_pontos = {
                    'barato': '#A2D9A1',       
                    'medio_baixo': '#AEDFF7',  
                    'medio_alto': '#F9E79F',   
                    'alto_padrao': '#F1948A'   
                }

                cores_linhas = {
                    'barato': '#196F3D',       
                    'medio_baixo': '#1A5276',  
                    'medio_alto': '#9A7D0A',   
                    'alto_padrao': '#943126'   
                }

                fig2 = px.scatter(
                    df_sem_outliers,
                    x='indice_localizacao',
                    y='preco_por_m2',
                    color='faixa',
                    color_discrete_map=cores_pontos, 
                    hover_data=['bairro', 'tipo_imovel'],
                    title='<b>Índice de Localização vs Preço por m²</b><br><sup>Por Faixa de Preço (sem outliers)</sup>',
                    labels={'indice_localizacao': 'Índice de Localização', 'preco_por_m2': 'Preço por m² (R$)'},
                    opacity=0.5, 
                    height=800,
                    template='plotly_white'
                )
                for faixa, cor_linha in cores_linhas.items():
                    df_f = df_sem_outliers[df_sem_outliers['faixa'] == faixa]
                    
                    if len(df_f) > 5:
                        # Cálculo da regressão
                        z_f = np.polyfit(df_f['indice_localizacao'], df_f['preco_por_m2'], 1)
                        p_f = np.poly1d(z_f)
                        x_f = np.linspace(df_f['indice_localizacao'].min(), df_f['indice_localizacao'].max(), 50)
                        
                        fig2.add_trace(go.Scatter(
                            x=x_f, 
                            y=p_f(x_f), 
                            mode='lines', 
                            name=f'Tendência {faixa}', 
                            line=dict(
                                color=cor_linha, # Usa a cor mais escura para a linha
                                width=3,         # Linha mais grossa
                                dash='dash'      # Estilo tracejado para diferenciar dos pontos
                            ),
                            showlegend=True
                        ))

                # 4. Ajustes Finais
                fig2.update_layout(
                    legend=dict(orientation="h", y=-0.2, xanchor="center", x=0.5),
                    margin=dict(t=80, b=100)
                )

                fig2.update_yaxes(tickprefix="R$ ", tickformat=",")

                st.plotly_chart(fig2, use_container_width=True)
         
        else:
            st.warning("Dados insuficientes para a análise.")
    except Exception as e:
        st.error(f"Dados de indice de localização indisponíveis. Erro: {e}")

    # Título da seção no Streamlit
    st.markdown("---")
        
    col_9, col_10 = st.columns(2)

    with col_9: 
        # Filtra para aceitar ambas as fontes de dados
        fontes_desejadas = ['zap_imoveis', 'viva_real']
        df_sem_outliers = df_sem_outliers[df_sem_outliers['fonte'].isin(fontes_desejadas)]
        if not df_sem_outliers.empty:
            df_sem_out = df_sem_outliers[df_sem_outliers['desvio_mediana'] <= 2.0]
            fig_tempo = px.scatter(
                df_sem_out,
                x='dias_publicacao',
                y='desvio_mediana',
                color='faixa',
                hover_data=['bairro', 'preco_por_m2'],
                labels={
                    'dias_publicacao': 'Dias Online',
                    'desvio_mediana': 'Desvio da Mediana (R$)',
                    'tipo_imovel': 'Tipo'
                },
                title="Dias de Publicação vs. Desvio da Mediana do Preço por m²",
                opacity=0.6,
                color_discrete_sequence=px.colors.qualitative.Bold,
                height=500
            )
            x = df_sem_out['dias_publicacao']
            y = df_sem_out['desvio_mediana']
            z = np.polyfit(x, y, 1)
            p = np.poly1d(z)
                
            fig_tempo.add_trace(go.Scatter(
                    x=x, 
                    y=p(x),
                    mode='lines',
                    name='Tendência',
                    line=dict(color='black', dash='dash')
                ))

            fig_tempo.add_hline(y=0, line_dash="solid", line_color="gray", opacity=0.5)

                # Ajustes de Layout
            fig_tempo.update_layout(
                    template='plotly_white',
                    hovermode='closest',
                    yaxis_title="Desvio do Preço Médio (R$)",
                    xaxis_title="Dias de Publicação",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )

            st.plotly_chart(fig_tempo, use_container_width=True)

            st.info("""
            **Interpretação:** A tendência geral mostra que os imóveis mais recentes (menos de 30 dias) apresentam um desvio do preço medio mais baixo, enquanto os imóveis mais antigos apresentam um desvio mais alto.
            """)
        else:
            st.warning("Dados insuficientes para gerar a análise de correlação.")

    with col_10:
        st.subheader('🎯 Correlação: Verticalização vs Valorização')

        # 1. Preparação dos dados (conforme sua lógica)
        contagem = df_filtrado.groupby(['bairro', 'tipo_imovel']).size().unstack(fill_value=0)
        # Garante que a coluna 'apartamento' existe, se não existir cria com 0
        if 'apartamento' not in contagem.columns:
            contagem['apartamento'] = 0

        contagem['total'] = contagem.sum(axis=1)

            # CÁLCULO CORRIGIDO: Garante que a divisão resulte em 0-100
        contagem['pct_apartamento'] = (contagem['apartamento'] / contagem['total']) * 100

            # Preço mediano por bairro
        mediana_bairro = df_filtrado.groupby('bairro')['preco_por_m2'].median()

            # Join e remoção de Bairros com apenas 1 imóvel (evita o erro do SVD e poluição)
        df_relacao = contagem[['pct_apartamento', 'total']].join(mediana_bairro).reset_index()
        df_relacao.columns = ['bairro', 'pct_apartamento', 'total_imoveis', 'mediana_preco_m2']
        df_relacao = df_relacao[df_relacao['total_imoveis'] > 2].dropna() # Filtro de relevância

        if not df_relacao.empty and df_relacao['pct_apartamento'].nunique() > 1:
            max_range = df_relacao['pct_apartamento'].max()
            fig = px.scatter(
                    df_relacao,
                    x='pct_apartamento',
                    y='mediana_preco_m2',
                    size='total_imoveis',
                    color='mediana_preco_m2',
                    hover_name='bairro',
                    # Removido text='bairro' para evitar sobreposição, o nome aparece no hover
                    title='Relação: % Apartamentos vs Preço/m²',
                    labels={'pct_apartamento': '% de Apartamentos', 'mediana_preco_m2': 'Preço/m² (R$)'},
                    color_continuous_scale='RdYlGn',
                    size_max=20,
                )

            try:
                z = np.polyfit(df_relacao['pct_apartamento'], df_relacao['mediana_preco_m2'], 1)
                p = np.poly1d(z)
                x_range = np.linspace(df_relacao['pct_apartamento'].min(), df_relacao['pct_apartamento'].max(), 100)
                    
                fig.add_trace(go.Scatter(
                        x=x_range, y=p(x_range), 
                        mode='lines', name='Tendência', 
                        line=dict(color='rgba(100,100,100,0.5)', dash='dash')
                    ))
            except:
                pass
                
            fig.update_layout(
                xaxis=dict(range=[-5, max_range*1.05], ticksuffix="%"), # Força o eixo de 0 a 100%
                height=600,
                template='plotly_white'
                )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Dados insuficientes para mostrar a dispersão (os bairros filtrados têm a mesma % de apartamentos).")

    st.markdown("---")

    col_11, col_12 = st.columns(2)

    with col_11:
        st.subheader('Tempo de Publicação do anúncio por Bairro')
        
        dfontes_desejadas = ['zap_imoveis', 'viva_real']
        df_filtrado = df_filtrado[df_filtrado['fonte'].isin(fontes_desejadas)]
        
        if not df_filtrado.empty:
            # 1. Preparação dos Dados (Geral para todos os bairros)
            bins = [0, 60, 180, 365, 730, 9999]
            
            labels = ['0-60 dias', '61-180 dias', '181-365 dias', '1 ano', '2 anos+']
            
            df_filtrado['faixa_tempo'] = pd.cut(df_filtrado['dias_publicacao'], bins=bins, labels=labels)

            df_geral = df_filtrado.groupby(['bairro', 'faixa_tempo'], observed=True).size().reset_index(name='quantidade')

            df_geral['total_bairro'] = df_geral.groupby('bairro')['quantidade'].transform('sum')
            
            df_geral['porcentagem'] = (df_geral['quantidade'] / df_geral['total_bairro'] * 100).round(1)
            
            df_geral = df_geral[df_geral['total_bairro'] >  20]

            df_geral['bairro_total'] = df_geral['bairro'] + "  (" + df_geral['total_bairro'].astype(str) + ")"

            bairros_ordenados = df_geral[df_geral['faixa_tempo'] == '2 anos+'].sort_values('porcentagem', ascending=False)['bairro_total']

            fig = px.bar(
                    df_geral,
                    x='bairro_total',
                    y='porcentagem',
                    color='faixa_tempo',
                    #title='<b>Ranking de Liquidez por Bairro (%)</b>',
                    category_orders={'bairro_total': bairros_ordenados}, # Ordena do mais líquido para o menos líquido
                    #color_discrete_sequence=px.colors.sequential.Plasma_r,
                    text=df_geral['porcentagem'].apply(lambda x: f'{int(x)}%' if x > 8 else ''), # Mostra % se houver espaço
                )

                # 3. Ajustes de Layout
            fig.update_layout(
                    height=700,
                    barmode='stack',
                    template='plotly_white',
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5, title=None),
                    yaxis=dict(title="Participação no Estoque (%)", ticksuffix="%"),
                    xaxis=dict(title=None, tickangle=45)
                )

            fig.update_traces(textposition='inside')

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Dados insuficientes para mostrar o gráfico.")
            
    with col_12:

        if not df_filtrado.empty:
            st.subheader('Tempo de Publicação do anúncio por Tipo de Imóvel')

            df_temp_ana = df_filtrado.groupby(['tipo_imovel', 'faixa_tempo'], observed=True).size().reset_index(name='quantidade')

            # Cálculo de Totais e Porcentagem
            df_temp_ana['total_grupo'] = df_temp_ana.groupby(['tipo_imovel'])['quantidade'].transform('sum')
            df_temp_ana['porcentagem'] = (df_temp_ana['quantidade'] / df_temp_ana['total_grupo'] * 100).round(1)

            # MÁGICA: Criar o rótulo do eixo X com o total absoluto
            df_temp_ana['tipo_com_total'] = df_temp_ana['tipo_imovel'] + "<br>(" + df_temp_ana['total_grupo'].astype(str) + ")"

            # 2. Criação do Gráfico
            fig = px.bar(
                df_temp_ana,
                x='tipo_com_total', # Usamos a nova coluna com o total
                y='porcentagem',
                color='faixa_tempo',
                # Melhoramos o texto interno para mostrar o % apenas se houver espaço
                text=df_temp_ana['porcentagem'].apply(lambda x: f'{int(x)}%' if x > 5 else ''),

            )

            # 3. Configurações de Layout
            fig.update_layout(
                height=600,
                #title_text="<b>Distribuição de Liquidez por Tipo de Imóvel</b><br><span style='font-size:12px'>(n) = Volume Total de Anúncios</span>",
                barmode="group",
                template='plotly_white',
                legend=dict(
                    orientation="h", 
                    yanchor="bottom", 
                    y=1.02, 
                    #xanchor="center", 
                    xanchor="auto", 
                    x=0.5,
                    title=None
                ),
                margin=dict(t=100) # Espaço para a legenda no topo
            )

            # Configurar eixos
            fig.update_yaxes(title_text="Participação (%)", ticksuffix="%", range=[0, df_temp_ana['porcentagem'].max()*1.1])
            fig.update_xaxes(title=None, tickangle=0, tickfont=dict(size=11))

            # Ajustar a posição do texto para dentro das barras
            fig.update_traces(textposition='inside', cliponaxis=False)

            st.plotly_chart(fig, use_container_width=True)


        else:
            st.warning("Nenhum dado disponível.")