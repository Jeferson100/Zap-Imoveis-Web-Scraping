# AGENTS.md — Preco-Imoveis

Python 3.12 only (`.python-version`). Package layout: `package-dir = src/`; installable packages limited to `pyproject.toml [tool.setuptools.packages.find]`: `scraping_zap_imoveis*`, `agente_*`, `roteador_llms*`, `shared*`. Other `src/*.py` (preprocessador, otimizador_optuna, etc.) are imported as top-level scripts, not packages.

## Commands (use these, not guesses)

- Setup: `uv venv && make uv_install` (CI: `pipeline_cidade_rodando.yml` does `uv venv`, `make uv_install`, `uv pip install -e .`, `uv run playwright install --with-deps chromium`). Minimal Streamlit-only install: `pip install -r requirements.txt`.
- Run everything with `uv run <path>` (e.g. `uv run codigos_rodando/joinville/joinville_limpando_dados_imoveis.py`), never bare `python` — CI and `rodando_joinville.py` assume `uv run`.
- Single test: `uv run pytest tests/test_chaves_mao_preco.py -v` (same for `test_agente_avaliacao_imagens.py`, `test_subgrafo_imagens_routing.py`). No `pytest.ini`/config in repo.
- Streamlit: `streamlit run app/app_streamlit.py` (entry; per-city files `app/1_Joinville-Imoveis.py` etc. are legacy/single-city). Reads newest `dados/<cidade>/*_imoveis_limpo_*.parquet` by filename date.
- Site export: `CIDADE_PASTA=joinville python scripts/exportar_site.py` → runs `exportar_dados.py` + `exportar_modelo_js.py`. `CIDADE_EXPORTAR=todas` exports all. Output goes to `site_estatico/` (synced to `Jeferson100/Analise-imoveis` by `atualizar_site.yml` — keep export+sync in one job, separate jobs lose artifacts).
- Node scrapers: `scraping-node/` (`npm install`, `npm run chave-mao` → `node chave-mao/coleta.js`). Requires Playwright browsers separately.

## Architecture — where to edit

- `src/scraping_zap_imoveis/` — reusable scrapers (`*_coleta.py` orchestrators, `extrair_dados_*_playwright_async.py`, `link_anuncios_*.py`, `total_page_*.py`). Tests import by file path (`importlib.util.spec_from_file_location`), not package import — keep filenames stable.
- `src/` ML lib — `config_features.py` (NUMERIC/CATEGORICAL_FEATURES canonical list), `preprocessador.py` (PreprocessadorFactory + `SKOPS_TRUSTED_TYPES`), `otimizador_optuna.py`, `mlflow_manager.py`, `melhor_modelo_geral.py`, `intervalo_predicao.py`. If adding a CatBoost/LGBM/XGB model, also add it to `SKOPS_TRUSTED_TYPES` or `mlflow.sklearn.log_model` breaks.
- `src/agente_avaliacao_imagens|agente_validacao|agente_potencial_flip|roteador_llms|shared/` — LLM image/flip agents (LangChain/LangGraph). Schemas in `schemas.py`.
- `codigos_rodando/<cidade>/` — runnable per-city pipeline copies (e.g. `joinville_coleta_dados_zap_imoveis_0_70.py`, `..._limpando_dados_imoveis.py`, `..._criando_indice_localizacao.py`, `..._melhores_configuraoes_modelo.py`, `rodando_<cidade>.py`). Naming convention: `<cidade>_<etapa>_<fonte>[_faixa].py`. CI `sparse-checkout` only includes `codigos_rodando/ dados/ src/ app/ scripts/ pyproject.toml Makefile` — files outside these don't exist in runners.
- `dados/<cidade>/` — committed CSV/Parquet results (CI commits `dados/` back to `main` after each run). Don't clean/generate into other paths.
- `scripts/` — `exportar_dados.py`, `exportar_modelo_js.py`, `exportar_modelo_onnx.py`, `gerar_features_modelo.py`, `exportar_pois.py`.
- `Notebooks/` — exploratory only; never executed by CI.

## Env / CI gotchas

- Scraping/training scripts read env, not argv: `CIDADE_PASTA`, `HEADLESS`, `MAX_CONCURRENCY[_CHAVE|_OLX|_ZAP]`, `MAX_CONCURRENCY_LOCALIZACAO`, `BATCH_LIMPEZA`, `TIPO_ASYNC`, `CIDADE_LIMPEZA/LOCALIZACAO`, `ESTADO_*`, `BAIRRO`, `URL_TEMPLATE_{CHAVES,VIVAREAL,OLX,ZAP}`, `FILTRO_BAIRRO`. Training adds `DATABRICKS_HOST`, `DATABRICKS_TOKEN` (secret), `LOCALIZAZAO_COMPLETA` (note typo: ZAZAO, keep as-is), `INCLUIR_TOPICOS="True"`. `.env` files exist in `codigos_rodando/<cidade>/.env` and root (gitignored) — `load_dotenv()` is used.
- Workflows chain via `workflow_run` (coleta OLX → Zap → limpeza → junção → treino → predição). Reusable workflow: `pipeline_cidade_rodando.yml` (`workflow_call` with `cidade_pasta` + `arquivo_rodando_imovel`). City workflows only pass those two + env overrides.
- MLflow: `MLflowManager.conectar()` tries Databricks token → profile → local `mlruns/` fallback. Local runs write `mlruns/` / `codigos_rodando/*/mlruns/` + `mlflow.db` (gitignored except some checked-in DBs — don't commit new ones).
- `dados/` CSVs >50MB stay local; CI pushes smaller Parquet/CSV updates.

## Testing quirks

- `test_chaves_mao_preco.py` uses `@pytest.mark.asyncio` but `pytest-asyncio` is NOT in `pyproject.toml` — that test errors without the plugin; `test_agente_avaliacao_imagens.py` avoids it via `asyncio.run` + `monkeypatch`. Prefer `asyncio.run` pattern for new async tests.
- Tests stub Playwright with `FakePage/FakeLocator` — don't require browsers. Real scrapers need `playwright install --with-deps chromium` + network access to portals (flaky, never run full scrape in verification).
