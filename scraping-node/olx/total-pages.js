// Espelha total_page_olx.py: fetch (Última página → o=N) + fallback Playwright.
const { newContext, launchChromium } = require('../chave-mao/browser');
const { info, warning } = require('../chave-mao/log');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36';

function totalPorHtml(html) {
  const m = html.match(/href="([^"]*[?&]o=(\d+)[^"]*)"[^>]*>[^<]*Última/i);
  if (m) return parseInt(m[2], 10);
  const vals = [...html.matchAll(/[?&]o=(\d+)/g)].map((x) => parseInt(x[1], 10));
  if (vals.length) return Math.max(...vals);
  return 1;
}

async function getTotalPages(urlPrimeiraPag, headless = true) {
  for (let t = 1; t <= 3; t++) {
    try {
      const ctrl = new AbortController();
      const to = setTimeout(() => ctrl.abort(), 60000);
      const resp = await fetch(urlPrimeiraPag, { headers: { 'User-Agent': UA }, signal: ctrl.signal });
      clearTimeout(to);
      if (resp.status !== 200) continue;
      const total = totalPorHtml(await resp.text());
      info(`Total de páginas via fetch: ${total}`);
      return total;
    } catch (e) { warning(`fetch total-pages tentativa ${t}: ${e.message}`); }
  }
  warning(`fetch falhou para ${urlPrimeiraPag}. Caindo para Playwright.`);
  const browser = await launchChromium(headless);
  try {
    const context = await newContext(browser);
    const page = await context.newPage();
    await page.goto(urlPrimeiraPag, { waitUntil: 'domcontentloaded', timeout: 60000 });
    try {
      const href = await page.getByRole('link', { name: 'Última página' }).getAttribute('href', { timeout: 5000 });
      const m = href && href.match(/[?&]o=(\d+)/);
      if (m) return parseInt(m[1], 10);
    } catch { /* estratégia 2 abaixo */ }
    const nums = await page.locator('a[data-lurker-detail="pagination_page"]').allTextContents().catch(() => []);
    const dig = nums.map((n) => parseInt(n, 10)).filter(Number.isFinite);
    if (dig.length) return Math.max(...dig);
    return 1;
  } catch (e) { warning(`Playwright total-pages: ${e.message}. Retornando 50.`); return 50; }
  finally { await browser.close(); }
}

module.exports = { getTotalPages };
