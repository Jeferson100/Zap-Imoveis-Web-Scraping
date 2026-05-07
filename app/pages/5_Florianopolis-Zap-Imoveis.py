from app_streamlit import gerar_pagina_analise_imoveis, carregar_mais_recentes_por_fonte

cidade_nome = 'Florianopolis'

prefixo_name = 'florianopolis'

cidade_path = 'florianopolis'

df_limpo, data_mais_recente = carregar_mais_recentes_por_fonte(cidade_path, prefixo_name)

gerar_pagina_analise_imoveis(cidade_path, cidade_nome, prefixo_name, df_limpo, data_mais_recente)