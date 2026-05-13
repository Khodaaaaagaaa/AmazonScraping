"""
upload_all.py — Sube todos los archivos de output/ a SharePoint
cada uno en su carpeta correspondiente.
"""
import logging, sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

import config as cfg
from uploader import get_token, get_folder_for_file
import requests

def upload_all():
    files = sorted(Path(cfg.OUTPUT_DIR).glob("*.xlsx"))
    if not files:
        logger.info("No hay archivos en output/")
        return

    logger.info(f"{len(files)} archivo(s) a subir:")
    for f in files:
        logger.info(f"  {f.name} → {get_folder_for_file(f.name)}")

    token = get_token(cfg)
    if not token:
        logger.error("No se pudo autenticar.")
        return

    ok = fail = 0
    for f in files:
        folder = get_folder_for_file(f.name)
        upload_url = (
            f"{cfg.SHAREPOINT_SITE_URL}/_api/web/"
            f"GetFolderByServerRelativeUrl('{folder}')/"
            f"Files/add(url='{f.name}',overwrite=true)"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Accept": "application/json;odata=verbose",
        }
        try:
            with open(f, "rb") as fh:
                resp = requests.post(upload_url, headers=headers, data=fh.read())
            if resp.status_code in (200, 201):
                logger.info(f"✓ {f.name}")
                ok += 1
            else:
                logger.error(f"✗ {f.name}: HTTP {resp.status_code} - {resp.text[:150]}")
                fail += 1
        except Exception as e:
            logger.error(f"✗ {f.name}: {e}")
            fail += 1

    logger.info(f"\nSubidos: {ok} | Errores: {fail}")

if __name__ == "__main__":
    upload_all()
