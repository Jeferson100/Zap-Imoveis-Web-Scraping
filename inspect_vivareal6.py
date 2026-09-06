import asyncio
import re
from playwright.async_api import async_playwright

# Try to use a search URL that might work
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
        
        # Search for Next.js data embedded in the page
        print("=== SEARCHING FOR EMBEDDED DATA ===")
        
        # Look for __NEXT_DATA__ or similar
        for pattern in ['__NEXT_DATA__', 'nextInitialData', 'initialData', '__DATA__', 
                        'window.__next', 'preloadedData', 'serverData']:
            if pattern in html:
                pos = html.find(pattern)
                snippet = html[max(0,pos-100):pos+500]
                print(f"\nFound '{pattern}' at pos {pos}:")
                print(snippet[:500])
        
        # Look for any JSON-like data in script tags
        print("\n=== SCRIPT TAGS WITH JSON DATA ===")
        scripts = await page.locator("script").all()
        for i, el in enumerate(scripts):
            try:
                content = await el.inner_text()
                if 'window.__' in content or '__NEXT_DATA__' in content or 'initialState' in content or 'preloaded' in content:
                    print(f"\nScript [{i}] length={len(content)}")
                    # Find the relevant data
                    for keyword in ['amenities', 'Amenity', 'privative', 'common', 'ELEVATOR', 'Elevador']:
                        if keyword in content:
                            pos = content.find(keyword)
                            snippet = content[max(0,pos-200):pos+300]
                            print(f"  Found '{keyword}': ...{snippet[:300]}...")
            except:
                pass
        
        # Look for any API endpoints in the HTML
        print("\n=== API ENDPOINTS IN HTML ===")
        api_urls = re.findall(r'(https?://[^\s"\'<>]*(?:api|glue|listing)[^\s"\'<>]*)', html)
        for url in set(api_urls):
            print(f"  {url}")
        
        # Look for fetch/XHR requests in the HTML
        print("\n=== FETCH/GRAPHQL ENDPOINTS ===")
        fetch_urls = re.findall(r'(https?://[^\s"\'<>]*(?:/v2/|/graphql|/api/)[^\s"\'<>]*)', html)
        for url in set(fetch_urls):
            print(f"  {url}")
        
        # Look for any JSON data structures in the HTML
        print("\n=== JSON DATA STRUCTURES ===")
        # Look for the specific property data
        for keyword in ['id-2879650023', 'RS349636', 'jarivatuba', '2879650023']:
            if keyword in html:
                pos = html.find(keyword)
                snippet = html[max(0,pos-500):pos+500]
                print(f"\n  '{keyword}' at pos {pos}:")
                print(f"  ...{snippet[:500]}...")
        
        # Look for the actual property content in the HTML
        # The page was a 404 but the canonical URL was present
        # Let's look for any JSON data that might contain the listing info
        print("\n=== LOOKING FOR LISTING DATA ===")
        for pattern in ['listing', 'Listing', 'LDP', 'ldp', 'rp-cardProperty', 'rp-card']:
            if pattern in html:
                count = html.count(pattern)
                print(f"  '{pattern}' found {count} times")
        
        # Try to find the Next.js page data
        print("\n=== NEXT.JS PAGE DATA ===")
        # Next.js typically embeds data in a script tag with id="__NEXT_DATA__"
        next_data = await page.locator("script[id='__NEXT_DATA__']").all()
        for el in next_data:
            content = await el.inner_text()
            print(f"__NEXT_DATA__ found! Length: {len(content)}")
            # Search for amenities in it
            for kw in ['amenity', 'Amenity', 'privative', 'common', 'Elevador', 'ELEVATOR']:
                if kw in content:
                    pos = content.find(kw)
                    print(f"  Found '{kw}' at pos {pos}")
                    print(f"  Context: ...{content[max(0,pos-100):pos+200]}...")
        
        # Also check for any script tag that might contain the data
        print("\n=== ALL SCRIPT IDs ===")
        for i, el in enumerate(scripts):
            try:
                sid = await el.get_attribute("id") or ""
                src = await el.get_attribute("src") or ""
                if sid or src:
                    print(f"  Script [{i}] id={sid} src={src[:100]}")
            except:
                pass
        
        # Check the page for any embedded JSON
        print("\n=== EMBEDDED JSON SEARCH ===")
        # Look for any JSON-like patterns
        json_patterns = [
            r'"amenities":\s*\[.*?\]',
            r'"amenitiesList":\s*\[.*?\]',
            r'"privativeItems":\s*\[.*?\]',
            r'"commonItems":\s*\[.*?\]',
            r'"features":\s*\[.*?\]',
            r'"characteristics":\s*\[.*?\]',
        ]
        for pat in json_patterns:
            matches = list(re.finditer(pat, html, re.S))
            if matches:
                for m in matches[:3]:
                    print(f"  Pattern '{pat}': ...{html[m.start():m.end()+100]}...")
        
        await browser.close()

asyncio.run(main())
