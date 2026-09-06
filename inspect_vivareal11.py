import asyncio
import re
from playwright.async_api import async_playwright

URL = "https://www.vivareal.com.br/imovel/casa-2-quartos-jarivatuba-bairros-joinville-com-garagem-60m2-venda-RS349636-id-2879650023/"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(5000)
        
        html = await page.content()
        
        # 1. Get the _R_ script
        r_el = page.locator("script[id='_R_']").first
        count = await r_el.count()
        if count > 0:
            r_content = await r_el.inner_text()
            print(f"_R_ script length: {len(r_content)}")
            
            # Search for listing data
            for kw in ['amenities', 'Amenity', 'privative', 'common', 'Elevador', 'ELEVATOR', 'listing', '2879650023', 'LDP']:
                if kw in r_content:
                    pos = r_content.find(kw)
                    snippet = r_content[max(0,pos-200):pos+500]
                    print(f"\nFound '{kw}' in _R_ at pos {pos}:")
                    print(snippet[:500])
        
        # 2. Search HTML for any JSON data
        print("\n=== SEARCHING HTML FOR AMENITY DATA ===")
        for kw in ['"amenities"', '"Amenity"', '"privative"', '"common"', '"features"', '"characteristics"']:
            if kw in html:
                pos = html.find(kw)
                snippet = html[max(0,pos-200):pos+500]
                print(f"\nFound '{kw}' at pos {pos}:")
                print(snippet[:500])
        
        # 3. Search for any JSON-like structures
        print("\n=== JSON PATTERNS ===")
        patterns = [
            r'"amenities":\s*\[[^\]]{0,300}\]',
            r'"privativeItems":\s*\[[^\]]{0,300}\]',
            r'"commonItems":\s*\[[^\]]{0,300}\]',
            r'"features":\s*\[[^\]]{0,300}\]',
            r'"characteristics":\s*\[[^\]]{0,300}\]',
        ]
        for pat in patterns:
            matches = list(re.finditer(pat, html, re.S))
            if matches:
                for m in matches[:3]:
                    print(f"  Found: {html[m.start():m.end()+100][:300]}")
        
        # 4. Check for the Next.js page data in self.__next_f
        print("\n=== CHECKING self.__next_f ===")
        next_f_data = await page.evaluate("""() => {
            const f = window.__next_f || [];
            const result = [];
            for (let i = 0; i < f.length; i++) {
                const item = f[i];
                if (typeof item === 'string') {
                    result.push(item.substring(0, 300));
                } else if (typeof item === 'object') {
                    try { result.push(JSON.stringify(item).substring(0, 300)); } catch(e) {}
                }
            }
            return result;
        }""")
        for i, item in enumerate(next_f_data[:20]):
            print(f"  [{i}] {item[:200]}")
        
        # 5. Check for the Next.js data in the document
        print("\n=== DOCUMENT DATA ===")
        doc_data = await page.evaluate("""() => {
            // Check for any data attributes on the body or root element
            const body = document.body;
            const dataset = body.dataset;
            return Object.fromEntries(Object.entries(dataset));
        }""")
        print(f"Body dataset: {doc_data}")
        
        # 6. Look for the actual property listing page data
        # The page might have the data in a Next.js chunk
        print("\n=== LOOKING FOR LISTING DATA IN CHUNKS ===")
        chunk_urls = re.findall(r'https://cdn-ldp-vivareal-ssr-prod\.vivareal\.com\.br/_next/static/chunks/([^"]+\.js)', html)
        
        # Try to fetch one of the chunks that might have the listing page
        # The 08eemc4b36lkd.js chunk was mentioned in the __next_f data
        for chunk_name in ['08eemc4b36lkd.js', '05gw701h0m5m-.js']:
            if chunk_name in html:
                print(f"  Found chunk: {chunk_name}")
                # Try to extract the chunk content
                chunk_pattern = f'https://cdn-ldp-vivareal-ssr-prod\\.vivareal\\.com\\.br/_next/static/chunks/{re.escape(chunk_name)}'
                matches = re.findall(chunk_pattern, html)
                if matches:
                    print(f"  Chunk URL found in HTML")
        
        # 7. Try to fetch the Next.js chunk that contains the listing page
        print("\n=== FETCHING NEXT.JS CHUNK ===")
        try:
            chunk_data = await page.evaluate("""async () => {
                try {
                    const res = await fetch('https://cdn-ldp-vivareal-ssr-prod.vivareal.com.br/_next/static/chunks/08eemc4b36lkd.js', {
                        headers: { 'Accept': '*/*' }
                    });
                    const text = await res.text();
                    return text.substring(0, 3000);
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }""")
            if chunk_data and 'Error' not in chunk_data:
                # Search for amenities in the chunk
                for kw in ['amenities', 'Amenity', 'privative', 'common', 'Elevador', 'ELEVATOR']:
                    if kw in chunk_data:
                        pos = chunk_data.find(kw)
                        snippet = chunk_data[max(0,pos-200):pos+500]
                        print(f"\nFound '{kw}' in chunk:")
                        print(snippet[:500])
            else:
                print(f"  Chunk fetch error or empty: {chunk_data[:100]}")
        except Exception as e:
            print(f"  Chunk fetch error: {e}")
        
        await browser.close()

asyncio.run(main())
