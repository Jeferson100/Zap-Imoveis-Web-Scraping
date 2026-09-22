// Espelha extrair_dados_chave_mao_playwright_async.py (mesmos seletores/fallbacks)
const MAX_RETRIES = 3;
const RETRY_DELAY = 2000;

function limparValor(v) {
  if (!v || /[-—]|Consulte/.test(v)) return '0';
  return (v.match(/\d/g) || []).join('');
}

function normalizarMonetario(v) {
  if (!v) return null;
  let s = String(v).trim().replace(/[^\d.,]/g, '');
  if (!s) return null;
  if (s.includes(',') && s.includes('.')) s = s.replace(/\./g, '').replace(',', '.');
  else if (s.includes(',')) s = s.replace(',', '.');
  else if (s.includes('.')) {
    const partes = s.split('.');
    if (partes[partes.length - 1].length === 3 && partes.length > 1) s = s.replace(/\./g, '');
  }
  const n = parseFloat(s);
  return Number.isNaN(n) ? (s.replace(/[^0-9]/g, '') || null) : String(Math.trunc(n));
}

async function texto(page, seletor, timeout = 5000) {
  try {
    const t = await page.locator(seletor).first.innerText({ timeout });
    return t.trim();
  } catch { return null; }
}

async function extrairValor(page) {
  try {
    const scripts = await page.locator('script[type="application/ld+json"]').allInnerTexts();
    for (const s of scripts) {
      if (!s) continue;
      let m = s.match(/"rawPrice"\s*:?"?([\d.,]+)"?/i) || s.match(/"price"\s*:?"?([\d.,]+)"?/i);
      if (m) return normalizarMonetario(m[1]);
      m = s.match(/"price"\s*:\s*"([^"]+)"/i);
      if (m) return normalizarMonetario(m[1]);
    }
  } catch { /* segue para fallbacks */ }
  try {
    const body = await page.locator('body').innerText();
    const padroes = [
      /(?:preço|valor do imóvel|valor)\s*[:\-]?\s*R\$\s*([\d.,]+)/i,
      /aluguel\s*[:\-]?\s*R\$\s*([\d.,]+)\s*(?:\/mês)?/i,
      /aluguel\s*\+\s*condomínio\s*R\$\s*([\d.,]+)/i,
    ];
    for (const p of padroes) {
      const m = body.match(p);
      if (m) return normalizarMonetario(m[1]);
    }
  } catch { /* segue para fallback */ }
  return normalizarMonetario(await texto(page, 'span.style_clamp__m7txb'));
}

async function extrairMetragens(page) {
  let total = null, util = null;
  try {
    const html = await page.content();
    const m = html.match(/"area"\s*:\s*\{\s*"total"\s*:\s*"([^"]+)"[^}]*"useful"\s*:\s*"([^"]+)"/);
    if (m) {
      total = ['$undefined', ''].includes(m[1]) ? null : m[1];
      util = ['$undefined', ''].includes(m[2]) ? null : m[2];
    }
  } catch { /* segue para fallbacks */ }
  if (!total) {
    const t = await texto(page, 'p[aria-label="area-total"] b');
    if (t) total = t.replace(/[^\d.,]/g, '') || null;
  }
  if (!util) {
    const u = await texto(page, 'p[aria-label="area-util"] b');
    if (u) util = u.replace(/[^\d.,]/g, '') || null;
  }
  if (!total && !util) {
    const g = await texto(page, 'b.row.spacing:has-text("m²")');
    if (g) total = g.replace(/[^\d.,]/g, '') || null;
  }
  return [total ? `${total} m²` : null, util ? `${util} m²` : null];
}

async function extrairCaracteristicas(page) {
  let priv = [], comum = [];
  try {
    const html = await page.content();
    const mp = html.match(/"privativeItems"\s*:\s*\[(.*?)\]/s);
    if (mp) priv = [...mp[1].matchAll(/"name"\s*:\s*"([^"]+)"/g)].map((m) => m[1]);
    const mc = html.match(/"commonItems"\s*:\s*\[(.*?)\]/s);
    if (mc) comum = [...mc[1].matchAll(/"name"\s*:\s*"([^"]+)"/g)].map((m) => m[1]);
  } catch { /* segue para fallback */ }
  return [priv.map((s) => s.trim()).filter(Boolean), comum.map((s) => s.trim()).filter(Boolean)];
}

async function extrairFotos(page) {
  try {
    await page.locator('#tablink-media').click();
    await page.waitForSelector('ul.galleryContainer', { timeout: 5000 });
    return await page.locator('ul.galleryContainer img').evaluateAll(
      (imgs) => imgs.map((img) => img.src || img.dataset.src)
    );
  } catch { return []; }
}

async function extrairMapa(page) {
  try {
    await page.locator('#tablink-map').click();
    await page.waitForSelector('iframe[src*="maps"]', { timeout: 5000 });
    return await page.locator('iframe[src*="maps"]').first.getAttribute('src', { timeout: 5000 });
  } catch { return null; }
}

// Recebe page JÁ ABERTA (browser reusado pelo orquestrador)
async function extrairChaveMao(page, url) {
  for (let t = 1; t <= MAX_RETRIES; t++) {
    try {
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
      // Espera determinística pela hidratação (título com texto) em vez de
      // sleep fixo: sem isso a extração pode rodar antes do React hidratar.
      // Seletor genérico (sem hash CSS) = imune a rotação de hashes do site.
      await page.waitForFunction(
        () => document.querySelector('h1')?.innerText?.trim().length > 0,
        { timeout: 25000 }
      ).catch(() => {});
      await page.waitForTimeout(1500); // settle final
      const [metragemTotal, metragemUtil] = await extrairMetragens(page);
      const [priv, comum] = await extrairCaracteristicas(page);
      return {
        url,
        titulo: await texto(page, 'h1.styles_typography__xG9rg'),
        metragem: metragemUtil || metragemTotal,
        metragem_total: metragemTotal,
        metragem_util: metragemUtil,
        valor_imovel: await extrairValor(page),
        quartos: await texto(page, "b:has(svg path[d^='M112.867 767.316'])"),
        banheiros: limparValor(await texto(page, 'p[aria-label="Banheiros"] b')),
        vagas: await texto(page, "p[aria-label='Garagens'] b"),
        endereco: await texto(page, 'h2[class*="styles_text-title-lg"].column, h2[class*="styles_text-title-lg"] b'),
        descricao: await texto(page, 'p[aria-label="descrição"]'),
        condominio: limparValor(await texto(page, 'p:has-text("Condomínio") + p')),
        iptu: limparValor(await texto(page, 'p:has-text("IPTU") + p')),
        caracteristicas: [],
        caracteristicas_privativa: priv,
        caracteristicas_comum: comum,
        fotos: await extrairFotos(page),
        link_maps: await extrairMapa(page),
      };
    } catch (e) {
      console.warn(`Tentativa ${t} falhou: ${e.message}`);
      if (t < MAX_RETRIES) await page.waitForTimeout(RETRY_DELAY * t);
    }
  }
  return { url };
}

module.exports = { extrairChaveMao, limparValor, normalizarMonetario };
