import asyncio
import re
import json
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
        
        # Try to access the Next.js data through evaluate
        print("=== EVALUATING NEXT.JS DATA ===")
        
        # Check for __NEXT_DATA__ in the window
        try:
            next_data = await page.evaluate("""() => {
                return window.__NEXT_DATA__ ? JSON.stringify(window.__NEXT_DATA__).substring(0, 2000) : 'not found';
            }""")
            print(f"__NEXT_DATA__: {next_data[:500]}")
        except Exception as e:
            print(f"__NEXT_DATA__ error: {e}")
        
        # Check for any data in the page state
        try:
            state = await page.evaluate("""() => {
                // Look for any global state variables
                const keys = Object.keys(window).filter(k => k.includes('STATE') || k.includes('data') || k.includes('preload') || k.includes('INITIAL'));
                return keys;
            }""")
            print(f"\nGlobal state keys: {state}")
        except Exception as e:
            print(f"State keys error: {e}")
        
        # Try to get the __NEXT_DATA__ or similar
        try:
            ldpu_data = await page.evaluate("""() => {
                // Try to find the listing data from the page
                const scripts = Array.from(document.querySelectorAll('script[type="application/json"]'));
                const data = {};
                scripts.forEach((s, i) => {
                    try { data[`script_${i}`] = JSON.parse(s.textContent); } catch(e) {}
                });
                return Object.keys(data);
            }""")
            print(f"\nJSON script keys: {ldpu_data}")
        except Exception as e:
            print(f"JSON script error: {e}")
        
        # Try to evaluate the page to find the listing data
        try:
            listing_data = await page.evaluate("""() => {
                // Try to find the listing data from the DOM
                const scripts = Array.from(document.querySelectorAll('script'));
                for (const s of scripts) {
                    const text = s.textContent || s.innerText;
                    if (text.includes('listing') && text.includes('amenities') && text.includes('2879650023')) {
                        return text.substring(0, 2000);
                    }
                }
                return 'not found';
            }""")
            if listing_data != 'not found':
                print(f"\nListing data found: {listing_data[:1000]}")
            else:
                print("\nListing data not found in scripts")
        except Exception as e:
            print(f"Listing data eval error: {e}")
        
        # Try to find the LDP data by checking the page data
        try:
            ldpu_page_data = await page.evaluate("""() => {
                // Check for any data-reactprops or data-ldp attributes
                const el = document.querySelector('[data-cy="card-property-content"]');
                if (el) {
                    return {
                        outerHTML: el.outerHTML.substring(0, 2000),
                        dataset: Object.fromEntries(Object.entries(el.dataset)),
                    };
                }
                return 'not found';
            }""")
            if ldpu_page_data != 'not found':
                print(f"\nCard property content: {str(ldpu_page_data)[:1000]}")
        except Exception as e:
            print(f"Card data error: {e}")
        
        # Try to access the glue API directly through the page context
        print("\n=== TRYING TO ACCESS GLUE API ===")
        try:
            # Use page.evaluate to make a fetch request
            api_data = await page.evaluate("""async () => {
                try {
                    const res = await fetch('https://glue-api.vivareal.com/v2/listings?ids=2879650023', {
                        headers: {
                            'x-domain': 'vivareal.com.br',
                            'Accept': 'application/json',
                        }
                    });
                    const text = await res.text();
                    return text.substring(0, 2000);
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }""")
            print(f"API response: {api_data[:1000]}")
        except Exception as e:
            print(f"API fetch error: {e}")
        
        # Check for the actual listing data in the page
        # The page might have the data embedded in a Next.js chunk
        try:
            page_data = await page.evaluate("""() => {
                // Look for any global data stores
                const g_keys = Object.keys(window).filter(k => typeof window[k] === 'object' && window[k] !== null);
                const data = {};
                for (const k of g_keys.slice(0, 20)) {
                    try {
                        const str = JSON.stringify(window[k]);
                        if (str.includes('amenities') || str.includes('2879650023') || str.includes('listing')) {
                            data[k] = str.substring(0, 500);
                        }
                    } catch(e) {}
                }
                return data;
            }""")
            if page_data:
                print(f"\nPage data found: {json.dumps(page_data, indent=2)[:2000]}")
            else:
                print("\nNo relevant page data found in global scope")
        except Exception as e:
            print(f"Page data eval error: {e}")
        
        await browser.close()

asyncio.run(main())
