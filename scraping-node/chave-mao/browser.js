// Helpers compartilhados: 1 browser reusado + bloqueio de mídia.
// Stealth parity com o Python (playwright-stealth).
const { chromium: chromiumVanilla } = require('playwright');

let chromiumStealth = null;
try {
  const { chromium } = require('playwright-extra');
  chromium.use(require('puppeteer-extra-plugin-stealth')());
  chromiumStealth = chromium;
} catch {
  // Sem stealth instalado: segue com Chromium puro (e avisa)
  try {
    const { warning } = require('./log');
    warning('Stealth indisponível, usando Chromium puro.');
  } catch {
    console.warn('Stealth indisponível, usando Chromium puro.');
  }
}

async function launchChromium(headless) {
  const engine = chromiumStealth || chromiumVanilla;
  return engine.launch({ headless });
}

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

module.exports = { UA, newContext, sleep, rand, launchChromium };
