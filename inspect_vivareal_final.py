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

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={"Accept": "text/html", "Accept-Language": "pt-BR,pt;q=0.9"}
    )
    page = context.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(3000)

    # 1. Click "Mostrar mais" to expand and see what's revealed
    print("=" * 80)
    print("CLICKING 'Mostrar mais' IN AMENITIES SECTION")
    print("=" * 80)
    try:
        page.click('[data-cy="ldp-TextCollapse-btn"]', timeout=10000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  Could not click: {e}")

    # Get the full amenities list HTML after click
    print("\nFull amenities-list HTML after click:")
    amenities_html = safe_eval_one(page, '[data-testid="amenities-list"]', "el => el.outerHTML")
    if amenities_html:
        print(amenities_html[:5000])

    # 2. Get the Condomínio tab panel content
    print("\n" + "=" * 80)
    print("CONDOMÍNIO TAB CONTENT")
    print("=" * 80)
    condo_panel = safe_eval_one(page, '#panel-sectionAmenities', "el => el.outerHTML")
    if condo_panel:
        print(condo_panel[:5000])
    
    # Also try clicking the Condomínio tab
    print("\nTrying to click Condomínio tab...")
    try:
        page.click('[id="sectionAmenities"]', timeout=5000)
        page.wait_for_timeout(2000)
        condo_panel_after = safe_eval_one(page, '#panel-sectionAmenities', "el => el.outerHTML")
        if condo_panel_after:
            print(f"\nCondomínio panel after click (first 5000 chars):")
            print(condo_panel_after[:5000])
    except Exception as e:
        print(f"  Could not click Condomínio tab: {e}")

    # 3. Get all text from the olx-tabs panels
    print("\n" + "=" * 80)
    print("ALL TAB PANEL CONTENT")
    print("=" * 80)
    panels = safe_eval(page, '.olx-tabs__tabpanel', "elements => elements.map(el => ({id: el.id, className: el.className, text: el.textContent?.trim(), html: el.outerHTML?.substring(0, 3000)}))")
    if panels and isinstance(panels, list):
        for i, panel in enumerate(panels):
            if panel:
                print(f"\n  Panel #{i}: id={panel.get('id')}")
                print(f"    Class: {panel.get('className')}")
                print(f"    Text: {panel.get('text')[:500]}")
                print(f"    HTML (first 2000 chars): {panel.get('html', '')[:2000]}")

    # 4. Check for any window data that might contain amenities
    print("\n" + "=" * 80)
    print("WINDOW DATA CHECK")
    print("=" * 80)
    window_state = safe_eval_one(page, "body", "el => { try { return window.__PRELOADED_STATE__ ? JSON.stringify(window.__PRELOADED_STATE__).substring(0, 5000) : (window.__INITIAL_STATE__ ? JSON.stringify(window.__INITIAL_STATE__).substring(0, 5000) : 'None'); } catch(e) { return 'Error: ' + e.message; } }")
    if window_state and window_state != 'None':
        print(f"  Found: {window_state[:3000]}")
    else:
        print("  No window state found")

    # 5. Check dmData for amenities
    print("\n" + "=" * 80)
    print("dmData CHECK")
    print("=" * 80)
    dm_data = safe_eval_one(page, "body", "el => { try { return window.dmData ? JSON.stringify(window.dmData).substring(0, 3000) : 'None'; } catch(e) { return 'Error: ' + e.message; } }")
    if dm_data and dm_data != 'None':
        print(f"  dmData: {dm_data[:3000]}")
    else:
        print("  No dmData found")

    # 6. Get ALL script tags with JSON content that might have amenities
    print("\n" + "=" * 80)
    print("ALL JSON-CONTAINING SCRIPTS")
    print("=" * 80)
    scripts = safe_eval(page, 'script', "elements => elements.map(el => ({type: el.getAttribute('type') || 'unknown', text: el.textContent?.substring(0, 2000)}))")
    if scripts and isinstance(scripts, list):
        for i, s in enumerate(scripts):
            if not s:
                continue
            text = s.get('text', '') or ''
            text_lower = text.lower()
            if any(kw in text_lower for kw in ['amenities', 'privativeitems', 'commonitems', 'caracteristicas', 'comodidades', 'diferenciais', 'lazer', 'infraestrutura']):
                if len(text) > 10 and (text.strip().startswith('{') or text.strip().startswith('[')):
                    try:
                        parsed = json.loads(text)
                        print(f"\n  Script #{i} (parsed JSON):")
                        print(f"    Keys: {list(parsed.keys()) if isinstance(parsed, dict) else 'array'}")
                        flat = json.dumps(parsed, indent=2, ensure_ascii=False)
                        for kw in ['amenities', 'features', 'privativeItems', 'commonItems', 'itens']:
                            if kw.lower() in flat.lower():
                                idx = flat.lower().find(kw.lower())
                                print(f"    *** Found '{kw}' at position {idx}")
                                print(f"    Context: {flat[max(0,idx-50):idx+200]}")
                    except json.JSONDecodeError:
                        print(f"\n  Script #{i}: Not valid JSON, first 500 chars: {text[:500]}")

    # 7. Get the full page HTML around the amenities section
    print("\n" + "=" * 80)
    print("FULL AMENITIES SECTION HTML (from DOM)")
    print("=" * 80)
    full_amenity_section = safe_eval_one(page, '.olx-tabs', "el => el.outerHTML")
    if full_amenity_section:
        print(full_amenity_section[:8000])

    browser.close()
    print("\n" + "=" * 80)
    print("COMPLETE INSPECTION DONE")
    print("=" * 80)
