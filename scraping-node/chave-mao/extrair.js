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
    const t = await page.locator(seletor).first().innerText({ timeout });
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

async function extrairCaracteristicas(page, descricao = '', url = '') {
  let priv = [], comum = [];
  const decodifica = (s) => s.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) => String.fromCharCode(parseInt(h, 16)));
  try {
    const html = await page.content();
    // Estrito (aspas literais, igual Python): payloads Flight escapados de
    // imóveis vizinhos NÃO casam — evita atribuir amenities alheias ao anúncio.
    const mp = html.match(/"privativeItems"\s*:\s*\[(.*?)\]/s);
    if (mp) priv = [...mp[1].matchAll(/"name"\s*:\s*"([^"]+)"/g)].map((m) => decodifica(m[1]));
    const mc = html.match(/"commonItems"\s*:\s*\[(.*?)\]/s);
    if (mc) comum = [...mc[1].matchAll(/"name"\s*:\s*"([^"]+)"/g)].map((m) => decodifica(m[1]));
    if (priv.length || comum.length) console.log(`caracteristicas: fonte=regex priv=${priv.length} comum=${comum.length}`);
  } catch { /* segue para fallback */ }
  if (!priv.length && !comum.length) {
    try {
      // Scroll: seção pode hidratar sob lazy-load. DOM renderizado é sempre
      // do próprio anúncio (sem risco de atribuição errada).
      await page.evaluate('window.scrollTo(0, document.body.scrollHeight)');
      await page.waitForTimeout(2000);
      if (await page.locator('div.style_optionalItemsContainer__7e5rw').count() > 0) {
        const spans = await page.locator('div.style_optionalItemsContainer__7e5rw span').all();
        for (const sp of spans) {
          // 1 evaluate por span: título (textContent, imune a falta de render)
          // + itens (textContent, imune a lazy) de uma vez — atômico e rápido
          const [titulo, itens] = await sp.evaluate((el) => {
            const bTexts = [...el.querySelectorAll('b')]
              .map((b) => (b.textContent || '').trim().toLowerCase())
              .filter(Boolean);
            const t = bTexts.length ? bTexts[0]
              : ((el.querySelector('p') || {}).textContent || '').trim().toLowerCase().slice(0, 60);
            const ps = [...el.querySelectorAll('ul li p.styles_text-body-sm-medium__FWa10')]
              .map((x) => (x.textContent || '').trim())
              .filter(Boolean);
            return [t, ps];
          }).catch(() => ['', []]);
          if (titulo.includes('privativa')) priv = itens;
          else if (titulo.includes('comum')) comum = itens;
        }
        if (priv.length || comum.length) console.log(`caracteristicas: fonte=dom priv=${priv.length} comum=${comum.length}`);
      }
    } catch { /* mantém o que já tem */ }
  }
  if (!priv.length && !comum.length) {
    const [p2, c2] = extrairCaracteristicasDescricao(descricao, url);
    if (p2.length || c2.length) console.log(`caracteristicas: fonte=prosa priv=${p2.length} comum=${c2.length}`);
    priv.push(...p2); comum.push(...c2);
  }
  if (!priv.length && !comum.length) console.log('caracteristicas: fonte=vazio priv=0 comum=0');
  return [priv.map((s) => s.trim()).filter(Boolean), comum.map((s) => s.trim()).filter(Boolean)];
}

// Termos espelham pipeline extrair_amenidades (substring match, igual check_arr).
// Mineração restrita à seção de características: fora dela há falsos positivos
// ("próximo a academia" em Localização não é amenity do imóvel).
const PROSE_PRIV = ['churrasqueira', 'varanda', 'closet', 'piscina'];
const PROSE_COMUM = ['elevador', 'salao', 'salão', 'playground', 'academia',
  'fitness', 'spa', 'sauna', 'piscina', 'churrasqueira'];
const PROSE_AMBIG = ['piscina', 'churrasqueira', 'sauna'];
const PROSE_HEADERS = /caracter[ií]sticas|diferenciais|detalhes(\s+do\s+im[óo]vel)?|sobre o im[óo]vel/i;
const PROSE_STOP = /^([aá]rea externa|localiza|condi[çc]|valores|observa|agende|entre em contato|ref\.|atualizado)/im;

function extrairCaracteristicasDescricao(descricao, url) {
  const priv = [], comum = [];
  if (!descricao) return [priv, comum];
  const texto = String(descricao);
  const h = texto.search(PROSE_HEADERS);
  if (h < 0) return [priv, comum]; // sem seção → não inventa
  let secao = texto.slice(h);
  const stop = secao.slice(50).search(PROSE_STOP);
  if (stop > 0) secao = secao.slice(0, 50 + stop);
  const low = secao.toLowerCase();
  const ehCasa = /casa-a-venda/.test(url || '');
  const ehApto = /apartamento-a-venda/.test(url || '');
  // Word-boundary (+ plural opcional): evita 'spa' casar dentro de 'espaços'
  const esc = (t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const tem = (t) => new RegExp(`\\b${esc(t)}s?\\b`).test(low);
  // suites: "sendo 4 suítes" → formato que o pipeline já parseia
  const ms = low.match(/(\d+)\s*su[ií]tes?\b/);
  if (ms) priv.push(`${parseInt(ms[1], 10)} suíte${parseInt(ms[1], 10) > 1 ? 's' : ''}`);
  for (const t of PROSE_PRIV) {
    if (PROSE_AMBIG.includes(t)) continue;
    if (tem(t) && !priv.includes(t)) priv.push(t);
  }
  for (const t of PROSE_COMUM) {
    if (PROSE_AMBIG.includes(t)) continue;
    if (tem(t) && !comum.includes(t)) comum.push(t);
  }
  for (const t of PROSE_AMBIG) {
    if (!tem(t)) continue;
    const lado = ehCasa ? priv : ehApto ? comum : priv;
    if (!lado.includes(t)) lado.push(t);
  }
  return [priv, comum];
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
    return await page.locator('iframe[src*="maps"]').first().getAttribute('src', { timeout: 5000 });
  } catch { return null; }
}

// Fallbacks aditivos (só rodam se o primário falhar; nada do que funciona é tocado)

// Fallback titulo: h1 genérico (só existe 1 por página) → <title> sem sufixo
async function extrairTitulo(page) {
  const t1 = await texto(page, 'h1.styles_typography__xG9rg');
  if (t1) return t1;
  try {
    const h1s = await page.locator('h1').allInnerTexts();
    const bom = h1s.map((s) => (s || '').trim()).find((s) => s.length > 10);
    if (bom) return bom;
  } catch { /* segue */ }
  try {
    const t = await page.title();
    const limpo = (t || '').split('|')[0].trim();
    if (limpo.length > 10) return limpo;
  } catch { /* segue */ }
  return null;
}

// Fallback autoritativo por anúncio: ld+json do próprio documento (sem risco de vizinho)
async function extrairNumeroLdJson(page, campo) {
  try {
    const scripts = await page.locator('script[type="application/ld+json"]').allInnerTexts();
    for (const s of scripts) {
      const m = s.match(new RegExp('"' + campo + '"\\s*:\\s*(\\d+)'));
      if (m) return m[1];
    }
  } catch { /* segue */ }
  return null;
}

// Fallback endereco: primeiro h2 com pinta de endereço (vírgula/barra, tamanho limitado).
// Rejeita agência ("A6 imóveis", sem pontuação) e cards vizinhos ("Preços de...", longo).
async function extrairEnderecoGenerico(page) {
  try {
    const textos = await page.locator('h2').allInnerTexts();
    for (const raw of textos) {
      const s = (raw || '').replace(/\s+/g, ' ').trim();
      if (s.length > 10 && s.length < 150 && (s.includes(',') || s.includes('/'))) return s;
    }
  } catch { /* segue */ }
  return null;
}

// Fallback vagas: specs do anúncio (li > small["Garagens:"] + b[valor]).
// Escopo preferencial na lista de specs; global como fallback.
// Vizinhos usam outra estrutura (p[aria-label], sem small+b) → sem poluição.
async function specGaragens(page) {
  const buscar = async (lis) => {
    for (const li of lis) {
      try {
        const lab = ((await li.locator('small').first().innerText().catch(() => '')) || '')
          .replace(':', '').trim().toLowerCase();
        if (lab.startsWith('garagen')) {
          const v = ((await li.locator('b').first().innerText().catch(() => '')) || '').trim();
          if (v) return v;
        }
      } catch { /* próxima */ }
    }
    return null;
  };
  try {
    const escopo = await page.locator('ul[class*="style_listContent"] li').all();
    if (escopo.length) return await buscar(escopo);
  } catch { /* cai para global */ }
  try {
    return await buscar(await page.locator('ul li').all());
  } catch { /* segue */ }
  return null;
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
      const [metragemTotalRaw, metragemUtilRaw] = await extrairMetragens(page);
      const descricao = await texto(page, 'p[aria-label="descrição"]');
      const [priv, comum] = await extrairCaracteristicas(page, descricao, url);
      const titulo = await extrairTitulo(page);
      let quartos = await texto(page, "b:has(svg path[d^='M112.867 767.316'])");
      if (!quartos) quartos = await texto(page, "p[aria-label='Quartos' i]");
      if (!quartos) quartos = await extrairNumeroLdJson(page, 'numberOfBedrooms');
      let banheirosRaw = await texto(page, 'p[aria-label="Banheiros"] b');
      if (!banheirosRaw) banheirosRaw = await extrairNumeroLdJson(page, 'numberOfBathroomsTotal');
      const banheiros = limparValor(banheirosRaw);
      let endereco = await texto(page, 'h2[class*="styles_text-title-lg"].column, h2[class*="styles_text-title-lg"] b');
      if (!endereco) endereco = await extrairEnderecoGenerico(page);
      let vagas = await texto(page, "p[aria-label='Garagens'] b");
      if (!vagas) vagas = await texto(page, "p[aria-label='Garagens' i] b");
      if (!vagas) vagas = await texto(page, "p[aria-label='Garagens' i]");
      if (!vagas) vagas = await specGaragens(page);
      // Saneamento: 0/1 m² não existem (default do site p/ ausente); vira null → limpeza trata
      const sanear = (v) => {
        if (!v) return null;
        const n = parseFloat(String(v).replace(/[^\d.,]/g, '').replace(',', '.'));
        return (Number.isFinite(n) && n > 1) ? v : null;
      };
      const metragemTotal = sanear(metragemTotalRaw);
      const metragemUtil = sanear(metragemUtilRaw);
      return {
        url,
        titulo,
        metragem: metragemUtil || metragemTotal,
        metragem_total: metragemTotal,
        metragem_util: metragemUtil,
        valor_imovel: await extrairValor(page),
        quartos,
        banheiros,
        vagas,
        endereco,
        descricao,
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
