import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

COOKIES_FILE = Path("cookies.json")
SALES_URL = "https://vendorcentral.amazon.com/retail-analytics/dashboard/sales"

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=str(Path("chrome_profile").resolve()),
        headless=False, channel="msedge",
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

    print("\n>>> Abrí el modal 'Customize Columns' manualmente en el navegador")
    print(">>> Cuando el modal esté abierto, presioná ENTER acá\n")
    input("Presioná ENTER cuando el modal esté abierto...")

    # Inspeccionar kat-checkboxes con el modal abierto
    result = page.evaluate("""() => {
        function deepGetAll(root, tag) {
            let found = Array.from(root.querySelectorAll(tag));
            for (const el of root.querySelectorAll('*')) {
                if (el.shadowRoot) found = found.concat(deepGetAll(el.shadowRoot, tag));
            }
            return found;
        }
        const checkboxes = deepGetAll(document, 'kat-checkbox');
        const info = checkboxes.slice(0, 5).map((cb, i) => ({
            index: i,
            label: cb.getAttribute('label'),
            checked: cb.getAttribute('checked'),
            value: cb.getAttribute('value'),
            id: cb.id,
            html: cb.outerHTML.substring(0, 300)
        }));
        return JSON.stringify(info, null, 2);
    }""")
    print("=== kat-checkbox (primeros 5) ===")
    print(result)

    time.sleep(60)
    context.close()