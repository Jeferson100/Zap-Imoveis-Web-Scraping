// Espelha link_anuncios_chave_mao_playwright_async.py
const { sleep } = require('./browser');
const { info, warning, error } = require('./log');

const MAX_RETRIES = 3;

async function getLinks(context, url, retries = MAX_RETRIES) {
  info(`Acessando: ${url}`);
  for (let i = 0; i < retries; i++) {
    const page = await context.newPage();
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      await page.waitForSelector("a[href*='/imovel/']", { timeout: 15000 });
      await page.evaluate('window.scrollBy(0, 1000)');
      await sleep(1000);
      const hrefs = await page.locator("a[href*='/imovel/']").evaluateAll(
        (els) => els.map((el) => el.href)
      );
      const validos = [...new Set(hrefs.filter((h) => h.includes('/imovel/')))];
      if (validos.length) {
        info(`Links encontrados para a URL ${url}`);
        return validos;
      }
      warning(`Tentativa ${i + 1}: Nenhum link encontrado na ${url}`);
    } catch (e) {
      error(`Tentativa ${i + 1} falhou para ${url}: ${e.message}`);
    } finally {
      await page.close().catch(() => {});
    }
  }
  return [];
}

module.exports = { getLinks };
