"""
main.py — Amazon Vendor Central Scraper
         Selección interactiva de categoría (Retail / Ads / Ambos),
         reportes específicos y rango de fechas.
"""

import logging
import sys
import json
import time
from pathlib import Path
import pyotp
from playwright.sync_api import sync_playwright

from config import START_DATE, END_DATE, OUTPUT_DIR, CHROME_PROFILE_DIR, ACCOUNTS
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

# ── Menús ─────────────────────────────────────────────────────────────────────

RETAIL_REPORT_MENU = [
    ("sales",        "Sales"),
    ("realtime",     "Real Time Sales"),
    ("inventory",    "Inventory"),
    ("traffic",      "Traffic"),
    ("forecasting",  "Forecasting"),
    ("df_forecast",  "Direct Fulfillment Forecasting"),
    ("netppm",       "Net PPM"),
    ("catalog",      "Catalog"),
]

ADS_REPORT_MENU = [
    ("search_term",           "Search term"),
    ("targeting",             "Targeting"),
    ("advertised_product",    "Advertised product"),
    ("campaign",              "Campaign"),
    ("budget",                "Budget"),
    ("placement",             "Placement"),
    ("audience",              "Audience"),
    ("perf_over_time",        "Performance Over Time"),
    ("search_term_imp_share", "Search Term Impression Share"),
    ("gross_invalid_traffic", "Gross and Invalid Traffic"),
    ("prompts",               "Prompts"),
    ("video",                 "Video"),
]


def select_accounts_interactively() -> list:
    """
    Pregunta qué cuenta(s) de Amazon usar.
    Retorna lista de dicts de cuenta desde ACCOUNTS.
    """
    print("\n" + "═"*54)
    print("  Cuenta(s) de Amazon")
    print("═"*54)
    for i, acc in enumerate(ACCOUNTS, 1):
        print(f"  [{i}] {acc['name']}")
    print(f"  [3] Ambas cuentas")
    print("═"*54)
    raw = input("  Seleccionar [1]: ").strip()
    if raw == "2":
        print(f"  → {ACCOUNTS[1]['name']} seleccionado.\n")
        return [ACCOUNTS[1]]
    if raw == "3":
        print(f"  → Ambas cuentas seleccionadas.\n")
        return list(ACCOUNTS)
    print(f"  → {ACCOUNTS[0]['name']} seleccionado.\n")
    return [ACCOUNTS[0]]


def select_report_category_interactively() -> str:
    """
    Pregunta si se van a descargar reportes Retail, Ads o ambos.
    Retorna: "retail" | "ads" | "both"
    """
    print("\n" + "═"*54)
    print("  Tipo de reportes")
    print("═"*54)
    print("  [1] Retail")
    print("  [2] Ads (Sponsored Products)")
    print("  [3] Ambos (Retail + Ads)")
    print("═"*54)
    raw = input("  Seleccionar [1]: ").strip()
    if raw == "2":
        print("  → Ads seleccionado.\n")
        return "ads"
    if raw == "3":
        print("  → Retail + Ads seleccionados.\n")
        return "both"
    print("  → Retail seleccionado.\n")
    return "retail"


def select_reports_interactively():
    """
    Muestra el menú de los 8 reportes Retail.
    Devuelve 'all' o lista de claves.
    """
    print("\n" + "═"*54)
    print("  Reportes Retail disponibles:")
    print("═"*54)
    for i, (key, name) in enumerate(RETAIL_REPORT_MENU, 1):
        print(f"  [{i}] {name}")
    print("  [A] Todos los reportes")
    print("═"*54)
    raw = input("  Seleccionar (ej: '1,3,5' o 'A') [A]: ").strip()

    if not raw or raw.upper() == "A":
        print("  → Todos los reportes Retail seleccionados.\n")
        return "all"

    keys = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(RETAIL_REPORT_MENU):
                keys.append(RETAIL_REPORT_MENU[idx][0])

    if not keys:
        print("  → Selección inválida; usando todos los reportes Retail.\n")
        return "all"

    names = [name for key, name in RETAIL_REPORT_MENU if key in keys]
    print(f"  → Seleccionados: {', '.join(names)}\n")
    return keys


def select_ads_reports_interactively():
    """
    Muestra el menú de los 12 reportes de Ads (Sponsored Products).
    Devuelve 'all' o lista de claves.
    """
    print("\n" + "═"*54)
    print("  Reportes Ads disponibles (Sponsored Products):")
    print("═"*54)
    for i, (key, name) in enumerate(ADS_REPORT_MENU, 1):
        print(f"  [{i:2}] {name}")
    print("  [ A] Todos los reportes")
    print("═"*54)
    raw = input("  Seleccionar (ej: '1,3,5' o 'A') [A]: ").strip()

    if not raw or raw.upper() == "A":
        print("  → Todos los reportes Ads seleccionados.\n")
        return "all"

    keys = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1
            if 0 <= idx < len(ADS_REPORT_MENU):
                keys.append(ADS_REPORT_MENU[idx][0])

    if not keys:
        print("  → Selección inválida; usando todos los reportes Ads.\n")
        return "all"

    names = [name for key, name in ADS_REPORT_MENU if key in keys]
    print(f"  → Seleccionados Ads: {', '.join(names)}\n")
    return keys


def select_dates_interactively():
    """
    Muestra las fechas de config y permite cambiarlas (Retail).
    Devuelve (start_date, end_date).
    """
    from datetime import datetime as _dt
    print("\n" + "═"*54)
    print("  Rango de fechas — Retail")
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


def select_ads_dates_interactively():
    """
    Muestra el rango del mes actual (primer día → hoy) y permite cambiarlo.
    Devuelve (start_date, end_date).
    """
    from datetime import date as _d, datetime as _dt
    today       = _d.today()
    month_start = _d(today.year, today.month, 1)

    print("\n" + "═"*54)
    print("  Rango de fechas — Ads")
    print("═"*54)
    print(f"  Mes actual: {month_start}  →  {today}")
    raw = input("  ¿Usar estas fechas? [S/n]: ").strip().lower()

    if raw not in ("n", "no"):
        print(f"  → Usando: {month_start} → {today}\n")
        return month_start, today

    while True:
        try:
            s = input("  Fecha inicio (YYYY-MM-DD): ").strip()
            e = input("  Fecha fin    (YYYY-MM-DD): ").strip()
            start = _dt.strptime(s, "%Y-%m-%d").date()
            end   = _dt.strptime(e, "%Y-%m-%d").date()
            if start <= end:
                print(f"  → Fechas Ads: {start} → {end}\n")
                return start, end
            print("  ✗ La fecha inicio debe ser <= fecha fin.")
        except ValueError:
            print("  ✗ Formato inválido. Usar YYYY-MM-DD.")


# ── Cookies ───────────────────────────────────────────────────────────────────

def load_cookies(context, cookies_file: Path):
    logger.info(f"Cargando cookies desde {cookies_file}...")
    try:
        raw = json.loads(cookies_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        logger.warning("cookies.json vacío o inválido — se omite la carga.")
        return

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


def auto_login(page, context) -> bool:
    """
    Completa el login en Amazon VC usando email, password y TOTP.
    Misma lógica que test_login.py: screenshots en cada paso para diagnóstico.
    Si tiene éxito guarda las cookies nuevas en cookies.json.
    Retorna True si la sesión quedó activa.
    """
    from config import EMAIL, PASSWORD, TOTP_SECRET

    logger.info("Navegando a Vendor Central...")
    page.goto("https://vendorcentral.amazon.com", timeout=30000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(2)

    url = page.url
    logger.info(f"URL inicial: {url}")

    # Si ya está logueado no hacer nada
    if not any(k in url.lower() for k in ["signin", "ap/signin", "login"]):
        logger.info("✓ Ya hay sesión activa — no se necesita login.")
        return True

    # ── Paso 1: Email ─────────────────────────────────────────────────────────
    logger.info("Ingresando email...")
    page.screenshot(path="debug_login_01_email.png")
    try:
        page.fill('input[type="email"], input[name="email"]', EMAIL, timeout=10000)
        page.click('input[type="submit"], #continue', timeout=8000)
        time.sleep(2)
        # Edge abre diálogo de Windows Hello / passkey después del email.
        # Escape lo descarta sin importar si apareció o no.
        page.keyboard.press('Escape')
        time.sleep(0.5)
    except Exception as e:
        logger.error(f"Auto-login: error en email — {e}")
        page.screenshot(path="debug_login_01_email_error.png")
        return False

    # ── Paso 2: Password ──────────────────────────────────────────────────────
    logger.info("Ingresando password...")
    page.screenshot(path="debug_login_02_password.png")
    try:
        page.fill('input[type="password"], input[name="password"]', PASSWORD, timeout=10000)
        # form.submit() bypasses todos los event listeners (incluyendo passkey interceptor)
        page.evaluate("document.getElementById('signInSubmit').form.submit()")
        # Esperar a que la URL cambie de ap/signin (puede redirigir a MFA o a VC)
        try:
            page.wait_for_url(lambda url: "ap/signin" not in url, timeout=15000)
        except Exception:
            pass
        time.sleep(1)
    except Exception as e:
        logger.error(f"Auto-login: error en password — {e}")
        page.screenshot(path="debug_login_02_password_error.png")
        return False

    # ── Paso 3: OTP / MFA ─────────────────────────────────────────────────────
    url_after_pw = page.url
    logger.info(f"URL tras password: {url_after_pw}")
    page.screenshot(path="debug_login_03_mfa.png")

    mfa_keywords = ["mfa", "otp", "auth", "code", "claimspicker", "accountfixup"]
    if any(k in url_after_pw.lower() for k in mfa_keywords):
        try:
            otp_code = pyotp.TOTP(TOTP_SECRET).now()
            logger.info(f"OTP generado: {otp_code}")
            page.fill('input[type="text"], input[name="otpCode"], input[id*="otp"]',
                      otp_code, timeout=10000)
            page.click('input[type="submit"], button[type="submit"]', timeout=8000)
            time.sleep(3)
        except Exception as e:
            logger.error(f"Auto-login: error en OTP — {e}")
            page.screenshot(path="debug_login_03_mfa_error.png")
            return False
    else:
        logger.info("No se detectó pantalla MFA — saltando paso OTP.")

    # ── Verificar y guardar cookies ───────────────────────────────────────────
    page.screenshot(path="debug_login_04_result.png")
    final_url = page.url
    logger.info(f"URL final: {final_url}")

    bad = ["signin", "ap/signin", "ap/mfa", "login", "ap/captcha"]
    if any(k in final_url.lower() for k in bad):
        logger.error(f"Auto-login falló — todavía en página de autenticación. URL: {final_url}")
        return False

    cookies = context.cookies()
    COOKIES_FILE.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"✓ Auto-login exitoso — {len(cookies)} cookies guardadas.")
    return True


def verify_session(page) -> bool:
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
    logger.info("Amazon Vendor Central — Retail + Ads Scraper")
    logger.info("=" * 60)

    if not COOKIES_FILE.exists():
        logger.warning("No se encontró cookies.json — se intentará auto-login.")

    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)
    profile_path = str(Path(CHROME_PROFILE_DIR).resolve())

    # ── Selección interactiva (antes de abrir el browser) ─────────────────────
    selected_accounts = select_accounts_interactively()
    report_category   = select_report_category_interactively()

    retail_reports = retail_start = retail_end = None
    ads_reports    = ads_start    = ads_end    = None

    if report_category in ("retail", "both"):
        retail_reports = select_reports_interactively()
        retail_start, retail_end = select_dates_interactively()

    if report_category in ("ads", "both"):
        ads_reports = select_ads_reports_interactively()
        ads_start, ads_end = select_ads_dates_interactively()

    account_names = [a["name"] for a in selected_accounts]
    logger.info(f"Cuentas    : {', '.join(account_names)}")
    logger.info(f"Categoría  : {report_category.upper()}")
    if retail_reports is not None:
        logger.info(f"Retail     : {'todos (8)' if retail_reports == 'all' else retail_reports}")
        logger.info(f"Período    : {retail_start} → {retail_end}")
    if ads_reports is not None:
        logger.info(f"Ads        : {'todos (12)' if ads_reports == 'all' else ads_reports}")
        logger.info(f"Período Ads: {ads_start} → {ads_end}")

    # ── Browser ───────────────────────────────────────────────────────────────
    with sync_playwright() as p:
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=WebAuthentication",
            "--password-store=basic",  # evita el diálogo de Windows Hello / Credential Manager
        ]
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=False,
                channel="msedge",
                args=browser_args,
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
                args=browser_args,
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
            if COOKIES_FILE.exists():
                load_cookies(context, COOKIES_FILE)

            if not verify_session(page):
                logger.warning("Cookies expiradas o inválidas — iniciando auto-login...")
                logged_in = False
                for attempt in range(1, 4):
                    logger.info(f"Auto-login intento {attempt}/3...")
                    if auto_login(page, context):
                        logged_in = True
                        break
                    logger.warning(f"Intento {attempt} fallido.")
                    time.sleep(5)
                    page.goto("https://vendorcentral.amazon.com", timeout=30000)
                    time.sleep(2)

                if not logged_in:
                    logger.error("Auto-login falló en los 3 intentos. Revisá debug_login_*.png")
                    sys.exit(1)

            # ── Iterar sobre las cuentas seleccionadas ────────────────────────
            for account in selected_accounts:
                logger.info("=" * 60)
                logger.info(f"CUENTA: {account['name']}")
                logger.info("=" * 60)

                # ── Retail ────────────────────────────────────────────────────
                if report_category in ("retail", "both"):
                    page = download_all_reports(
                        page=page,
                        start=retail_start,
                        end=retail_end,
                        context=context,
                        reports_to_run=retail_reports,
                        account=account,
                    )

                # ── Ads ───────────────────────────────────────────────────────
                if report_category in ("ads", "both"):
                    from ads_downloader import download_all_ads_reports
                    page = download_all_ads_reports(
                        page=page,
                        context=context,
                        start=ads_start,
                        end=ads_end,
                        reports_to_run=ads_reports,
                        account=account,
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
