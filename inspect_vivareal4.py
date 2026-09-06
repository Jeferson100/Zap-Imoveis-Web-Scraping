import asyncio
import re
from playwright.async_api import async_playwright

URL = "https://www.vivareal.com.br/imovel/casa-2-quartos-jarivatuba-bairros-joinville-com-garagem-60m2-venda-RS349636-id-2879650023/"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headless=False for debugging
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(8000)
        
        # Check page title and URL
        title = await page.title()
        url = page.url
        print(f"Title: {title}")
        print(f"URL: {url}")
        
        # Check if it's a 404
        body_text = await page.locator("body").inner_text()
        if "Não conseguimos encontrar" in body_text or "Oops" in body_text or "404" in body_text:
            print("\n!!! PAGE IS A 404 - showing recommendations instead !!!")
            print("Page text excerpt:")
            print(body_text[:500])
        
        # Try to find any property-specific content
        # Look for the actual property details in the HTML
        html = await page.content()
        
        # Search for any property-specific identifiers
        print("\n=== SEARCHING FOR PROPERTY-RELATED JSON DATA ===")
        # Look for Next.js data
        for pattern in ['__NEXT_DATA__', 'window.__', 'initialState', 'preloadedState', 'store']:
            matches = list(re.finditer(pattern, html))
            if matches:
                print(f"  Found '{pattern}' {len(matches)} times")
                for m in matches[:3]:
                    start = max(0, m.start()-20)
                    end = min(len(html), m.end()+200)
                    print(f"    ...{html[start:end]}...")
        
        # Look for the property data in the page
        # Check if there's any server-side rendered data
        print("\n=== SEARCHING FOR PROPERTY DATA IN HTML ===")
        for keyword in ['id-2879650023', 'RS349636', 'jarivatuba', 'joinville']:
            if keyword in html:
                print(f"  Found '{keyword}' in HTML!")
                pos = html.find(keyword)
                snippet = html[max(0,pos-200):pos+200]
                print(f"    {snippet}")
            else:
                print(f"  '{keyword}' NOT found in HTML")
        
        # Check for the actual property section
        print("\n=== LOOKING FOR PROPERTY DETAILS SECTION ===")
        # Look for h1 or property title
        h1_elems = await page.locator("h1").all()
        for i, el in enumerate(h1_elems[:10]):
            text = await el.inner_text()
            if text.strip():
                print(f"  h1[{i}]: {text[:100]}")
        
        # Look for any section with "Sobre" or "Descrição"
        for keyword in ['Sobre', 'Descrição', 'Informações', 'Características', 'Dados']:
            elems = await page.locator(f"xpath=//*[contains(text(), '{keyword}')]").all()
            if elems:
                for el in elems[:5]:
                    text = await el.inner_text()
                    print(f"  '{keyword}' -> {text[:100]}")
        
        # Get the full page text
        print("\n=== FULL PAGE TEXT ===")
        print(body_text[:2000])
        
        input("\nPress Enter to close...")
        await browser.close()

asyncio.run(main())
