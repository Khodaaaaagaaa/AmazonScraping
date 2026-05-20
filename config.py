"""
config.py — Configuración central del scraper
"""

from datetime import date

# ─── CREDENCIALES AMAZON ─────────────────────────────────────────────────────
EMAIL    = "analytics@candobrands.com"
PASSWORD = ""
TOTP_SECRET = ""

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
SHAREPOINT_SITE_URL = ""
SHAREPOINT_USER     = ""
SHAREPOINT_PASSWORD = ""

# Rutas base heredadas (usadas como fallback si no se pasa account dict)
SHAREPOINT_BASE_PATH = (
    "Shared Documents/Data Manuel Dashboard PBI"
    "/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK"
)
SHAREPOINT_ADS_BASE_PATH = (
    "Shared Documents/Data Manuel Dashboard PBI"
    "/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK/SP check Honey"
)

# ─── CUENTAS ─────────────────────────────────────────────────────────────────
# Cada cuenta lleva su propia configuración de rutas, prefijos y entity IDs.
# ads_entity_id    → ver en advertising.amazon.com cuando la cuenta está activa (URL: entityId=XXXX)
# retail_entity_id → ver en vendorcentral.amazon.com cuando la cuenta está activa (URL: entityId=XXXX)
# retail_year_subfolder → si True, crea subcarpeta de año en SP Retail (ej: 00 Sales/2026/)
# has_df_forecast  → si True, descarga Direct Fulfillment Forecasting
ACCOUNTS = [
    {
        "name":                  "Honey Can Do HK Limited",
        "file_prefix":           "Honey",
        "vc_header_name":        "US - Honey Can Do HK Limited",
        "ads_entity_id":         "ENTITY2BTHXP5BCM35L",
        "retail_entity_id":      None,
        "output_dir":            "output_HK",
        "sp_folder":             (
            "Shared Documents/Data Manuel Dashboard PBI"
            "/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK"
        ),
        "sp_ads_folder":         (
            "Shared Documents/Data Manuel Dashboard PBI"
            "/DATA MANUAL DOWNLOAD/Honey Can Do Brand LK/SP check Honey"
        ),
        "retail_year_subfolder": False,
        "has_df_forecast":       False,
    },
    {
        "name":                  "Can Do Brands",
        "file_prefix":           "CanDo",
        "vc_header_name":        "US - Can Do Brands",
        "ads_entity_id":         "ENTITY27XA4F90VRJ2Y",
        "retail_entity_id":      None,
        "output_dir":            "output_CDB",   # Buscar en vendorcentral.amazon.com → URL → entityId=XXXX
        "sp_folder":             (
            "Shared Documents/Data Manuel Dashboard PBI"
            "/DATA MANUAL DOWNLOAD/Can Do Brands"
        ),
        "sp_ads_folder":         (
            "Shared Documents/Data Manuel Dashboard PBI"
            "/DATA MANUAL DOWNLOAD/Can Do Brands/SP Check Can Do"
        ),
        "retail_year_subfolder": True,
        "has_df_forecast":       False,
    },
]

# ─── COMPATIBILIDAD HACIA ATRÁS ───────────────────────────────────────────────
ACCOUNT_NAME     = ACCOUNTS[0]["name"]
HK_ADS_ENTITY_ID = ACCOUNTS[0]["ads_entity_id"]
