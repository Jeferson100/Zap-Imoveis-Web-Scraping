NUMERIC_FEATURES = [
    "metragem", "quartos", "banheiros", "vagas",
    "score_escola_privada", "score_escola_publica", "score_hospitais",
    "score_mercado", "score_farmacia", "score_parque",
    "score_seguranca", "score_educacao",
    "metro_quadrado_bairro_mean", "metro_quadrado_bairro_median",
    "valor_bairro_mean", "bairro_rank",
    "quartos_por_metro", "vagas_por_metro", "banheiros_por_quarto",
    "dist_centro", "sem_rua",
    "lat", "lng",
    "predicao_idade",
    
    # NOVAS - AMENIDADES PRIVADAS (4)
    "priv_churrasqueira", "priv_varanda", "priv_piscina", "priv_closet",
    
    # NOVAS - AMENIDADES COMUNS (7)
    "comum_piscina", "comum_elevador", "comum_salao", "comum_churrasqueira",
    "comum_playground", "comum_academia", "comum_spa",
    
    # NOVA - SUITES
    "suites",
]

CATEGORICAL_FEATURES = [
    "tipo_imovel", "bairro", "novo_lancamento", "tem_elevador",
    "dist_centro_faixa", "bairro_cluster",
]
