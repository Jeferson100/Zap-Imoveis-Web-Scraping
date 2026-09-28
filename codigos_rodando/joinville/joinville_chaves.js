// Espelha joinville_coleta_dados_chave_mao.py — versão Node.
// Uso (da raiz do repo):
//   Sequencial (modelo atual): node codigos_rodando/joinville/joinville_chaves.js [--pages 0]
//   Paralelo (modelo novo):    node codigos_rodando/joinville/joinville_chaves.js --faixas-concorrentes 2
// Saída .parquet por faixa (via bridge) + junção final (consolidar_parquet do Python).
const path = require('path');
const { execFileSync } = require('node:child_process');
const { parseArgs } = require('node:util');
const pLimit = require('../../scraping-node/node_modules/p-limit');
const { runColeta, resolvePython } = require('../../scraping-node/chave-mao/coleta');
const { info, warning, error, progress, fmtDur } = require('../../scraping-node/chave-mao/log');

const URL_TEMPLATE =
  'https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/' +
  '?filtro=amin:{min},amax:{max}&pg={pagina}';

const AREA_RANGES = [
  //['0', '50'], ['51', '60'],
  //['61', '65'], ['66', '70'], ['71', '75'],
  //['76', '80'], 
  ['81', '90'], ['91', '100'], ['101', '110'], ['111', '120'],
  ['121', '130'], ['131', '150'], ['151', '175'], ['176', '200'], ['201', '250'],
  ['251', '300'], ['301', '400'], ['401', '500'], ['501', '600'], ['601', '3000000'],
];

const { values } = parseArgs({
  options: {
    pages: { type: 'string', default: '0' },  // 0 = automático (detecta por faixa)
    concurrency: { type: 'string', default: '10' },
    'faixas-concorrentes': { type: 'string', default: '2' }, // 1=atual sequencial, 2+=novo paralelo
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
  info(`Modo: ${nFaixas === 1 ? 'sequencial (atual)' : `paralelo x${nFaixas} (novo)`}`);

  async function rodaFaixa(min, max, idx) {
    const rotulo = `[faixa ${min}-${max}]`;
    if (nFaixas === 1) progress(idx, AREA_RANGES.length, `Faixa [${idx + 1}/${AREA_RANGES.length}]`, t0Geral);
    info(nFaixas === 1 ? `Coletando dados de ${min} a ${max}` : `${rotulo} início`);
    const out = path.join(outDir, `joinville_chave_mao_${now}_${min}_${max}.parquet`);
    const url = URL_TEMPLATE.replace('{min}', min).replace('{max}', max);
    info(nFaixas === 1 ? `Arquivo de dados gerado em: ${out}` : `${rotulo} out: ${out}`);
    const res = await runColeta({ urlTemplate: url, totalPages, out, maxConc, headless, rotulo: nFaixas === 1 ? '' : rotulo });
    info(`${nFaixas === 1 ? `Faixa [${idx + 1}/${AREA_RANGES.length}] ${min}-${max}` : rotulo} finalizada: ${(res || []).length} imóveis em ${fmtDur(Date.now() - t0Geral)} (total).`);
    return res;
  }

  if (nFaixas === 1) {
    for (let idx = 0; idx < AREA_RANGES.length; idx++) {
      const [min, max] = AREA_RANGES[idx];
      await rodaFaixa(min, max, idx);
    }
  } else {
    const limitFaixa = pLimit(nFaixas);
    let concluidas = 0;
    await Promise.all(AREA_RANGES.map(([min, max], idx) => limitFaixa(async () => {
      const r = await rodaFaixa(min, max, idx);
      concluidas++;
      progress(concluidas, AREA_RANGES.length, 'Faixas', t0Geral);
      return r;
    })));
  }
  progress(AREA_RANGES.length, AREA_RANGES.length, 'Faixas Joinville', t0Geral);
  info(`Arquivo de dados gerado em: ${outDir}`);

  // --- JUNÇÃO FINAL (reusa consolidar_parquet do Python: mesmos globs,
  // validações e limpeza das fatias; paridade total, sem reimplementar) ---
  try {
    execFileSync(resolvePython(), ['-c',
      "import sys; sys.path.insert(0, 'codigos_rodando');"
      + "from pathlib import Path;"
      + "from unificando_dados import consolidar_parquet;"
      + `consolidar_parquet('chave_mao', 'joinville', Path(r'${outDir}'))`,
    ], { stdio: 'inherit', cwd: path.join(__dirname, '..', '..') });
  } catch (e) {
    warning(`Consolidação final falhou (${e.message}). Fatias preservadas em ${outDir}.`);
  }
  info('Coleta Joinville finalizada. Arquivo único + fatias removidas (se ok).');
  info(`Tempo total Joinville: ${fmtDur(Date.now() - t0Geral)}.`);
}

if (require.main === module) {
  main().catch((e) => { error(e.message || e); process.exit(1); });
}
