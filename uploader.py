"""
uploader.py — Sube archivos a SharePoint en la carpeta correcta según el tipo de reporte
"""
import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

TENANT_ID  = "fdac34dd-697c-497a-aa80-23c83ef6527c"
CLIENT_ID  = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
TOKEN_FILE = Path("sharepoint_token.json")
BASE_PATH  = "Shared Documents/Data Manuel Dashboard PBI/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK"

FOLDER_MAP = {
    "SALES":       f"{BASE_PATH}/00 Sales",
    "REALTIME":    f"{BASE_PATH}/01 Real Time Sales",
    "INVENTORY":   f"{BASE_PATH}/02 Inventory",
    "TRAFFIC":     f"{BASE_PATH}/03 Traffic",
    "FORECASTING": f"{BASE_PATH}/04 Forecasting",
    "DF_FORECAST": f"{BASE_PATH}/04 Forecasting",
    "NETPPM":      f"{BASE_PATH}/05 Net PPM",
    "CATALOG":     f"{BASE_PATH}/06 Catalog",
}


def get_folder_for_file(filename: str) -> str:
    name_upper = Path(filename).name.upper()
    for prefix, folder in FOLDER_MAP.items():
        if name_upper.startswith(prefix):
            return folder
    return FOLDER_MAP["SALES"]


def get_token(config) -> str | None:
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

    accounts = app.get_accounts(username=config.SHAREPOINT_USER)
    if accounts:
        r = app.acquire_token_silent(scopes, account=accounts[0])
        if r and "access_token" in r:
            TOKEN_FILE.write_text(cache.serialize())
            return r["access_token"]

    r = app.acquire_token_by_username_password(
        username=config.SHAREPOINT_USER,
        password=config.SHAREPOINT_PASSWORD,
        scopes=scopes,
    )
    if "access_token" in r:
        TOKEN_FILE.write_text(cache.serialize())
        return r["access_token"]

    logger.error(f"No se pudo obtener token: {r.get('error_description','')}")
    return None


def upload_to_sharepoint(filepath: str, config, sp_base: str = None) -> bool:
    file_path = Path(filepath)
    if not file_path.exists():
        logger.error(f"Archivo no encontrado: {filepath}")
        return False

    token = get_token(config)
    if not token:
        logger.error("Sin token SharePoint.")
        return False

    folder = get_folder_for_file(file_path.name, sp_base=sp_base)
    logger.info(f"Subiendo {file_path.name} → {folder}")

    upload_url = (
        f"{config.SHAREPOINT_SITE_URL}/_api/web/"
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
        else:
            logger.error(f"HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        logger.error(f"Error: {e}")
        return False
