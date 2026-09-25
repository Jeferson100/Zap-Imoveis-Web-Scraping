// Espelha total_page_chaves.py: detecta o total de páginas da listagem.
const { newContext, launchChromium } = require('./browser');
const { info, warning } = require('./log');

async function getTotalPages(urlPrimeiraPag, headless = true, porPagina = 15) {
  const browser = await launchChromium(headless);
  try {
    const context = await newContext(browser);
    const page = await context.newPage();
    // networkidle garante os cards (igual Python: TotalPageChavesNaMao)
    await page.goto(urlPrimeiraPag, { waitUntil: 'networkidle', timeout: 60000 });
    let textoTotal = '';
    try {
      const loc = page.locator('h1[class*="styles_text-display"] strong');
      await loc.waitFor({ state: 'visible', timeout: 20000 });
      textoTotal = await loc.innerText();
    } catch {
      // Fallback: primeiro h1 com dígitos (caso o hash da classe rode)
      const h1s = await page.locator('h1').allInnerTexts().catch(() => []);
      textoTotal = h1s.find((t) => /\d/.test(t || '')) || '';
    }
    const m = (textoTotal || '').replace(/[.,]/g, '').match(/\d+/);
    if (!m) return 100;
    const total = Math.ceil(parseInt(m[0], 10) / porPagina);
    info(`Detectado: ${m[0]} imóveis -> ${total} páginas.`);
    return Math.min(total, 100);
  } catch (e) {
    warning(`Erro no Chaves na Mão: ${e.message}. Retornando total de páginas padrão: 100.`);
    return 100;
  } finally {
    await browser.close();
  }
}

module.exports = { getTotalPages };
