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
        
        # Get the _R_ script content
        print("=== _R_ SCRIPT CONTENT ===")
        r_script = await page.locator("script[id='_R_']").first
        if (await r_script.count()) > 0:
            content = await r_script.inner_text()
            # Look for listing data in the _R_ script
            for kw in ['amenities', 'Amenity', 'privative', 'common', 'Elevador', 'ELEVATOR', 'listing', '2879650023']:
                if kw in content:
                    pos = content.find(kw)
                    snippet = content[max(0,pos-200):pos+500]
                    print(f"\nFound '{kw}' at pos {pos}:")
                    print(snippet[:500])
        
        # Look for the Next.js runtime data in self.__next_f
        print("\n=== self.__next_f DATA ===")
        next_f_data = await page.evaluate("""() => {
            // The __next_f array contains the Next.js page data
            const f = window.__next_f || [];
            const result = [];
            for (let i = 0; i < f.length; i++) {
                const item = f[i];
                if (typeof item === 'string') {
                    result.push(item.substring(0, 200));
                } else if (typeof item === 'object') {
                    result.push(JSON.stringify(item).substring(0, 200));
                }
            }
            return result;
        }""")
        for i, item in enumerate(next_f_data[:20]):
            print(f"  [{i}] {item[:200]}")
        
        # Look for the actual page data in the Next.js runtime
        print("\n=== NEXT.JS PAGE RUNTIME DATA ===")
        page_runtime = await page.evaluate("""() => {
            // Look for any object containing listing data
            const scripts = Array.from(document.querySelectorAll('script'));
            for (const s of scripts) {
                const text = s.textContent || s.innerText;
                if (text.includes('window.__next_f')) {
                    // Extract the data from __next_f
                    const match = text.match(/__next_f\.push\(\[1,(\{[^}]+)\}\]/);
                    if (match) {
                        return match[1];
                    }
                }
            }
            return 'not found';
        }""")
        if page_runtime != 'not found':
            print(f"Page runtime: {page_runtime[:1000]}")
        
        # Look for the specific listing data in the HTML
        print("\n=== LOOKING FOR LDP DATA IN HTML ===")
        html = await page.content()
        
        # Search for the listing data in the HTML
        # Look for the Next.js page data structure
        for pattern in [
            r'"listing":\{[^}]{0,500}',
            r'"property":\{[^}]{0,500}',
            r'"amenity":[^,]{0,200}',
            r'"features":[^,]{0,200}',
            r'"characteristics":[^,]{0,200}',
            r'"amenities":\[[^\]]{0,300}\]',
        ]:
            matches = list(re.finditer(pattern, html, re.S))
            if matches:
                for m in matches[:3]:
                    print(f"  Pattern '{pattern[:50]}': {html[m.start():m.end()+100][:300]}")
        
        r_content = ""
        r_el = page.locator("script[id='_R_']").first
        if (await r_el.count()) > 0:
            r_content = await r_el.inner_text()
        print(f"\n_R_ script length: {len(r_content)}")
        
        # Look for listing-related data in the _R_ script
        for kw in ['amenities', 'Amenity', 'privative', 'common', 'Elevador', 'ELEVATOR', 'listing', '2879650023', 'LDP']:
            if kw in r_content:
                pos = r_content.find(kw)
                snippet = r_content[max(0,pos-200):pos+500]
                print(f"\nFound '{kw}' in _R_ at pos {pos}:")
                print(snippet[:500])
        
        # Check for the Next.js page data in the entire HTML
        print("\n=== LOOKING FOR LISTING DATA IN FULL HTML ===")
        for kw in ['"amenities"', '"Amenity"', '"privative"', '"common"', '"features"']:
            if kw in html:
                pos = html.find(kw)
                snippet = html[max(0,pos-200):pos+500]
                print(f"\nFound '{kw}' at pos {pos}:")
                print(snippet[:500])
        
        await browser.close()

asyncio.run(main())
