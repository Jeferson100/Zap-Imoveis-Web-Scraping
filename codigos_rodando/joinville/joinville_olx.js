// Espelha joinville_coleta_dados_olx_*.py (5 faixas se/ss) — versão Node.
// Uso (da raiz do repo):
//   Sequencial: node codigos_rodando/joinville/joinville_olx.js [--pages 0]
//   Paralelo:   node codigos_rodando/joinville/joinville_olx.js --faixas-concorrentes 2
// Saída .parquet por faixa (via bridge) + junção final (consolidar_parquet('olx', ...) do Python).
const path = require('path');
const { execFileSync } = require('node:child_process');
const { parseArgs } = require('node:util');
const pLimit = require('../../scraping-node/node_modules/p-limit');
const { runColeta, resolvePython } = require('../../scraping-node/olx/coleta');
const { info, warning, error, progress, fmtDur } = require('../../scraping-node/chave-mao/log');

const URL_TEMPLATE = 'https://www.olx.com.br/imoveis/venda/estado-sc?q=joinville{ss}{se}&o={pagina}';

// 5 faixas dos splits Python: se=67 / ss=68,se=90 / ss=91,se=125 / ss=126,se=195 / ss=196,se=15000000
const SE_RANGES = [
  [null, '67'], ['68', '90'], ['91', '125'], ['126', '195'], ['196', '15000000'],
];

const { values } = parseArgs({
  options: {
    pages: { type: 'string', default: '0' },  // 0 = automático (detecta por faixa)
    concurrency: { type: 'string', default: process.env.MAX_CONCURRENCY_OLX || '5' },
    'faixas-concorrentes': { type: 'string', default: '1' }, // 1=sequencial, 2+=paralelo
    headless: { type: 'string', default: 'true' },
  },
});

async function main() {
  const now = new Date().toISOString().slice(0, 7); // YYYY-MM
  const outDir = path.join(__dirname, '..', '..', 'dados', 'joinville');
  const maxConc = parseInt(values.concurrency, 10);
  const headless = values.headless !== 'false';
  const pagesArg = parseInt(values.pages, 10);
  const totalPages = pagesArg > 0 ? pagesArg : null;  // null → runColeta auto-detecta por faixa
  const nFaixas = Math.max(1, parseInt(values['faixas-concorrentes'], 10) || 1);

  const t0Geral = Date.now();
  info(`Modo OLX: ${nFaixas === 1 ? 'sequencial (atual)' : `paralelo x${nFaixas} (novo)`}`);

  async function rodaFaixa(ss, se, idx) {
    const rotulo = `[olx ${ss || 0}-${se}]`;
    if (nFaixas === 1) progress(idx, SE_RANGES.length, `Faixa OLX [${idx + 1}/${SE_RANGES.length}]`, t0Geral);
    info(nFaixas === 1 ? `Coletando OLX de ${ss || 0} a ${se}` : `${rotulo} início`);
    const out = path.join(outDir, `joinville_olx_${now}_${ss || 0}_${se}.parquet`);
    const url = URL_TEMPLATE.replace('{ss}', ss ? `&ss=${ss}` : '').replace('{se}', `&se=${se}`);
    info(nFaixas === 1 ? `Arquivo de dados gerado em: ${out}` : `${rotulo} out: ${out}`);
    const res = await runColeta({
      urlTemplate: url, totalPages, out, maxConc, headless,
      rotulo: nFaixas === 1 ? '' : rotulo, limite_falhas: 3, cooldown: 0,
    });
    info(`${nFaixas === 1 ? `Faixa OLX [${idx + 1}/${SE_RANGES.length}] ${ss || 0}-${se}` : rotulo} finalizada: ${(res || []).length} imóveis em ${fmtDur(Date.now() - t0Geral)} (total).`);
    return res;
  }

  if (nFaixas === 1) {
    for (let idx = 0; idx < SE_RANGES.length; idx++) {
      const [ss, se] = SE_RANGES[idx];
      await rodaFaixa(ss, se, idx);
    }
  } else {
    const limitFaixa = pLimit(nFaixas);
    let concluidas = 0;
    await Promise.all(SE_RANGES.map(([ss, se], idx) => limitFaixa(async () => {
      const r = await rodaFaixa(ss, se, idx);
      concluidas++;
      progress(concluidas, SE_RANGES.length, 'Faixas OLX', t0Geral);
      return r;
    })));
  }
  progress(SE_RANGES.length, SE_RANGES.length, 'Faixas OLX', t0Geral);
  info(`Arquivo de dados gerado em: ${outDir}`);

  // --- JUNÇÃO FINAL (reusa consolidar_parquet do Python: mesmos globs,
  // validações e limpeza das fatias; paridade total, sem reimplementar) ---
  try {
    execFileSync(resolvePython(), ['-c',
      "import sys; sys.path.insert(0, 'codigos_rodando');"
      + "from pathlib import Path;"
      + "from unificando_dados import consolidar_parquet;"
      + `consolidar_parquet('olx', 'joinville', Path(r'${outDir}'))`,
    ], { stdio: 'inherit', cwd: path.join(__dirname, '..', '..') });
  } catch (e) {
    warning(`Consolidação final falhou (${e.message}). Fatias preservadas em ${outDir}.`);
  }
  info('Coleta OLX Joinville finalizada. Arquivo único + fatias removidas (se ok).');
  info(`Tempo total OLX Joinville: ${fmtDur(Date.now() - t0Geral)}.`);
}

if (require.main === module) {
  main().catch((e) => { error(e.message || e); process.exit(1); });
}
