import asyncio
import re
import json
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
        
        print(f"Visiting: {URL}")
        await page.goto(URL, wait_until="networkidle")
        await page.wait_for_timeout(5000)
        print("Page loaded.")
        
        html = await page.content()
        
        # 1. Find ALL data-cy attributes
        print("\n=== ALL data-cy ATTRIBUTES ===")
        data_cy_matches = re.findall(r'data-cy="([^"]+)"', html)
        for m in sorted(set(data_cy_matches)):
            print(f"  data-cy=\"{m}\"")
        
        # 2. Find all elements with "amenity" in class or data-cy
        print("\n=== ELEMENTS WITH 'amenity' in class/data-cy ===")
        amenity_elems = await page.locator('[class*="amenity"], [data-cy*="amenity"], [class*="Amenity"], [data-cy*="Amenity"]').all()
        for i, el in enumerate(amenity_elems[:30]):
            text = await el.inner_text()
            cls = await el.get_attribute("class") or ""
            testid = await el.get_attribute("data-testid") or ""
            datacy = await el.get_attribute("data-cy") or ""
            print(f"  [{i}] class={cls} data-cy={datacy} data-testid={testid} text={text[:100]}")
        
        # 3. Find elements with "privativa" or "comum" text
        print("\n=== ELEMENTS WITH 'privativa' or 'comum' text ===")
        priv_elems = await page.locator("xpath=//*[contains(translate(., 'PRIVATIVA', 'privativa'), 'privativa')]").all()
        for i, el in enumerate(priv_elems[:20]):
            text = await el.inner_text()
            print(f"  [{i}] text={text[:100]}")
        
        comum_elems = await page.locator("xpath=//*[contains(translate(., 'COMUM', 'comum') or translate(., 'CONDOMÍNIO', 'condomínio'), 'comum')]").all()
        for i, el in enumerate(comum_elems[:20]):
            text = await el.inner_text()
            print(f"  [{i}] text={text[:100]}")
        
        # 4. Look for card/list items
        print("\n=== LI ELEMENTS WITH TEXT ===")
        li_elems = await page.locator("li").all()
        for i, el in enumerate(li_elems[:50]):
            try:
                text = await el.inner_text()
                if text.strip():
                    cls = await el.get_attribute("class") or ""
                    datacy = await el.get_attribute("data-cy") or ""
                    if any(k in text.lower() for k in ['elevador', 'piscina', 'churras', 'academia', 'vagas', 'área', 'garagem', 'quarto', 'banheiro', 'amenities', 'feature']):
                        print(f"  [{i}] class={cls} data-cy={datacy} text={text[:100]}")
            except:
                pass
        
        # 5. Look for the actual card structure - search for data-cy patterns
        print("\n=== DATA-CY PATTERNS WITH 'property' or 'card' ===")
        card_cy = [m for m in set(data_cy_matches) if 'property' in m.lower() or 'card' in m.lower() or 'item' in m.lower()]
        for m in sorted(card_cy):
            print(f"  data-cy=\"{m}\"")
        
        # 6. Find all div sections with headers
        print("\n=== SECTION HEADINGS ON PAGE ===")
        headings = await page.locator("xpath=//h1|//h2|//h3|//h4|//*[has-class('text-xl') or has-class('text-lg') or has-class('font-bold')]").all()
        for i, el in enumerate(headings[:30]):
            text = await el.inner_text()
            if text.strip():
                print(f"  [{i}] {text[:100]}")
        
        # 7. Look for JSON in script tags
        print("\n=== SCRIPT TAGS WITH JSON-LD OR EMBEDDED DATA ===")
        scripts = await page.locator("script").all()
        for i, el in enumerate(scripts):
            try:
                content = await el.inner_text()
                if len(content) > 100 and any(k in content for k in ['privativeItems', 'commonItems', 'amenities', 'Amenity', 'features']):
                    print(f"\n  [{i}] Script length={len(content)}")
                    # Find the relevant part
                    for pattern in ['privativeItems', 'commonItems', 'amenities']:
                        for m in re.finditer(pattern, content):
                            start = max(0, m.start()-100)
                            end = min(len(content), m.end()+300)
                            print(f"    Pattern '{pattern}' at pos {m.start()}: ...{content[start:end]}...")
                            break  # Just first occurrence
            except:
                pass
        
        # 8. Search HTML for any JSON structure with arrays of objects containing "name"
        print("\n=== SEARCHING HTML FOR JSON WITH 'name' KEYS ===")
        # Look for JSON patterns with name arrays
        json_patterns = [
            r'"name"\s*:\s*"[^"]+"',
            r'"label"\s*:\s*"[^"]+"',
            r'"title"\s*:\s*"[^"]+"',
        ]
        for pat in json_patterns:
            matches = re.findall(pat, html)
            if matches:
                print(f"  Pattern '{pat}': found {len(matches)} matches")
                for m in matches[:10]:
                    print(f"    {m}")
        
        # 9. Look for the actual amenities section - find all divs with role or aria-label
        print("\n=== ELEMENTS WITH ROLE='list' OR aria-label containing amenity ===")
        role_elems = await page.locator("[role='list'], [aria-label*='amenity' i], [aria-label*='feature' i], [aria-label*='característica' i]").all()
        for i, el in enumerate(role_elems[:20]):
            text = await el.inner_text()
            aria = await el.get_attribute("aria-label") or ""
            print(f"  [{i}] aria-label={aria} text={text[:100]}")
        
        # 10. Print the full body text to understand page structure
        print("\n=== FULL BODY TEXT (first 3000 chars) ===")
        body_text = await page.locator("body").inner_text()
        print(body_text[:3000])
        
        # 11. Look for tabs/panels
        print("\n=== TABS/PANELS (role='tab' or data-testid containing 'panel') ===")
        tab_elems = await page.locator("[role='tab'], [data-testid*='panel'], [class*='tab']").all()
        for i, el in enumerate(tab_elems[:20]):
            text = await el.inner_text()
            testid = await el.get_attribute("data-testid") or ""
            cls = await el.get_attribute("class") or ""
            print(f"  [{i}] testid={testid} class={cls} text={text[:100]}")
        
        await browser.close()

asyncio.run(main())
