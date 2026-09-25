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

Sem `--pages`, detecta o total automaticamente. Saída `.parquet` por faixa
(via `to-parquet.py`, mesmo escritor do pipeline) + junção final com
`consolidar_parquet` do Python. Defina `PYTHON_BIN` se o Python não
estiver no PATH (default: `.venv` do repo, senão `python`).

## Diferenças vs. Python

- **1 browser reusado** (launch único; pool de páginas) em vez de launch por item
- **Bloqueio de imagens/fontes/mídia** via `route.abort`
- Concorrência com `p-limit` (default 5)
