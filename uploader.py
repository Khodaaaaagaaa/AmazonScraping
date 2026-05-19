"""
uploader.py — Sube archivos a SharePoint en la carpeta correcta según el tipo de reporte.
              Soporta múltiples cuentas: si se pasa un dict 'account' con 'sp_folder',
              usa esa ruta como base; si no, usa config.SHAREPOINT_BASE_PATH.
"""
import json
import logging
import re
import requests
from pathlib import Path
from urllib.parse import urlparse

import config as _cfg

logger = logging.getLogger(__name__)

TENANT_ID  = "fdac34dd-697c-497a-aa80-23c83ef6527c"
CLIENT_ID  = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
TOKEN_FILE = Path("sharepoint_token.json")

# Subcarpetas relativas a la carpeta base de la cuenta.
# Las claves son prefijos del nombre de archivo EN MAYÚSCULAS.
# Se incluyen variantes porque Amazon puede nombrar los archivos de distintas formas.
# Orden: más específicos primero para evitar matches parciales incorrectos.
RELATIVE_FOLDERS = {
    # ── Retail — nombres reales de Amazon ────────────────────────────────────
    # Más específicos primero para evitar matches parciales.
    "REAL_TIME_SALES": "01 Real Time Sales",   # Amazon: Real_Time_Sales_ASIN_...
    "REAL_TIME":       "01 Real Time Sales",   # variante sin _SALES
    "REALTIME":        "01 Real Time Sales",   # sin guión bajo
    "DF_FORECASTING":  "04 Forecasting",       # Amazon: DF_Forecasting_...
    "DF_FORECAST":     "04 Forecasting",
    "DF":              "04 Forecasting",
    "FORECASTING":     "04 Forecasting",
    "NET_PPM":         "05 Net PPM",           # Amazon: Net_PPM_ASIN_...
    "NETPPM":          "05 Net PPM",
    "SALES":           "00 Sales",             # Amazon: Sales_ASIN_...
    "INVENTORY":       "02 Inventory",         # Amazon: Inventory_ASIN_...
    "TRAFFIC":         "03 Traffic",           # Amazon: Traffic_ASIN_...
    "CATALOG":         "06 Catalog",           # Amazon: Catalog_ASIN_...

    # ── Ads (Sponsored Products) — base path: SHAREPOINT_ADS_BASE_PATH ────────
    # Nombres nuevos: Honey_Sponsored_Products_<Type>_report_YYYYMM.csv
    # Más específicos primero para evitar matches parciales.
    "HONEY_SPONSORED_PRODUCTS_SEARCH_TERM_IMPRESSION": "08 SP Search Term Impression",
    "HONEY_SPONSORED_PRODUCTS_SEARCH_TERM":            "00 SP Search Term",
    "HONEY_SPONSORED_PRODUCTS_TARGETING":              "01 SP Targeting",
    "HONEY_SPONSORED_PRODUCTS_ADVERTISED":             "02 SP Advertised",
    "HONEY_SPONSORED_PRODUCTS_CAMPAIGN":               "03 SP Campaign",
    "HONEY_SPONSORED_PRODUCTS_BUDGET":                 "04 SP Budget",
    "HONEY_SPONSORED_PRODUCTS_PLACEMENT":              "05 SP Placement",
    "HONEY_SPONSORED_PRODUCTS_AUDIENCE":               "06 SP Audience",
    "HONEY_SPONSORED_PRODUCTS_PERFORMANCE":            "07 SP Perfomance Over Time",
    "HONEY_SPONSORED_PRODUCTS_GROSS":                  "09 SP Gross and Invalid Traffic",
    "HONEY_SPONSORED_PRODUCTS_PROMPTS":                "10 SP Prompts",
    "HONEY_SPONSORED_PRODUCTS_VIDEO":                  "11 SP Video",
    # Nombres legacy ADS_ (compatibilidad hacia atrás)
    "ADS_SEARCH_TERM_IMP_SHARE":  "08 SP Search Term Impression",
    "ADS_SEARCH_TERM":            "00 SP Search Term",
    "ADS_TARGETING":              "01 SP Targeting",
    "ADS_ADVERTISED_PRODUCT":     "02 SP Advertised",
    "ADS_CAMPAIGN":               "03 SP Campaign",
    "ADS_BUDGET":                 "04 SP Budget",
    "ADS_PLACEMENT":              "05 SP Placement",
    "ADS_AUDIENCE":               "06 SP Audience",
    "ADS_PERF_OVER_TIME":         "07 SP Perfomance Over Time",
    "ADS_GROSS_INVALID_TRAFFIC":  "09 SP Gross and Invalid Traffic",
    "ADS_PROMPTS":                "10 SP Prompts",
    "ADS_VIDEO":                  "11 SP Video",
}

# Prefijos que corresponden a reportes ADS (para carpeta de año y base path)
_ADS_PREFIXES = {k for k in RELATIVE_FOLDERS if k.startswith(("ADS_", "HONEY_SPONSORED_PRODUCTS_"))}


def get_base_path(filename: str = None, account: dict = None) -> str:
    """
    Prioridad:
    1. account["sp_folder"] si está definido.
    2. Nombre de archivo empieza con "ADS_" → usar SHAREPOINT_ADS_BASE_PATH.
    3. Fallback: SHAREPOINT_BASE_PATH (retail).
    """
    if account and account.get("sp_folder"):
        return account["sp_folder"]
    if filename:
        name_up = Path(filename).name.upper()
        if name_up.startswith(("ADS_", "HONEY_SPONSORED_PRODUCTS_")):
            return _cfg.SHAREPOINT_ADS_BASE_PATH
    return _cfg.SHAREPOINT_BASE_PATH


def _ensure_folder(folder_path: str, token: str) -> bool:
    """
    Crea la carpeta en SharePoint nivel por nivel si no existe.
    Usa POST /_api/web/Folders con la URL relativa al servidor.
    """
    site_path = urlparse(_cfg.SHAREPOINT_SITE_URL).path.rstrip('/')
    headers_get = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json;odata=verbose",
    }
    headers_post = {
        **headers_get,
        "Content-Type": "application/json;odata=verbose",
    }

    # Si la carpeta ya existe, listo
    check_url = (
        f"{_cfg.SHAREPOINT_SITE_URL}/_api/web/"
        f"GetFolderByServerRelativeUrl('{folder_path}')"
    )
    try:
        if requests.get(check_url, headers=headers_get).status_code == 200:
            return True
    except Exception:
        pass

    # Crear nivel por nivel
    parts = folder_path.split('/')
    for depth in range(1, len(parts) + 1):
        partial   = '/'.join(parts[:depth])
        full_rel  = f"{site_path}/{partial}"
        body      = json.dumps({
            "__metadata": {"type": "SP.Folder"},
            "ServerRelativeUrl": full_rel,
        })
        try:
            r = requests.post(
                f"{_cfg.SHAREPOINT_SITE_URL}/_api/web/Folders",
                headers=headers_post,
                data=body,
            )
            if r.status_code in (200, 201):
                logger.info(f"Carpeta creada: {partial}")
            # 400/500 generalmente significa que ya existe — ok
        except Exception as e:
            logger.debug(f"_ensure_folder '{partial}': {e}")

    return True


def get_folder_for_file(filename: str, base_path: str) -> str:
    """
    Determina la subcarpeta de destino a partir del nombre del archivo.
    Para archivos ADS añade subcarpeta de año: base/subfolder/YYYY.
    """
    name_upper = Path(filename).name.upper()
    for prefix, subfolder in RELATIVE_FOLDERS.items():
        if name_upper.startswith(prefix):
            folder = f"{base_path}/{subfolder}"
            if prefix in _ADS_PREFIXES:
                # Extraer año: nuevo formato _YYYYMM., viejo formato _YYYYMMDD_
                m = re.search(r'_(\d{4})\d{2}[._]', name_upper)
                if m:
                    folder = f"{folder}/{m.group(1)}"
            return folder
    logger.warning(f"Sin carpeta específica para '{filename}'; usando '00 Sales' como fallback.")
    return f"{base_path}/00 Sales"


def get_token() -> str | None:
    """Obtiene (o refresca) el token de SharePoint con MSAL."""
    try:
        import msal
    except ImportError:
        logger.error("Falta: pip install msal")
        return None

    cache = msal.SerializableTokenCache()
    if TOKEN_FILE.exists():
        cache.deserialize(TOKEN_FILE.read_text())

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )
    scopes = ["https://hatchecom.sharepoint.com/.default"]

    accounts = app.get_accounts(username=_cfg.SHAREPOINT_USER)
    if accounts:
        r = app.acquire_token_silent(scopes, account=accounts[0])
        if r and "access_token" in r:
            TOKEN_FILE.write_text(cache.serialize())
            return r["access_token"]

    r = app.acquire_token_by_username_password(
        username=_cfg.SHAREPOINT_USER,
        password=_cfg.SHAREPOINT_PASSWORD,
        scopes=scopes,
    )
    if "access_token" in r:
        TOKEN_FILE.write_text(cache.serialize())
        return r["access_token"]

    logger.error(f"No se pudo obtener token: {r.get('error_description', '')}")
    return None


def upload_to_sharepoint(filepath: str, account: dict = None) -> bool:
    """
    Sube 'filepath' a la subcarpeta correcta de SharePoint.

    Parámetros:
      filepath  — ruta local al archivo descargado
      account   — dict con al menos 'sp_folder' para determinar la carpeta base;
                  si es None usa config.SHAREPOINT_BASE_PATH
    """
    file_path = Path(filepath)
    if not file_path.exists():
        logger.error(f"Archivo no encontrado: {filepath}")
        return False

    token = get_token()
    if not token:
        logger.error("Sin token SharePoint — no se pudo subir el archivo.")
        return False

    base_path = get_base_path(file_path.name, account)
    folder    = get_folder_for_file(file_path.name, base_path)

    logger.info(f"Subiendo '{file_path.name}' → {folder}")
    _ensure_folder(folder, token)

    upload_url = (
        f"{_cfg.SHAREPOINT_SITE_URL}/_api/web/"
        f"GetFolderByServerRelativeUrl('{folder}')/"
        f"Files/add(url='{file_path.name}',overwrite=true)"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Accept": "application/json;odata=verbose",
    }

    try:
        with open(file_path, "rb") as f:
            resp = requests.post(upload_url, headers=headers, data=f.read())
        if resp.status_code in (200, 201):
            logger.info(f"✓ Subido: {file_path.name}")
            return True
        logger.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
        return False
    except Exception as e:
        logger.error(f"upload_to_sharepoint error: {e}")
        return False


# ── CLI — python uploader.py ──────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    from pathlib import Path

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    output_dir = Path(_cfg.OUTPUT_DIR)
    if not output_dir.exists():
        print(f"Carpeta '{output_dir}' no encontrada.")
        sys.exit(1)

    files = sorted(output_dir.glob("*.xlsx")) + sorted(output_dir.glob("*.csv"))
    if not files:
        print(f"No hay archivos .xlsx/.csv en '{output_dir}'.")
        sys.exit(0)

    print(f"\nArchivos encontrados en '{output_dir}': {len(files)}")
    for f in files:
        print(f"  {f.name}")

    confirm = input("\n¿Subir todos a SharePoint? [S/n]: ").strip().lower()
    if confirm in ("n", "no"):
        print("Cancelado.")
        sys.exit(0)

    ok = failed = 0
    for f in files:
        if upload_to_sharepoint(str(f)):
            ok += 1
        else:
            failed += 1

    print(f"\nResultado: {ok} subidos, {failed} fallidos.")
