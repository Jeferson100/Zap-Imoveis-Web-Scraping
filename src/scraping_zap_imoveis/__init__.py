# Import apenas os componentes necessários para coleta ImovelWeb
from .link_anuncios_imovelweb_playwright_async import ImovelWebScraperLinksAsync
from .extrair_dados_imovelweb_playwright_async import ImovelWebDadosImovelAsync, DadosImovelImovelWeb
from .total_page_imovelweb import TotalPageImovelWeb
from .imovelweb_coleta import ImovelWebColeta

__all__ = [
    "ImovelWebScraperLinksAsync",
    "ImovelWebDadosImovelAsync",
    "DadosImovelImovelWeb",
    "TotalPageImovelWeb",
    "ImovelWebColeta",
]