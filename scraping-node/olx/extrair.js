// Espelha extrair_dados_olx_playwright_async.py: _parse_html_anuncio (fetch) + fallback Playwright.
const { info, warning, error } = require('../chave-mao/log');

const MAX_RETRIES = 3;
const RETRY_DELAY = 2000;
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36';

const dec = (s) => String(s || '').replace(/&quot;/g, '"').replace(/&amp;/g, '&').replace(/&#39;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>');

// Fetch com charset real (corrige mojibake tipo 'C�digo', 'Padr�o' quando a OLX
// serve latin1 sem charset no content-type e text() decodifica como UTF-8).
async function fetchHtml(url, timeoutMs = 35000) {
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { headers: { 'User-Agent': UA }, signal: ctrl.signal });
    if (resp.status !== 200) return { status: resp.status, html: null };
    const buf = Buffer.from(await resp.arrayBuffer());
    const meta = buf.toString('latin1').match(/<meta[^>]*charset=["']?([^"'\s>]+)/i);
    const hint = `${meta ? meta[1] : ''} ${resp.headers.get('content-type') || ''}`;
    const label = /iso-8859|latin1/i.test(hint) ? 'latin1' : 'utf-8';
    return { status: 200, html: new TextDecoder(label).decode(buf) };
  } finally {
    clearTimeout(to);
  }
}

function attrValue(html, name) {
  const m = html.match(new RegExp('"name"\\s*:\\s*"' + name + '"[^}]*?"value"\\s*:\\s*"([^"]+)"'))
    || html.match(new RegExp('"name"\\s*:\\s*"' + name + '"[^}]*?"value"\\s*:\\s*(\\d+)'));
  return m ? m[1] : null;
}

// Tenta vários nomes de atributo (a OLX renomeia chaves; primeiro acerto vence).
// Lista exata sai do diag-olx.js; estes alternativos são defensivos e não quebram o atual.
function attrValueAny(html, names) {
  for (const n of names) {
    const v = attrValue(html, n);
    if (v) return v;
  }
  return null;
}

// Formato alternativo: {"label":"Dormitórios",...,"value":"2"} (aspas opcionais no value).
function labelValue(html, labels) {
  for (const lab of labels) {
    const m = html.match(new RegExp('"label"\\s*:\\s*"' + lab + '"[^}]*?"value"\\s*:\\s*"([^"]+)"'))
      || html.match(new RegExp('"label"\\s*:\\s*"' + lab + '"[^}]*?"value"\\s*:\\s*(\\d+)'));
    if (m) return m[1];
  }
  return null;
}

function soDig(s) {
  if (s == null) return null;
  const d = String(s).replace(/\D/g, '');
  return d ? parseInt(d, 10) : null;
}

// Primeiro número isolado do texto (não amontoa dígitos).
// Ex: "2 quartos, 2 salas, 1 banheiro" → 2 (soDig daria 221).
function primeiroNum(s) {
  if (s == null) return null;
  const m = String(s).match(/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

// Trava de sanidade para contagens (quartos/banheiros/vagas).
// Rejeita digitões colados de CEP/telefone/metragem vindos de container grande.
function sanearQtd(n, max = 20) {
  return Number.isFinite(n) && n >= 0 && n <= max ? n : null;
}

function numQuebrado(s) {
  if (s == null) return null;
  try {
    const v = parseFloat(String(s).replace(/[^0-9.,]/g, '').replace(/\./g, '').replace(',', '.'));
    return Number.isFinite(v) ? parseInt(v, 10) : null;
  } catch { return null; }
}

function parseHtmlAnuncio(url, raw) {
  // Next.js Flight/__NEXT_DATA__ escapa aspas como \" ou \u0022:
  // nenhum regex de "price" casa sem normalizar antes.
  const html = dec(raw).replace(/\\"/g, '"').replace(/\\u0022/gi, '"');
  // Valor em cascata: dataLayer "price" → og:price:amount → adPrice → offers.price (JSON-LD).
  let valor = null;
  const m = html.match(/"price"\s*:\s*"([\d.]+)"/) || html.match(/"price"\s*:\s*(\d+)/)
    || html.match(/property="og:price:amount"\s+content="([^"]+)"/)
    || html.match(/"adPrice"\s*:\s*"?([\d.]+)"?/)
    || html.match(/"offers"\s*:\s*\{[^}]*?"price"\s*:?\s*"?([\d.]+)"?/s)
    || html.match(/data-testid="ad-price-container"[^>]*>.*?R\$\s*([\d.,]+)/s);
  if (m) {
    const n = parseInt(String(m[1]).replace(/[^\d]/g, ''), 10);
    if (Number.isFinite(n)) valor = n;
  }
  // Último recurso: primeiro "R$ X" do HTML (padrão que o Chaves usa).
  // Trava: só aceita >= R$ 20 mil (venda) para não gravar condomínio/IPTU como preço.
  // Tolera &nbsp;, NBSP e comentários React entre o cifrão e o número.
  if (valor == null) {
    const mr = html.match(/R\$\s*(?:&nbsp;|<!--.*?-->)*([\d.,]+)/);
    if (mr) {
      const n = parseInt(String(mr[1]).replace(/[^\d]/g, ''), 10);
      if (Number.isFinite(n) && n >= 20000) valor = n;
    }
  }
  const metragem_raw = attrValueAny(html, ['size', 'area', 'area_util', 'useful_area', 'living_area']);
  let titulo = (html.match(/property="og:title" content="([^"]+)"/) || [])[1];
  if (titulo) titulo = dec(titulo).trim();
  if (!titulo) {
    const h1 = html.match(/<h1[^>]*>(.*?)<\/h1>/s);
    if (h1) titulo = dec(h1[1]).replace(/<[^>]+>/g, '').trim() || null;
  }
  let descricao = (html.match(/property="og:description" content="([^"]*)"/) || [])[1];
  if (descricao) descricao = dec(descricao).replace(/\s+/g, ' ').trim() || null;
  let data_criacao = null;
  const ma = html.match(/"adDate"\s*:\s*(\d+)/);
  if (ma) {
    try { data_criacao = new Date(parseInt(ma[1], 10) * 1000).toISOString().slice(0, 19).replace('T', ' '); } catch { /* mantém null */ }
  }
  // Fotos: qualquer host OLX com extensão de imagem (o host img.olx.com.br/images/ mudou).
  const fotos = [...new Set(
    [...html.matchAll(/https:\/\/[a-z0-9.-]*olx[a-z0-9.-]*\/[^"'\s\\()]+?\.(?:jpg|jpeg|png|webp)[^"'\s\\()]*/gi)]
      .map((x) => x[0].replace(/\\u0026/g, '&'))
  )];
  const bairro = (html.match(/"label"\s*:\s*"Bairro"\s*,\s*"value"\s*:\s*"([^"]+)"/) || [])[1];
  const municipio = (html.match(/"label"\s*:\s*"Munic[uí]pio"\s*,\s*"value"\s*:\s*"([^"]+)"/) || [])[1];
  const uf = (html.match(/"addressRegion"\s*:\s*"([^"]+)"/) || [])[1];
  const endereco = [bairro && dec(bairro), municipio && dec(municipio), uf].filter(Boolean).join(', ') || null;
  const feat = (...names) => {
    for (const name of names) {
      const mm = html.match(new RegExp('"name"\\s*:\\s*"' + name + '".*?"values"\\s*:\\s*\\[(.*?)\\]', 's'));
      if (mm) {
        const labs = [...mm[1].matchAll(/"label"\s*:\s*"([^"]+)"/g)].map((x) => dec(x[1]).trim()).filter(Boolean);
        if (labs.length) return labs;
      }
      const v = attrValue(html, name);
      if (v) {
        const items = v.split(',').map((s) => dec(s).trim()).filter(Boolean);
        if (items.length) return items;
      }
    }
    return [];
  };
  const dados = {
    url,
    titulo: titulo || null,
    valor_imovel: valor,
    metragem: numQuebrado(metragem_raw),
    quartos: sanearQtd(primeiroNum(attrValueAny(html, ['rooms', 'bedrooms', 'dorms', 'quartos', 'dormitorios'])))
      ?? sanearQtd(primeiroNum(labelValue(html, ['Dormitórios', 'Dormitorios', 'Quartos']))),
    banheiros: sanearQtd(primeiroNum(attrValueAny(html, ['bathrooms', 'banheiros']))),
    vagas: sanearQtd(primeiroNum(attrValueAny(html, ['garage_spaces', 'garage', 'vagas', 'parking_spaces']))),
    condominio: numQuebrado(attrValueAny(html, ['condominio', 'condominium', 'condo', 'condo_fee', 'condominio_value']))
      ?? numQuebrado(labelValue(html, ['Condomínio', 'Condominio', 'Taxa de condomínio'])),
    iptu: numQuebrado(attrValueAny(html, ['iptu', 'iptu_value']))
      ?? numQuebrado(labelValue(html, ['IPTU'])),
    endereco,
    descricao: descricao || null,
    data_criacao,
    fotos,
    caracteristicas: [],
    caracteristicas_privativa: feat('re_features', 're_characteristics', 'features', 'characteristics'),
    caracteristicas_comum: feat('re_complex_features', 'complex_features', 'condo_features', 'common_features'),
  };
  if (dados.valor_imovel == null && !dados.titulo) return null;
  return dados;
}

async function texto(page, sel, timeout = 2500) {
  try {
    const t = await page.locator(sel).first().innerText({ timeout });
    return (t || '').trim() || null;
  } catch { return null; }
}

// Espelho fiel de _get_quartos do Python: div:has(> span "Quartos") → ÚLTIMO span/a
// em ordem de documento (.last), com espera attached + retry de conteúdo.
// ATENÇÃO: .last() (método) ≠ span:last-child (pseudo-classe CSS) — o port antigo
// usava :last-child e casava outro conjunto de elementos (nulos ou lixo de CEP).
async function textoQuartos(page, timeout = 2500) {
  try {
    const el = page.locator('div:has(> span:has-text("Quartos"))').locator('span, a').last();
    await el.waitFor({ state: 'attached', timeout });
    for (let i = 0; i < 2; i++) {
      const t = ((await el.innerText().catch(() => '')) || '').trim();
      if (t) return t;
      await page.waitForTimeout(150);
    }
    return null;
  } catch { return null; }
}

// Espelho fiel de _get_text do Python aplicado ao par do Python em
// _extrair_dados_da_pagina: xpath=//span[normalize-space(text())='Rótulo']/
// following-sibling::div//span[last()]. Sem fallbacks nem parse — o Python grava
// o texto cru (ex: "R$ 750") e a limpeza (limpar_valor_condominio/iptu) faz o parse.
async function textoCondominio(page, rotulo) {
  try {
    const el = page.locator(`xpath=//span[normalize-space(text())='${rotulo}']/following-sibling::div//span[last()]`).first();
    await el.waitFor({ state: 'visible', timeout: 2500 });
    for (let i = 0; i < 2; i++) {
      const t = ((await el.innerText().catch(() => '')) || '').trim();
      if (t) return t;
      await page.waitForTimeout(150);
    }
    return null;
  } catch { return null; }
}

async function extrairPlaywright(page, url) {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 35000 });
  // Espera a hidratação do preço (React renderiza tarde); scroll ajuda o lazy-load.
  await page.waitForFunction(
    () => document.body && document.body.innerText && document.body.innerText.includes('R$'),
    { timeout: 15000 }
  ).catch(() => {});
  await page.evaluate('window.scrollTo(0, document.body.scrollHeight)').catch(() => {});
  await page.waitForTimeout(1500);
  const metragem_raw = await texto(page, 'span:has-text("Área útil") + span')
    || await texto(page, 'span:has-text("Tamanho") + span');
  const titulo = await texto(page, 'span[data-side-margin="false"]');
  const descricao = await texto(page, 'span.typo-body-medium[style*="word-break: break-word"]');
  const bairro = await texto(page, '#location span.typo-body-medium');
  const cidade = await texto(page, '#location span.typo-body-small.text-neutral-110');
  // Preço em cascata: testid estável (padrão DS da OLX) → h3 com R$ → classes legadas.
  let valor = soDig(await texto(page, 'div[data-testid="ad-price-container"] h3'))
    || soDig(await texto(page, 'h3:has-text("R$")'))
    || soDig(await texto(page, 'span.typo-title-large:has-text("R$")'))
    || soDig(await texto(page, 'div.ad__sc-q5xder-1 span.typo-title-large'))
    || soDig(await texto(page, 'div.ad__sc-q5xder-1 span:has-text("R$")'));
  if (valor == null) {
    // Último recurso: primeiro R$ do texto renderizado, trava >= 20000 (venda).
    try {
      const body = await page.locator('body').innerText();
      const mb = body.match(/R\$\s*([\d.,]+)/);
      if (mb) {
        const n = parseInt(String(mb[1]).replace(/[^\d]/g, ''), 10);
        if (Number.isFinite(n) && n >= 20000) valor = n;
      }
    } catch { /* mantém null */ }
  }
  const fotos = await page.locator('#item-gallery-image picture img').evaluateAll(
    (els) => els.map((el) => el.src)
  ).catch(() => []);
  // Fallback: carrossel do Design System (mesmo padrão dos extratores Zap/VivaReal).
  const fotosFinais = fotos.length ? fotos : await page.locator('[data-testid="carousel-photos"] picture img').evaluateAll(
    (els) => els.map((el) => el.src || el.dataset.src)
  ).catch(() => []);
  // Contagens: primeiro número do texto + trava 0–20 (container grande amontoa
  // dígitos de CEP/telefone/metragem — ex: "2 quartos, 2 salas" → 2, não 221).
  // Quartos começa pelo espelho fiel do Python (.last em ordem de documento).
  let quartos = sanearQtd(primeiroNum(await textoQuartos(page)));
  if (quartos == null) {
    for (const sel of ["span:has-text('Dormitórios') + span", "span:has-text('Dormitorios') + span",
        "span:has-text('Quartos') + span"]) {
      quartos = sanearQtd(primeiroNum(await texto(page, sel)));
      if (quartos != null) break;
    }
  }
  const banheiros = sanearQtd(primeiroNum(await texto(page, "span:has-text('Banheiros') + span")));
  const vagas = sanearQtd(primeiroNum(await texto(page, "span:has-text('Vagas na garagem') + span")));
  return {
    url,
    titulo,
    valor_imovel: valor,
    metragem: soDig(metragem_raw),
    quartos,
    banheiros,
    vagas,
    condominio: await textoCondominio(page, 'Condomínio'),
    iptu: await textoCondominio(page, 'IPTU'),
    endereco: bairro && cidade ? `${bairro}, ${cidade}` : (bairro || cidade),
    descricao,
    data_criacao: await texto(page, 'span.typo-caption.text-neutral-100.font-semibold'),
    fotos: fotosFinais,
    caracteristicas: [],
    caracteristicas_privativa: [],
    caracteristicas_comum: [],
  };
}

async function extrairOlx(page, url) {
  for (let t = 1; t <= MAX_RETRIES; t++) {
    try {
      info(`Tentativa ${t}/${MAX_RETRIES} — ${url}`);
      try {
        const { status, html } = await fetchHtml(url);
        if (status === 200 && html) {
          const dados = parseHtmlAnuncio(url, html);
          if (dados) { info('Anúncio extraído via fetch'); return dados; }
        } else {
          warning(`fetch detalhe status ${status} para ${url}`);
        }
      } catch (e) { warning(`fetch detalhe falhou: ${e.message}`); }
      const dados = await extrairPlaywright(page, url);
      if (dados.valor_imovel != null || dados.titulo) { info('Dados extraídos via Playwright'); return dados; }
      throw new Error('página sem conteúdo (shell)');
    } catch (e) {
      warning(`Tentativa ${t} falhou: ${e.message}`);
      if (t < MAX_RETRIES) await page.waitForTimeout(RETRY_DELAY * t).catch(() => {});
    }
  }
  error(`Falha total: ${url}`);
  return { url };
}

module.exports = { extrairOlx, parseHtmlAnuncio, fetchHtml, attrValueAny, textoQuartos, textoCondominio };
