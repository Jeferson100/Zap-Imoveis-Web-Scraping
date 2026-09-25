// Uso: node diag-metragem.js <url>
const { chromium } = require('playwright-extra');
chromium.use(require('puppeteer-extra-plugin-stealth')());

(async () => {
  const url = process.argv[2];
  if (!url) { console.error('Passe a URL como argumento'); process.exit(1); }
  const b = await chromium.launch({ headless: true });
  const p = await (await b.newContext()).newPage();
  await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await p.waitForTimeout(8000);
  const html = await p.content();
  // 1. Blocos "area" no HTML (candidatos ao eco de filtro)
  let pos = 0, n = 0;
  while (n < 5) {
    const i = html.indexOf('"area"', pos);
    if (i < 0) break;
    console.log('BLOCO-AREA:', JSON.stringify(html.slice(Math.max(0, i - 60), i + 200)));
    pos = i + 1; n++;
  }
  if (!n) console.log('BLOCO-AREA: nenhum');
  // 2. Elemento aria-util (candidato DOM)
  console.log('aria-util count:', await p.locator('p[aria-label="area-util"]').count());
  try {
    const t = await p.locator('p[aria-label="area-util"] b').first().innerText({ timeout: 5000 });
    console.log('aria-util text:', JSON.stringify(t));
  } catch (e) { console.log('aria-util ERRO:', e.message.split('\n')[0]); }
  await b.close();
})().catch((e) => console.error('ERRO:', e.message));