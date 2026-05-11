"""
upload_all.py — Sube archivos de output/ a SharePoint via MSAL
Sin browser, sin legacy auth.
"""
import logging, sys, json
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

import config as cfg

TENANT_ID  = "fdac34dd-697c-497a-aa80-23c83ef6527c"
CLIENT_ID  = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
SCOPES     = ["https://hatchecom.sharepoint.com/.default"]
TOKEN_FILE = Path("sharepoint_token.json")


def get_token():
    import msal
    cache = msal.SerializableTokenCache()
    if TOKEN_FILE.exists():
        cache.deserialize(TOKEN_FILE.read_text())

    app = msal.PublicClientApplication(
        CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
        token_cache=cache,
    )

    # 1. Token cacheado
    accounts = app.get_accounts(username=cfg.SHAREPOINT_USER)
    if accounts:
        r = app.acquire_token_silent(SCOPES, account=accounts[0])
        if r and "access_token" in r:
            logger.info("✓ Token desde caché")
            TOKEN_FILE.write_text(cache.serialize())
            return r["access_token"]

    # 2. Usuario + contraseña
    logger.info("Autenticando con usuario/contraseña...")
    r = app.acquire_token_by_username_password(
        username=cfg.SHAREPOINT_USER,
        password=cfg.SHAREPOINT_PASSWORD,
        scopes=SCOPES,
    )
    if "access_token" in r:
        logger.info("✓ Token obtenido")
        TOKEN_FILE.write_text(cache.serialize())
        return r["access_token"]

    # 3. Device code (abrís una URL en el browser)
    logger.warning(f"Usuario/contraseña falló: {r.get('error_description','')}")
    logger.info("Iniciando Device Code flow...")
    flow = app.initiate_device_flow(scopes=SCOPES)
    print("\n" + "="*60)
    print(flow["message"])
    print("="*60 + "\n")
    r = app.acquire_token_by_device_flow(flow)
    if "access_token" in r:
        logger.info("✓ Token via device code")
        TOKEN_FILE.write_text(cache.serialize())
        return r["access_token"]

    logger.error(f"Falló: {r.get('error_description','')}")
    return None


def upload_all():
    files = sorted(Path(cfg.OUTPUT_DIR).glob("*.xlsx"))
    if not files:
        logger.info("No hay archivos en output/")
        return

    logger.info(f"{len(files)} archivo(s) a subir:")
    for f in files:
        logger.info(f"  {f.name}")

    token = get_token()
    if not token:
        return

    from office365.sharepoint.client_context import ClientContext
    from office365.runtime.auth.token_response import TokenResponse

    def token_provider():
        return TokenResponse.from_json({"token_type": "Bearer", "access_token": token})

    ctx = ClientContext(cfg.SHAREPOINT_SITE_URL).with_access_token(token_provider)

    try:
        web = ctx.web
        ctx.load(web)
        ctx.execute_query()
        logger.info(f"✓ Conectado: {web.title}")
    except Exception as e:
        logger.error(f"Error conexión: {e}")
        return

    folder = ctx.web.get_folder_by_server_relative_url(cfg.SHAREPOINT_FOLDER_PATH)
    ok = fail = 0
    for f in files:
        try:
            # Usar large_file_upload para evitar el bug de datetimes
            with open(f, "rb") as fh:
                content_bytes = fh.read()
            from office365.sharepoint.files.file import File
            File.save_binary(ctx, f"/{cfg.SHAREPOINT_FOLDER_PATH}/{f.name}", content_bytes)
            ctx.execute_query()
            logger.info(f"✓ {f.name}")
            ok += 1
        except Exception as e1:
            # Fallback: upload directo via requests con el token
            try:
                import requests
                upload_url = (
                    f"{cfg.SHAREPOINT_SITE_URL}/_api/web/"
                    f"GetFolderByServerRelativeUrl('{cfg.SHAREPOINT_FOLDER_PATH}')/"
                    f"Files/add(url='{f.name}',overwrite=true)"
                )
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/octet-stream",
                    "Accept": "application/json;odata=verbose",
                }
                with open(f, "rb") as fh:
                    resp = requests.post(upload_url, headers=headers, data=fh.read())
                if resp.status_code in (200, 201):
                    logger.info(f"✓ {f.name} (via REST)")
                    ok += 1
                else:
                    logger.error(f"✗ {f.name}: HTTP {resp.status_code} - {resp.text[:200]}")
                    fail += 1
            except Exception as e2:
                logger.error(f"✗ {f.name}: {e2}")
                fail += 1

    logger.info(f"\nSubidos: {ok} | Errores: {fail}")

if __name__ == "__main__":
    upload_all()