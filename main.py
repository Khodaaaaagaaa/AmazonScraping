"""
main.py — Amazon Vendor Central Scraper
         Selección interactiva de reportes y rango de fechas
"""

import logging
import sys
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

from config import START_DATE, END_DATE, OUTPUT_DIR, CHROME_PROFILE_DIR
from downloader import download_all_reports

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

# ── Menú de reportes ──────────────────────────────────────────────────────────

REPORT_MENU = [
    ("sales",        "Sales"),
    ("realtime",     "Real Time Sales"),
    ("inventory",    "Inventory"),
    ("traffic",      "Traffic"),
    ("forecasting",  "Forecasting"),
    ("df_forecast",  "Direct Fulfillment Forecasting"),
    ("netppm",       "Net PPM"),
    ("catalog",      "Catalog"),
]


def select_reports_interactively():
    """
    Muestra el menú de los 8 reportes disponibles.
    Devuelve 'all' o una lista de claves seleccionadas.
    """
    print("\n" + "═"*54)
    print("  Reportes disponibles:")
    print("═"*54)
    for i, (key, name) in enumerate(REPORT_MENU, 1):
        print(f"  [{i}] {name}")
    print("  [A] Todos los reportes")
    print("═"*54)
    raw = input("  Seleccionar (ej: '1,3,5' o 'A') [A]: ").strip()

    if not raw or raw.upper() == "A":
        print("  → Todos los reportes seleccionados.\n")
        return "all"

    keys = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(REPORT_MENU):
                keys.append(REPORT_MENU[idx][0])

    if not keys:
        print("  → Selección inválida; usando todos los reportes.\n")
        return "all"

    names = [name for key, name in REPORT_MENU if key in keys]
    print(f"  → Seleccionados: {', '.join(names)}\n")
    return keys


def select_dates_interactively():
    """
    Muestra las fechas de config y permite cambiarlas.
    Devuelve (start_date, end_date).
    """
    from datetime import datetime as _dt
    print("\n" + "═"*54)
    print("  Rango de fechas")
    print("═"*54)
    print(f"  Config actual: {START_DATE}  →  {END_DATE}")
    raw = input("  ¿Usar estas fechas? [S/n]: ").strip().lower()

    if raw not in ("n", "no"):
        print(f"  → Usando: {START_DATE} → {END_DATE}\n")
        return START_DATE, END_DATE

    while True:
        try:
            s = input("  Fecha inicio (YYYY-MM-DD): ").strip()
            e = input("  Fecha fin    (YYYY-MM-DD): ").strip()
            start = _dt.strptime(s, "%Y-%m-%d").date()
            end   = _dt.strptime(e, "%Y-%m-%d").date()
            if start <= end:
                print(f"  → Fechas: {start} → {end}\n")
                return start, end
            print("  ✗ La fecha inicio debe ser <= fecha fin.")
        except ValueError:
            print("  ✗ Formato inválido. Usar YYYY-MM-DD (ej: 2026-01-15).")


# ── Cookies ───────────────────────────────────────────────────────────────────

def load_cookies(context, cookies_file: Path):
    """Inyecta las cookies exportadas de Edge en el contexto de Playwright."""
    logger.info(f"Cargando cookies desde {cookies_file}...")
    raw = json.loads(cookies_file.read_text(encoding="utf-8"))

    cookies = []
    for c in raw:
        cookie = {
            "name":     c["name"],
            "value":    c["value"],
            "domain":   c.get("domain", ".amazon.com"),
            "path":     c.get("path", "/"),
            "secure":   c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
        }
        same_site = c.get("sameSite", "None")
        if same_site not in ("Strict", "Lax", "None"):
            same_site = "None"
        cookie["sameSite"] = same_site
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


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("Amazon Vendor Central — Retail Scraper")
    logger.info("=" * 60)

    if not COOKIES_FILE.exists():
        logger.error("No se encontró cookies.json")
        logger.error("1. Instalar Cookie Editor en Edge")
        logger.error("2. Ir a vendorcentral.amazon.com logueado")
        logger.error("3. Abrir Cookie Editor -> Export -> Export as JSON")
        logger.error("4. Guardar el contenido en cookies.json en esta carpeta")
        sys.exit(1)

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    profile_path = str(Path(CHROME_PROFILE_DIR).resolve())

    # ── Selección interactiva (antes de abrir el browser) ─────────────────────
    selected_reports = select_reports_interactively()
    start_date, end_date = select_dates_interactively()

    logger.info(f"Período  : {start_date} → {end_date}")
    logger.info(f"Reportes : {'todos (8)' if selected_reports == 'all' else selected_reports}")

    # ── Browser ───────────────────────────────────────────────────────────────
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
            load_cookies(context, COOKIES_FILE)

            if not verify_session(page):
                logger.error("Cookies inválidas. Exportalas de nuevo desde Edge.")
                sys.exit(1)

            download_all_reports(
                page=page,
                start=start_date,
                end=end_date,
                context=context,
                reports_to_run=selected_reports,
            )

        except KeyboardInterrupt:
            logger.info("Interrumpido por el usuario.")
        except Exception as e:
            logger.error(f"Error: {e}", exc_info=True)
            try:
                page.screenshot(path="debug_error.png")
            except Exception:
                pass
            sys.exit(1)
        finally:
            context.close()

    logger.info("Scraper finalizado.")


if __name__ == "__main__":
    main()
