// Espelha olx_coleta.py: CLI + 3 fases + save parcial + progress/ETA + rotulo.
// Uso: node coleta.js --url-template "https://...&o={pagina}" [--pages N] [--out out.parquet] [--concurrency 5] [--headless true]
const fs = require('fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { parseArgs } = require('node:util');
const pLimit = require('p-limit');
const { newContext, sleep, rand, launchChromium } = require('../chave-mao/browser');
const { info, warning, error, progress, fmtDur } = require('../chave-mao/log');
const { getLinks } = require('./links');
const { extrairOlx } = require('./extrair');
const { getTotalPages } = require('./total-pages');

function resolvePython() {
  const candidatos = [];
  if (process.env.PYTHON_BIN) candidatos.push(process.env.PYTHON_BIN);
  candidatos.push(path.join(__dirname, '..', '..', '.venv',
    process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python'));
  for (const c of candidatos) {
    try { fs.accessSync(c, fs.constants.X_OK); return c; } catch { /* próximo */ }
  }
  return 'python';
}

function salvar(out, dados) {
  if (!out.endsWith('.parquet')) {
    fs.writeFileSync(out, JSON.stringify(dados, null, 4));
    return;
  }
  const tmp = path.join(os.tmpdir(), `coleta-olx-${Date.now()}-${Math.floor(Math.random() * 1e6)}.json`);
  try {
    fs.writeFileSync(tmp, JSON.stringify(dados));
    execFileSync(resolvePython(), [path.join(__dirname, '..', 'chave-mao', 'to-parquet.py'), tmp, out], { stdio: 'inherit' });
    fs.rmSync(tmp, { force: true });
  } catch (e) {
    warning(`Falha ao gerar parquet (${e.message}). Mantido JSON: ${tmp}`);
  }
}

async function runColeta({ urlTemplate, totalPages, out, maxConc = 5, headless = true, rotulo = '', limite_falhas = 3, cooldown = 0 }) {
  const tag = rotulo ? `${rotulo} ` : '';
  info(`${tag}Parametros recebidos: totalPages=${totalPages}, max_concurrency=${maxConc}, headless=${headless}`);
  if (!totalPages) info(`${tag}Total de páginas não definido. Iniciando detecção automática...`);
  const total = totalPages || await getTotalPages(urlTemplate.replace('{pagina}', '1'), headless);
  if (!total) { error(`${tag}Não foi possível determinar o total de páginas.`); return []; }
  info(`${tag}Total de páginas: ${total}`);

  let browser;
  try {
    browser = await launchChromium(headless);
  } catch (e) {
    error(`${tag}Erro ao inicializar navegador: ${e.message}`);
    throw e;
  }
  try {
    info(`${tag}Iniciando coleta de links em ${total} páginas`);
    const contextLinks = await newContext(browser);
    const todosLinks = [];
    let falhas = 0;
    let pagina = 1;
    const t0Links = Date.now();
    while (pagina <= total) {
      const lote = Array.from({ length: Math.min(maxConc, total - pagina + 1) }, (_, i) => pagina + i);
      const res = await Promise.all(lote.map((pg) =>
        getLinks(contextLinks, urlTemplate.replace('{pagina}', pg))));
      res.forEach((links, idx) => {
        if (links.length) {
          info(`${tag}Página ${lote[idx]}: ${links.length} links encontrados.`);
          falhas = 0;
          todosLinks.push(...links);
        } else {
          falhas++;
          warning(`${tag}Página ${lote[idx]} não retornou links. Falhas consecutivas: ${falhas}/${limite_falhas}.`);
        }
      });
      if (falhas >= limite_falhas) {
        error(`${tag}Interrompendo: ${limite_falhas} páginas seguidas sem links.`);
        break;
      }
      pagina += maxConc;
      progress(Math.min(pagina - 1, total), total, `${tag}Links`, t0Links);
      await sleep(rand(200, 1000));
    }
    const unicos = [...new Set(todosLinks)];
    info(`${tag}Total de links únicos coletados: ${unicos.length}`);
    if (!unicos.length) { error(`${tag}Nenhum link foi encontrado. Encerrando.`); return []; }

    if (cooldown > 0) {
      info(`${tag}Aguardando ${cooldown}s antes da extração detalhada...`);
      for (let s = cooldown; s > 0; s -= 5) {
        progress(cooldown - s, cooldown, `${tag}Aguardando extração (s)`);
        await sleep(5000);
      }
    }

    info(`${tag}Iniciando extração de dados de ${unicos.length} imóveis...`);
    const context = await newContext(browser);
    const limit = pLimit(maxConc);
    const pool = [];
    for (let i = 0; i < maxConc; i++) pool.push(await context.newPage());
    let cursor = 0;
    const resultados = [];
    const loteSize = Math.max(maxConc * 10, maxConc);
    info(`${tag}Processando em lotes de ${loteSize} para otimizar a extração com concorrência de ${maxConc}.`);
    const nLotes = Math.ceil(unicos.length / loteSize);
    const t0Ext = Date.now();
    for (let i = 0, k = 1; i < unicos.length; i += loteSize, k++) {
      const lote = unicos.slice(i, i + loteSize);
      const out2 = await Promise.all(lote.map((url) => limit(async () => {
        const page = pool[cursor++ % pool.length];
        try {
          return await extrairOlx(page, url);
        } catch (e) {
          error(`${tag}Erro ao extrair ${url}: ${e.message}`);
          return { url };
        }
      })));
      resultados.push(...out2.filter(Boolean));
      progress(Math.min(i + loteSize, unicos.length), unicos.length, `${tag}Extração lote ${k}/${nLotes}`, t0Ext);
      if (resultados.length % 100 === 0) salvar(out, resultados); // save parcial
    }
    salvar(out, resultados);
    const nSalvos = resultados.length;
    if (!nSalvos) warning(`${tag}Nenhum dado coletado para salvar.`);
    else info(`${tag}Dados salvos em ${out}. Total: ${nSalvos} imóveis.`);
    info(`${tag}Execução finalizada. Total de imóveis coletados: ${resultados.length} em ${fmtDur(Date.now() - t0Ext)} (extração) / ${fmtDur(Date.now() - t0Links)} (links+extração)`);
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
