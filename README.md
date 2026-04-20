# Preço Imóveis 🏠

[![Streamlit](https://img.shields.io/badge/Streamlit-100000?style=for-the-badge&logo=streamlit&logoColor=white)](https://santa-catarina-zap-imoveis.streamlit.app/) 
[![Python](https://img.shields.io/badge/Python-3.12+-3776ab?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![Playwright](https://img.shields.io/badge/Playwright-45B7D1?style=for-the-badge&logo=microsoft&logoColor=white)](https://playwright.dev/python/)

**Coleta multi-plataforma e análise de preços de imóveis** em 11 cidades do Brasil utilizando **4 portais imobiliários** principais.

Automatiza a extração de dados de [Zap Imóveis](https://www.zapimoveis.com.br), [OLX](https://www.olx.com.br), [Viva Real](https://www.vivareal.com.br) e [Chave Mão](https://www.chavemao.com.br), com limpeza automática, geocodificação e dashboards interativos em Streamlit.

---

## 📋 Visão Geral

Projeto robusto de **scraping multi-fonte e análise de preços de imóveis** cobrindo 11 cidades brasileiras. 

La ideia principal é automatizar a extração de dados de 4 plataformas imobiliárias principais, processar/limpar os resultados em formatos reutilizáveis e facilitar análises avançadas, visualizações e modelagem preditiva.

**Características:**
- 📍 **11 cidades** (8 em SC, 2 no Sul, 1 em SP) com coleta automática mensal
- 🏢 **4 portais** (Zap Imóveis, OLX, Viva Real, Chave Mão)
- 🛠️ **2 métodos** de scraping (Playwright async/sync + Selenium)
- 🔄 **Processamento automático**: limpeza, geocodificação e indexação geoespacial
- 📊 **Análise avançada**: machine learning, estatísticas, visualizações interativas
- 🌐 **Dashboard web** com filtros, gráficos e insights em tempo real

---

## 🎯 Plataformas de Coleta

| Portal | Link | Tipo | Status |
|--------|------|------|--------|
| **Zap Imóveis** | [zapimoveis.com.br](https://www.zapimoveis.com.br) | Plataforma especializada | ✅ Ativo |
| **OLX** | [olx.com.br](https://www.olx.com.br) | Classificados geral | ✅ Ativo |
| **Viva Real** | [vivareal.com.br](https://www.vivareal.com.br) | Plataforma especializada | ✅ Ativo |
| **Chave Mão** | [chavemao.com.br](https://www.chavemao.com.br) | Portal imobiliário | ✅ Ativo |

---

## 📍 Cidades Coletadas

**Santa Catarina (8 cidades):**
- Joinville
- Balneário Camboriú
- Balneário Piçarras
- Blumenau
- Itajaí
- Itapema
- Itapoá
- Jaragrá do Sul

**Sudeste (1 cidade):**
- São Paulo

**Sul (2 cidades):**
- Florianópolis
- Curitiba

---

## 🛠️ Tecnologias e Dependências

**Requisitos:**
- Python >= 3.12
- [Playwright](https://playwright.dev/python/) (navegação e scraping)
- [Selenium](https://selenium-python.readthedocs.io/) (alternativa de scraping)
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) (parsing HTML)
- [Pandas](https://pandas.pydata.org/) (manipulação e análise de dados)
- [Crawlee](https://crawlee.dev/) (framework de scraping)
- asyncio (programação assíncrona)
- [Geopy](https://geopy.readthedocs.io/) (geocodificação)
- [Google Maps API](https://googlemaps.github.io/google-maps-services-python/) (georeferenciamento)
- [OSMNX](https://osmnx.readthedocs.io/) (dados OpenStreetMap)
- [Streamlit](https://streamlit.io/) (dashboards web)
- [Plotly](https://plotly.com/) (visualizações interativas)
- [Scikit-learn](https://scikit-learn.org/) (machine learning)

> Veja `requirements.txt` e `pyproject.toml` para a lista completa de pacotes.

---

## 📦 Instalação

Recomenda-se usar o [uv](https://github.com/astral-sh/uv) para gerenciamento de dependências.

### Com uv (sugestão)
```bash
uv sync            # instala e mantém ambiente atualizado
```

### Com pip
```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1  # Windows
pip install -e .
```

---

## 📂 Estrutura do Repositório

```text
preco-imoveis/
├── src/
│   └── scraping_zap_imoveis/         # código Python reutilizável
│       ├── link_anuncios_*.py        # coleta URLs de anúncios (multi-plataforma)
│       ├── extrair_dados_*.py        # extração de detalhes do anúncio
│       ├── total_pagina_*.py         # calcula número de páginas
│       ├── zap_imoveis_coleta.py     # orquestrador Zap
│       ├── olx_coleta.py             # orquestrador OLX
│       ├── viva_real_coleta.py       # orquestrador Viva Real
│       └── chave_mao_coleta.py       # orquestrador Chave Mão
├── codigos_rodando/                   # scripts de produção por cidade
│       ├── criando_indice.py          # indexação geoespacial
│       ├── limpando_dados.py          # limpeza geral de dados
│       ├── unificando_dados.py        # unificação multi-fonte
│       └── [cidade]/
│           ├── [cidade]_coleta_dados_chave_mao.py
│           ├── [cidade]_coleta_dados_olx.py
│           ├── [cidade]_coleta_dados_viva_real.py
│           ├── [cidade]_coleta_dados_zap_imoveis.py
│           ├── [cidade]_limpando_dados.py
│           ├── [cidade]_indice_localizacao.py
│           ├── rodando_[cidade].py
│           └── executar_mensalmente_[cidade].bat
├── Notebooks/                         # análises exploratórias e demos
│   ├── indice_localizacao.ipynb       # geocodificação e geoespacial
│   ├── web_scrapen_zip_imoveis_selenium.ipynb
│   ├── web_scraping_*.py              # exemplos de scraping por plataforma
│   └── cache/
├── dados/                             # resultados brutos e processados (CSV/JSON)
│   └── [cidade]/                      # dados separados por cidade
├── app/                               # aplicação Streamlit
│   ├── app_streamlit.py               # dashboard principal
│   └── pages/
│       ├── 1_Joinville-Zap-Imoveis.py
│       ├── 2_Balneario-Camboriu-Zap-Imoveis.py
│       └── ... (outros dashboards por cidade)
├── pyproject.toml                     # configuração do pacote
├── requirements.txt                   # dependências fixas
├── LICENSE                            # MIT License
├── Makefile                           # comandos úteis
└── README.md                          # este documento
```

---

## 🚀 Uso

### Coletar dados programaticamente
```python
import asyncio
from scraping_zap_imoveis import ZapImoveisColeta
from datetime import datetime

now = datetime.now().strftime("%Y-%m-%d")
coletor = ZapImoveisColeta()

# salva JSON em `dados/`
resultado = asyncio.run(
    coletor.run(output_file=f"dados/zap_imoveis_joinville_{now}.json")
)
```

## 📊 Dados Obtidos

Campos registrados no conjunto final:

- Preço (aluguel/venda)
- Área total e útil
- Quartos, banheiros, garagens, etc.
- Endereço e bairro
- Descrição textual do anúncio
- URLs de imagens e do anúncio
- Data de publicação e atualizações
- Características (piscina, churrasqueira, etc.)
- Link para mapa do imóvel

Os arquivos gerados estão em `dados/` e podem ser limpos em `codigos_rodando/limpando_dados.py`.

---

## 🧹 Processamento de Dados

Os scripts de processamento executam automaticamente:

1. **Limpeza**: `[cidade]_limpando_dados.py` - normalização, remoção de duplicatas
2. **Geocodificação**: `[cidade]_indice_localizacao.py` - extração de coordenadas e indexação
3. **Unificação**: `unificando_dados.py` - fusão de dados multi-origem
4. **Criação de Índices**: `criando_indice.py` - indexação geoespacial com OSMNX

---

## 📈 Aplicação Streamlit

Abra `app/app_streamlit.py` e execute:
```bash
streamlit run app/app_streamlit.py
```

Isso inicia uma interface onde é possível filtrar bairros, ver estatísticas e visualizar gráficos de preço.

---

## 🧪 Processamento de Dados

Os scripts de processamento executam automaticamente:

1. **Limpeza**: `[cidade]_limpando_dados.py` - normalização, remoção de duplicatas
2. **Geocodificação**: `[cidade]_indice_localizacao.py` - extração de coordenadas e indexação
3. **Unificação**: `unificando_dados.py` - fusão de dados multi-origem
4. **Criação de Índices**: `criando_indice.py` - indexação geoespacial com OSMNX

---

## 📓 Notebooks

Vários notebooks em `Notebooks/` demonstram análise exploratória e incorporação de recursos geoespaciais (usando OSMNX, por exemplo). Abra-os com Jupyter ou VS Code.

---

## ⚖️ Licença

Este projeto está licenciado sob a **MIT License**. Veja [LICENSE](LICENSE) para detalhes.

---

## 📞 Contato

Dúvidas ou sugestões? Abra uma issue ou entre em contato pelo perfil do GitHub.

