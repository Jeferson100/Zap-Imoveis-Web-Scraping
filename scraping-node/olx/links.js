// Espelha link_anuncios_olx_playwright_async.py: fetch primário (curl_cffi) + fallback Playwright.
// Seletor estável: a[data-testid="adcard-link"], filtra olx.com.br + "-".
const { sleep, rand } = require('../chave-mao/browser');
const { info, warning, error } = require('../chave-mao/log');

const MAX_RETRIES = 3;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';

function extrairLinksHtml(html) {
  const re = /<a[^>]*data-testid="adcard-link"[^>]*href="([^"]+)"/g;
  const out = new Set();
  let m;
  while ((m = re.exec(html)) !== null) {
    const h = m[1];
    if (h.includes('olx.com.br') && h.includes('-')) out.add(h);
  }
  return [...out];
}

async function getLinksFetch(url, retries = MAX_RETRIES) {
  for (let t = 1; t <= retries; t++) {
    try {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 30000);
      const resp = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'text/html' }, signal: ctrl.signal });
      clearTimeout(to);
      if (resp.status !== 200) { warning(`fetch status ${resp.status} (tentativa ${t}) ${url}`); continue; }
      const html = await resp.text();
      const links = extrairLinksHtml(html);
      if (links.length) { info(`Links via fetch para ${url}: ${links.length}`); return links; }
      warning(`fetch tentativa ${t}: nenhum link em ${url}`);
    } catch (e) { warning(`fetch tentativa ${t} falhou ${url}: ${e.message}`); }
    await sleep(rand(1500, 4000));
  }
  return [];
}

async function getLinksPlaywright(context, url, retries = MAX_RETRIES) {
  for (let i = 0; i < retries; i++) {
    const page = await context.newPage();
    try {
      info(`Acessando listagem OLX: ${url}`);
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForSelector('a[data-testid="adcard-link"]', { timeout: 10000 });
      await page.evaluate('window.scrollBy(0, 800)');
      await sleep(400);
      const hrefs = await page.locator('a[data-testid="adcard-link"]').evaluateAll((els) => els.map((el) => el.href));
      const validos = [...new Set(hrefs.filter((h) => h.includes('olx.com.br') && h.includes('-')))];
      if (validos.length) { info(`Links via Playwright para ${url}: ${validos.length}`); return validos; }
      warning(`Tentativa ${i + 1}: nenhum link em ${url}`);
    } catch (e) { error(`Tentativa ${i + 1} falhou ${url}: ${e.message}`); }
    finally { await page.close().catch(() => {}); }
    await sleep(rand(1500, 4000));
  }
  return [];
}

async function getLinks(context, url, retries = MAX_RETRIES) {
  const viaFetch = await getLinksFetch(url, retries);
  if (viaFetch.length) return viaFetch;
  warning(`fetch falhou para ${url}. Caindo para Playwright.`);
  return getLinksPlaywright(context, url, retries);
}

module.exports = { getLinks };
