"""
downloader.py — Descarga los 8 reportes de Retail Analytics
"""

import time, random, logging, os, re
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import Page

from config import (
    OUTPUT_DIR, POLL_INTERVAL_SEC, REPORT_TIMEOUT_SEC, DELAY_BETWEEN_REQUESTS
)

logger = logging.getLogger(__name__)
BASE = "https://vendorcentral.amazon.com/retail-analytics/dashboard"

REPORT_URLS = {
    "sales":        f"{BASE}/sales",
    "realtime":     f"{BASE}/real-time-sales-v2",
    "inventory":    f"{BASE}/inventory",
    "traffic":      f"{BASE}/traffic",
    "forecasting":  f"{BASE}/forecasting",
    "df_forecast":  f"{BASE}/df-forecasting",
    "netppm":       f"{BASE}/net-ppm",
    "catalog":      f"{BASE}/product-catalog",
}


def random_delay():
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))

def setup_output_dir():
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)


# ── KAT dropdowns ─────────────────────────────────────────────────────────────

def js_open_dropdown(page: Page, current_value: str):
    page.evaluate(f"""() => {{
        function getAll(root) {{
            let all = [];
            const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            let n; while (n = w.nextNode()) {{ all.push(n); if (n.shadowRoot) all = all.concat(getAll(n.shadowRoot)); }}
            return all;
        }}
        for (const el of getAll(document)) {{
            if (el.tagName === 'SLOT' && el.name === 'selected-option' && el.textContent.includes('{current_value}')) {{
                let n = el;
                while (n) {{ if (n.tagName && n.tagName.startsWith('KAT-')) {{ n.click(); return; }} n = n.parentElement || (n.getRootNode && n.getRootNode().host); }}
            }}
        }}
    }}""")
    time.sleep(1.5)

def js_click_option(page: Page, text: str) -> bool:
    result = page.evaluate(f"""() => {{
        function getAll(root) {{
            let all = [];
            const w = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            let n; while (n = w.nextNode()) {{ all.push(n); if (n.shadowRoot) all = all.concat(getAll(n.shadowRoot)); }}
            return all;
        }}
        for (const el of getAll(document)) {{
            if (typeof el.className === 'string' && el.className.includes('standard-option-name') && el.textContent.trim() === '{text}') {{
                el.click(); return 'clicked';
            }}
        }}
        return 'not found';
    }}""")
    time.sleep(0.8)
    return result == 'clicked'

def kat_select(page: Page, current: str, desired: str) -> bool:
    logger.info(f"Dropdown: '{current}' → '{desired}'")
    js_open_dropdown(page, current)
    ok = js_click_option(page, desired)
    if not ok:
        time.sleep(0.5)
        ok = js_click_option(page, desired)
    return ok


# ── Fecha ──────────────────────────────────────────────────────────────────────

def set_date(page: Page, target_date: date):
    date_str = target_date.strftime("%m/%d/%Y")
    time.sleep(1)
    try:
        inputs = page.locator('input[type="text"]:visible').all()
        for inp in inputs:
            ph = (inp.get_attribute('placeholder') or '').lower()
            if 'search' in ph or 'asin' in ph:
                continue
            val = inp.input_value()
            inp.click(click_count=3)
            time.sleep(0.3)
            inp.type(date_str)
            time.sleep(0.3)
            inp.press('Escape')
            time.sleep(0.3)
            inp.press('Tab')
            time.sleep(0.5)
            logger.info(f"Fecha: {date_str} (era: '{val}')")
            return
        logger.warning("set_date: no input encontrado")
    except Exception as e:
        logger.warning(f"set_date error: {e}")


# ── Apply ──────────────────────────────────────────────────────────────────────

def click_apply(page: Page):
    try:
        apply = page.locator('button:has-text("Apply")').first
        apply.wait_for(timeout=5000, state="visible")
        # Esperar que se habilite
        for _ in range(15):
            if apply.is_enabled():
                break
            time.sleep(1)
        apply.click()
        logger.info("Apply clickeado.")
        time.sleep(3)
    except Exception as e:
        logger.warning(f"Apply error: {e}")


# ── Customize Columns ─────────────────────────────────────────────────────────

def columns_are_complete(page: Page) -> bool:
    col = page.locator('text=/Displaying \\d+ of \\d+ columns/i').first
    if col.count() == 0:
        return False
    txt = col.inner_text()
    nums = re.findall(r'\d+', txt)
    ok = len(nums) == 2 and nums[0] == nums[1]
    logger.info(f"Columnas: {txt} → {'✓' if ok else '✗'}")
    return ok

def select_all_columns(page: Page):
    logger.info("Customize Columns → Select All → Save...")
    page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.textContent && el.textContent.trim().startsWith('Customize Columns')) {
                el.click(); return;
            }
        }
    }""")
    time.sleep(2)
    try:
        cb = page.locator('kat-checkbox[label="Select All"]').first
        cb.wait_for(timeout=5000, state="visible")
        cb.click()
        logger.info("Select All clickeado.")
        time.sleep(0.8)
    except Exception as e:
        logger.warning(f"Select All error: {e}")
    page.locator('button:has-text("Save")').first.wait_for(timeout=5000, state="visible")
    page.locator('button:has-text("Save")').first.click()
    time.sleep(2)
    logger.info("✓ Columnas guardadas.")


# ── Excel + Download ───────────────────────────────────────────────────────────

def click_excel(page: Page) -> bool:
    try:
        excel = page.locator('button:has-text("Excel")').first
        excel.wait_for(timeout=8000, state="visible")
        excel.click()
        time.sleep(2)
        warn = page.locator('text=/exceeded/i, text=/superado/i').first
        if warn.count() > 0:
            logger.warning("Límite detectado — esperando 6 min...")
            time.sleep(360)
            excel.click()
            time.sleep(2)
        logger.info("✓ Excel solicitado.")
        return True
    except Exception as e:
        logger.error(f"Excel error: {e}")
        return False

def upload_file(filepath: str, account: dict = None):
    """Sube el archivo a la carpeta correcta de SharePoint."""
    try:
        import config as cfg
        from uploader import upload_to_sharepoint
        sp_base = account.get("sp_folder") if account else None
        upload_to_sharepoint(filepath, cfg, sp_base=sp_base)
    except Exception as e:
        logger.warning(f"No se pudo subir a SharePoint: {e}")


def download_from_panel(page: Page, report_name: str, filename: str,
                        account: dict = None) -> bool:
    """
    Busca en el panel Manage Downloads el reporte por nombre parcial
    y lo descarga guardándolo como filename en OUTPUT_DIR.
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    deadline = time.time() + REPORT_TIMEOUT_SEC

    logger.info(f"Esperando reporte '{report_name}' en Manage Downloads...")

    while time.time() < deadline:
        try:
            page.evaluate("document.getElementById('downloadManager').click()")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"No pude abrir panel: {e}")
            time.sleep(5)
            continue

        try:
            links = page.locator('a:has-text("Download")').all()
            logger.info(f"Links Download en panel: {len(links)}")
            for link in links:
                try:
                    row = link.locator('xpath=ancestor::div[4]').first
                    row_text = row.inner_text()
                    logger.info(f"Fila: {row_text[:120]}")
                    if report_name.lower() in row_text.lower():
                        logger.info(f"✓ Reporte encontrado. Descargando...")
                        with page.expect_download(timeout=60000) as dl_info:
                            link.click()
                        dl_info.value.save_as(filepath)
                        logger.info(f"✓ Guardado: {filepath}")
                        upload_file(filepath, account)
                        return True
                except Exception as e:
                    logger.debug(f"Link error: {e}")
        except Exception as e:
            logger.warning(f"Error leyendo panel: {e}")

        logger.info(f"No listo. Esperando {POLL_INTERVAL_SEC}s...")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SEC)

    logger.error(f"Timeout para {filename}")
    return False


# ── Reportes con fecha (loop diario) ──────────────────────────────────────────

def download_daily_report(page: Page, report_key: str, target_date: date,
                           file_suffix: str = "HoneyCanDoHK",
                           extra_filters: dict = None,
                           account: dict = None) -> bool:
    """
    Descarga un reporte diario (Sales, Inventory, Traffic, Net PPM).
    extra_filters: dict de {current_value: desired_value} para dropdowns adicionales.
    """
    url = REPORT_URLS[report_key]
    date_tag = f"{target_date.month}-{target_date.day}-{target_date.year}"
    filename = f"{report_key.upper()}_{target_date.strftime('%Y%m%d')}_{file_suffix}.xlsx"

    if os.path.exists(os.path.join(OUTPUT_DIR, filename)):
        logger.info(f"Ya existe: {filename}")
        return True

    logger.info(f"\n{'='*50}")
    logger.info(f"Reporte: {report_key.upper()} | Fecha: {target_date}")

    page.goto(url, timeout=40000)
    page.locator(f'h1:has-text("{report_key.replace("_"," ").title()}")').first.wait_for(timeout=20000)
    time.sleep(2)

    # Filtros base: Daily + fecha
    kat_select(page, "Custom", "Daily")
    time.sleep(1)
    set_date(page, target_date)

    # Filtros extra (ej: Distributor View, Program View)
    if extra_filters:
        for current, desired in extra_filters.items():
            kat_select(page, current, desired)

    click_apply(page)

    # Customize Columns si no están todas
    if not columns_are_complete(page):
        select_all_columns(page)
        # Re-aplicar filtros
        kat_select(page, "Custom", "Daily")
        time.sleep(1)
        set_date(page, target_date)
        if extra_filters:
            for current, desired in extra_filters.items():
                kat_select(page, current, desired)
        click_apply(page)

    if not click_excel(page):
        return False

    return download_from_panel(page, date_tag, filename, account=account)


def download_static_report(page: Page, report_key: str,
                            file_suffix: str = "HoneyCanDoHK",
                            filters: dict = None, h1_text: str = None,
                            account: dict = None) -> bool:
    """
    Descarga un reporte sin fecha (Real Time Sales, Forecasting, DF Forecast, Catalog).
    Se descarga una sola vez por ejecución.
    """
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    filename = f"{report_key.upper()}_{today}_{file_suffix}.xlsx"

    logger.info(f"\n{'='*50}")
    logger.info(f"Reporte estático: {report_key.upper()}")

    url = REPORT_URLS[report_key]
    page.goto(url, timeout=40000)

    h1 = h1_text or report_key.replace("_", " ").title()
    try:
        page.locator(f'h1:has-text("{h1}")').first.wait_for(timeout=20000)
    except Exception:
        time.sleep(3)
    time.sleep(2)

    # Aplicar filtros específicos
    if filters:
        for current, desired in filters.items():
            kat_select(page, current, desired)

    click_apply(page)
    time.sleep(2)

    # Customize Columns
    if not columns_are_complete(page):
        select_all_columns(page)
        if filters:
            for current, desired in filters.items():
                kat_select(page, current, desired)
        click_apply(page)

    if not click_excel(page):
        return False

    # Para reportes estáticos buscamos por tipo de reporte en el nombre
    search_term = {
        "realtime":    "Real_Time",
        "forecasting": "Forecasting",
        "df_forecast": "DF",
        "catalog":     "Catalog",
    }.get(report_key, report_key)

    return download_from_panel(page, search_term, filename, account=account)


# ── Orquestador principal ──────────────────────────────────────────────────────

def download_all_reports(page: Page, start: date, end: date, account: dict = None):
    setup_output_dir()

    # Configurar cuenta
    if account is None:
        from config import ACCOUNTS
        account = ACCOUNTS[0]

    file_suffix = account.get("file_suffix", "HoneyCanDoHK")
    has_df = account.get("has_df_forecast", True)

    all_dates = []
    d = start
    while d <= end:
        all_dates.append(d)
        d += timedelta(days=1)

    logger.info(f"Total días: {len(all_dates)} ({start} → {end})")
    logger.info(f"Cuenta: {account['name']} | Sufijo: {file_suffix}")
    logger.info("Reportes: Sales, Real Time Sales, Inventory, Traffic,")
    logger.info("          Forecasting, Direct Fulfillment, Net PPM, Catalog")

    total = 0

    # ── 1. Sales (diario) ──────────────────────────────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 1: SALES")
    for d in all_dates:
        ok = download_daily_report(page, "sales", d, file_suffix,
             extra_filters={"Manufacturing": "Sourcing"}, account=account)
        if ok: total += 1
        random_delay()

    # ── 2. Real Time Sales (estático, solo una vez) ────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 2: REAL TIME SALES")
    ok = download_static_report(page, "realtime", file_suffix,
         filters={"Trailing 24 hours": "Trailing 48 hours"},
         h1_text="Real Time Sales", account=account)
    if ok: total += 1

    # ── 3. Inventory (diario) ──────────────────────────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 3: INVENTORY")
    for d in all_dates:
        ok = download_daily_report(page, "inventory", d, file_suffix,
             extra_filters={"Manufacturing": "Sourcing"}, account=account)
        if ok: total += 1
        random_delay()

    # ── 4. Traffic (diario) ────────────────────────────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 4: TRAFFIC")
    for d in all_dates:
        # Traffic no tiene Distributor View
        ok = download_daily_report(page, "traffic", d, file_suffix, account=account)
        if ok: total += 1
        random_delay()

    # ── 5. Forecasting (estático) ──────────────────────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 5: FORECASTING")
    ok = download_static_report(page, "forecasting", file_suffix,
         filters={"Manufacturing": "Retail", "Mean Forecast": "Mean Forecast"},
         h1_text="Forecasting", account=account)
    if ok: total += 1

    # ── 6. Direct Fulfillment Forecasting (estático) ───────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 6: DIRECT FULFILLMENT FORECASTING")
    ok = download_static_report(page, "df_forecast", file_suffix,
         filters={"Region": "Warehouse", "Mean Forecast": "Mean Forecast"},
         h1_text="Direct Fulfillment", account=account) if has_df is not False else None
    if ok: total += 1

    # ── 7. Net PPM (diario) ────────────────────────────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 7: NET PPM")
    for d in all_dates:
        ok = download_daily_report(page, "netppm", d, file_suffix,
             extra_filters={"Manufacturing": "Sourcing"}, account=account)
        if ok: total += 1
        random_delay()

    # ── 8. Catalog (estático) ──────────────────────────────────────────────────
    logger.info("\n" + "█"*50)
    logger.info("SECCIÓN 8: CATALOG")
    ok = download_static_report(page, "catalog", file_suffix,
         filters={"Manufacturing": "Sourcing"},
         h1_text="Catalog", account=account)
    if ok: total += 1

    logger.info(f"\n{'█'*50}")
    logger.info(f"✓ COMPLETO. Total archivos descargados: {total}")


# Mantener compatibilidad con main.py que llama download_sales_range
def download_sales_range(page: Page, start: date, end: date):
    from config import ACCOUNTS
    download_all_reports(page, start, end, account=ACCOUNTS[0])
