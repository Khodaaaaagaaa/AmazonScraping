"""
config.py — Configuración central del scraper
"""

from datetime import date

# ─── CREDENCIALES ────────────────────────────────────────────────────────────
EMAIL = ""
PASSWORD = ""                          
TOTP_SECRET = ""

# ─── CUENTA ──────────────────────────────────────────────────────────────────
ACCOUNT_NAME = ""

# ─── RANGO DE FECHAS ─────────────────────────────────────────────────────────
START_DATE = date(2026, 1, 2)
END_DATE   = date(2026, 1, 2)

# ─── CONFIGURACIÓN DE DESCARGA ───────────────────────────────────────────────
OUTPUT_DIR = "output"
MAX_QUEUE  = 1
POLL_INTERVAL_SEC  = 30
REPORT_TIMEOUT_SEC = 300
DELAY_BETWEEN_REQUESTS = (8, 15)

# ─── CHROME ──────────────────────────────────────────────────────────────────
CHROME_PROFILE_DIR = "chrome_profile"
HEADLESS = False

# ─── URLS ────────────────────────────────────────────────────────────────────
BASE_URL      = ""
LOGIN_URL     = ""
SALES_URL     = ""
DOWNLOADS_URL = ""
# ─── SHAREPOINT ──────────────────────────────────────────────────────────────
SHAREPOINT_SITE_URL    = ""
SHAREPOINT_USER        = ""
SHAREPOINT_PASSWORD    = ""   
SHAREPOINT_FOLDER_PATH = ""
