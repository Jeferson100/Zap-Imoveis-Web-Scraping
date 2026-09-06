import asyncio
import re
from playwright.async_api import async_playwright

# Try the URL without the trailing slash, or try the first listed property URL
URL = "https://www.vivareal.com.br/imovel/casa-2-quartos-jarivatuba-bairros-joinville-com-garagem-60m2-venda-RS349636-id-2879650023"

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
        
        url = page.url
        title = await page.title()
        print(f"Final URL: {url}")
        print(f"Title: {title}")
        
        html = await page.content()
        
        # Check if it's still a 404 or if it redirected
        if "Não conseguimos encontrar" in html or "Oops" in html:
            print("\nStill 404. Trying alternative URLs...")
            
            # Try one of the other URLs from the scraper file
            alt_urls = [
                'https://www.vivareal.com.br/imovel/casa-3-quartos-paranaguamirim-bairros-joinville-com-garagem-180m2-venda-RS290000-id-2879676230/',
                'https://www.vivareal.com.br/imovel/sobrado-2-quartos-vila-nova-bairros-joinville-com-garagem-59m2-venda-RS380000-id-2879679877/',
                'https://www.vivareal.com.br/imovel/casa-4-quartos-espinheiros-bairros-joinville-com-garagem-181m2-venda-RS510000-id-2879682973/',
            ]
            
            for alt_url in alt_urls:
                print(f"\n  Trying: {alt_url}")
                await page.goto(alt_url, wait_until="networkidle")
                await page.wait_for_timeout(3000)
                body_text = await page.locator("body").inner_text()
                if "Não conseguimos encontrar" not in body_text and "Oops" not in body_text:
                    print(f"  SUCCESS! Page loaded.")
                    print(f"  Title: {await page.title()}")
                    
                    # Now inspect the page structure
                    html = await page.content()
                    
                    # Search for amenities structure
                    print("\n  === AMENITIES SEARCH ===")
                    for keyword in ['amenities', 'Amenity', 'privativeItems', 'commonItems', 'Elevador', 'Piscina']:
                        if keyword in html:
                            pos = html.find(keyword)
                            snippet = html[max(0,pos-100):pos+200]
                            print(f"  Found '{keyword}' at pos {pos}: ...{snippet[:200]}...")
                        
                    # Search for data-cy patterns
                    data_cy_matches = re.findall(r'data-cy="([^"]+)"', html)
                    amenity_cy = [m for m in set(data_cy_matches) if any(k in m.lower() for k in ['amenity', 'feature', 'item', 'property'])]
                    print(f"\n  Relevant data-cy patterns: {amenity_cy}")
                    
                    # Search for ul/li structures
                    print("\n  === UL/LI STRUCTURES ===")
                    ul_elems = await page.locator("ul").all()
                    for i, el in enumerate(ul_elems[:20]):
                        text = await el.inner_text()
                        cls = await el.get_attribute("class") or ""
                        if text.strip() and any(k in text.lower() for k in ['elevador', 'piscina', 'churras', 'academia', 'vagas', 'área', 'garagem', 'amenity', 'privativa', 'comum']):
                            print(f"  [{i}] class={cls[:80]} text={text[:150]}")
                    
                    # Search for any list items with amenity text
                    print("\n  === ELEMENTS WITH AMENITY TEXT ===")
                    for keyword in ['Elevador', 'Piscina', 'Churrasqueira', 'Academia', 'Ar condicionado', 'Área', 'Vaga']:
                        elems = await page.locator(f"xpath=//*[contains(text(), '{keyword}')]").all()
                        if elems:
                            for el in elems[:5]:
                                text = await el.inner_text()
                                cls = await el.get_attribute("class") or ""
                                datacy = await el.get_attribute("data-cy") or ""
                                tag = await el.evaluate("el => el.tagName") if hasattr(el, 'evaluate') else "?"
                                print(f"    '{keyword}' -> tag={tag} class={cls[:80]} data-cy={datacy} text={text[:80]}")
                    
                    # Print full body text
                    print("\n  === PAGE TEXT ===")
                    print(body_text[:3000])
                    break
                else:
                    print(f"  Still 404")
            else:
                print("\nAll alternative URLs also returned 404.")
                print("The property listings may have been removed from VivaReal.")
                
                # Let's try searching the web for a working URL
                print("\nTrying to find a working URL via web search...")
        else:
            # Page loaded successfully, inspect it
            print("\nPage loaded successfully!")
            print(f"HTML length: {len(html)}")
        
        await browser.close()

asyncio.run(main())
