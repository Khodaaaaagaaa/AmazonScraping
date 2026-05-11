"""
downloader.py — Filters working + download from Manage Downloads panel
"""

import time
import random
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from playwright.sync_api import Page

from config import (
    OUTPUT_DIR, MAX_QUEUE, POLL_INTERVAL_SEC, REPORT_TIMEOUT_SEC,
    DELAY_BETWEEN_REQUESTS
)

logger = logging.getLogger(__name__)
SALES_URL = "https://vendorcentral.amazon.com/retail-analytics/dashboard/sales"


def random_delay():
    time.sleep(random.uniform(*DELAY_BETWEEN_REQUESTS))

def setup_output_dir():
    Path(OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

def navigate_to_sales(page: Page):
    logger.info("Navegando a Sales...")
    page.goto(SALES_URL, timeout=40000)
    page.locator('h1:has-text("Sales")').wait_for(timeout=20000)
    time.sleep(2)

# ── KAT dropdowns ─────────────────────────────────────────────────────────────

def js_open_dropdown(page: Page, current_value: str):
    """Abre un dropdown KAT buscando el slot con current_value."""
    page.evaluate(f"""() => {{
        function getAll(root) {{
            let all = [];
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            let node;
            while (node = walker.nextNode()) {{
                all.push(node);
                if (node.shadowRoot) all = all.concat(getAll(node.shadowRoot));
            }}
            return all;
        }}
        for (const el of getAll(document)) {{
            if (el.tagName === 'SLOT' && el.name === 'selected-option' && el.textContent.includes('{current_value}')) {{
                let node = el;
                while (node) {{
                    if (node.tagName && node.tagName.startsWith('KAT-')) {{ node.click(); return; }}
                    node = node.parentElement || (node.getRootNode && node.getRootNode().host);
                }}
            }}
        }}
    }}""")
    time.sleep(1.5)


def js_click_option(page: Page, text: str) -> bool:
    """Clickea div.standard-option-name con el texto dado en cualquier shadow DOM."""
    result = page.evaluate(f"""() => {{
        function getAll(root) {{
            let all = [];
            const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
            let node;
            while (node = walker.nextNode()) {{
                all.push(node);
                if (node.shadowRoot) all = all.concat(getAll(node.shadowRoot));
            }}
            return all;
        }}
        for (const el of getAll(document)) {{
            if (typeof el.className === 'string' && el.className.includes('standard-option-name') && el.textContent.trim() === '{text}') {{
                el.click();
                return 'clicked';
            }}
        }}
        return 'not found';
    }}""")
    logger.info(f"js_click_option('{text}'): {result}")
    time.sleep(0.8)
    return result == 'clicked'


def open_and_select(page: Page, current_value: str, desired_value: str) -> bool:
    logger.info(f"Dropdown: '{current_value}' → '{desired_value}'")
    js_open_dropdown(page, current_value)
    ok = js_click_option(page, desired_value)
    if not ok:
        time.sleep(0.5)
        ok = js_click_option(page, desired_value)
    return ok


# ── Fecha ──────────────────────────────────────────────────────────────────────

def set_date(page: Page, target_date: date):
    """Triple click en el input Day y pegar la fecha directamente."""
    date_str = target_date.strftime("%m/%d/%Y")
    time.sleep(1)  # Esperar que el input Day aparezca tras seleccionar Daily
    try:
        # El input Day tiene un valor de fecha tipo MM/DD/YYYY
        # Buscar el input visible que no sea de busqueda
        day_input = page.locator('input[type="text"]:visible').all()
        for inp in day_input:
            ph = (inp.get_attribute('placeholder') or '').lower()
            if 'search' in ph or 'asin' in ph:
                continue
            val = inp.input_value()
            logger.info(f"Input encontrado: value='{val}' placeholder='{ph}'")
            # Hacer triple click para seleccionar todo y reemplazar
            inp.click(click_count=3)
            time.sleep(0.3)
            inp.type(date_str)
            time.sleep(0.3)
            # Escape cierra el calendar picker, Tab confirma
            inp.press('Escape')
            time.sleep(0.3)
            inp.press('Tab')
            time.sleep(0.5)
            logger.info(f"set_date: {date_str}")
            return
        logger.warning("set_date: no input visible encontrado")
    except Exception as e:
        logger.warning(f"set_date error: {e}")



# ── Filtros ────────────────────────────────────────────────────────────────────

def set_filters(page: Page, target_date: date):
    logger.info(f"--- Filtros para {target_date.strftime('%Y-%m-%d')} ---")

    # 1. Time frame: Custom → Daily
    open_and_select(page, "Custom", "Daily")
    time.sleep(1)

    # 2. Fecha
    set_date(page, target_date)

    # 3. Distributor View: Manufacturing → Sourcing
    open_and_select(page, "Manufacturing", "Sourcing")

    # 4. Apply — forzar click aunque esté disabled (la fecha puede tardar en registrarse)
    try:
        apply = page.locator('button:has-text("Apply")').first
        apply.wait_for(timeout=5000, state="visible")
        # Esperar que se habilite (máx 10s)
        for _ in range(10):
            if apply.is_enabled():
                break
            time.sleep(1)
        apply.click()
        logger.info("Apply clickeado.")
        page.locator('text=/Displaying \\d+ of \\d+ columns/i').first.wait_for(timeout=25000)
        time.sleep(2)
        logger.info("✓ Tabla cargada.")
    except Exception as e:
        logger.warning(f"Apply error: {e}")

    page.screenshot(path=f"debug_filters_{target_date.strftime('%Y%m%d')}.png")


# ── Columnas ───────────────────────────────────────────────────────────────────

def columns_are_all_selected(page: Page) -> bool:
    """Devuelve True si el contador dice X of X (todos seleccionados)."""
    import re
    col_text = page.locator('text=/Displaying \d+ of \d+ columns/i').first
    if col_text.count() == 0:
        return False
    txt = col_text.inner_text()
    nums = re.findall(r'\d+', txt)
    result = len(nums) == 2 and nums[0] == nums[1]
    logger.info(f"Columnas: {txt} → {'✓ OK' if result else '✗ incompletas'}")
    return result


def open_customize_select_all_save(page: Page):
    """Abre Customize Columns, hace Select All y guarda."""
    logger.info("Customize Columns → Select All → Save...")

    # Abrir el modal
    page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.textContent && el.textContent.trim().startsWith('Customize Columns')) {
                el.click();
                return;
            }
        }
    }""")
    time.sleep(2)

    # Click Select All usando Playwright locator (maneja shadow DOM de KAT)
    try:
        select_all_cb = page.locator('kat-checkbox[label="Select All"]').first
        select_all_cb.wait_for(timeout=5000, state="visible")
        select_all_cb.click()
        logger.info("Select All: clickeado via Playwright locator")
        time.sleep(0.8)
    except Exception as e:
        logger.warning(f"Select All locator falló ({e}), intentando JS...")
        # Fallback: click via JS con dispatchEvent
        page.evaluate("""() => {
            const cbs = document.querySelectorAll('kat-checkbox');
            for (const cb of cbs) {
                if ((cb.getAttribute('label') || '') === 'Select All') {
                    cb.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    return;
                }
            }
        }""")
        time.sleep(0.8)

    # Save
    page.locator('button:has-text("Save")').first.wait_for(timeout=5000, state="visible")
    page.locator('button:has-text("Save")').first.click()
    time.sleep(2)
    logger.info("✓ Modal guardado.")


# ── Excel ──────────────────────────────────────────────────────────────────────

def request_excel(page: Page) -> bool:
    """Solo descarga si se ve 'Displaying X of X columns' (todas las columnas)."""
    # Verificar que estén todas las columnas antes de proceder
    col_text = page.locator('text=/Displaying \d+ of \d+ columns/i').first
    if col_text.count() > 0:
        import re
        txt = col_text.inner_text()
        nums = re.findall(r'\d+', txt)
        if len(nums) == 2 and nums[0] != nums[1]:
            logger.warning(f"No están todas las columnas ({txt}), no descargo.")
            return False
        logger.info(f"✓ Columnas OK: {txt}")
    else:
        logger.warning("No se encontró el contador de columnas, abortando Excel.")
        return False

    logger.info("Solicitando Excel...")
    try:
        excel = page.locator('button:has-text("Excel")').first
        excel.wait_for(timeout=8000, state="visible")
        excel.click()
        time.sleep(2)
        warn = page.locator('text=/exceeded/i, text=/superado/i').first
        if warn.count() > 0:
            logger.warning("Límite — esperando 6 min...")
            time.sleep(360)
            excel.click()
            time.sleep(2)
        logger.info("✓ Excel solicitado.")
        return True
    except Exception as e:
        logger.error(f"Excel error: {e}")
        return False


# ── Descarga desde panel Manage Downloads ─────────────────────────────────────

def download_from_panel(page: Page, target_date: date) -> bool:
    """
    Abre el panel Manage Downloads y descarga el reporte del día.
    Nombre del reporte: Sales_ASIN_Sourcing_Retail_UnitedStates_Daily_M-D-YYYY_M-D-YYYY
    """
    # Formato de fecha que aparece en el nombre del archivo: 1-1-2026
    date_tag  = f"{target_date.month}-{target_date.day}-{target_date.year}"
    filename  = f"SALES_{target_date.strftime('%Y%m%d')}_HoneyCanDoHK.xlsx"
    filepath  = os.path.join(OUTPUT_DIR, filename)
    deadline  = time.time() + REPORT_TIMEOUT_SEC

    logger.info(f"Esperando reporte '{date_tag}' en Manage Downloads...")

    while time.time() < deadline:

        # 1. Abrir panel Manage Downloads via JS (evita divs que interceptan clicks)
        try:
            page.evaluate("document.getElementById('downloadManager').click()")
            time.sleep(2)
        except Exception as e:
            logger.warning(f"No pude abrir panel: {e}")
            time.sleep(5)
            continue

        page.screenshot(path=f"debug_panel_{target_date.strftime('%Y%m%d')}.png")

        # 2. Buscar link "Download" cuya fila contenga nuestra fecha y "Sourcing"
        try:
            links = page.locator('a:has-text("Download")').all()
            logger.info(f"Links 'Download' en panel: {len(links)}")

            for link in links:
                try:
                    # Subir varios niveles para obtener el texto de toda la fila
                    row = link.locator('xpath=ancestor::div[4]').first
                    row_text = row.inner_text()
                    logger.info(f"Fila: {row_text[:150]}")

                    if date_tag in row_text and "Sourcing" in row_text:
                        logger.info(f"✓ Reporte encontrado para {target_date}. Descargando...")
                        with page.expect_download(timeout=60000) as dl_info:
                            link.click()
                        dl_info.value.save_as(filepath)
                        logger.info(f"✓ Guardado: {filepath}")
                        return True
                except Exception as e:
                    logger.debug(f"Error procesando link: {e}")

        except Exception as e:
            logger.warning(f"Error leyendo panel: {e}")

        # 3. No estaba listo — cerrar panel y esperar
        logger.info(f"No listo aún. Esperando {POLL_INTERVAL_SEC}s...")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        time.sleep(POLL_INTERVAL_SEC)

    logger.error(f"Timeout para {target_date}")
    return False


# ── Orquestador ────────────────────────────────────────────────────────────────

def download_sales_range(page: Page, start: date, end: date):
    setup_output_dir()

    all_dates = []
    d = start
    while d <= end:
        all_dates.append(d)
        d += timedelta(days=1)

    logger.info(f"Total: {len(all_dates)} días ({start} → {end})")

    columns_configured = False
    downloaded_total   = 0

    for target_date in all_dates:
        filename = f"SALES_{target_date.strftime('%Y%m%d')}_HoneyCanDoHK.xlsx"
        if os.path.exists(os.path.join(OUTPUT_DIR, filename)):
            logger.info(f"Ya existe: {filename}")
            continue

        # 1. Navegar y filtrar
        navigate_to_sales(page)
        set_filters(page, target_date)

        # 2. Si las columnas no están completas, abrir Customize → Select All → Save
        #    y SIEMPRE re-aplicar filtros después para que el contador se actualice
        if not columns_are_all_selected(page):
            open_customize_select_all_save(page)
            # Re-aplicar filtros: esto resetea la fecha correcta y refresca el contador
            set_filters(page, target_date)

        # 3. Verificación final antes de Excel
        if not columns_are_all_selected(page):
            logger.warning(f"Columnas incompletas para {target_date}, saltando.")
            continue

        # 4. Solicitar Excel
        if not request_excel(page):
            logger.warning(f"No se pudo solicitar Excel para {target_date}")
            continue

        # 5. Descargar desde el panel
        if download_from_panel(page, target_date):
            downloaded_total += 1
            logger.info(f"[{downloaded_total}] ✓ {target_date}")

            # 6. Subir a SharePoint
            try:
                import config as cfg
                from uploader import upload_to_sharepoint
                filepath = os.path.join(OUTPUT_DIR, f"SALES_{target_date.strftime('%Y%m%d')}_HoneyCanDoHK.xlsx")
                upload_to_sharepoint(filepath, cfg)
            except Exception as e:
                logger.warning(f"No se pudo subir a SharePoint: {e}")
        else:
            logger.warning(f"No se pudo descargar {target_date}, continuando...")

        random_delay()
        logger.info(f"Progreso: {downloaded_total} descargados.")

    logger.info(f"✓ Fin. {downloaded_total} archivos en output/")