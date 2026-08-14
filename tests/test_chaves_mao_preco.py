import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / 'src' / 'scraping_zap_imoveis' / 'extrair_dados_chave_mao_playwright_async.py'
SPEC = importlib.util.spec_from_file_location('chave_mao_scraper', MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
ChavesNaMaoScraperAsync = MODULE.ChavesNaMaoScraperAsync


class FakeLocator:
    def __init__(self, value):
        self.value = value

    async def all_inner_texts(self):
        if isinstance(self.value, list):
            return self.value
        return [self.value]

    async def inner_text(self):
        return self.value


class FakePage:
    def __init__(self, scripts, body_text):
        self.scripts = scripts
        self.body_text = body_text

    def locator(self, selector):
        if selector == 'script[type="application/ld+json"]':
            return FakeLocator(self.scripts)
        if selector == 'body':
            return FakeLocator(self.body_text)
        raise AssertionError(f'Selecionador não tratado: {selector}')


@pytest.mark.asyncio
async def test_extrair_valor_imovel_venda():
    scraper = ChavesNaMaoScraperAsync(headless=True)
    scraper._page = FakePage(
        scripts=[
            '{"price": "R$ 732.300"}'
        ],
        body_text='Preço: R$ 732.300 IPTU: R$ 638/mês'
    )

    valor = await scraper._extrair_valor_imovel()

    assert valor == '732300'


@pytest.mark.asyncio
async def test_extrair_valor_imovel_aluguel():
    scraper = ChavesNaMaoScraperAsync(headless=True)
    scraper._page = FakePage(
        scripts=[],
        body_text='Aluguel R$ 1.800/mês Condomínio R$ 380/mês'
    )

    valor = await scraper._extrair_valor_imovel()

    assert valor == '1800'
