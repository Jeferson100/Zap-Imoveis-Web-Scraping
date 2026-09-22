// Espelha joinville_coleta_dados_chave_mao.py — versão Node.
// Uso (da raiz do repo): node codigos_rodando/joinville/joinville_chaves.js [--pages 100]
const path = require('path');
const { parseArgs } = require('node:util');
const { runColeta } = require('../../scraping-node/chave-mao/coleta');

const URL_TEMPLATE =
  'https://www.chavesnamao.com.br/imoveis-a-venda/sc-joinville/' +
  '?filtro=amin:{min},amax:{max}&pg={pagina}';

const AREA_RANGES = [
  ['0', '50'], ['51', '60'], ['61', '65'], ['66', '70'], ['71', '75'],
  ['76', '80'], ['81', '90'], ['91', '100'], ['101', '110'], ['111', '120'],
  ['121', '130'], ['131', '150'], ['151', '175'], ['176', '200'], ['201', '250'],
  ['251', '300'], ['301', '400'], ['401', '500'], ['501', '600'], ['601', '3000000'],
];

const { values } = parseArgs({
  options: {
    pages: { type: 'string', default: '100' },
    concurrency: { type: 'string', default: process.env.MAX_CONCURRENCY || '3' },
    headless: { type: 'string', default: 'true' },
  },
});

async function main() {
  const now = new Date().toISOString().slice(0, 7); // YYYY-MM
  const outDir = path.join(__dirname, '..', '..', 'dados', 'joinville');
  const maxConc = parseInt(values.concurrency, 10);
  const headless = values.headless !== 'false';
  const totalPages = parseInt(values.pages, 10);

  for (const [min, max] of AREA_RANGES) {
    console.log(`Coletando dados de ${min} a ${max}`);
    const out = path.join(outDir, `joinville_chave_mao_${now}_${min}_${max}.json`);
    const url = URL_TEMPLATE.replace('{min}', min).replace('{max}', max);
    console.log(`Arquivo de dados: ${out}`);
    await runColeta({ urlTemplate: url, totalPages, out, maxConc, headless });
  }
  console.log('Coleta Joinville finalizada. Rode consolidar_parquet no Python para gerar os .parquet.');
}

if (require.main === module) {
  main().catch((e) => { console.error(e); process.exit(1); });
}
