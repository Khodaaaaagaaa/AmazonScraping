"""
debug_selects.py v3 — Busca elementos con texto Daily, Sourcing, Custom, Manufacturing
"""
import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

COOKIES_FILE = Path("cookies.json")
SALES_URL = "https://vendorcentral.amazon.com/retail-analytics/dashboard/sales"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(Path("chrome_profile").resolve()),
        headless=False,
        channel="msedge",
        args=["--disable-blink-features=AutomationControlled"],
    )
    page = context.new_page()

    raw = COOKIES_FILE.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'): raw = raw[3:]
    cookies = json.loads(raw.decode('utf-8'))
    cleaned = []
    for c in cookies:
        cc = {"name": c["name"], "value": c["value"],
              "domain": c.get("domain", ".amazon.com"), "path": c.get("path", "/"),
              "secure": c.get("secure", False), "httpOnly": c.get("httpOnly", False),
              "sameSite": c.get("sameSite", "None") or "None"}
        if cc["sameSite"] not in ("Strict","Lax","None"): cc["sameSite"] = "None"
        if c.get("expirationDate") and c["expirationDate"] > 0:
            cc["expires"] = int(c["expirationDate"])
        cleaned.append(cc)
    context.add_cookies(cleaned)

    page.goto(SALES_URL, timeout=40000)
    page.locator('h1:has-text("Sales")').wait_for(timeout=20000)
    time.sleep(3)

    # Buscar el dropdown de Time frame (el que actualmente dice "Custom")
    print("=== Dropdown Time frame (busco el que dice 'Custom') ===")
    for keyword in ["Custom", "Daily", "Time frame"]:
        els = page.locator(f'text="{keyword}"').all()
        for el in els:
            try:
                tag = el.evaluate("e => e.tagName")
                role = el.get_attribute("role") or ""
                cls = el.get_attribute("class") or ""
                outer = el.evaluate("e => e.outerHTML")[:300]
                print(f"  [{keyword}] tag={tag} role={role}")
                print(f"  HTML: {outer}")
                print()
            except: pass

    print("=== Dropdown Distributor View (el que dice 'Manufacturing') ===")
    for keyword in ["Manufacturing", "Sourcing", "Distributor"]:
        els = page.locator(f'text="{keyword}"').all()
        for el in els:
            try:
                tag = el.evaluate("e => e.tagName")
                role = el.get_attribute("role") or ""
                outer = el.evaluate("e => e.outerHTML")[:300]
                print(f"  [{keyword}] tag={tag} role={role}")
                print(f"  HTML: {outer}")
                print()
            except: pass

    # HTML completo del área de filtros
    print("=== HTML del contenedor de filtros ===")
    try:
        html = page.evaluate("""
            () => {
                const el = document.querySelector('h1');
                const container = el ? el.closest('div') : null;
                return container ? container.parentElement.innerHTML.substring(0, 3000) : 'no encontrado';
            }
        """)
        print(html)
    except Exception as e:
        print(f"Error: {e}")

    print("\n=== Esperando 60s ===")
    time.sleep(60)
    context.close()