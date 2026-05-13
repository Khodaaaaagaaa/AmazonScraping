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

# ─── RANGO DE FECHAS ─────────────────────────────────────────────────────────
START_DATE = date(2026, 1, 1)
END_DATE   = date(2026, 1, 2)   # ← Cambiá a date(2026, 5, 4) para el histórico completo

# ─── CONFIGURACIÓN DE DESCARGA ───────────────────────────────────────────────
OUTPUT_DIR             = "output"
MAX_QUEUE              = 1
POLL_INTERVAL_SEC      = 30
REPORT_TIMEOUT_SEC     = 300
DELAY_BETWEEN_REQUESTS = (8, 15)

# ─── CHROME ──────────────────────────────────────────────────────────────────
CHROME_PROFILE_DIR = "chrome_profile"
HEADLESS           = False

# ─── SHAREPOINT ──────────────────────────────────────────────────────────────
SHAREPOINT_SITE_URL = ""
SHAREPOINT_USER     = ""
SHAREPOINT_PASSWORD = ""

# Carpeta base — cada reporte va a su subcarpeta (ver uploader.py → FOLDER_MAP)
SHAREPOINT_BASE_PATH = (

)
