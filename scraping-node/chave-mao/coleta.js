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
    console.warn(`Falha ao gerar parquet (${e.message}). Mantido JSON: ${tmp}`);
  }
}

async function runColeta({ urlTemplate, totalPages, out, maxConc = 5, headless = true }) {
  const total = totalPages || await getTotalPages(urlTemplate.replace('{pagina}', '1'), headless);
  if (!total) { console.error('Sem páginas.'); return []; }
  console.log(`Total de páginas: ${total}`);

  // Browser ÚNICO reusado (diferença vs. Python: sem launch por item)
  const browser = await launchChromium(headless);
  try {
    // ETAPA 2: links em lotes
    const contextLinks = await newContext(browser);
    const todosLinks = [];
    for (let p = 1; p <= total; p += maxConc) {
      const lote = Array.from({ length: Math.min(maxConc, total - p + 1) }, (_, i) => p + i);
      const res = await Promise.all(lote.map((pg) =>
        getLinks(contextLinks, urlTemplate.replace('{pagina}', pg))));
      res.flat().forEach((l) => todosLinks.push(l));
      await sleep(rand(200, 1000));
    }
    const unicos = [...new Set(todosLinks)];
    console.log(`Links únicos: ${unicos.length}`);
    if (!unicos.length) return [];

    console.log('Aguardando 30s antes da extração detalhada...');
    await sleep(30000);

    // ETAPA 4: detalhe com pool de páginas reusadas
    const context = await newContext(browser);
    const limit = pLimit(maxConc);
    const pool = [];
    for (let i = 0; i < maxConc; i++) pool.push(await context.newPage());
    let cursor = 0;
    const resultados = [];
    const loteSize = Math.max(maxConc * 10, maxConc);
    for (let i = 0; i < unicos.length; i += loteSize) {
      const lote = unicos.slice(i, i + loteSize);
      const out2 = await Promise.all(lote.map((url) => limit(async () => {
        const page = pool[cursor++ % pool.length];
        try {
          return await extrairChaveMao(page, url);
        } catch (e) {
          console.error(`Erro em ${url}: ${e.message}`);
          return { url };
        }
      })));
      resultados.push(...out2.filter(Boolean));
      if (resultados.length % 100 === 0) salvar(out, resultados); // save parcial
    }
    salvar(out, resultados);
    console.log(`Finalizado: ${resultados.length} imóveis.`);
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
  if (!urlTemplate) { console.error('Faltou --url-template'); process.exit(1); }
  await runColeta({
    urlTemplate,
    totalPages: values.pages ? parseInt(values.pages, 10) : null,
    out: values.out,
    maxConc: parseInt(values.concurrency, 10),
    headless: values.headless !== 'false',
  });
}

if (require.main === module) {
  main().catch((e) => { console.error(e); process.exit(1); });
}

module.exports = { runColeta, resolvePython };
