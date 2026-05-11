"""
config.py — Configuración central del scraper
"""

from datetime import date

# ─── CREDENCIALES ────────────────────────────────────────────────────────────
EMAIL = "analytics@candobrands.com"
PASSWORD = "Hatchecom2025$"                          
TOTP_SECRET = "BOTEXJXFCIZAIHLX6GXBEEH4WIIT3ZKBO66HBD4VDEBZGDTCUBYQ"

# ─── CUENTA ──────────────────────────────────────────────────────────────────
ACCOUNT_NAME = "Honey Can Do HK Limited"

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
BASE_URL      = "https://vendorcentral.amazon.com"
LOGIN_URL     = "https://vendorcentral.amazon.com/signin"
SALES_URL     = "https://vendorcentral.amazon.com/analytics/dashboard/salesDiagnostic"
DOWNLOADS_URL = "https://vendorcentral.amazon.com/analytics/dashboard/managedDownloads"
# ─── SHAREPOINT ──────────────────────────────────────────────────────────────
SHAREPOINT_SITE_URL    = "https://hatchecom.sharepoint.com/sites/Hatchecom"
SHAREPOINT_USER        = "carlos.p@hatchecom.com"
SHAREPOINT_PASSWORD    = "Thor2026!*"   
SHAREPOINT_FOLDER_PATH = "Shared Documents/Data Manuel Dashboard PBI/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK/00 Sales"