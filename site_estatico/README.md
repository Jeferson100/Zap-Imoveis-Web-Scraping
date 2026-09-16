<div align="center">

# Analise de Imoveis

Painel web para visualizacao e analise de imoveis a venda e aluguel
em **11 cidades** brasileiras com **280+ mil imoveis**.

<br>

[![Abrir Site](https://img.shields.io/badge/ABRIR%20SITE-1a237e?style=for-the-badge&logo=githubpages&logoColor=white)](https://jeferson100.github.io/Analise-imoveis/)
[![Stack](https://img.shields.io/badge/STACK-HTML--JS--CSS-212121?style=for-the-badge&logo=javascript&logoColor=white)]()
[![Demo](https://img.shields.io/badge/DEMO-disponivel-00C853?style=for-the-badge&logo=googlechrome&logoColor=white)]()

</div>

---

## Cidades disponiveis

| Cidade | Estado | Imoveis | Aluguel | Predicao |
|:-------|:------:|--------:|:-------:|:--------:|
| Joinville | SC | ~24k | ✅ | ✅ |
| Florianopolis | SC | ~50k | — | — |
| Blumenau | SC | ~15k | — | — |
| Balneario Camboriu | SC | ~16k | ✅ | ✅ |
| Balneario Picarras | SC | ~5k | — | — |
| Itai | SC | ~12k | — | — |
| Itapema | SC | ~12k | — | — |
| Itapoa | SC | ~4k | — | — |
| Jaragua do Sul | SC | ~4k | — | — |
| Curitiba | PR | ~39k | — | — |
| Sao Paulo | SP | ~106k | — | — |

## Funcionalidades

### :house: Modo Venda
- Metricas gerais: preco por m2, valor do imovel, dimensoes
- Filtros: bairro, tipo, quartos, banheiros, vagas, metragem
- Remocao de outliers (IQR e percentil 99.6%)
- Tabela ordenavel com todos os imoveis
- Mapa com geolocalizacao (Leaflet)
- Graficos interativos (Plotly.js)

### :key: Modo Aluguel
- Joinville e Balneario Camboriu possuem dados de aluguel
- Metricas: valor do aluguel, condominio, IPTU

### :brain: Predicao de Preco
> Disponivel para Joinville e Balneario Camboriu

- Formulario para prever o valor de um imovel
- Modelo: **GradientBoostingRegressor** (200 arvores)
- Inferencia **100% em JavaScript** (sem servidor)
- Intervalo de predicao via conformal prediction

## Arquitetura

```
site_estatico/
├── index.html                # Pagina principal
├── css/
│   └── style.css             # Estilos com gradientes e responsividade
├── js/
│   ├── app.js                # Logica: filtros, tabela, mapa, graficos
│   └── predicao.js           # Inferencia de preco em JS puro
└── data/
    ├── dados_{cidade}.js      # Dados dos imoveis (via <script>)
    ├── stats_{cidade}.js      # Estatisticas por bairro
    ├── modelo_{cidade}.json   # Modelo de predicao (arvores + preprocessing)
    └── config_aluguel.json    # Cidades com dados de aluguel
```

### Como os dados sao carregados

- Tags `<script>` dinamicas para cada cidade
- Funciona via `file://` protocol (sem servidor)
- Cada cidade tem seus proprios arquivos JS/JSON

### Pipeline de predicao

```
  Entrada do usuario
        |
        v
+-----------------------------------+
| Pre-processamento (JavaScript)    |
|  1. Imputacao (mediana)           |
|  2. Yeo-Johnson                   |
|  3. StandardScaler                |
|  4. RobustScaler                  |
|  5. One-Hot Encoding              |
+-----------------------------------+
        |
        v
+-----------------------------------+
| GradientBoostingRegressor         |
|  200 arvores de decisao           |
|  Exportado como JSON puro         |
+-----------------------------------+
        |
        v
  Preco predito + intervalo
```

## Stack

| Tecnologia | Uso |
|:-----------|:----|
| **HTML/CSS/JS** | Interface pura, sem frameworks |
| **Plotly.js** | Graficos interativos (scatter, histograma, barras) |
| **Leaflet.js** | Mapa com geolocalizacao (OpenStreetMap) |
| **GradientBoostingRegressor** | Modelo de predicao (scikit-learn) |
| **JSON** | Exportacao do modelo para inferencia client-side |

## Pipeline de dados

| Etapa | Ferramentas | Detalhes |
|:------|:------------|:---------|
| **Scraping** | ZAP, VivaReal, OLX, Chave na Mao | Coleta automatizada de imoveis |
| **Limpeza** | Filtros, Dedup, Outliers, NaN | Tratamento de dados invalidos |
| **Feature Eng.** | Geoscore, Clusters, Topics, Metragem | Criacao de variaveis derivadas |
| **Treino** | Optuna, 5-Fold CV, R2=0.998 | Otimizacao de hiperparametros |
| **Export** | JSON/JS, .joblib | Exportacao do modelo e dados |
| **Deploy** | GitHub Pages | Hospedagem estatica gratuita |

---

