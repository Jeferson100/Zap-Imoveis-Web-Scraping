try:
    from scraping_zap_imoveis.link_anuncios_zap_imoveis_playwright import ZapScraperLinks
except ImportError:
    ZapScraperLinks = None

try:
    from scraping_zap_imoveis.link_anuncios_zap_imoveis_playwright_async import ZapScraperLinksAsync
except ImportError:
    ZapScraperLinksAsync = None

try:
    from scraping_zap_imoveis.total_page_zap import TotalPageZap
except ImportError:
    TotalPageZap = None

try:
    from scraping_zap_imoveis.extrair_dados_zap_imoveis_playwright import ZapScraperDadosImovel
except ImportError:
    ZapScraperDadosImovel = None

try:
    from scraping_zap_imoveis.extrair_dados_zap_imoveis_playwright_async import ZapScraperDadosImovelAsync, DadosImovel
except ImportError:
    ZapScraperDadosImovelAsync = None
    DadosImovel = None

try:
    from scraping_zap_imoveis.zap_imoveis_coleta import ZapImoveisColeta
except ImportError:
    ZapImoveisColeta = None

try:
    from scraping_zap_imoveis.extrair_dados_chave_mao_playwright_async import ChavesNaMaoScraperAsync
except ImportError:
    ChavesNaMaoScraperAsync = None

try:
    from scraping_zap_imoveis.link_anuncios_chave_mao_playwright_async import ChaveMaoScraperLinksAsync
except ImportError:
    ChaveMaoScraperLinksAsync = None

try:
    from scraping_zap_imoveis.chave_mao_coleta import ChavesMaoColeta
except ImportError:
    ChavesMaoColeta = None

try:
    from scraping_zap_imoveis.extrair_dados_olx_playwright_async import OLXScraperAsync
except ImportError:
    OLXScraperAsync = None

try:
    from scraping_zap_imoveis.link_anuncios_olx_playwright_async import OLXScraperLinksAsync
except ImportError:
    OLXScraperLinksAsync = None

try:
    from scraping_zap_imoveis.olx_coleta import OLXColeta
except ImportError:
    OLXColeta = None

try:
    from scraping_zap_imoveis.viva_real_coleta import VivaRealColeta
except ImportError:
    VivaRealColeta = None
try:
    from funcoes_limpando_dados_imoveis import (limpar_metragem, 
                                                limpar_valor_venda, 
                                                limpar_banheiros, 
                                                limpar_vagas, 
                                                limpar_valor_condominio, 
                                                limpar_valor_iptu, 
                                                limpar_data_publicacao, 
                                                converter_para_data, 
                                                classificar_tipo_imovel, 
                                                reclassificar_outros, 
                                                preencher_todas_coordenadas, 
                                                main_example, 
                                                limpar_quartos, 
                                                pirabeiraba_dona_francisca, 
                                                geocodificar_dataframe,
                                                processar_todos_scores_localizacao,
                                                limpa_endereco_apply_zap,
                                                limpa_endereco_apply_chave_mao,
                                                limpa_endereco_apply_olx)
except ImportError:
    limpar_metragem = None
    limpar_valor_venda = None
    limpar_banheiros = None
    limpar_vagas = None
    limpar_valor_condominio = None
    limpar_valor_iptu = None
    limpar_data_publicacao = None
    converter_para_data = None
    classificar_tipo_imovel = None
    reclassificar_outros = None
    preencher_todas_coordenadas = None
    main_example = None
    limpar_quartos = None
    pirabeiraba_dona_francisca = None
    geocodificar_dataframe = None
    processar_todos_scores_localizacao = None
    limpa_endereco_apply_zap = None
    limpa_endereco_apply_chave_mao = None
    limpa_endereco_apply_olx = None
try:
    from .preco_imoveis_model_analysis import PrecoImoveisModelAnalyzer
except ImportError:
    PrecoImoveisModelAnalyzer = None

try:
    from .predicao_preco_imoveis import (
        listar_experimentos_mlflow,
        comparar_modelos_mlflow,
        treinar_pipeline_com_mlflow,
        otimizar_mlp_com_mlflow,
    )
except ImportError:
    listar_experimentos_mlflow = None
    comparar_modelos_mlflow = None
    treinar_pipeline_com_mlflow = None
    otimizar_mlp_com_mlflow = None

try:
    from .criando_indices_individuais import CriandoIndicesIndividuais
except ImportError:
    CriandoIndicesIndividuais = None

try:
    from .mlflow_manager import MLflowManager
except ImportError:
    MLflowManager = None

try:
    from .otimizador_optuna import OtimizadorOptuna, OtimizadorMLP, FactoryModelos, ConstrutorKeras, OtimizadorMLP
except ImportError:
    OtimizadorOptuna = None
    OtimizadorMLP = None
    FactoryModelos = None
    ConstrutorKeras = None

try:
    from .preprocessador import PreprocessadorFactory, Avaliador, TreinadorPipeline
except ImportError:
    PreprocessadorFactory = None
    Avaliador = None
    TreinadorPipeline = None


__all__ = [#"ZapScraperTotalPagina",
            "ZapScraperLinks",
            "ZapScraperLinksAsync",
            "TotalPageZap",
            "ZapScraperDadosImovel",
            "ZapScraperDadosImovelAsync",
            "DadosImovel",
            "ZapImoveisColeta", 
            "limpar_metragem",
            "limpar_valor_venda",
            "limpar_banheiros",
            "limpar_vagas",
            "limpar_valor_condominio",
            "limpar_valor_iptu",
            "limpar_data_publicacao",
            "limpar_quartos",
            "converter_para_data",
            "classificar_tipo_imovel",
            "reclassificar_outros",
            "preencher_todas_coordenadas",
            "main_example",
            "pirabeiraba_dona_francisca",
            "geocodificar_dataframe",
            "processar_todos_scores_localizacao",
            "PrecoImoveisModelAnalyzer",
            "listar_experimentos_mlflow",
            "comparar_modelos_mlflow",
            "treinar_pipeline_com_mlflow",
            "otimizar_mlp_com_mlflow",
            "ChavesMaoColeta",
            "ChavesNaMaoScraperAsync",
            "ChaveMaoScraperLinksAsync",
            "OLXScraperAsync",
            "OLXScraperLinksAsync",
            "OLXColeta",
            "VivaRealColeta",
            "limpa_endereco_apply_zap",
            "limpa_endereco_apply_chave_mao",
            "limpa_endereco_apply_olx",
            "CriandoIndicesIndividuais",
            "MLflowManager",
            "OtimizadorOptuna",
            "OtimizadorMLP", 
            "FactoryModelos",
            "ConstrutorKeras",
            "PreprocessadorFactory",
            "Avaliador",
            "TreinadorPipeline",
            #"TesteIncrementalFeatures"
            ]