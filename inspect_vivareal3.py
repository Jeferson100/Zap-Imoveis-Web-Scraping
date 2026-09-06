import asyncio
import re
from playwright.async_api import async_playwright

URL = "https://www.vivareal.com.br/imovel/casa-2-quartos-jarivatuba-bairros-joinville-com-garagem-60m2-venda-RS349636-id-2879650023/"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
        """)
        
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(5000)
        
        html = await page.content()
        
        # 1. Search for any section that might be the amenities card
        # Look for card-related divs
        print("=== SEARCHING FOR CARD-RELATED STRUCTURES ===")
        
        # Find all divs with "card" in class
        card_divs = await page.locator("[class*='card']").all()
        print(f"\nFound {len(card_divs)} elements with 'card' in class")
        for i, el in enumerate(card_divs[:20]):
            text = await el.inner_text()
            cls = await el.get_attribute("class") or ""
            datacy = await el.get_attribute("data-cy") or ""
            if text.strip():
                print(f"  [{i}] class={cls[:100]} data-cy={datacy} text={text[:100]}")
        
        # 2. Look for the full HTML around "card-property-content"
        print("\n=== HTML AROUND card-property-content ===")
        pos = html.find('card-property-content')
        if pos >= 0:
            snippet = html[max(0,pos-500):pos+3000]
            print(snippet[:3000])
        
        # 3. Look for any text containing "Privativa" or "Comum" or "Condomínio"
        print("\n=== SEARCHING HTML FOR KEY TEXT ===")
        for keyword in ['Privativa', 'Comum', 'Condomínio', 'características', 'Amenities', 'amenities', 'Amenities:', 'Privative', 'Common']:
            positions = [m.start() for m in re.finditer(re.escape(keyword), html)]
            if positions:
                print(f"\n  '{keyword}' found {len(positions)} times")
                for pos in positions[:3]:
                    snippet = html[max(0,pos-100):pos+300]
                    print(f"    pos={pos}: ...{snippet}...")
        
        # 4. Look for any list-like structures
        print("\n=== LOOKING FOR UL/LI STRUCTURES ===")
        ul_count = len(re.findall(r'<ul', html))
        li_count = len(re.findall(r'<li', html))
        print(f"  <ul count: {ul_count}, <li count: {li_count}")
        
        # 5. Search for "Elevador" anywhere in HTML
        print("\n=== SEARCHING FOR 'Elevador' ===")
        elev_positions = [m.start() for m in re.finditer('Elevador', html)]
        print(f"  Found {len(elev_positions)} times")
        for pos in elev_positions[:5]:
            snippet = html[max(0,pos-200):pos+200]
            print(f"    pos={pos}: ...{snippet}...")
        
        # 6. Look for any data attributes that might be related
        print("\n=== ALL DATA-CY ATTRIBUTES (full list) ===")
        data_cy_matches = re.findall(r'data-cy="([^"]+)"', html)
        for m in sorted(set(data_cy_matches)):
            count = data_cy_matches.count(m)
            print(f"  {m} (x{count})")
        
        # 7. Look for any JSON-like embedded data
        print("\n=== SEARCHING FOR JSON STRUCTURES ===")
        # Look for window.__INITIAL_STATE__ or similar
        for pattern in ['__INITIAL_STATE__', '__PRELOADED_STATE__', '__DATA__', '__APPLICATION_DATA__']:
            pos = html.find(pattern)
            if pos >= 0:
                print(f"  Found {pattern} at pos {pos}")
                snippet = html[pos:pos+500]
                print(f"    {snippet[:500]}")
        
        # 8. Look for any script tags with JSON data
        print("\n=== SCRIPT TAGS CONTENT (first 5 that contain JSON) ===")
        scripts = await page.locator("script").all()
        json_scripts = []
        for i, el in enumerate(scripts):
            try:
                content = await el.inner_text()
                if len(content) > 50 and ('{' in content or '[' in content):
                    json_scripts.append((i, len(content), content[:200]))
            except:
                pass
        
        print(f"  Found {len(json_scripts)} script tags with JSON-like content")
        for i, length, preview in json_scripts[:10]:
            print(f"  Script [{i}] length={length}: {preview[:150]}...")
        
        # 9. Look for the full page text to understand the layout
        print("\n=== PAGE TEXT (full) ===")
        body_text = await page.locator("body").inner_text()
        lines = body_text.split('\n')
        for line in lines[:100]:
            line = line.strip()
            if line:
                print(f"  {line[:150]}")
        
        # 10. Look for any elements containing text like "Área", "Lazer", "Dependência"
        print("\n=== ELEMENTS WITH FEATURE TEXT ===")
        feature_keywords = ['Área', 'Lazer', 'Dependência', 'Sala', 'Cozinha', 'Banheiro', 'Quarto', 'Vaga', 'Garagem', 'Elevador', 'Academia', 'Piscina', 'Churrasqueira', 'Varanda', 'Mobiliado', 'Ar condicionado']
        for kw in feature_keywords:
            elems = await page.locator(f"xpath=//*[contains(text(), '{kw}')]").all()
            if elems:
                for el in elems[:5]:
                    text = await el.inner_text()
                    cls = await el.get_attribute("class") or ""
                    datacy = await el.get_attribute("data-cy") or ""
                    tag = await el.evaluate("el => el.tagName") if hasattr(el, 'evaluate') else "?"
                    print(f"  '{kw}' -> tag={tag} class={cls[:80]} data-cy={datacy} text={text[:80]}")
        
        await browser.close()

asyncio.run(main())
