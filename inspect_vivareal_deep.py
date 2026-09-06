from playwright.sync_api import sync_playwright
import sys, io, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

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
            }
        )
        page = context.new_page()
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        # 1. Full JSON-LD Product data
        print("=" * 80)
        print("FULL JSON-LD PRODUCT DATA")
        print("=" * 80)
        json_ld_scripts = safe_eval(page, 'script[type="application/ld+json"]', "elements => elements.map(el => el.textContent)")
        if json_ld_scripts and isinstance(json_ld_scripts, list):
            for i, content in enumerate(json_ld_scripts):
                if content:
                    try:
                        parsed = json.loads(content)
                        if parsed.get('@type') == 'Product':
                            print(f"\n  JSON-LD Product #{i}:")
                            flat = json.dumps(parsed, indent=2, ensure_ascii=False)
                            print(f"  {flat[:3000]}")
                    except json.JSONDecodeError:
                        pass

        # 2. The amenities-list element
        print("\n" + "=" * 80)
        print("amenities-list element (data-testid)")
        print("=" * 80)
        amenities_list = safe_eval_one(page, '[data-testid="amenities-list"]', "el => ({html: el.outerHTML, text: el.textContent, className: el.className, children: el.children.length})")
        if amenities_list:
            print(f"  Text: {amenities_list.get('text', '')[:1000]}")
            print(f"  Class: {amenities_list.get('className')}")
            print(f"  Children count: {amenities_list.get('children')}")
            print(f"  HTML (first 2000 chars): {amenities_list.get('html', '')[:2000]}")
        
        # 3. All elements with data-testid="amenities-list" and their children
        print("\n" + "=" * 80)
        print("All children of amenities-list")
        print("=" * 80)
        children_info = safe_eval(page, '[data-testid="amenities-list"] *', 
            "elements => elements.map(el => ({tag: el.tagName, className: el.className, text: el.textContent?.trim(), dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid')}))")
        if children_info:
            for c in children_info[:50]:
                if c and c.get('text'):
                    print(f"  <{c['tag']}> class='{c['className']}' data-cy='{c['dataCy']}' data-testid='{c['dataTestid']}'")
                    print(f"    Text: {c['text'][:150]}")

        # 4. The "Mostrar mais" button
        print("\n" + "=" * 80)
        print("'Mostrar mais' button")
        print("=" * 80)
        show_more = safe_eval(page, '*:has-text("Mostrar mais")', 
            "elements => elements.map(el => ({text: el.textContent?.trim(), tag: el.tagName, className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid'), disabled: el.disabled, visible: el.offsetParent !== null}))")
        if show_more:
            for btn in show_more:
                if btn:
                    print(f"  Text: {btn.get('text')}")
                    print(f"  Tag: {btn.get('tag')}")
                    print(f"  Class: {btn.get('className')}")
                    print(f"  data-cy: {btn.get('dataCy')}")
                    print(f"  data-testid: {btn.get('dataTestid')}")
                    print(f"  Visible: {btn.get('visible')}")

        # 5. The full characteristics section
        print("\n" + "=" * 80)
        print("Characteristics section (Características)")
        print("=" * 80)
        char_section = safe_eval(page, 'section', 
            "elements => elements.filter(el => el.textContent?.includes('Características')).map(el => ({className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid'), html: el.outerHTML?.substring(0, 3000), text: el.textContent?.substring(0, 2000)}))")
        if char_section:
            for cs in char_section:
                if cs:
                    print(f"  Class: {cs.get('className')}")
                    print(f"  data-cy: {cs.get('dataCy')}")
                    print(f"  data-testid: {cs.get('dataTestid')}")
                    print(f"  HTML (first 3000 chars): {cs.get('html', '')[:3000]}")
                    print(f"  Text: {cs.get('text', '')[:2000]}")

        # 6. The olx-tabs element
        print("\n" + "=" * 80)
        print("Amenities tabs element")
        print("=" * 80)
        tabs = safe_eval(page, '.olx-tabs, [class*="AmenitiesTabs"]', 
            "elements => elements.map(el => ({tag: el.tagName, className: el.className, id: el.id, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid'), html: el.outerHTML?.substring(0, 3000), text: el.textContent?.substring(0, 2000)}))")
        if tabs:
            for t in tabs:
                if t:
                    print(f"  Tag: {t.get('tag')}")
                    print(f"  Class: {t.get('className')}")
                    print(f"  data-cy: {t.get('dataCy')}")
                    print(f"  data-testid: {t.get('dataTestid')}")
                    print(f"  HTML (first 3000 chars): {t.get('html', '')[:3000]}")
                    print(f"  Text: {t.get('text', '')[:2000]}")

        # 7. All spans with amenities-item-text
        print("\n" + "=" * 80)
        print("All amenities-item-text spans")
        print("=" * 80)
        amenity_items = safe_eval(page, '.amenities-item-text', 
            "elements => elements.map(el => ({text: el.textContent?.trim(), className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid')}))")
        if amenity_items:
            for item in amenity_items:
                if item:
                    print(f"  Text: {item.get('text')}")
                    print(f"  Class: {item.get('className')}")
                    print(f"  data-cy: {item.get('dataCy')}")
                    print(f"  data-testid: {item.get('dataTestid')}")

        # 8. All elements with ldp- class names
        print("\n" + "=" * 80)
        print("All elements with ldp- class or data-cy")
        print("=" * 80)
        ldp_elements = safe_eval(page, '[class*="ldp-"], [data-cy^="ldp-"]', 
            "elements => elements.map(el => ({tag: el.tagName, className: el.className, dataCy: el.getAttribute('data-cy'), dataTestid: el.getAttribute('data-testid'), text: el.textContent?.trim().substring(0, 100)}))")
        if ldp_elements:
            for el in ldp_elements[:30]:
                if el and el.get('className'):
                    print(f"  <{el['tag']}> class='{el['className']}' data-cy='{el['dataCy']}' data-testid='{el['dataTestid']}'")
                    print(f"    Text: {el['text'][:100]}")

        # 9. Full HTML of the description container
        print("\n" + "=" * 80)
        print("Full description container HTML")
        print("=" * 80)
        desc_container = safe_eval_one(page, '[data-testid="description-container"]', "el => el.outerHTML")
        if desc_container:
            print(desc_container[:3000])

        # 10. Check for any JSON data in window.__INITIAL_STATE__ or similar
        print("\n" + "=" * 80)
        print("Checking window.__INITIAL_STATE__ or similar global variables")
        print("=" * 80)
        window_data = safe_eval(page, "body", "el => window.__INITIAL_STATE__ ? JSON.stringify(window.__INITIAL_STATE__).substring(0, 5000) : (window.__PRELOADED_STATE__ ? JSON.stringify(window.__PRELOADED_STATE__).substring(0, 5000) : 'None')")
        if window_data and isinstance(window_data, list):
            wd = window_data[0] if window_data else ""
            if wd and wd != 'None':
                print(f"  Found global state: {wd[:3000]}")
            else:
                print("  No window.__INITIAL_STATE__ found")
        
        # 11. Check all data-testid elements more carefully
        print("\n" + "=" * 80)
        print("All elements with data-testid containing 'amenity' or 'feature' or 'char'")
        print("=" * 80)
        feature_testids = safe_eval(page, '[data-testid*="amenity"], [data-testid*="feature"], [data-testid*="char"], [data-testid*="item"]', 
            "elements => elements.map(el => ({tag: el.tagName, dataTestid: el.getAttribute('data-testid'), className: el.className, text: el.textContent?.trim().substring(0, 150)}))")
        if feature_testids:
            for el in feature_testids:
                if el:
                    print(f"  Tag: {el.get('tag')}, data-testid: {el.get('dataTestid')}")
                    print(f"    Text: {el.get('text')[:150]}")

        browser.close()
        print("\n" + "=" * 80)
        print("DEEP INSPECTION COMPLETE")
        print("=" * 80)

if __name__ == "__main__":
    main()
