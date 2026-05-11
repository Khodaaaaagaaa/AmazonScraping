"""
main.py — Usa cookies exportadas de Edge para saltear el login
"""

import logging
import sys
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from config import START_DATE, END_DATE, OUTPUT_DIR, CHROME_PROFILE_DIR
from downloader import download_sales_range

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


def load_cookies(context, cookies_file: Path):
    """Inyecta las cookies exportadas de Edge en el contexto de Playwright."""
    logger.info(f"Cargando cookies desde {cookies_file}...")
    raw = json.loads(cookies_file.read_text(encoding="utf-8"))

    cookies = []
    for c in raw:
        cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".amazon.com"),
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
        }
        # sameSite debe ser uno de: "Strict", "Lax", "None"
        same_site = c.get("sameSite", "None")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "None"
        cookie["sameSite"] = same_site

        # expires: ignorar si es -1 o session cookie
        if c.get("expirationDate") and c["expirationDate"] > 0:
            cookie["expires"] = int(c["expirationDate"])

        cookies.append(cookie)

    context.add_cookies(cookies)
    logger.info(f"✓ {len(cookies)} cookies cargadas.")


def verify_session(page) -> bool:
    """Verifica que la sesión esté activa con las cookies inyectadas."""
    logger.info("Verificando sesión con cookies...")
    page.goto("https://vendorcentral.amazon.com", timeout=30000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(3)

    current_url = page.url
    logger.info(f"URL tras cargar cookies: {current_url}")
    page.screenshot(path="debug_session_check.png")

    bad_keywords = ["signin", "ap/signin", "ap/mfa", "login", "ap/captcha"]
    if any(kw in current_url.lower() for kw in bad_keywords):
        logger.error("Las cookies no son válidas o expiraron.")
        return False

    logger.info("✓ Sesión activa con cookies.")
    return True


def main():
    logger.info("=" * 60)
    logger.info("Amazon Vendor Central — Sales Scraper")
    logger.info(f"Período : {START_DATE} → {END_DATE}")
    logger.info("=" * 60)

    # Verificar que existe el archivo de cookies
    if not COOKIES_FILE.exists():
        logger.error("No se encontró cookies.json")
        logger.error("Seguí estos pasos:")
        logger.error("1. Instalá Cookie Editor en Edge")
        logger.error("2. Andá a vendorcentral.amazon.com logueado")
        logger.error("3. Abrí Cookie Editor → Export → Export as JSON")
        logger.error("4. Guardá el contenido en cookies.json en esta carpeta")
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
            logger.info("Edge no disponible, usando Chromium...")
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
            window.chrome = { runtime: {} };
        """)

        try:
            # Inyectar cookies
            load_cookies(context, COOKIES_FILE)

            # Verificar sesión
            if not verify_session(page):
                logger.error("Cookies inválidas. Exportalas de nuevo desde Edge.")
                sys.exit(1)

            # Arrancar descarga
            download_sales_range(page, START_DATE, END_DATE)

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