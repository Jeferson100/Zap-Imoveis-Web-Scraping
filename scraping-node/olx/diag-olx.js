// Diagnóstico: despeja chaves reais do HTML atual da OLX.
// A OLX retorna 403 para fetch de datacenter, então este script deve rodar
// na máquina local (IP residencial).
// Uso: node scraping-node/olx/diag-olx.js "https://sc.olx.com.br/...-1538145188"
const { launchChromium, newContext } = require('../chave-mao/browser');
const { info } = require('../chave-mao/log');

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';

async function main() {
  const url = process.argv[2];
  if (!url) { console.error('Uso: node diag-olx.js <url-anuncio>'); process.exit(1); }

  // 1. Fetch: charset + status + tamanho
  const resp = await fetch(url, { headers: { 'User-Agent': UA, Accept: 'text/html' } });
  const buf = Buffer.from(await resp.arrayBuffer());
  info(`fetch status=${resp.status} content-type=${resp.headers.get('content-type')} bytes=${buf.length}`);
  const meta = buf.toString('latin1').match(/<meta[^>]*charset=["']?([^"'\s>]+)/i);
  info(`meta charset=${meta ? meta[1] : '(ausente)'}`);
  for (const label of ['utf-8', 'latin1']) {
    const html = new TextDecoder(label).decode(buf);
    info(`[${label}] price=${(html.match(/"price"/g) || []).length} rooms=${(html.match(/"rooms"/g) || []).length} re_features=${(html.match(/re_features/g) || []).length} img.olx=${(html.match(/img\.olx\.com\.br/g) || []).length} adDate=${(html.match(/adDate/g) || []).length}`);
  }
  const html = new TextDecoder('utf-8').decode(buf);

  // 2. Todas as chaves "name":"..." (atributos estruturados)
  const names = [...new Set([...html.matchAll(/"name"\s*:\s*"([a-zA-Z_]+)"/g)].map((m) => m[1]))].sort();
  info(`ATTR NAMES (${names.length}): ${names.join(', ')}`);

  // 3. Chaves tipo price (candidatas a valor)
  const prices = [...new Set([...html.matchAll(/"([a-zA-Z]*[Pp]rice[a-zA-Z]*)"\s*:/g)].map((m) => m[1]))].sort();
  info(`PRICE KEYS: ${prices.join(', ') || '(nenhuma)'}`);
  const mOffer = html.match(/"offers"\s*:\s*\{[^}]{0,300}/);
  info(`offers snippet: ${mOffer ? mOffer[0].slice(0, 200) : '(ausente)'}`);
  const mOgPrice = html.match(/property="og:price:amount"\s+content="([^"]+)"/);
  info(`og:price:amount: ${mOgPrice ? mOgPrice[1] : '(ausente)'}`);

  // 4. Hosts de imagem (candidatos a fotos)
  const imgHosts = [...new Set([...html.matchAll(/https:\/\/([a-z0-9.-]*olx[a-z0-9.-]*)\//gi)].map((m) => m[1]))].sort();
  info(`IMG HOSTS: ${imgHosts.join(', ') || '(nenhum olx)'}`);

  // 5. Chaves *feature*
  const feats = [...new Set([...html.matchAll(/"([a-zA-Z_]*features?[a-zA-Z_]*)"/g)].map((m) => m[1]))].sort();
  info(`FEATURE KEYS: ${feats.join(', ') || '(nenhuma)'}`);

  // 6. Playwright: seletores de preço ainda existem?
  const browser = await launchChromium(true);
  try {
    const ctx = await newContext(browser);
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 35000 });
    await page.waitForFunction(
      () => document.body && document.body.innerText && document.body.innerText.includes('R$'),
      { timeout: 15000 }
    ).catch(() => {});
    await page.evaluate('window.scrollTo(0, document.body.scrollHeight)').catch(() => {});
    await page.waitForTimeout(1500);
    for (const sel of ['div.ad__sc-q5xder-1 span.typo-title-large', 'span.typo-title-large', 'span:has-text("R$")']) {
      const n = await page.locator(sel).count().catch(() => -1);
      info(`PW sel "${sel}": count=${n}`);
    }

    // 7. Todos os data-testid da página (revela nomes novos de galeria/preço/blocos)
    const testids = await page.evaluate(() =>
      [...new Set([...document.querySelectorAll('[data-testid]')]
        .map((el) => el.getAttribute('data-testid')))].sort()
    ).catch(() => []);
    info(`TESTIDS (${testids.length}): ${testids.join(', ')}`);

    // 8. Contexto do rótulo Condomínio/IPTU (revela a estrutura irmã atual)
    const ctxHtml = await page.evaluate(() => {
      const out = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const txt = (node.nodeValue || '').trim();
        if (/^(Condomínio|IPTU)$/i.test(txt)) {
          let el = node.parentElement;
          for (let i = 0; i < 3 && el && el !== document.body; i++) el = el.parentElement;
          if (el) out.push(el.outerHTML.slice(0, 600));
        }
        if (out.length >= 4) break;
      }
      return out;
    }).catch(() => []);
    ctxHtml.forEach((h, i) => info(`CONDO-CTX[${i}]: ${h.replace(/\s+/g, ' ')}`));
    if (!ctxHtml.length) info('CONDO-CTX: (rótulo Condomínio/IPTU não achado no DOM)');

    // 9. Bloco #details completo (se condo/IPTU migraram p/ lá, aparece aqui)
    const details = await page.locator('#details').innerText().catch(() => '');
    info(`DETAILS: ${(details || '(ausente)').replace(/\s+/g, ' ').slice(0, 600)}`);

    // 10. Imagens com "olx" no src + container pai (revela galeria atual)
    const imgs = await page.evaluate(() =>
      [...document.querySelectorAll('img')].map((img) => img.src || img.dataset.src || '')
        .filter((s) => s.includes('olx')).slice(0, 5)
    ).catch(() => []);
    info(`IMGS-OLX (${imgs.length}): ${imgs.join(' | ') || '(nenhuma)'}`);
  } finally { await browser.close(); }
}

if (require.main === module) {
  main().catch((e) => { console.error(e); process.exit(1); });
}

module.exports = {};
