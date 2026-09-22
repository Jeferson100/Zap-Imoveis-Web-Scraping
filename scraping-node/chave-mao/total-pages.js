// Espelha total_page_chaves.py: detecta o total de páginas da listagem.
const { chromium } = require('playwright');
const { newContext } = require('./browser');

async function getTotalPages(urlPrimeiraPag, headless = true) {
  const browser = await chromium.launch({ headless });
  try {
    const context = await newContext(browser);
    const page = await context.newPage();
    await page.goto(urlPrimeiraPag, { waitUntil: 'domcontentloaded', timeout: 60000 });
    // Padrão Chave na Mão: paginador com links ?pg=N
    const hrefs = await page.locator("a[href*='pg=']").evaluateAll(
      (els) => els.map((el) => el.href)
    );
    let max = 1;
    for (const h of hrefs) {
      const m = h.match(/[?&]pg=(\d+)/);
      if (m) max = Math.max(max, parseInt(m[1], 10));
    }
    return max;
  } finally {
    await browser.close();
  }
}

module.exports = { getTotalPages };
