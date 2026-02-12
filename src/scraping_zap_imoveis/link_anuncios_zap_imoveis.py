from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth


class ZapScannerLinks:

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._playwright = Stealth().use_sync(sync_playwright()).__enter__()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()

    def get_links(self, url: str) -> list[str]:
        page = self._context.new_page()

        try:
            page.goto(url)

            links = page.locator('.listings-wrapper a.olx-core-surface').evaluate_all(
                "nodes => nodes.map(n => n.href)"
            )

            return links

        except Exception as e:
            print(f"Erro ao obter links: {e}")
            return []

        finally:
            page.close()


# Uso:
if __name__ == "__main__":
    link = "https://www.zapimoveis.com.br/venda/?pagina=2&transacao=Venda"

    with ZapScannerLinks(headless=True) as scanner:
        links = scanner.get_links(link)
        print(f"Total de links: {len(links)}")
        print(f"Primeiro link: {links}")