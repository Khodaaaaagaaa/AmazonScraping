"""
config.py — Configuración central del scraper
"""
 
from datetime import date
 
# ─── CREDENCIALES AMAZON ─────────────────────────────────────────────────────
EMAIL    = ""
PASSWORD = ""
TOTP_SECRET = ""
 
# ─── CUENTA ──────────────────────────────────────────────────────────────────
ACCOUNT_NAME = "Honey Can Do HK Limited"

# EntityId de HK Limited en Amazon Advertising Console.
# Verificar en la URL cuando se navega a advertising.amazon.com con esa cuenta activa.
HK_ADS_ENTITY_ID = "ENTITY2BTHXP5BCM35L"
 
# ─── RANGO DE FECHAS ─────────────────────────────────────────────────────────
START_DATE = date(2026, 2, 1)
END_DATE   = date(2026, 2, 28)   # ← Cambiá a date(2026, 5, 4) para el histórico completo
 
# ─── CONFIGURACIÓN DE DESCARGA ───────────────────────────────────────────────
OUTPUT_DIR             = "output"
MAX_QUEUE              = 1
POLL_INTERVAL_SEC      = 30
REPORT_TIMEOUT_SEC     = 600
DELAY_BETWEEN_REQUESTS = (8, 15)

# ─── CONFIGURACIÓN ADS ───────────────────────────────────────────────────────
ADS_REPORT_TIMEOUT_SEC = 7200   # 120 min para Search Term / Advertised Product
ADS_POLL_INTERVAL_SEC  = 300    # Chequear cada 5 min
 
# ─── CHROME ──────────────────────────────────────────────────────────────────
CHROME_PROFILE_DIR = "chrome_profile"
HEADLESS           = False
 
# ─── SHAREPOINT ──────────────────────────────────────────────────────────────
SHAREPOINT_SITE_URL = "https://hatchecom.sharepoint.com/sites/Hatchecom"
SHAREPOINT_USER     = ""
SHAREPOINT_PASSWORD = ""
 
# Carpeta base Retail — subcarpetas 00-06 (ver uploader.py → RELATIVE_FOLDERS)
SHAREPOINT_BASE_PATH = (
    "Shared Documents/Data Manuel Dashboard PBI"
    "/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK"
)

# Carpeta base Ads (Sponsored Products) — subcarpetas 00-11 SP ...
SHAREPOINT_ADS_BASE_PATH = (
    "Shared Documents/Data Manuel Dashboard PBI"
    "/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK/SP check Honey"
)
