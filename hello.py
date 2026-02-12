from scraping_zap_imoveis import ZapScannerTotalPagina
from scraping_zap_imoveis import ZapScannerLinks

"""if __name__ == "__main__":
    
    link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"
    
    with ZapScannerTotalPagina(headless=True) as scanner:
        total = scanner.get_total_pages(link)
        print(f"Resultado Final: {total}")"""
        
if __name__ == "__main__":
    link = "https://www.zapimoveis.com.br/venda/?pagina=1&transacao=Venda"

    with ZapScannerLinks(headless=True) as scanner:
        links = scanner.get_links(link)
        print(f"Total de links: {len(links)}")
        print(f"Primeiro link: {links}")