// Espelha chave_mao_coleta.py: CLI + 3 fases + save parcial.
// Uso: node coleta.js --url-template "https://.../?pg={pagina}" [--pages N] [--out out.json] [--concurrency 5] [--headless true]
// Saída .parquet via bridge Python (mesmo escritor do pipeline); .json sai direto.
const fs = require('fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { parseArgs } = require('node:util');
const pLimit = require('p-limit');
const { newContext, sleep, rand, launchChromium } = require('./browser');
const { info, warning, error } = require('./log');
const { getLinks } = require('./links');
const { extrairChaveMao } = require('./extrair');
const { getTotalPages } = require('./total-pages');

function resolvePython() {
  const candidatos = [];
  if (process.env.PYTHON_BIN) candidatos.push(process.env.PYTHON_BIN);
  candidatos.push(path.join(__dirname, '..', '..', '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'));
  for (const c of candidatos) {
    try { fs.accessSync(c, fs.constants.X_OK); return c; } catch { /* próximo */ }
  }
  return 'python'; // último recurso (PATH); se falhar, cai no fallback JSON
}

function salvar(out, dados) {
  if (!out.endsWith('.parquet')) {
    fs.writeFileSync(out, JSON.stringify(dados, null, 4));
    return;
  }
  const tmp = path.join(os.tmpdir(), `coleta-${Date.now()}-${Math.floor(Math.random() * 1e6)}.json`);
  try {
    fs.writeFileSync(tmp, JSON.stringify(dados));
    execFileSync(resolvePython(), [path.join(__dirname, 'to-parquet.py'), tmp, out], { stdio: 'inherit' });
    fs.rmSync(tmp, { force: true });
  } catch (e) {
    warning(`Falha ao gerar parquet (${e.message}). Mantido JSON: ${tmp}`);
  }
}

async function runColeta({ urlTemplate, totalPages, out, maxConc = 5, headless = true }) {
  info(`Parametros recebidos: totalPages=${totalPages}, max_concurrency=${maxConc}, headless=${headless}`);
  if (!totalPages) info('Total de páginas não definido. Iniciando detecção automática...');
  const total = totalPages || await getTotalPages(urlTemplate.replace('{pagina}', '1'), headless);
  if (!total) { error('Não foi possível determinar o total de páginas.'); return []; }
  info(`Total de páginas: ${total}`);

  // Browser ÚNICO reusado (diferença vs. Python: sem launch por item)
  let browser;
  try {
    browser = await launchChromium(headless);
  } catch (e) {
    error(`Erro ao inicializar navegador: ${e.message}`);
    throw e;
  }
  try {
    info(`Iniciando coleta de links em ${total} páginas`);
    // ETAPA 2: links em lotes
    const contextLinks = await newContext(browser);
    const todosLinks = [];
    for (let p = 1; p <= total; p += maxConc) {
      const lote = Array.from({ length: Math.min(maxConc, total - p + 1) }, (_, i) => p + i);
      const res = await Promise.all(lote.map((pg) =>
        getLinks(contextLinks, urlTemplate.replace('{pagina}', pg))));
      res.forEach((links, idx) => {
        if (links.length) info(`Página ${lote[idx]}: ${links.length} links encontrados.`);
        else warning(`Página ${lote[idx]} não retornou links.`);
      });
      res.flat().forEach((l) => todosLinks.push(l));
      await sleep(rand(200, 1000));
    }
    const unicos = [...new Set(todosLinks)];
    info(`Total de links únicos coletados: ${unicos.length}`);
    if (!unicos.length) { error('Nenhum link foi encontrado. Encerrando.'); return []; }

    info('Aguardando 30s antes da extração detalhada...');
    await sleep(30000);

    // ETAPA 4: detalhe com pool de páginas reusadas
    info(`Iniciando extração de dados de ${unicos.length} imóveis...`);
    const context = await newContext(browser);
    const limit = pLimit(maxConc);
    const pool = [];
    for (let i = 0; i < maxConc; i++) pool.push(await context.newPage());
    let cursor = 0;
    const resultados = [];
    const loteSize = Math.max(maxConc * 10, maxConc);
    info(`Processando em lotes de ${loteSize} para otimizar a extração com concorrência de ${maxConc}.`);
    for (let i = 0; i < unicos.length; i += loteSize) {
      const lote = unicos.slice(i, i + loteSize);
      const out2 = await Promise.all(lote.map((url) => limit(async () => {
        const page = pool[cursor++ % pool.length];
        try {
          return await extrairChaveMao(page, url);
        } catch (e) {
          error(`Erro ao extrair ${url}: ${e.message}`);
          return { url };
        }
      })));
      resultados.push(...out2.filter(Boolean));
      if (resultados.length % 100 === 0) salvar(out, resultados); // save parcial
    }
    salvar(out, resultados);
    const nSalvos = resultados.length;
    if (!nSalvos) warning('Nenhum dado coletado para salvar.');
    else info(`Dados salvos em ${out}. Total: ${nSalvos} imóveis.`);
    info(`Execução finalizada. Total de imóveis coletados: ${resultados.length}`);
    await context.close();
    await contextLinks.close();
    return resultados;
  } finally {
    await browser.close();
  }
}

async function main() {
  const { values } = parseArgs({
    options: {
      'url-template': { type: 'string' },
      pages: { type: 'string' },
      out: { type: 'string', default: 'resultados.json' },
      concurrency: { type: 'string', default: '5' },
      headless: { type: 'string', default: 'true' },
    },
  });
  const urlTemplate = values['url-template'];
  if (!urlTemplate) { error('Faltou --url-template'); process.exit(1); }
  await runColeta({
    urlTemplate,
    totalPages: values.pages ? parseInt(values.pages, 10) : null,
    out: values.out,
    maxConc: parseInt(values.concurrency, 10),
    headless: values.headless !== 'false',
  });
}

if (require.main === module) {
  main().catch((e) => { error(e.message || e); process.exit(1); });
}

module.exports = { runColeta, resolvePython };
