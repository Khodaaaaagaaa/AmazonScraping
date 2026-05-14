"""
main.py — Amazon Vendor Central Sales Scraper (multi-cuenta)
"""

import logging
import sys
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from config import (
    START_DATE, END_DATE, OUTPUT_DIR, CHROME_PROFILE_DIR,
    SHAREPOINT_SITE_URL, SHAREPOINT_USER, SHAREPOINT_PASSWORD,
    ACCOUNTS
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("scraper.log", encoding="utf-8"),
    ]
)
logger = logging.getLogger(__name__)

COOKIES_FILE = Path("cookies.json")
SESSION_FLAG = Path(CHROME_PROFILE_DIR) / "session_ready.txt"


def load_cookies(context):
    raw = COOKIES_FILE.read_bytes()
    if raw.startswith(b'\xef\xbb\xbf'):
        raw = raw[3:]
    cookies = json.loads(raw.decode('utf-8'))
    cleaned = []
    for c in cookies:
        cc = {
            "name": c["name"], "value": c["value"],
            "domain": c.get("domain", ".amazon.com"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": c.get("sameSite", "None") or "None"
        }
        if cc["sameSite"] not in ("Strict", "Lax", "None"):
            cc["sameSite"] = "None"
        if c.get("expirationDate") and c["expirationDate"] > 0:
            cc["expires"] = int(c["expirationDate"])
        cleaned.append(cc)
    context.add_cookies(cleaned)
    logger.info(f"✓ {len(cleaned)} cookies cargadas.")


def verify_session(page) -> bool:
    logger.info("Verificando sesión con cookies...")
    page.goto("https://vendorcentral.amazon.com", timeout=20000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)
    current_url = page.url
    logger.info(f"URL tras cargar cookies: {current_url}")
    bad = ["signin", "ap/signin", "ap/mfa", "login"]
    if any(kw in current_url.lower() for kw in bad):
        logger.error("Las cookies no son válidas o expiraron.")
        logger.error("Cookies inválidas. Exportalas de nuevo desde Edge.")
        return False
    logger.info("✓ Sesión activa con cookies.")
    return True


def switch_account(page, account_name: str) -> bool:
    """Cambia la cuenta activa en Vendor Central."""
    logger.info(f"Cambiando a cuenta: {account_name}")
    try:
        # Buscar el dropdown de cuenta en el header
        page.goto("https://vendorcentral.amazon.com", timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(2)

        # El dropdown de cuenta está en el header
        account_dropdown = page.locator(f'text="{account_name}"').first
        if account_dropdown.count() > 0:
            logger.info(f"✓ Ya en la cuenta correcta: {account_name}")
            return True

        # Buscar el selector de cuenta (puede ser un <select> o KAT dropdown)
        selects = page.locator('select').all()
        for sel in selects:
            try:
                opts = sel.inner_text()
                if account_name in opts:
                    sel.select_option(label=account_name)
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    time.sleep(2)
                    logger.info(f"✓ Cuenta cambiada a: {account_name}")
                    return True
            except Exception:
                pass

        # Intentar via KAT dropdown
        js_open_dropdown_account = page.evaluate(f"""() => {{
            const slots = document.querySelectorAll('slot[name="selected-option"]');
            for (const slot of slots) {{
                let n = slot;
                while (n) {{
                    if (n.tagName && n.tagName.startsWith('KAT-')) {{ n.click(); return true; }}
                    n = n.parentElement || (n.getRootNode && n.getRootNode().host);
                }}
            }}
            return false;
        }}""")
        time.sleep(1)

        opt = page.locator(f'div.standard-option-name').filter(has_text=account_name).first
        if opt.count() > 0:
            opt.click()
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            time.sleep(2)
            logger.info(f"✓ Cuenta cambiada a: {account_name}")
            return True

        logger.warning(f"No se pudo cambiar a la cuenta: {account_name}")
        return False

    except Exception as e:
        logger.error(f"Error cambiando cuenta: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("Amazon Vendor Central — Sales Scraper (Multi-cuenta)")
    logger.info(f"Período : {START_DATE} → {END_DATE}")
    logger.info(f"Cuentas : {[a['name'] for a in ACCOUNTS]}")
    logger.info("=" * 60)

    if not COOKIES_FILE.exists():
        logger.error("No se encontró cookies.json — exportalas desde Edge.")
        sys.exit(1)

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    profile_path = str(Path(CHROME_PROFILE_DIR).resolve())

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=False,
                channel="msedge",
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                accept_downloads=True,
                downloads_path=str(Path(OUTPUT_DIR).resolve()),
            )
        except Exception:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                accept_downloads=True,
                downloads_path=str(Path(OUTPUT_DIR).resolve()),
            )

        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        try:
            logger.info("Cargando cookies...")
            load_cookies(context)

            if not verify_session(page):
                sys.exit(1)

            # Iterar sobre cada cuenta
            for account in ACCOUNTS:
                logger.info("\n" + "█"*60)
                logger.info(f"CUENTA: {account['name']}")
                logger.info("█"*60)

                # Cambiar a la cuenta correspondiente
                if not switch_account(page, account["name"]):
                    logger.warning(f"Saltando cuenta {account['name']}")
                    continue

                # Importar downloader con contexto de cuenta
                from downloader import download_all_reports
                download_all_reports(
                    page=page,
                    start=START_DATE,
                    end=END_DATE,
                    account=account,
                )

            logger.info("\n" + "█"*60)
            logger.info("✓ TODAS LAS CUENTAS PROCESADAS")

        except KeyboardInterrupt:
            logger.info("Interrumpido.")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            page.screenshot(path="debug_error.png")
            sys.exit(1)
        finally:
            context.close()

    logger.info("Scraper finalizado.")


if __name__ == "__main__":
    main()
