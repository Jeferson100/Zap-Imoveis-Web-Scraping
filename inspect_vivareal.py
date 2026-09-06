from playwright.sync_api import sync_playwright
import json

URL = "https://www.vivareal.com.br/imovel/imovel-comercial-centro-bairros-joinville-34m2-venda-RS420000-id-2760103415/?source=ranking%2Crp"

def safe_eval(page, selector, fn):
    try:
        return page.eval_on_selector_all(selector, fn)
    except Exception as e:
        return None

def safe_eval_one(page, selector, fn):
    try:
        return page.eval_on_selector(selector, fn)
    except Exception as e:
        return None

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                "Referer": "https://www.google.com/",
            }
        )
        page = context.new_page()

        print("=" * 80)
        print("NAVIGATING TO URL...")
        print("=" * 80)
        try:
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"  goto error: {e}")

        print("Waiting 5 seconds after page load...")
        page.wait_for_timeout(5000)

        # Also try waiting for network to settle
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        page.wait_for_timeout(3000)

        # Get page title and URL to verify
        title = page.title()
        print(f"\nPage title: {title}")
        print(f"Page URL: {page.url}")

        # Check if page has content
        body_text = safe_eval_one(page, "body", "el => el.textContent") or ""
        print(f"Body text length: {len(body_text)}")
        if body_text:
            print(f"First 200 chars: {body_text[:200]}")

        print("\n" + "=" * 80)
        print("a) ALL data-cy attributes on the page")
        print("=" * 80)
        data_cy = safe_eval(page, "[data-cy]", "elements => elements.map(el => el.getAttribute('data-cy'))")
        if data_cy:
            for val in sorted(set(data_cy)):
                if val:
                    print(f"  data-cy: {val}")
        else:
            print("  No data-cy attributes found")

        print("\n" + "=" * 80)
        print("b) ALL data-testid attributes on the page")
        print("=" * 80)
        data_testid = safe_eval(page, "[data-testid]", "elements => elements.map(el => el.getAttribute('data-testid'))")
        if data_testid:
            for val in sorted(set(data_testid)):
                if val:
                    print(f"  data-testid: {val}")
        else:
            print("  No data-testid attributes found")

        # c) Elements containing amenity-related words
        print("\n" + "=" * 80)
        print("c) Elements containing amenity-related words")
        print("=" * 80)
        keywords = ["amenit", "feature", "caracteristica", "comodidad", "diferencial", "maior", "detalhe", "ver mais", "mais detalhes"]
        for kw in keywords:
            results = safe_eval(page, f"*:has-text('{kw}')",
                "elements => elements.map(el => ({text: el.textContent?.trim().substring(0, 100), tag: el.tagName, className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid')}))")
            if results:
                print(f"\n  Keyword: '{kw}'")
                for r in results[:20]:
                    if r and r.get('text'):
                        print(f"    <{r['tag']}> class='{r['className']}' data-cy='{r['dataCy']}' data-testid='{r['dataTestid']}'")
                        print(f"      Text: {r['text'][:100]}")

        # d-f) Amenity containers
        print("\n" + "=" * 80)
        print("d-f) Looking for amenity containers (ul, div, section)")
        print("=" * 80)
        amenity_patterns = ["amenities", "features", "caracteristicas", "comodidades", "diferenciais", "privative", "commonItems", "itens", "infraestrutura", "conforto", "lazer"]
        for pattern in amenity_patterns:
            results = safe_eval(page, f"*:has-text('{pattern}')",
                "elements => elements.map(el => ({tag: el.tagName, className: el.className, id: el.id, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid'), text: el.textContent?.trim().substring(0, 150)}))")
            if results:
                print(f"\n  Pattern: '{pattern}' found {len(results)} element(s)")
                for r in results[:10]:
                    if r and r.get('text'):
                        print(f"    Tag: {r['tag']}, Class: {r['className']}, ID: {r['id']}")
                        print(f"    data-cy: {r['dataCy']}, data-testid: {r['dataTestid']}")
                        print(f"    Text: {r['text'][:100]}")

        # ul elements
        print("\n  Searching for <ul> elements with amenity-related content:")
        ul_elements = safe_eval(page, "ul",
            "elements => elements.map(el => ({text: el.textContent?.trim().substring(0, 200), className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid')}))")
        if ul_elements:
            for i, ul in enumerate(ul_elements):
                if ul and ul.get('text'):
                    text_lower = ul['text'].lower()
                    if any(kw in text_lower for kw in ['amenit', 'feature', 'caracteristica', 'comodidad', 'diferencial', 'privative', 'common', 'lazer', 'infraestrutura', 'conforto']):
                        print(f"\n  UL #{i}: class='{ul['className']}' data-cy='{ul['dataCy']}' data-testid='{ul['dataTestid']}'")
                        print(f"    Text: {ul['text'][:200]}")

        # f) JSON-LD
        print("\n" + "=" * 80)
        print("f) JSON-LD structured data (application/ld+json)")
        print("=" * 80)
        json_ld_scripts = safe_eval(page, 'script[type="application/ld+json"]',
            "elements => elements.map(el => ({text: el.textContent?.substring(0, 500)}))")
        if json_ld_scripts:
            for i, script in enumerate(json_ld_scripts):
                text = script.get('text', '') if script else ''
                print(f"\n  JSON-LD Script #{i}:")
                print(f"    Content (first 500 chars): {text[:500]}")
                text_lower = text.lower()
                for kw in ['amenities', 'features', 'privativeitems', 'commonitems', 'itens', 'caracteristicas', 'comodidades']:
                    if kw.lower() in text_lower:
                        print(f"    *** Contains keyword: {kw}")
        else:
            print("  No JSON-LD scripts found")

        # g) Embedded JSON
        print("\n" + "=" * 80)
        print("g) Embedded JSON with amenity-related keywords")
        print("=" * 80)
        scripts = safe_eval(page, 'script',
            "elements => elements.map(el => ({type: el.getAttribute('type') || 'unknown', id: el.getAttribute('id'), text: el.textContent?.substring(0, 1000)}))")
        if scripts:
            for i, s in enumerate(scripts):
                if not s:
                    continue
                text = s.get('text', '') or ''
                text_lower = text.lower()
                for kw in ['amenities', 'features', 'privativeitems', 'commonitems', 'itens', 'caracteristicas', 'comodidades', 'diferenciais', 'lazer', 'infraestrutura']:
                    if kw.lower() in text_lower and len(text) > 10:
                        stripped = text.strip()
                        if stripped.startswith('{') or stripped.startswith('['):
                            print(f"\n  Script #{i} (type={s.get('type')}) contains '{kw}':")
                            print(f"    First 500 chars: {text[:500]}")
                            break

        # h) Expand buttons
        print("\n" + "=" * 80)
        print("h) 'Mais detalhes' or 'Ver mais' buttons")
        print("=" * 80)
        expand_buttons = safe_eval(page, '*:has-text("Mais detalhes"), *:has-text("Ver mais"), *:has-text("Ver Mais"), *:has-text("Ver mais")',
            "elements => elements.map(el => ({text: el.textContent?.trim(), tag: el.tagName, className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid')}))")
        if expand_buttons:
            for btn in expand_buttons:
                if btn:
                    print(f"\n  Found button:")
                    print(f"    Text: {btn.get('text')}")
                    print(f"    Tag: {btn.get('tag')}")
                    print(f"    Class: {btn.get('className')}")
                    print(f"    data-cy: {btn.get('dataCy')}")
                    print(f"    data-testid: {btn.get('dataTestid')}")
        else:
            print("  No expand buttons found")

        # i) Text around amenity areas
        print("\n" + "=" * 80)
        print("i) Full text content around amenity areas")
        print("=" * 80)
        if body_text:
            for kw in ["características", "comodidades", "diferenciais", "infraestrutura", "lazer", "amenidades", "features", "amenities", "privativo", "comum"]:
                idx = body_text.lower().find(kw.lower())
                if idx >= 0:
                    start = max(0, idx - 100)
                    end = min(len(body_text), idx + 500)
                    print(f"\n  Around '{kw}' (index {idx}):")
                    print(f"    {body_text[start:end]}")
                    print()

        # Elements with amenity-related CSS classes
        print("\n" + "=" * 80)
        print("Elements with amenity-related CSS classes")
        print("=" * 80)
        class_results = safe_eval(page, "[class*='amenit'], [class*='feature'], [class*='caracteristica'], [class*='comodidad'], [class*='diferencial'], [class*='lazer'], [class*='infra'], [class*='privative'], [class*='common']",
            "elements => elements.map(el => ({tag: el.tagName, className: el.className, id: el.id, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid'), text: el.textContent?.trim().substring(0, 150)}))")
        if class_results:
            for r in class_results:
                if r:
                    print(f"\n  Tag: {r['tag']}, Class: {r['className']}, ID: {r['id']}")
                    print(f"    data-cy: {r['dataCy']}, data-testid: {r['dataTestid']}")
                    print(f"    Text: {r['text'][:150]}")
        else:
            print("  No elements with amenity-related CSS classes found")

        # All data-cy
        print("\n" + "=" * 80)
        print("All data-cy attributes on the page")
        print("=" * 80)
        all_data_cy = safe_eval(page, "[data-cy]", "elements => elements.map(el => el.getAttribute('data-cy'))")
        if all_data_cy:
            for v in sorted(set(all_data_cy)):
                if v:
                    print(f"  {v}")
        else:
            print("  No data-cy attributes found")

        # iframes
        print("\n" + "=" * 80)
        print("Checking for iframes")
        print("=" * 80)
        frames = page.frames
        print(f"  Total frames: {len(frames)}")
        for frame in frames:
            print(f"    Frame: {frame.url}")

        # Portuguese terms
        print("\n" + "=" * 80)
        print("Searching for Portuguese amenity terms")
        print("=" * 80)
        pt_terms = ["privativo", "comum", "área de serviço", "sacada", "quadra", "piscina", "academia", "salão", "portaria", "vaga", "garagem"]
        for term in pt_terms:
            count = safe_eval(page, f"*:has-text('{term}')", "elements => elements.length")
            if count and count > 0:
                print(f"  '{term}': {count} element(s) found")

        # All text content pattern matching
        print("\n" + "=" * 80)
        print("Searching page text for all amenity-related patterns")
        print("=" * 80)
        if all_text := (body_text or ""):
            for pattern in ["Privativo", "Comum", "Vaga", "Piscina", "Academia", "Salão", "Churrasqueira", "Área de serviço", "Sacada", "Quadra", "Portaria", "Lazer", "Infraestrutura", "Diferenciais", "Características", "Comodidades", "Amenities", "Features"]:
                count = all_text.count(pattern)
                if count > 0:
                    print(f"  '{pattern}': found {count} time(s)")

        # JSON-LD parsing
        print("\n" + "=" * 80)
        print("Full parsed JSON-LD content")
        print("=" * 80)
        json_ld_full = safe_eval(page, 'script[type="application/ld+json"]', "elements => elements.map(el => el.textContent)")
        if json_ld_full and isinstance(json_ld_full, list):
            for i, content in enumerate(json_ld_full):
                if content:
                    try:
                        parsed = json.loads(content)
                        print(f"\n  JSON-LD #{i} (parsed):")
                        flat = json.dumps(parsed, indent=2)
                        for kw in ['amenities', 'features', 'privativeItems', 'commonItems', 'itens']:
                            if kw.lower() in flat.lower():
                                print(f"    *** Contains: {kw}")
                        if isinstance(parsed, dict):
                            for key in parsed:
                                if any(kw in key.lower() for kw in ['amenit', 'feature', 'char', 'item', 'detail', 'spec', 'comod', 'difere', 'privative', 'common']):
                                    print(f"    Key '{key}': {json.dumps(parsed[key], indent=4)[:500]}")
                    except json.JSONDecodeError:
                        print(f"\n  JSON-LD #{i}: Not valid JSON")
                        print(f"    First 300 chars: {content[:300]}")

        browser.close()
        print("\n" + "=" * 80)
        print("INSPECTION COMPLETE")
        print("=" * 80)

if __name__ == "__main__":
    main()
