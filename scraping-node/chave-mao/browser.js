// Helpers compartilhados: 1 browser reusado + bloqueio de mídia.
// (Melhorias vs. Python: sem launch por item, sem imagens/fontes/mídia.)
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) ' +
  'AppleWebKit/537.36 (KHTML, like Gecko) ' +
  'Chrome/120.0.0.0 Safari/537.36';

async function newContext(browser) {
  const context = await browser.newContext({ userAgent: UA });
  // Corta imagens/fontes/mídia: páginas Next.js ficam bem mais leves
  await context.route(/\.(png|jpe?g|gif|webp|svg|woff2?|ttf|mp4|webm)$/i, (route) => route.abort());
  return context;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const rand = (a, b) => a + Math.random() * (b - a);

module.exports = { UA, newContext, sleep, rand };
