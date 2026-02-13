# Preço Imóveis 🏠

Web scraping de dados de preços de imóveis em Joinville-SC, Brasil utilizando dados do site [Zap Imóveis](https://www.zapimoveis.com.br).

## 📋 Sobre o Projeto

Este projeto coleta e analisa dados de imóveis listados no portal Zap Imóveis, focando especificamente em Joinville, Santa Catarina. Utilizamos técnicas avançadas de web scraping com Playwright e Selenium para extrair informações de preços, características dos imóveis e anúncios.

## 🛠️ Tecnologias

- **Python** >= 3.12
- **Playwright** - Automação de navegador moderna
- **Selenium** - Automação de navegador tradicional
- **BeautifulSoup4** - Parsing de HTML
- **Pandas** - Análise e manipulação de dados
- **Crawlee** - Framework de web scraping
- **asyncio** - Programação assíncrona

## 📦 Requisitos

- Python 3.12 ou superior
- pip ou [uv](https://github.com/astral-sh/uv) como gerenciador de pacotes

## 🚀 Instalação

### Usando uv (recomendado)

```bash
uv sync
```

### Usando pip

```bash
pip install -e .
```

## 📂 Estrutura do Projeto

```
preco-imoveis/
├── src/
│   └── scraping_zap_imoveis/
│       ├── link_anuncios_zap_imoveis_playwright.py       # Extrai links dos anúncios
│       ├── link_anuncios_zap_imoveis_playwright_async.py # Versão assíncrona
│       ├── extrair_dados_zap_imoveis_playwright.py       # Extrai dados dos anúncios
│       ├── extrair_dados_zap_imoveis_playwright_async.py # Versão assíncrona
│       ├── total_pagina_zap_imovel_playwright.py         # Obtém total de páginas
│       ├── total_pagina_zap_imovel_playwright_async.py   # Versão assíncrona
│       └── zap_imoveis_coleta.py                         # Orquestrador principal
├── Notebooks/                                              # Jupyter notebooks para análise
├── codigos_rodando/                                        # Scripts em execução
├── dados/                                                  # Dados coletados
└── pyproject.toml                                          # Configuração do projeto
```

## 💻 Como Usar

### Coleta de Dados

A coleta de dados é orquestrada pelo módulo principal:

```python
from scraping_zap_imoveis import ZapImoveisColeta

coletor = ZapImoveisColeta()

resultado = asyncio.run(coletor.run(output_file=f"../dados/zap_imoveis_joinville_{now}.json"))

```

### Módulos Disponíveis

1. **link_anuncios_zap_imoveis_playwright.py**
   - Coleta os links de todos os anúncios da região

2. **extrair_dados_zap_imoveis_playwright.py**
   - Extrai dados detalhados dos anúncios (preço, características, etc)

3. **total_pagina_zap_imovel_playwright.py**
   - Determina o número total de páginas de resultados

#### Versões Assíncronas
Cada módulo possui uma versão `_async.py` para coleta paralela de dados, oferecendo melhor performance.

## 📊 Dados Coletados

O projeto coleta as seguintes informações dos imóveis:

- 💰 Preço do imóvel
- 📐 Área total
- 🛏️ Número de quartos
- 🚗 Número de garagens
- 🚿 Número de banheiros
- 📍 Localização/Endereço
- 📝 Descrição do anúncio
- 🔗 URL do anúncio
- 📅 Data de publicação
- 📸 Link das fotos do anúncio
- 📌 Características do imóvel
- 🌐 Link do imóvel no Google Maps


## 📖 Exemplos

## ⚙️ Configuração

Os parâmetros de configuração podem ser ajustados nos arquivos Python:

- **Timeouts**: Tempo de espera para carregamento de páginas
- **Delays**: Intervalo entre requisições
- **Headless**: Executar navegador em modo visível ou não

## ⚖️ Licença

Este projeto está licenciado sob a Licença MIT. Veja o arquivo [LICENSE](LICENSE) para mais detalhes.

## 📞 Contato

Para dúvidas ou sugestões sobre o projeto, abra uma issue no repositório.

---

**Última atualização**: Fevereiro de 2026
