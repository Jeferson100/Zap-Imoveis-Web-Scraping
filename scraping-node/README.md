# scraping-node

Módulo Node.js de scraping (Playwright), espelhando `src/scraping_zap_imoveis/`.

## Pré-requisitos

- Node.js 18+
- `npm install` (dentro de `scraping-node/`)
- `npx playwright install chromium`

## Chave na Mão

```bash
node chave-mao/coleta.js \
  --url-template "https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/?pg={pagina}" \
  --pages 1 \
  --out resultados.json \
  --concurrency 5 \
  --headless true
```

Sem `--pages`, detecta o total automaticamente. Saída em JSON com o mesmo
schema do coletor Python (`url, titulo, metragem, ..., fotos, link_maps`).

## Diferenças vs. Python

- **1 browser reusado** (launch único; pool de páginas) em vez de launch por item
- **Bloqueio de imagens/fontes/mídia** via `route.abort`
- Concorrência com `p-limit` (default 5)
