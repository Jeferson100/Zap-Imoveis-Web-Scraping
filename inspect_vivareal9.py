import asyncio
import re
from playwright.async_api import async_playwright

# Try the glue API with correct headers
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        # Try to access the glue API with correct headers
        print("=== GLUE API WITH CORRECT HEADERS ===")
        api_data = await page.evaluate("""async () => {
            try {
                const res = await fetch('https://glue-api.vivareal.com/v2/listings?ids=2879650023', {
                    headers: {
                        'x-domain': 'www.vivareal.com.br',
                        'Accept': 'application/json',
                        'Origin': 'https://www.vivareal.com.br',
                        'Referer': 'https://www.vivareal.com.br/',
                    }
                });
                const text = await res.text();
                return text.substring(0, 3000);
            } catch(e) {
                return 'Error: ' + e.message;
            }
        }""")
        print(api_data[:3000])
        
        # Also try a different endpoint format
        try:
            api_data2 = await page.evaluate("""async () => {
                try {
                    const res = await fetch('https://glue-api.vivareal.com/v2/listings/2879650023', {
                        headers: {
                            'x-domain': 'www.vivareal.com.br',
                            'Accept': 'application/json',
                            'Origin': 'https://www.vivareal.com.br',
                        }
                    });
                    const text = await res.text();
                    return text.substring(0, 3000);
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }""")
            print(f"\nListing endpoint: {api_data2[:1000]}")
        except Exception as e:
            print(f"Listing endpoint error: {e}")
        
        # Try to search for a working listing
        try:
            search_data = await page.evaluate("""async () => {
                try {
                    const res = await fetch('https://glue-api.vivareal.com/v2/listings?size=5&businessType=SALE&locationQueries=Joinville', {
                        headers: {
                            'x-domain': 'www.vivareal.com.br',
                            'Accept': 'application/json',
                            'Origin': 'https://www.vivareal.com.br',
                        }
                    });
                    const text = await res.text();
                    return text.substring(0, 3000);
                } catch(e) {
                    return 'Error: ' + e.message;
                }
            }""")
            print(f"\nSearch results: {search_data[:3000]}")
        except Exception as e:
            print(f"Search error: {e}")
        
        await browser.close()

asyncio.run(main())
