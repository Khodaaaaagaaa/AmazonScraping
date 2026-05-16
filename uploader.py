"""
uploader.py — Sube archivos a SharePoint en la carpeta correcta según el tipo de reporte.
              Soporta múltiples cuentas: si se pasa un dict 'account' con 'sp_folder',
              usa esa ruta como base; si no, usa config.SHAREPOINT_BASE_PATH.
"""
import logging
import requests
from pathlib import Path

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
    "REAL_TIME":    "01 Real Time Sales",   # Amazon: Real_Time_Sales_...
    "REALTIME":     "01 Real Time Sales",   # por si empieza sin guión bajo
    "DF_FORECAST":  "04 Forecasting",       # clave interna
    "DF":           "04 Forecasting",       # Amazon: DF_Forecasting_...
    "FORECASTING":  "04 Forecasting",
    "NET_PPM":      "05 Net PPM",           # Amazon: Net_PPM_...
    "NETPPM":       "05 Net PPM",           # clave interna
    "SALES":        "00 Sales",
    "INVENTORY":    "02 Inventory",
    "TRAFFIC":      "03 Traffic",
    "CATALOG":      "06 Catalog",
}


def get_base_path(account: dict = None) -> str:
    """
    Devuelve la ruta base de SharePoint para la cuenta indicada.
    Si 'account' tiene 'sp_folder', usa ese valor.
    Si no, usa config.SHAREPOINT_BASE_PATH.
    """
    if account and account.get("sp_folder"):
        return account["sp_folder"]
    return _cfg.SHAREPOINT_BASE_PATH


def get_folder_for_file(filename: str, base_path: str) -> str:
    """
    Determina la subcarpeta de destino a partir del nombre del archivo.
    Retorna la ruta completa: base_path + subcarpeta.
    """
    name_upper = Path(filename).name.upper()
    for prefix, subfolder in RELATIVE_FOLDERS.items():
        if name_upper.startswith(prefix):
            return f"{base_path}/{subfolder}"
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

    base_path = get_base_path(account)
    folder    = get_folder_for_file(file_path.name, base_path)

    logger.info(f"Subiendo '{file_path.name}' → {folder}")

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
