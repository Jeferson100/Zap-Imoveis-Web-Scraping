# Import apenas os componentes necessários para coleta ImovelWeb
from .link_anuncios_imovelweb_playwright_async import ImovelWebScraperLinksAsync
from .extrair_dados_imovelweb_playwright_async import ImovelWebDadosImovelAsync, DadosImovelImovelWeb
from .total_page_imovelweb import TotalPageImovelWeb
from .imovelweb_coleta import ImovelWebColeta
from .chave_mao_coleta import ChavesMaoColeta
from .olx_coleta import OLXColeta
from .zap_imoveis_coleta import ZapImoveisColeta
from .viva_real_coleta import VivaRealColeta

__all__ = [
    "ImovelWebScraperLinksAsync",
    "ImovelWebDadosImovelAsync",
    "DadosImovelImovelWeb",
    "TotalPageImovelWeb",
    "ImovelWebColeta",
    "ChavesMaoColeta",
    "OLXColeta",
    "ZapImoveisColeta",
    "VivaRealColeta"
]