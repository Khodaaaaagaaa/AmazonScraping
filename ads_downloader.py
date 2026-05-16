"""
ads_downloader.py — Descarga reportes de Sponsored Products (Amazon Advertising)

Flujo:
  1. Navegar a Amazon Advertising Console
  2. Ir a Campaign Manager → Reports
  3. Crear cada tipo de reporte con el rango de fechas
  4. Esperar hasta que genere (Search Term y Advertised tardan 30-90 min)
  5. Descargar

NOTA: La consola de Advertising usa la misma sesión Amazon que Vendor Central.
Si el contexto tiene cookies válidas de amazon.com, debería funcionar.
"""

import time, logging, os, json
from datetime import date, datetime
from pathlib import Path
from playwright.sync_api import Page, BrowserContext

from config import OUTPUT_DIR, ADS_REPORT_TIMEOUT_SEC, ADS_POLL_INTERVAL_SEC
from downloader import ensure_page, upload_file, setup_output_dir, _GET_ALL_FN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# URLs de entrada (Amazon Advertising Console)
# ---------------------------------------------------------------------------
ADS_ENTRY_URLS = [
    "https://advertising.amazon.com/cm/reports",
    "https://advertising.amazon.com/",
]

# Tipos de reporte Sponsored Products y sus timeouts
# Los lentos (Search Term, Advertised Product) pueden tardar 30-90 min
ADS_REPORT_TYPES = [
    {
        "label":       "Campaign",
        "file_name":   "campaign",
        "timeout_sec": 1800,   # 30 min
    },
    {
        "label":       "Ad group",
        "file_name":   "ad_group",
        "timeout_sec": 1800,
    },
    {
        "label":       "Targeting",
        "file_name":   "targeting",
        "timeout_sec": 3600,   # 60 min
    },
    {
        "label":       "Search term",
        "file_name":   "search_term",
        "timeout_sec": ADS_REPORT_TIMEOUT_SEC,  # 120 min por defecto
    },
    {
        "label":       "Advertised product",
        "file_name":   "advertised_product",
        "timeout_sec": ADS_REPORT_TIMEOUT_SEC,
    },
    {
        "label":       "Placement",
        "file_name":   "placement",
        "timeout_sec": 3600,
    },
]

# JavaScript shadow DOM helper (mismo patrón que downloader.py)
JS_FIND_CLICK = """(searchText, exactMatch) => {
""" + _GET_ALL_FN + """
    var all = getAll(document);
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var txt = (el.textContent || '').trim();
        var matches = exactMatch ? (txt === searchText) : (txt.indexOf(searchText) >= 0);
        if (!matches) continue;
        if (!el.offsetParent && el.tagName !== 'BODY') continue;
        var tag = el.tagName.toLowerCase();
        if (['a','button','span','div','li'].indexOf(tag) >= 0 ||
            (el.getAttribute && el.getAttribute('role') === 'button')) {
            el.click();
            return 'clicked:' + tag + ':' + txt.substring(0, 60);
        }
    }
    return 'not_found';
}"""

JS_ADS_CLICK_READY_DOWNLOAD = """() => {
""" + _GET_ALL_FN + """
    var all = getAll(document);

    // Estrategia 1: buscar fila con "Complete" / "Ready" y clicar Download en ella
    var statusWords = ['Complete', 'Ready', 'COMPLETE', 'READY', 'Completed'];
    var statusEls = all.filter(function(n) {
        var t = (n.textContent || '').trim();
        return statusWords.indexOf(t) >= 0;
    });

    function crossParent(el) {
        if (el.parentElement) return el.parentElement;
        var r = el.getRootNode();
        return (r && r !== document && r.host) ? r.host : null;
    }

    for (var ri = 0; ri < statusEls.length; ri++) {
        var ancestor = crossParent(statusEls[ri]);
        for (var up = 0; up < 10 && ancestor; up++) {
            var sub = getAll(ancestor);
            for (var si = 0; si < sub.length; si++) {
                var node = sub[si];
                var txt = (node.textContent || '').trim();
                if (txt !== 'Download' && txt !== 'download') continue;
                var tag = node.tagName.toLowerCase();
                if (['a', 'button', 'span'].indexOf(tag) >= 0) {
                    node.click();
                    return 'clicked_from_status';
                }
            }
            ancestor = crossParent(ancestor);
        }
    }

    // Estrategia 2: cualquier botón/link exacto "Download"
    for (var ai = 0; ai < all.length; ai++) {
        var node2 = all[ai];
        var txt2 = (node2.textContent || '').trim();
        if (txt2 !== 'Download') continue;
        var tag2 = node2.tagName.toLowerCase();
        if (['a', 'button'].indexOf(tag2) >= 0) {
            node2.click();
            return 'clicked_direct';
        }
    }

    var inProc = all.filter(function(n) {
        var t = (n.textContent || '').trim();
        return t === 'In progress' || t === 'In Progress' || t === 'Processing' || t === 'Pending';
    }).length;
    return JSON.stringify({not_ready: true, in_progress: inProc, ready: statusEls.length});
}"""


# ---------------------------------------------------------------------------
# Navegación a la consola de Advertising
# ---------------------------------------------------------------------------

def navigate_to_ads_reports(page: Page) -> bool:
    """
    Navega a la sección de reportes en Amazon Advertising Console.
    Retorna True si llegó a alguna página de reportes.
    """
    for url in ADS_ENTRY_URLS:
        try:
            logger.info(f"Intentando: {url}")
            page.goto(url, timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            time.sleep(3)

            cur = page.url.lower()
            # Si redirigió a sign-in, abortar este URL
            if "signin" in cur or "ap/signin" in cur or "login" in cur:
                logger.warning(f"Redirigió a login: {cur}")
                continue

            logger.info(f"URL actual: {page.url}")

            # Buscar y clicar "Reports" en la navegación si no estamos ya ahí
            if "reports" not in cur:
                for report_label in ["Reports", "Report center", "Reporting"]:
                    try:
                        result = page.evaluate(JS_FIND_CLICK, [report_label, True])
                        if "clicked" in result:
                            logger.info(f"✓ Cliqueado: {result}")
                            time.sleep(2)
                            break
                    except Exception:
                        pass

            return True
        except Exception as e:
            logger.warning(f"navigate_to_ads_reports ({url}): {e}")

    logger.error("No se pudo acceder a Amazon Advertising Console")
    return False


def select_ads_account(page: Page, account_name: str) -> bool:
    """
    Si hay múltiples perfiles de advertising, selecciona el correcto.
    """
    try:
        time.sleep(2)
        # Intentar encontrar el nombre de la cuenta en un selector de perfil
        result = page.evaluate(JS_FIND_CLICK, [account_name, False])
        if "clicked" in result:
            logger.info(f"✓ Cuenta ADS seleccionada: {result}")
            time.sleep(3)
            return True
        logger.info(f"Selector de cuenta ADS: {result}")
    except Exception as e:
        logger.warning(f"select_ads_account: {e}")
    return True  # Continuar aunque no se encontró (puede que ya esté seleccionada)


# ---------------------------------------------------------------------------
# Crear un reporte en la consola
# ---------------------------------------------------------------------------

def create_ads_report(page: Page, report_type: str,
                       start: date, end: date) -> bool:
    """
    Crea un reporte de Sponsored Products del tipo dado.
    Retorna True si el reporte fue solicitado.
    """
    start_str = start.strftime("%m/%d/%Y")
    end_str   = end.strftime("%m/%d/%Y")

    logger.info(f"Creando reporte ADS: {report_type} ({start_str} → {end_str})")

    try:
        # Clicar "Create report" o "+" o "Run report"
        created = False
        for label in ["Create report", "Create Report", "New report", "Run report", "+ Create"]:
            result = page.evaluate(JS_FIND_CLICK, [label, False])
            if "clicked" in result:
                logger.info(f"✓ Create: {result}")
                time.sleep(2)
                created = True
                break

        if not created:
            logger.warning("No se encontró botón 'Create report'")
            page.screenshot(path=f"debug_ads_create_{report_type}.png")
            return False

        # Seleccionar "Sponsored Products" si aparece el selector de tipo de campaña
        time.sleep(1)
        for sp_label in ["Sponsored Products", "Sponsored products"]:
            result = page.evaluate(JS_FIND_CLICK, [sp_label, True])
            if "clicked" in result:
                logger.info(f"✓ Sponsored Products: {result}")
                time.sleep(1)
                break

        # Seleccionar el tipo de reporte
        time.sleep(1)
        result = page.evaluate(JS_FIND_CLICK, [report_type, True])
        if "clicked" in result:
            logger.info(f"✓ Tipo: {result}")
        else:
            # Intento parcial
            result = page.evaluate(JS_FIND_CLICK, [report_type, False])
            logger.info(f"Tipo parcial: {result}")
        time.sleep(1)

        # Configurar rango de fechas
        # Intentar seleccionar "Custom" o similar
        for date_range_label in ["Custom date range", "Custom", "Date range"]:
            result = page.evaluate(JS_FIND_CLICK, [date_range_label, False])
            if "clicked" in result:
                logger.info(f"✓ Date range: {result}")
                time.sleep(1)
                break

        # Llenar fechas de inicio y fin
        try:
            date_inputs = page.locator('input[type="text"]:visible, input[type="date"]:visible').all()
            filled = 0
            for inp in date_inputs:
                if filled >= 2:
                    break
                try:
                    ph = (inp.get_attribute("placeholder") or "").lower()
                    val = inp.input_value() or ""
                    # Primera fecha visible = inicio, segunda = fin
                    target = start_str if filled == 0 else end_str
                    inp.click(click_count=3)
                    time.sleep(0.2)
                    inp.fill(target)
                    time.sleep(0.2)
                    inp.press("Tab")
                    time.sleep(0.3)
                    logger.info(f"Fecha {filled+1}: {target}")
                    filled += 1
                except Exception as e:
                    logger.debug(f"Date input {filled}: {e}")
        except Exception as e:
            logger.warning(f"Fechas ADS: {e}")

        # Clicar "Run" / "Create" / "Submit"
        time.sleep(1)
        submitted = False
        for submit_label in ["Run", "Create", "Submit", "Run report", "Create report"]:
            try:
                btn = page.locator(f'button:has-text("{submit_label}")').first
                if btn.count() > 0 and btn.is_visible() and btn.is_enabled():
                    btn.click()
                    logger.info(f"✓ Submit: {submit_label}")
                    time.sleep(3)
                    submitted = True
                    break
            except Exception:
                pass

        if not submitted:
            logger.warning("No se encontró botón Submit para el reporte ADS")
            page.screenshot(path=f"debug_ads_submit_{report_type}.png")
            return False

        logger.info(f"✓ Reporte {report_type} solicitado.")
        return True

    except Exception as e:
        logger.error(f"create_ads_report ({report_type}): {e}")
        page.screenshot(path=f"debug_ads_error_{report_type}.png")
        return False


# ---------------------------------------------------------------------------
# Esperar y descargar un reporte ADS
# ---------------------------------------------------------------------------

def wait_and_download_ads_report(page: Page, context: BrowserContext,
                                  report_type: str, filename: str,
                                  account: dict = None,
                                  timeout_sec: int = None) -> tuple:
    """
    Espera hasta que el reporte esté listo y lo descarga.
    Navega a la lista de reportes en cada ciclo para refrescar.
    Retorna (success, page).
    """
    filepath = os.path.join(OUTPUT_DIR, filename)
    timeout_sec = timeout_sec or ADS_REPORT_TIMEOUT_SEC
    deadline = time.time() + timeout_sec
    attempt = 0

    logger.info(f"Esperando reporte ADS '{report_type}' (timeout: {timeout_sec//60} min)...")

    while time.time() < deadline:
        attempt += 1
        remaining = int(deadline - time.time())
        logger.info(f"[ADS Intento {attempt}] '{report_type}' — quedan {remaining//60} min {remaining%60}s")

        page = ensure_page(context, page)

        # Navegar a la lista de reportes para refrescar estado
        try:
            navigate_to_ads_reports(page)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"navigate_ads_reports: {e}")
            time.sleep(ADS_POLL_INTERVAL_SEC)
            continue

        # Intentar descargar
        try:
            with page.expect_download(timeout=8000) as dl_info:
                result = page.evaluate(JS_ADS_CLICK_READY_DOWNLOAD)

            if result and "clicked" in str(result):
                dl = dl_info.value
                amazon_name = dl.suggested_filename
                logger.info(f"✓ ADS Descargado: {amazon_name}")
                dl.save_as(filepath)
                logger.info(f"✓ Guardado: {filepath}")
                upload_file(filepath, account)
                return True, page
            else:
                logger.info(f"Estado ADS: {result}")

        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str or "waiting" in err_str:
                logger.info(f"Reporte ADS no listo aún")
            else:
                logger.warning(f"wait_and_download_ads_report: {e}")

        wait = min(ADS_POLL_INTERVAL_SEC, max(30, int(deadline - time.time())))
        logger.info(f"Próximo chequeo en {wait//60}m {wait%60}s...")
        time.sleep(wait)

    logger.error(f"Timeout ADS ({timeout_sec//60} min) para '{filename}'")
    return False, page


# ---------------------------------------------------------------------------
# Orquestador principal — ADS
# ---------------------------------------------------------------------------

def download_all_ads_reports(page: Page, context: BrowserContext,
                               start: date, end: date,
                               account: dict = None) -> Page:
    """
    Descarga todos los reportes de Sponsored Products para una cuenta.
    Retorna la página activa al finalizar.
    """
    setup_output_dir()

    if account is None:
        from config import ACCOUNTS
        account = ACCOUNTS[0]

    file_suffix = account.get("file_suffix", "HoneyCanDoHK")
    today_str   = datetime.now().strftime("%Y%m%d")

    logger.info(f"\n{'█'*50}")
    logger.info(f"ADS REPORTS — {account['name']} | {start} → {end}")
    logger.info("█"*50)

    page = ensure_page(context, page)

    # Navegar a la consola de advertising
    if not navigate_to_ads_reports(page):
        logger.error("No se pudo acceder a Amazon Advertising. Saltando ADS reports.")
        return page

    # Seleccionar la cuenta correcta si hay múltiples perfiles
    select_ads_account(page, account["name"])

    total = 0

    # Fase 1: Solicitar todos los reportes primero
    logger.info("\n--- FASE 1: Solicitando reportes ---")
    requested = []
    for rpt in ADS_REPORT_TYPES:
        filename = f"ADS_{rpt['file_name'].upper()}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}_{file_suffix}.csv"
        filepath = os.path.join(OUTPUT_DIR, filename)

        if os.path.exists(filepath):
            logger.info(f"Ya existe: {filename}")
            continue

        # Navegar a reports antes de crear cada uno
        navigate_to_ads_reports(page)
        time.sleep(2)

        ok = create_ads_report(page, rpt["label"], start, end)
        if ok:
            requested.append(rpt)
            logger.info(f"✓ Solicitado: {rpt['label']}")
        else:
            logger.warning(f"✗ No se pudo solicitar: {rpt['label']}")

        time.sleep(3)

    if not requested:
        logger.warning("No se solicitó ningún reporte ADS")
        return page

    logger.info(f"\nSolicitados: {len(requested)} reportes. Esperando generación...")

    # Fase 2: Esperar y descargar cada reporte
    # Los reportes lentos (search_term, advertised_product) se esperan más
    logger.info("\n--- FASE 2: Descargando reportes ---")
    for rpt in requested:
        filename = f"ADS_{rpt['file_name'].upper()}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}_{file_suffix}.csv"

        logger.info(f"\n{'='*50}")
        logger.info(f"Esperando: {rpt['label']} (timeout: {rpt['timeout_sec']//60} min)")

        ok, page = wait_and_download_ads_report(
            page, context,
            rpt["label"], filename,
            account=account,
            timeout_sec=rpt["timeout_sec"],
        )
        if ok:
            total += 1

    logger.info(f"\n{'█'*50}\n✓ ADS completo. Descargados: {total}/{len(requested)}")
    return page
