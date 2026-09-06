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
        
        # 1. Look for self.__next_f.push data
        print("=== SELF.__NEXT_F DATA ===")
        next_f_matches = re.findall(r'self\.__next_f\.push\(\[1,"([^"]+)"', html)
        for i, m in enumerate(next_f_matches[:10]):
            print(f"  [{i}] {m[:200]}")
        
        # 2. Look for the _R_ script content
        print("\n=== _R_ SCRIPT CONTENT ===")
        r_scripts = await page.locator("script[id='_R_']").all()
        for el in r_scripts:
            content = await el.inner_text()
            # Look for listing/property data
            for kw in ['amenities', 'Amenity', 'privative', 'common', 'Elevador', 'ELEVATOR', 'listing', 'LDP']:
                if kw in content:
                    pos = content.find(kw)
                    snippet = content[max(0,pos-200):pos+300]
                    print(f"  Found '{kw}' at pos {pos}: ...{snippet[:300]}...")
        
        # 3. Look for any script with __NEXT_DATA__
        print("\n=== __NEXT_DATA__ SEARCH ===")
        next_data_scripts = await page.locator("script").all()
        for i, el in enumerate(next_data_scripts):
            try:
                content = await el.inner_text()
                if '__NEXT_DATA__' in content or 'nextData' in content or '__PRELOADED_STATE__' in content:
                    print(f"\n  Script [{i}] has NEXT_DATA")
                    print(f"  Content length: {len(content)}")
                    print(f"  First 500 chars: {content[:500]}")
            except:
                pass
        
        # 4. Look for the page data in the HTML - search for the specific property id
        print("\n=== PROPERTY ID IN JSON ===")
        # Look for the listing id in the HTML
        for pattern in ['"id":"2879650023"', '"id":2879650023', '"listingId":"2879650023"', '"listingId":2879650023', '"propertyId":"2879650023"']:
            if pattern in html:
                pos = html.find(pattern)
                snippet = html[max(0,pos-500):pos+500]
                print(f"  Found '{pattern}' at pos {pos}:")
                print(f"    ...{snippet[:500]}...")
        
        # 5. Try to find any data-reactprops or similar
        print("\n=== DATA-REACTPROPS / DATA-ATTRIBUTES ===")
        react_props = re.findall(r'data-(?:react|next|ldp)-[^=]+="[^"]+"', html)
        for rp in sorted(set(react_props))[:20]:
            print(f"  {rp}")
        
        # 6. Look for the LDP (Listing Detail Page) data
        print("\n=== LDP DATA SEARCH ===")
        ldp_matches = re.findall(r'LDP[^"]*', html)
        for m in ldp_matches[:10]:
            pos = html.find(m)
            snippet = html[max(0,pos-100):pos+200]
            print(f"  {m[:100]}: ...{snippet[:200]}...")
        
        # 7. Look for the actual Next.js page chunk that contains listing data
        # Check the chunks that might have the listing page
        print("\n=== NEXT.JS CHUNKS ===")
        chunk_urls = re.findall(r'https://cdn-ldp-vivareal-ssr-prod\.vivareal\.com\.br/_next/static/chunks/([^"]+)', html)
        for c in sorted(set(chunk_urls)):
            print(f"  {c[:100]}")
        
        # 8. Look for the actual JSON data in the page
        # Search for any object with property-related keys
        print("\n=== JSON-ISH DATA ===")
        # Look for patterns like {"listing":... or {"property":... or {"amenity":...
        json_patterns = [
            r'\{"listing[^}]{0,100}',
            r'\{"property[^}]{0,100}',
            r'\{"amenity[^}]{0,100}',
            r'"amenities":\[[^\]]{0,200}\]',
            r'"amenitiesList":\[[^\]]{0,200}\]',
            r'"privativeItems":\[[^\]]{0,200}\]',
            r'"commonItems":\[[^\]]{0,200}\]',
            r'"features":\[[^\]]{0,200}\]',
        ]
        for pat in json_patterns:
            matches = re.findall(pat, html, re.S)
            if matches:
                for m in matches[:3]:
                    print(f"  Pattern '{pat}': {m[:200]}")
        
        # 9. Look for the actual property data by searching for the listing data structure
        print("\n=== LISTING DATA STRUCTURE ===")
        # Search for the listing data in the HTML
        for kw in ['"title"', '"description"', '"address"', '"pricing"', '"amenities"']:
            if kw in html:
                pos = html.find(kw)
                snippet = html[max(0,pos-200):pos+200]
                print(f"\n  '{kw}' at pos {pos}:")
                print(f"    ...{snippet[:300]}...")
        
        # 10. Check the page for any visible content related to the property
        # Even if it's a 404, there might be some embedded data
        print("\n=== FULL HTML SNIPPET AROUND card-property-content ===")
        pos = html.find('card-property-content')
        if pos >= 0:
            # Get a larger snippet
            snippet = html[max(0,pos-1000):pos+5000]
            print(snippet[:5000])
        
        await browser.close()

asyncio.run(main())
