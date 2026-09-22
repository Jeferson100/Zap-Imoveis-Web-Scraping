// Espelha chave_mao_coleta.py: CLI + 3 fases + save parcial.
// Uso: node coleta.js --url-template "https://.../?pg={pagina}" [--pages N] [--out out.json] [--concurrency 5] [--headless true]
const fs = require('fs');
const { parseArgs } = require('node:util');
const { chromium } = require('playwright');
const pLimit = require('p-limit');
const { newContext, sleep, rand } = require('./browser');
const { getLinks } = require('./links');
const { extrairChaveMao } = require('./extrair');
const { getTotalPages } = require('./total-pages');

const { values } = parseArgs({
  options: {
    'url-template': { type: 'string' },
    pages: { type: 'string' },
    out: { type: 'string', default: 'resultados.json' },
    concurrency: { type: 'string', default: '5' },
    headless: { type: 'string', default: 'true' },
  },
});
const URL_TEMPLATE = values['url-template'];
const MAX_CONC = parseInt(values.concurrency, 10);
const HEADLESS = values.headless !== 'false';
if (!URL_TEMPLATE) { console.error('Faltou --url-template'); process.exit(1); }

function salvar(out, dados) {
  fs.writeFileSync(out, JSON.stringify(dados, null, 4));
}

async function main() {
  const totalPages = values.pages
    ? parseInt(values.pages, 10)
    : await getTotalPages(URL_TEMPLATE.replace('{pagina}', '1'), HEADLESS);
  if (!totalPages) { console.error('Sem páginas.'); return; }
  console.log(`Total de páginas: ${totalPages}`);

  // Browser ÚNICO reusado (diferença vs. Python: sem launch por item)
  const browser = await chromium.launch({ headless: HEADLESS });
  try {
    // ETAPA 2: links em lotes
    const contextLinks = await newContext(browser);
    const todosLinks = [];
    for (let p = 1; p <= totalPages; p += MAX_CONC) {
      const lote = Array.from({ length: Math.min(MAX_CONC, totalPages - p + 1) }, (_, i) => p + i);
      const res = await Promise.all(lote.map((pg) =>
        getLinks(contextLinks, URL_TEMPLATE.replace('{pagina}', pg))));
      res.flat().forEach((l) => todosLinks.push(l));
      await sleep(rand(200, 1000));
    }
    const unicos = [...new Set(todosLinks)];
    console.log(`Links únicos: ${unicos.length}`);
    if (!unicos.length) return;

    console.log('Aguardando 30s antes da extração detalhada...');
    await sleep(30000);

    // ETAPA 4: detalhe com pool de páginas reusadas
    const context = await newContext(browser);
    const limit = pLimit(MAX_CONC);
    const pool = [];
    for (let i = 0; i < MAX_CONC; i++) pool.push(await context.newPage());
    let cursor = 0;
    const resultados = [];
    const loteSize = Math.max(MAX_CONC * 10, MAX_CONC);
    for (let i = 0; i < unicos.length; i += loteSize) {
      const lote = unicos.slice(i, i + loteSize);
      const out = await Promise.all(lote.map((url) => limit(async () => {
        const page = pool[cursor++ % pool.length];
        try {
          return await extrairChaveMao(page, url);
        } catch (e) {
          console.error(`Erro em ${url}: ${e.message}`);
          return { url };
        }
      })));
      resultados.push(...out.filter(Boolean));
      if (resultados.length % 100 === 0) salvar(values.out, resultados); // save parcial
    }
    salvar(values.out, resultados);
    console.log(`Finalizado: ${resultados.length} imóveis.`);
    await context.close();
    await contextLinks.close();
  } finally {
    await browser.close();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
