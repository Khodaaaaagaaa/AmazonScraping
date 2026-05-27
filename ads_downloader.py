"""
ads_downloader.py — Descarga reportes de Sponsored Products (Amazon Advertising)

Flujo:
  1. Navegar a Amazon Advertising Console → Sponsored ads reports
  2. FASE 1: Crear los reportes solicitados uno por uno
  3. FASE 2: Esperar y descargar cada reporte cuando esté listo
"""

import time, logging, os, json, re, requests
from datetime import date, datetime, timedelta
from pathlib import Path
from playwright.sync_api import Page, BrowserContext

from config import OUTPUT_DIR, ADS_REPORT_TIMEOUT_SEC, ADS_POLL_INTERVAL_SEC, ACCOUNT_NAME, ACCOUNTS
from downloader import ensure_page, upload_file, setup_output_dir, _GET_ALL_FN

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Los 12 tipos de reporte
# ---------------------------------------------------------------------------
ADS_REPORT_TYPES = [
    {"key": "search_term",            "label": "Search term",                  "mrc": True,  "show_biz": None,  "timeout_sec": ADS_REPORT_TIMEOUT_SEC},
    {"key": "targeting",              "label": "Targeting",                    "mrc": True,  "show_biz": None,  "timeout_sec": ADS_REPORT_TIMEOUT_SEC},
    {"key": "advertised_product",     "label": "Advertised product",           "mrc": True,  "show_biz": None,  "timeout_sec": ADS_REPORT_TIMEOUT_SEC},
    {"key": "campaign",               "label": "Campaign",                     "mrc": True,  "show_biz": None,  "timeout_sec": 1800},
    {"key": "budget",                 "label": "Budget",                       "mrc": True,  "show_biz": None,  "timeout_sec": 1800},
    {"key": "placement",              "label": "Placement",                    "mrc": True,  "show_biz": False, "timeout_sec": 1800},
    {"key": "audience",               "label": "Audience",                     "mrc": False, "show_biz": None,  "timeout_sec": 1800},
    {"key": "perf_over_time",         "label": "Performance Over Time",        "mrc": True,  "show_biz": None,  "timeout_sec": 1800},
    {"key": "search_term_imp_share",  "label": "Search Term Impression Share", "mrc": False, "show_biz": None,  "timeout_sec": 1800},
    {"key": "gross_invalid_traffic",  "label": "Gross and Invalid Traffic",    "mrc": True,  "show_biz": None,  "timeout_sec": 1800},
    {"key": "prompts",                "label": "Prompts",                      "mrc": False, "show_biz": None,  "timeout_sec": 1800},
    {"key": "video",                  "label": "Video",                        "mrc": False, "show_biz": None,  "timeout_sec": 1800},
]

# ---------------------------------------------------------------------------
# JavaScript helpers
# ---------------------------------------------------------------------------

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

# Obtiene los meses visibles en el calendar picker (ej: [{month:4, year:2026}, {month:5, year:2026}])
JS_GET_CALENDAR_MONTHS = """() => {
    var MONTHS_RE = /^(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(\\d{4})/;
    var MONTH_NAMES = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"];
    var result = [];
    var seen = {};
    var candidates = document.querySelectorAll('button, span, div, h4, h3, [role="heading"]');
    for (var i = 0; i < candidates.length; i++) {
        var el = candidates[i];
        var txt = (el.textContent || '').trim();
        if (txt.length < 8 || txt.length > 25) continue;
        var m = txt.match(MONTHS_RE);
        if (m && el.childElementCount < 3) {
            var key = m[1] + '-' + m[2];
            if (!seen[key]) {
                seen[key] = true;
                result.push({month: MONTH_NAMES.indexOf(m[1]) + 1, year: parseInt(m[2])});
            }
        }
    }
    return JSON.stringify(result);
}"""

# Hace click en un día del calendario por aria-label o por número de día dentro del mes correcto
JS_CLICK_CALENDAR_DAY = """(targetDay, targetMonth, targetYear) => {
    var MONTH_NAMES = ["January","February","March","April","May","June",
                       "July","August","September","October","November","December"];
    var monthName = MONTH_NAMES[targetMonth - 1];
    var dayStr = String(targetDay);

    // Intento 1: aria-label que incluya el mes, día y año
    var all = document.querySelectorAll('button, td, [role="gridcell"], [role="button"]');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var aria = (el.getAttribute('aria-label') || '');
        if (aria.includes(monthName) && aria.includes(dayStr) && aria.includes(String(targetYear))) {
            if (!el.disabled && el.getAttribute('aria-disabled') !== 'true') {
                el.click();
                return 'clicked_aria:' + aria;
            }
        }
    }

    // Intento 2: celda con texto exacto del día, dentro de un padre que menciona el mes/año
    var cells = document.querySelectorAll('td, [role="gridcell"], button');
    for (var i = 0; i < cells.length; i++) {
        var cell = cells[i];
        var txt = (cell.textContent || '').trim();
        if (txt !== dayStr) continue;
        if (cell.disabled || cell.getAttribute('aria-disabled') === 'true') continue;

        var parent = cell.parentElement;
        for (var depth = 0; depth < 12 && parent; depth++) {
            var pTxt = (parent.textContent || '').substring(0, 300);
            if (pTxt.includes(monthName) && pTxt.includes(String(targetYear))) {
                cell.click();
                return 'clicked_cell:' + monthName + ' ' + dayStr + ' ' + targetYear;
            }
            parent = parent.parentElement;
        }
    }
    return 'not_found:' + monthName + ' ' + dayStr + ' ' + targetYear;
}"""

# Encuentra y hace click en el botón de descarga (ícono ↓) de la fila correcta.
# Estrategia 1: match EXACTO en columna "Report type" (evita confundir
#   "Search term" con "Search Term Impression Share").
# Estrategia 2: match por nombre del reporte "Sponsored Products X report".
# Solo hace click si la fila tiene fecha en "Last run" (reporte completado).
JS_ADS_CLICK_DOWNLOAD_BY_TYPE = """(reportTypeLabel) => {
    var labelLower = reportTypeLabel.toLowerCase();
    var reportName = "sponsored products " + labelLower + " report";
    var matchingRows = [];

    // Estrategia 1: columna "Report type" — match EXACTO
    var allCells = document.querySelectorAll('td, [role="cell"]');
    for (var ci = 0; ci < allCells.length; ci++) {
        var cell = allCells[ci];
        var ct = (cell.textContent || '').trim().toLowerCase();
        if (ct === labelLower && ct.length >= 3) {
            var rowEl = cell.closest('tr, [role="row"]');
            if (rowEl && matchingRows.indexOf(rowEl) === -1) matchingRows.push(rowEl);
        }
    }

    // Estrategia 2: link con el nombre exacto del reporte
    if (matchingRows.length === 0) {
        var links = document.querySelectorAll('a, [role="link"]');
        for (var li = 0; li < links.length; li++) {
            var lt = (links[li].textContent || '').trim().toLowerCase();
            if (lt === reportName) {
                var rowEl = links[li].closest('tr, [role="row"]');
                if (rowEl && matchingRows.indexOf(rowEl) === -1) matchingRows.push(rowEl);
            }
        }
    }

    if (matchingRows.length === 0) {
        return JSON.stringify({status:'no_rows', label:reportTypeLabel});
    }

    // Para cada fila candidata: debe tener fecha en "Last run" (reporte completado)
    for (var ri = 0; ri < matchingRows.length; ri++) {
        var row    = matchingRows[ri];
        var rowTxt = (row.textContent || '');

        var hasDate = /\\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\\b/.test(rowTxt);
        if (!hasDate) continue;

        // ── Estrategia 1: enlace cuyo href contiene "download-report" ───────
        var dlBtn = row.querySelector('a[href*="download-report"]');
        if (dlBtn) {
            dlBtn.click();
            return JSON.stringify({status:'clicked', label:reportTypeLabel, via:'href-download-report', href:(dlBtn.href||'').substring(0,80)});
        }

        // ── Estrategia 2: ícono storm-ui con data-testid → subir al <a> padre ─
        var dlIcon = row.querySelector('i[data-testid="storm-ui-icon-download"]');
        if (dlIcon) {
            var parent = dlIcon.parentElement;
            for (var depth = 0; depth < 5 && parent && parent !== row; depth++) {
                if (parent.tagName.toLowerCase() === 'a') {
                    parent.click();
                    return JSON.stringify({status:'clicked', label:reportTypeLabel, via:'storm-ui-icon-parent-a'});
                }
                parent = parent.parentElement;
            }
            dlIcon.click();
            return JSON.stringify({status:'clicked', label:reportTypeLabel, via:'storm-ui-icon-direct'});
        }

        // ── Estrategia 3: cualquier <a> o botón con "download" en href/aria ──
        var interactive = row.querySelectorAll('a, button, [role="button"]');
        for (var ii = 0; ii < interactive.length; ii++) {
            var el   = interactive[ii];
            var href = (el.getAttribute('href')        || '').toLowerCase();
            var aria = (el.getAttribute('aria-label') || '').toLowerCase();
            var title= (el.getAttribute('title')       || '').toLowerCase();
            if (href.includes('download') || href.includes('amazonaws.com') ||
                aria.includes('download') || title.includes('download')) {
                el.click();
                return JSON.stringify({status:'clicked', label:reportTypeLabel, via:'attr-fallback', href:href.substring(0,80)});
            }
        }
    }

    // Contar pendientes para diagnóstico
    var pending = 0;
    document.querySelectorAll('*').forEach(function(n) {
        var t = (n.textContent || '').trim().toLowerCase();
        if (t.length < 30 && (t === 'in progress' || t === 'processing' || t === 'pending' || t === 'running')) pending++;
    });
    return JSON.stringify({status:'no_download', label:reportTypeLabel, rows_found:matchingRows.length, pending:pending});
}"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Cache de entityIds por nombre de cuenta: {account_name: entityId}
_entity_id_cache: dict = {
    acc["name"]: acc["ads_entity_id"]
    for acc in ACCOUNTS
    if acc.get("ads_entity_id")
}


def _get_entity_id(page: Page) -> str:
    m = re.search(r'entityId=([A-Z0-9]+)', page.url)
    return m.group(1) if m else None


def _switch_ads_account(page: Page, account_name: str) -> bool:
    """
    Selecciona la cuenta indicada en Amazon Advertising Console.

    Pasos:
      1. Verificar si ya estamos en la cuenta correcta — si sí, retornar.
      2. Clickear el selector de cuenta en el header (sin importar qué cuenta esté activa).
      3. Esperar 2 s a que se despliegue el menú.
      4. Clickear el elemento con texto exacto de la cuenta destino.
      5. Confirmar que la página muestra la cuenta correcta.
    """
    logger.info(f"Verificando cuenta → {account_name}")

    # ── Paso 0: ¿Ya estamos en la cuenta correcta? ────────────────────────────
    try:
        if account_name in page.inner_text('body'):
            logger.info(f"✓ Ya en la cuenta correcta: {account_name}")
            return True
    except Exception:
        pass

    page.screenshot(path="debug_ads_before_switch.png")
    logger.info("Cambiando de cuenta...")

    # ── Paso 1: click en el selector de cuenta del header ────────────────────
    # Estrategia A: buscar un botón/div en el header con texto de cuenta corto (< 60 chars)
    clicked_trigger = False
    try:
        result = page.evaluate("""() => {
            // Buscar en header/nav el elemento con texto de cuenta (no menú, no nav links)
            var zones = document.querySelectorAll('header, nav, [class*="header"], [class*="Header"], [class*="topbar"], [class*="Topbar"], [class*="navbar"], [class*="Navbar"]');
            var candidates = [];
            zones.forEach(function(zone) {
                var els = zone.querySelectorAll('button, a, div, span, [role="button"], [role="combobox"]');
                els.forEach(function(el) {
                    if (!el.offsetParent) return;
                    var t = el.textContent.trim();
                    // Texto que parece un nombre de cuenta: entre 3 y 60 chars, no es un link de nav
                    if (t.length >= 3 && t.length <= 60 && !t.includes('\\n')) {
                        candidates.push(el);
                    }
                });
            });
            if (candidates.length === 0) return 'no_candidates';
            // Preferir el más específico (texto más corto) que no sea un link de navegación conocido
            candidates.sort(function(a, b) { return a.textContent.trim().length - b.textContent.trim().length; });
            for (var i = 0; i < candidates.length; i++) {
                var el = candidates[i];
                var t = el.textContent.trim().toLowerCase();
                var skip = ['reports','campaigns','portfolio','billing','settings','help','home','dashboard'];
                if (skip.some(function(s){ return t === s; })) continue;
                el.click();
                return 'clicked:' + el.tagName + ':' + el.textContent.trim().substring(0, 60);
            }
            return 'no_match';
        }""")
        if "clicked" in result:
            clicked_trigger = True
            logger.info(f"✓ Click selector de cuenta: {result}")
    except Exception as e:
        logger.debug(f"trigger JS zona: {e}")

    # Estrategia B: cualquier elemento visible con texto que coincida con nombre de cuenta
    if not clicked_trigger:
        try:
            result = page.evaluate("""(target) => {
                var all = document.querySelectorAll('button, a, div, span, li');
                var exact = [], partial = [];
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (!el.offsetParent) continue;
                    var t = el.textContent.trim();
                    if (t.length > 0 && t.length <= 80) {
                        if (t === target) exact.push(el);
                        else if (t.indexOf('Can Do') >= 0 || t.indexOf('Brands') >= 0) partial.push(el);
                    }
                }
                var pool = exact.length > 0 ? exact : partial;
                if (pool.length === 0) return 'not_found';
                pool.sort(function(a,b){ return a.textContent.trim().length - b.textContent.trim().length; });
                pool[0].click();
                return 'clicked:' + pool[0].tagName + ':' + pool[0].textContent.trim().substring(0,60);
            }""", account_name)
            if "clicked" in result:
                clicked_trigger = True
                logger.info(f"✓ Click selector B: {result}")
        except Exception as e:
            logger.debug(f"trigger B: {e}")

    if not clicked_trigger:
        logger.warning("No se encontró el selector de cuenta en el header")
        page.screenshot(path="debug_ads_account_menu.png")
        return False

    # ── Paso 2: esperar a que se despliegue el menú ───────────────────────────
    time.sleep(4)  # darle más tiempo al dropdown de cargar

    # Screenshot del estado del dropdown para diagnóstico
    page.screenshot(path="debug_ads_dropdown_open.png")

    # ── Paso 3: click en la cuenta destino dentro del dropdown ────────────────
    clicked_account = False

    # Intentar Playwright: exact=False para tolerar variaciones menores de nombre
    try:
        option = page.locator('[role="listbox"], [role="menu"], ul, [role="option"], li').get_by_text(
            account_name, exact=False
        ).first
        if option.is_visible(timeout=3000):
            option.click()
            clicked_account = True
            logger.info(f"✓ Cuenta seleccionada (locator): {account_name}")
    except Exception as e:
        logger.debug(f"option locator: {e}")

    # Fallback JS: matching flexible usando palabras clave del nombre de cuenta
    if not clicked_account:
        # Generar keywords dinámicamente desde el nombre de cuenta
        # Palabras de 3+ caracteres que identifican la cuenta
        keywords = [w for w in account_name.split() if len(w) >= 3]
        try:
            result = page.evaluate("""([target, keywords]) => {
                function matchesAccount(txt) {
                    var t = txt.trim();
                    return keywords.every(function(k){ return t.indexOf(k) >= 0; });
                }

                // Paso 1: buscar en menús/dropdowns desplegados
                var zones = document.querySelectorAll(
                    '[role="listbox"], [role="menu"], [role="list"], ' +
                    '[aria-expanded="true"], [class*="dropdown"], [class*="Dropdown"], ' +
                    '[class*="menu"], [class*="Menu"], [class*="popover"], [class*="Popover"]'
                );
                for (var zi = 0; zi < zones.length; zi++) {
                    var items = zones[zi].querySelectorAll('li, [role="option"], a, button, div, span');
                    for (var ii = 0; ii < items.length; ii++) {
                        var el = items[ii];
                        if (!el.offsetParent) continue;
                        var t = el.textContent.trim();
                        if (t.length > 0 && t.length < 100 && matchesAccount(t)) {
                            el.click();
                            return 'clicked_zone:' + el.tagName + ':' + t;
                        }
                    }
                }

                // Paso 2: búsqueda global en todo el DOM
                var all = document.querySelectorAll('a, button, li, div, span, option');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (!el.offsetParent) continue;
                    var t = el.textContent.trim();
                    if (t.length > 0 && t.length < 100 && matchesAccount(t)) {
                        el.click();
                        return 'clicked_global:' + el.tagName + ':' + t;
                    }
                }

                // Diagnóstico: listar elementos visibles con la primera keyword
                var found = [];
                var kw0 = keywords[0] || '';
                document.querySelectorAll('*').forEach(function(el) {
                    if (!el.offsetParent) return;
                    var t = el.textContent.trim();
                    if (t.indexOf(kw0) >= 0 && t.length < 80) found.push(t.substring(0,60));
                });
                return 'not_found:visible=' + JSON.stringify(found.slice(0,10));
            }""", [account_name, keywords])
            if "clicked" in result:
                clicked_account = True
                logger.info(f"✓ Cuenta JS: {result}")
        except Exception as e:
            logger.debug(f"account JS: {e}")

    if not clicked_account:
        logger.warning(f"No se encontró '{account_name}' en el menú desplegado")
        page.screenshot(path="debug_ads_account_menu.png")
        return False

    # ── Paso 4: esperar confirmación de la cuenta ─────────────────────────────
    try:
        page.wait_for_function(
            f"() => document.body.innerText.includes('{account_name}')",
            timeout=15000
        )
        logger.info(f"✓ Cuenta confirmada en página: {account_name}")
        time.sleep(2)
        return True
    except Exception as e:
        logger.warning(f"Timeout esperando confirmación de cuenta: {e}")
        # Verificar si está en la página de todas formas
        try:
            if account_name in page.inner_text('body'):
                logger.info(f"✓ Cuenta presente en página (post-timeout): {account_name}")
                return True
        except Exception:
            pass
        return False


def fill_ads_date_range(page: Page, start: date, end: date) -> bool:
    """
    Selecciona el rango de fechas en el calendar picker de Amazon Ads.
    Intenta usar un preset si aplica; si no, navega el calendario manualmente.
    """
    today       = date.today()
    month_start = date(today.year, today.month, 1)
    prev_end    = month_start - timedelta(days=1)
    prev_start  = date(prev_end.year, prev_end.month, 1)

    # Determinar preset
    preset = None
    if start == today and end == today:
        preset = "Today"
    elif start == month_start and end == today:
        preset = "Month to date"
    elif start == prev_start and end == prev_end:
        preset = "Last month"
    elif end == today and (today - start).days == 6:
        preset = "Last 7 days"
    elif end == today and (today - start).days == 29:
        preset = "Last 30 days"

    # Abrir el date picker
    try:
        period_btn = page.locator('button').filter(
            has_text=re.compile(r'Last \d+ days|Month to date|Last month|Today|Yesterday|Last week|Last 7 days', re.I)
        ).first
        if period_btn.count() == 0:
            # Buscar cualquier botón con icono de calendario o texto de fecha
            period_btn = page.locator('[class*="DateRange"], [class*="date-range"], [class*="period"]').first
        if period_btn.count() == 0:
            logger.warning("fill_ads_date_range: botón de período no encontrado")
            return False
        period_btn.click()
        time.sleep(1)
    except Exception as e:
        logger.warning(f"fill_ads_date_range open: {e}")
        return False

    # Intentar preset
    if preset:
        try:
            preset_el = page.locator('li, button, [role="option"]').filter(has_text=preset).first
            if preset_el.count() > 0 and preset_el.is_visible():
                preset_el.click()
                time.sleep(0.5)
                save_btn = page.locator('button:has-text("Save")').first
                if save_btn.count() > 0 and save_btn.is_visible():
                    save_btn.click()
                    time.sleep(1)
                logger.info(f"✓ Fecha preset: {preset}")
                return True
        except Exception as e:
            logger.debug(f"Preset '{preset}': {e}")

    # Navegación manual del calendario
    def get_displayed_months():
        try:
            raw  = page.evaluate(JS_GET_CALENDAR_MONTHS)
            data = json.loads(raw)
            return [(d['month'], d['year']) for d in data]
        except Exception:
            return []

    def nav_prev():
        try:
            btn = page.locator('button').filter(has_text=re.compile(r'^[<‹◀]$|previous', re.I)).first
            if btn.count() == 0:
                btn = page.get_by_role("button", name=re.compile("previous|prev", re.I)).first
            btn.click()
            time.sleep(0.4)
        except Exception as e:
            logger.debug(f"nav_prev: {e}")

    def nav_next():
        try:
            btn = page.locator('button').filter(has_text=re.compile(r'^[>›▶]$|next', re.I)).first
            if btn.count() == 0:
                btn = page.get_by_role("button", name=re.compile("^next$|forward", re.I)).first
            btn.click()
            time.sleep(0.4)
        except Exception as e:
            logger.debug(f"nav_next: {e}")

    def ensure_month_visible(yr: int, mo: int) -> bool:
        target = date(yr, mo, 1)
        for _ in range(24):
            displayed = get_displayed_months()
            if not displayed:
                return False
            dates = [date(y, m, 1) for m, y in displayed]
            if target in dates:
                return True
            if target < min(dates):
                nav_prev()
            else:
                nav_next()
        return False

    def click_calendar_date(target: date) -> bool:
        try:
            result = page.evaluate(JS_CLICK_CALENDAR_DAY, [target.day, target.month, target.year])
            logger.info(f"Calendar click {target}: {result}")
            return "clicked" in result
        except Exception as e:
            logger.warning(f"click_calendar_date {target}: {e}")
            return False

    ensure_month_visible(start.year, start.month)
    click_calendar_date(start)
    time.sleep(0.5)

    if (end.year, end.month) != (start.year, start.month):
        ensure_month_visible(end.year, end.month)
    click_calendar_date(end)
    time.sleep(0.5)

    try:
        save_btn = page.locator('button:has-text("Save")').first
        if save_btn.count() > 0 and save_btn.is_visible():
            save_btn.click()
            time.sleep(1)
            logger.info(f"✓ Fechas: {start} → {end}")
            return True
        logger.warning("Save button no encontrado después de seleccionar fechas")
        page.screenshot(path="debug_ads_calendar.png")
        return False
    except Exception as e:
        logger.warning(f"Date save: {e}")
        return False


# ---------------------------------------------------------------------------
# Navegación
# ---------------------------------------------------------------------------

def navigate_to_ads_reports(page: Page, account: dict = None) -> bool:
    """
    Navega a Sponsored ads reports de la cuenta indicada.
    Si se conoce el entityId (config o cache), usa la URL directa.
    Si no: flujo completo con switch de cuenta.
    """
    account_name = (account or {}).get("name", ACCOUNT_NAME)
    entity_id    = (account or {}).get("ads_entity_id") or _entity_id_cache.get(account_name)

    # ── Atajo: URL directa con entityId ──────────────────────────────────────
    if entity_id:
        try:
            direct = f"https://advertising.amazon.com/reports?entityId={entity_id}"
            logger.info(f"ADS directo ({account_name}): {direct}")
            page.goto(direct, timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            time.sleep(2)
            cur = page.url.lower()
            if any(k in cur for k in ["signin", "login"]):
                logger.warning("Sesión expirada con entityId cacheado — flujo completo.")
                _entity_id_cache.pop(account_name, None)
            else:
                logger.info(f"✓ ADS Reports (directo): {page.url}")
                return True
        except Exception as e:
            logger.warning(f"Atajo entityId falló: {e} — flujo completo.")
            _entity_id_cache.pop(account_name, None)

    # ── Flujo completo ─────────────────────────────────────────────────────────

    # Paso 1: base URL
    try:
        logger.info(f"ADS paso 1: cargando advertising.amazon.com ({account_name})...")
        page.goto("https://advertising.amazon.com", timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(4)

        cur = page.url.lower()
        if any(k in cur for k in ["signin", "ap/signin", "login"]):
            logger.error(f"Sesión inválida. URL: {cur}")
            return False
        logger.info(f"✓ Base: {page.url}")

        # Verificar que estamos en la cuenta correcta
        try:
            body_txt = page.inner_text('body')
            if account_name not in body_txt:
                logger.info(f"Cuenta incorrecta. Cambiando a: {account_name}")
                _switch_ads_account(page, account_name)
                time.sleep(2)
        except Exception as e:
            logger.debug(f"Verificación de cuenta: {e}")

    except Exception as e:
        logger.warning(f"ADS paso 1: {e}")
        return False

    # Paso 2: click "Sponsored ads reports" en el menú lateral
    if "reports" not in page.url.lower():
        logger.info("ADS paso 2: buscando menú 'Sponsored ads reports'...")
        for lbl in ["Sponsored ads reports", "Sponsored Products reports", "Reports"]:
            try:
                result = page.evaluate(JS_FIND_CLICK, [lbl, True])
                if "clicked" in result:
                    logger.info(f"✓ Menú: {result}")
                    time.sleep(3)
                    break
            except Exception as e:
                logger.debug(f"click '{lbl}': {e}")

    # Paso 3: fallback a URL directa genérica
    if "reports" not in page.url.lower():
        logger.info("ADS paso 3: fallback URL directa...")
        try:
            page.goto("https://advertising.amazon.com/reports", timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            time.sleep(3)
        except Exception as e:
            logger.error(f"ADS paso 3: {e}")
            return False

    cur = page.url.lower()
    if any(k in cur for k in ["signin", "login"]):
        logger.error("ADS: sesión inválida post-navegación.")
        return False

    # Cachear entityId descubierto para navegaciones futuras
    eid = _get_entity_id(page)
    if eid:
        try:
            if account_name in page.inner_text('body'):
                _entity_id_cache[account_name] = eid
                logger.info(f"✓ EntityId cacheado ({account_name}): {eid}")
        except Exception:
            pass

    logger.info(f"✓ ADS Reports: {page.url}")
    return True


def select_ads_account(page: Page, account_name: str) -> bool:
    try:
        time.sleep(2)
        result = page.evaluate(JS_FIND_CLICK, [account_name, False])
        if "clicked" in result:
            logger.info(f"✓ Cuenta: {result}")
            time.sleep(3)
    except Exception as e:
        logger.warning(f"select_ads_account: {e}")
    return True


# ---------------------------------------------------------------------------
# Crear un reporte (FASE 1)
# ---------------------------------------------------------------------------

def create_ads_report(page: Page, report_cfg: dict, start: date, end: date) -> bool:
    label    = report_cfg["label"]
    mrc      = report_cfg["mrc"]
    show_biz = report_cfg["show_biz"]

    logger.info(f"Creando reporte ADS: {label} ({start} → {end})")

    try:
        # Navegar directamente al formulario de nuevo reporte
        entity_id = _get_entity_id(page)
        new_url = (
            f"https://advertising.amazon.com/reports/new?entityId={entity_id}"
            if entity_id else "https://advertising.amazon.com/reports/new"
        )
        page.goto(new_url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)

        if "reports" not in page.url.lower():
            logger.error(f"Formulario no cargó. URL: {page.url}")
            page.screenshot(path=f"debug_ads_form_{label.replace(' ', '_')}.png")
            return False

        page.screenshot(path=f"debug_ads_form_{label.replace(' ', '_')}.png")
        logger.info(f"Formulario: {page.url}")

                # ── MRC checkbox ──────────────────────────────────────────────────────
        if mrc:
            try:
                logger.info("Buscando checkbox MRC...")

                page.get_by_text("Show only Media Rating Council", exact=False).wait_for(
                    state="visible",
                    timeout=10000
                )

                mrc_checkbox = page.locator(
                    "xpath=//*[contains(normalize-space(.), 'Show only Media Rating Council') "
                    "and .//input[@type='checkbox']]//input[@type='checkbox']"
                ).first

                if mrc_checkbox.count() == 0:
                    raise Exception("No se encontró input checkbox de MRC")

                if not mrc_checkbox.is_checked():
                    mrc_checkbox.check(force=True)
                    logger.info("✓ MRC activado")
                else:
                    logger.info("✓ MRC ya estaba activado")

                time.sleep(0.5)

            except Exception as e:
                logger.warning(f"MRC: no se pudo activar con locator: {e}")

                try:
                    result = page.evaluate("""
                    () => {
                        const text = 'Show only Media Rating Council';
                        const nodes = Array.from(document.querySelectorAll('label, div, span, section, form'));

                        for (const node of nodes) {
                            const nodeText = (node.innerText || node.textContent || '').trim();

                            if (!nodeText.includes(text)) {
                                continue;
                            }

                            const checkbox = node.querySelector('input[type="checkbox"]');

                            if (!checkbox) {
                                continue;
                            }

                            if (!checkbox.checked) {
                                checkbox.click();
                            }

                            return checkbox.checked ? 'checked' : 'clicked';
                        }

                        return 'not_found';
                    }
                    """)

                    if result in ["checked", "clicked"]:
                        logger.info("✓ MRC activado con JS fallback")
                        time.sleep(0.5)
                    else:
                        logger.warning(f"MRC: no encontrado en fallback JS ({result})")
                        page.screenshot(path=f"debug_mrc_{label.replace(' ', '_')}.png")

                except Exception as e2:
                    logger.warning(f"MRC fallback JS error: {e2}")
                    page.screenshot(path=f"debug_mrc_{label.replace(' ', '_')}.png")

        # ── Report type dropdown ──────────────────────────────────────────────
        if label != "Search term":
            try:
                time.sleep(0.5)
                # Abrir el dropdown (muestra "Search term" por defecto)
                opened = False

                # Intentar como native <select>
                sel = page.locator('select').filter(has_text=re.compile('search term|targeting|campaign', re.I)).first
                if sel.count() > 0:
                    sel.select_option(label=label)
                    logger.info(f"✓ Report type (select): {label}")
                    opened = True
                else:
                    # Custom dropdown: click el trigger actual
                    default_types = ["Search term", "Targeting", "Campaign", "Budget",
                                     "Placement", "Audience", "Video", "Prompts"]
                    for dt in default_types:
                        trigger = page.locator('button, [role="combobox"]').filter(has_text=dt).first
                        if trigger.count() > 0 and trigger.is_visible():
                            trigger.click()
                            time.sleep(0.8)
                            opened = True
                            break

                    if opened:
                        # Click la opción deseada
                        option = page.locator('[role="option"], li, option').filter(has_text=label).first
                        if option.count() > 0:
                            option.click()
                            logger.info(f"✓ Report type (dropdown): {label}")
                        else:
                            result = page.evaluate(JS_FIND_CLICK, [label, True])
                            logger.info(f"Report type JS: {result}")
                        time.sleep(0.5)
                    else:
                        result = page.evaluate(JS_FIND_CLICK, [label, True])
                        logger.info(f"Report type JS fallback: {result}")
                        time.sleep(0.5)

            except Exception as e:
                logger.warning(f"Report type: {e}")

        # ── Amazon Business — OFF para Placement ─────────────────────────────
        if show_biz is False:
            try:
                checkboxes = page.locator('input[type="checkbox"]').all()
                for cb in checkboxes:
                    pt = cb.evaluate("el => (el.closest('label') || el.parentElement || {}).textContent || ''")
                    if "Amazon Business" in pt or "business" in pt.lower():
                        if cb.is_checked():
                            cb.click()
                            logger.info("✓ Amazon Business OFF")
                            time.sleep(0.5)
                        break
            except Exception as e:
                logger.debug(f"Biz checkbox: {e}")

        # ── Currency conversion — OFF ─────────────────────────────────────────
        try:
            checkboxes = page.locator('input[type="checkbox"]').all()
            for cb in checkboxes:
                pt = cb.evaluate("el => (el.closest('label') || el.parentElement || {}).textContent || ''")
                if "currency" in pt.lower() or "converted" in pt.lower():
                    if cb.is_checked():
                        cb.click()
                        logger.info("✓ Currency OFF")
                        time.sleep(0.5)
                    break
        except Exception as e:
            logger.debug(f"Currency: {e}")

        # ── Time unit: Daily ──────────────────────────────────────────────────
        try:
            daily_label = page.locator('label').filter(has_text=re.compile(r'^Daily$')).first
            if daily_label.count() > 0:
                daily_label.click()
                logger.info("✓ Time unit: Daily")
                time.sleep(0.5)
            else:
                result = page.evaluate(JS_FIND_CLICK, ["Daily", True])
                logger.info(f"Daily JS: {result}")
                time.sleep(0.5)
        except Exception as e:
            logger.debug(f"Daily: {e}")

        # ── Date range ────────────────────────────────────────────────────────
        fill_ads_date_range(page, start, end)

        # ── Run report ────────────────────────────────────────────────────────
        time.sleep(1)
        submitted = False
        try:
            run_btn = page.locator('button:has-text("Run report")').first
            if run_btn.count() > 0 and run_btn.is_visible():
                run_btn.click()
                logger.info(f"✓ Run report: {label}")
                time.sleep(4)
                submitted = True
        except Exception as e:
            logger.debug(f"Run report locator: {e}")

        if not submitted:
            for btn_txt in ["Run report", "Run", "Create"]:
                result = page.evaluate(JS_FIND_CLICK, [btn_txt, True])
                if "clicked" in result:
                    logger.info(f"✓ Submit JS: {result}")
                    time.sleep(4)
                    submitted = True
                    break

        if not submitted:
            logger.warning(f"No se encontró botón Submit para {label}")
            page.screenshot(path=f"debug_ads_submit_{label.replace(' ', '_')}.png")
            return False

        logger.info(f"✓ Reporte '{label}' solicitado.")
        return True

    except Exception as e:
        logger.error(f"create_ads_report ({label}): {e}")
        page.screenshot(path=f"debug_ads_error_{label.replace(' ', '_')}.png")
        return False


# ---------------------------------------------------------------------------
# Esperar y descargar un reporte (FASE 2)
# ---------------------------------------------------------------------------

def wait_and_download_ads_report(page: Page, context: BrowserContext,
                                  report_cfg: dict, filename: str,
                                  account: dict = None,
                                  timeout_sec: int = None) -> tuple:
    label       = report_cfg["label"]
    timeout_sec = timeout_sec or report_cfg.get("timeout_sec", ADS_REPORT_TIMEOUT_SEC)
    deadline    = time.time() + timeout_sec
    attempt     = 0

    logger.info(f"Esperando '{label}' (timeout: {timeout_sec // 60} min)...")

    while time.time() < deadline:
        attempt += 1
        remaining = int(deadline - time.time())
        logger.info(f"[ADS {attempt}] '{label}' — quedan {remaining // 60}m {remaining % 60}s")

        page = ensure_page(context, page)

        try:
            navigate_to_ads_reports(page, account)
            time.sleep(2)
        except Exception as e:
            logger.warning(f"navigate: {e}")
            time.sleep(ADS_POLL_INTERVAL_SEC)
            continue

        try:
            # ── 1. Encontrar la fila del reporte ──────────────────────────────────────
            # La tabla usa ag-grid que virtualiza columnas — la col "Last run" con la fecha
            # puede no estar en el DOM. En cambio, el <a href*="download-report"> solo
            # aparece en col-id="reportName" cuando el reporte ya tiene su download UUID.
            row = None
            for sel in [
                f"[role='row']:has-text('Sponsored Products {label} report')",
                f"[role='row']:has-text('{label}')",
                f"tr:has-text('{label}')",
            ]:
                try:
                    candidate = page.locator(sel).first
                    if candidate.count() > 0:
                        row = candidate
                        break
                except Exception:
                    pass

            if row is None or row.count() == 0:
                logger.info(f"'{label}' — fila no encontrada en la tabla.")
                raise Exception("pending")

            # ── 2. Buscar el enlace de descarga en la fila ────────────────────────────
            # Su presencia es la señal real de que el reporte está listo.
            href = None
            for link_sel in [
                'a[href*="download-report"]',
                'a[href*="amazonaws.com"]',
                'a[download]',
            ]:
                try:
                    link = row.locator(link_sel).first
                    if link.count() > 0:
                        href = link.get_attribute('href')
                        if href:
                            logger.info(f"'{label}' — enlace encontrado ({link_sel}): {href[:80]}")
                            break
                except Exception:
                    pass

            if not href:
                logger.info(f"'{label}' — enlace de descarga no disponible aún (reporte en cola).")
                raise Exception("pending")

            # ── 3. Hacer absoluta si es relativa ─────────────────────────────────────
            if href.startswith('/'):
                href = 'https://advertising.amazon.com' + href

            logger.info(f"'{label}' — descargando vía HTTP: {href[:100]}...")

            # ── 4. Descargar con cookies de la sesión actual del browser ─────────────
            cookies = page.context.cookies()
            session_cookies = {c['name']: c['value'] for c in cookies}
            resp_headers = {
                'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 (KHTML, like Gecko) '
                               'Chrome/120.0.0.0 Safari/537.36'),
                'Referer': page.url,
            }
            response = requests.get(href, cookies=session_cookies,
                                    headers=resp_headers, timeout=60)

            if response.status_code == 200:
                acct_output_dir = (account or {}).get("output_dir", OUTPUT_DIR)
                Path(acct_output_dir).mkdir(parents=True, exist_ok=True)
                save_path = os.path.join(acct_output_dir, filename)
                with open(save_path, 'wb') as f:
                    f.write(response.content)
                logger.info(f"✓ Descargado: {filename} ({len(response.content):,} bytes)")
                upload_file(save_path, account)
                return True, page
            else:
                logger.warning(f"HTTP {response.status_code} al descargar '{label}'")
                raise Exception(f"HTTP {response.status_code}")

        except Exception as e:
            err_str = str(e).lower()
            if "pending" in err_str:
                logger.info(f"'{label}' aún no disponible.")
            elif "http" in err_str:
                logger.warning(f"'{label}' error de descarga: {e}")
            else:
                logger.warning(f"wait_download '{label}': {e}")

        wait = min(ADS_POLL_INTERVAL_SEC, max(30, int(deadline - time.time())))
        logger.info(f"Próximo chequeo: {wait // 60}m {wait % 60}s...")
        time.sleep(wait)

    logger.error(f"Timeout ADS ({timeout_sec // 60} min) para '{label}'")
    return False, page


# ---------------------------------------------------------------------------
# Orquestador principal
# ---------------------------------------------------------------------------

def download_all_ads_reports(page: Page, context: BrowserContext,
                               start: date, end: date,
                               account: dict = None,
                               reports_to_run=None) -> Page:
    """
    Descarga los reportes de Sponsored Products.
    reports_to_run: "all" o lista de keys, ej: ["campaign", "targeting"]
    """
    setup_output_dir()

    run_all      = (reports_to_run is None or reports_to_run == "all")
    selected     = set() if run_all else set(reports_to_run)
    active_types = [r for r in ADS_REPORT_TYPES if (run_all or r["key"] in selected)]

    if not active_types:
        logger.warning("Ningún reporte ADS seleccionado.")
        return page

    # Si no se pasa account, usar la primera cuenta (HK Limited)
    if account is None:
        account = ACCOUNTS[0]
    ads_account      = dict(account)
    account_name     = ads_account.get("name", ACCOUNT_NAME)
    file_prefix      = ads_account.get("file_prefix", "Honey")
    acct_output_dir  = ads_account.get("output_dir", OUTPUT_DIR)
    Path(acct_output_dir).mkdir(parents=True, exist_ok=True)

    logger.info(f"\n{'█' * 50}")
    logger.info(f"ADS REPORTS — {account_name} | {start} → {end}")
    logger.info(f"Reportes: {[r['label'] for r in active_types]}")
    logger.info("█" * 50)

    page = ensure_page(context, page)

    if not navigate_to_ads_reports(page, ads_account):
        logger.error("No se pudo acceder a Amazon Advertising.")
        return page

    select_ads_account(page, account_name)

    # ── FASE 1: Solicitar todos los reportes ──────────────────────────────────
    logger.info("\n--- FASE 1: Solicitando reportes ---")
    requested = []
    for rpt in active_types:
        label_clean = rpt['label'].replace(' ', '_')
        filename = f"{file_prefix}_Sponsored_Products_{label_clean}_report_{start.strftime('%Y%m')}.csv"
        if os.path.exists(os.path.join(acct_output_dir, filename)):
            logger.info(f"Ya existe: {filename}")
            continue

        navigate_to_ads_reports(page, ads_account)
        time.sleep(2)

        ok = create_ads_report(page, rpt, start, end)
        if ok:
            requested.append(rpt)
            logger.info(f"✓ Solicitado: {rpt['label']}")
        else:
            logger.warning(f"✗ Fallo al solicitar: {rpt['label']}")
        time.sleep(3)

    if not requested:
        logger.warning("No se solicitó ningún reporte ADS nuevo.")
        return page

    logger.info(f"\nSolicitados: {len(requested)}. Iniciando espera...")

    # ── FASE 2: Descargar ─────────────────────────────────────────────────────
    logger.info("\n--- FASE 2: Descargando reportes ---")
    total = 0
    for rpt in requested:
        label_clean = rpt['label'].replace(' ', '_')
        filename = f"{file_prefix}_Sponsored_Products_{label_clean}_report_{start.strftime('%Y%m')}.csv"
        logger.info(f"\n{'=' * 50}")
        logger.info(f"Esperando: {rpt['label']} (timeout: {rpt['timeout_sec'] // 60} min)")

        ok, page = wait_and_download_ads_report(
            page, context, rpt, filename, account=ads_account
        )
        if ok:
            total += 1

    logger.info(f"\n{'█' * 50}\n✓ ADS completo. Descargados: {total}/{len(requested)}")
    return page
