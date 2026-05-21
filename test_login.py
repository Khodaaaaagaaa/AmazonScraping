"""
test_login.py — Prueba el flujo de auto-login en Amazon Vendor Central.
               Genera TOTP desde config.TOTP_SECRET, completa el formulario
               de login y verifica que la sesión queda activa.
               Si tiene éxito, sobreescribe cookies.json con las nuevas cookies.

Uso: python test_login.py
"""

import json
import logging
import sys
import time
from pathlib import Path

import pyotp
from playwright.sync_api import sync_playwright

import config as cfg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

COOKIES_FILE  = Path("cookies.json")
PROFILE_DIR   = Path(cfg.CHROME_PROFILE_DIR).resolve()
LOGIN_URL     = "https://vendorcentral.amazon.com"
SIGNIN_URL    = "https://www.amazon.com/ap/signin"


def do_login(page) -> bool:
    """
    Ejecuta el flujo completo de login:
      1. Email
      2. Password
      3. OTP (TOTP generado desde cfg.TOTP_SECRET)
    Retorna True si la sesión queda activa.
    """
    logger.info("Navegando a Vendor Central...")
    page.goto(LOGIN_URL, timeout=30000)
    page.wait_for_load_state("domcontentloaded", timeout=15000)
    time.sleep(2)

    url = page.url
    logger.info(f"URL inicial: {url}")

    # Si ya está logueado no hacer nada
    if not any(k in url.lower() for k in ["signin", "ap/signin", "login"]):
        logger.info("✓ Ya hay sesión activa — no se necesita login.")
        return True

    # ── Paso 1: Email ─────────────────────────────────────────────────────────
    logger.info("Ingresando email...")
    page.screenshot(path="debug_login_01_email.png")
    try:
        page.fill('input[type="email"], input[name="email"]', cfg.EMAIL, timeout=10000)
        page.click('input[type="submit"], #continue', timeout=8000)
        time.sleep(2)
        # Edge abre diálogo de Windows Hello / passkey después del email.
        # Escape lo descarta sin importar si apareció o no.
        page.keyboard.press('Escape')
        time.sleep(0.5)
    except Exception as e:
        logger.error(f"Error en campo email: {e}")
        page.screenshot(path="debug_login_01_email_error.png")
        return False

    # ── Paso 2: Password ──────────────────────────────────────────────────────
    logger.info("Ingresando password...")
    page.screenshot(path="debug_login_02_password.png")
    try:
        page.fill('input[type="password"], input[name="password"]', cfg.PASSWORD, timeout=10000)
        page.evaluate("document.getElementById('signInSubmit').form.submit()")
        try:
            page.wait_for_url(lambda url: "ap/signin" not in url, timeout=15000)
        except Exception:
            pass
        time.sleep(1)
    except Exception as e:
        logger.error(f"Error en campo password: {e}")
        page.screenshot(path="debug_login_02_password_error.png")
        return False

    # ── Paso 3: OTP / MFA ─────────────────────────────────────────────────────
    url_after_pw = page.url
    logger.info(f"URL tras password: {url_after_pw}")
    page.screenshot(path="debug_login_03_mfa.png")

    if any(k in url_after_pw.lower() for k in ["mfa", "otp", "auth", "code", "claimspicker", "accountfixup"]):
        try:
            otp_code = pyotp.TOTP(cfg.TOTP_SECRET).now()
            logger.info(f"OTP generado: {otp_code}")
            page.fill('input[type="text"], input[name="otpCode"], input[id*="otp"]',
                      otp_code, timeout=10000)
            page.click('input[type="submit"], button[type="submit"]', timeout=8000)
            time.sleep(3)
        except Exception as e:
            logger.error(f"Error en campo OTP: {e}")
            page.screenshot(path="debug_login_03_mfa_error.png")
            return False
    else:
        logger.info("No se detectó pantalla MFA — saltando paso OTP.")

    # ── Verificar sesión ──────────────────────────────────────────────────────
    page.screenshot(path="debug_login_04_result.png")
    final_url = page.url
    logger.info(f"URL final: {final_url}")

    bad = ["signin", "ap/signin", "ap/mfa", "login", "ap/captcha"]
    if any(k in final_url.lower() for k in bad):
        logger.error("❌ Login falló — todavía en página de autenticación.")
        return False

    logger.info("✓ Login exitoso.")
    return True


def save_cookies(context) -> int:
    """Extrae cookies del contexto de Playwright y las guarda en cookies.json."""
    cookies = context.cookies()
    COOKIES_FILE.write_text(
        json.dumps(cookies, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"✓ {len(cookies)} cookies guardadas en {COOKIES_FILE}")
    return len(cookies)


def main():
    logger.info("=" * 55)
    logger.info("  TEST AUTO-LOGIN — Amazon Vendor Central")
    logger.info("=" * 55)
    logger.info(f"  Email  : {cfg.EMAIL}")
    logger.info(f"  TOTP   : {'configurado' if cfg.TOTP_SECRET else '❌ FALTA'}")
    logger.info("=" * 55)

    if not cfg.TOTP_SECRET:
        logger.error("TOTP_SECRET no configurado en config.py")
        sys.exit(1)

    # Verificar que pyotp está instalado
    try:
        test_otp = pyotp.TOTP(cfg.TOTP_SECRET).now()
        logger.info(f"OTP de prueba generado correctamente: {test_otp}")
    except Exception as e:
        logger.error(f"Error generando OTP: {e}")
        logger.error("Instalá pyotp: pip install pyotp")
        sys.exit(1)

    with sync_playwright() as p:
        browser_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=WebAuthentication",
            "--password-store=basic",
        ]
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                channel="msedge",
                args=browser_args,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )
        except Exception:
            logger.info("Edge no disponible, usando Chromium...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=False,
                args=browser_args,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
            )

        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.chrome = { runtime: {} };
        """)

        success = False
        for attempt in range(1, 4):
            logger.info(f"\n── Intento {attempt}/3 ──────────────────────────────")
            if do_login(page):
                n = save_cookies(context)
                logger.info(f"\n{'='*55}")
                logger.info(f"  ✅ LOGIN EXITOSO — {n} cookies guardadas")
                logger.info(f"  Archivo: {COOKIES_FILE.resolve()}")
                logger.info(f"  Screenshots: debug_login_*.png")
                logger.info(f"{'='*55}")
                success = True
                break
            else:
                logger.warning(f"Intento {attempt} fallido.")
                if attempt < 3:
                    logger.info("Esperando 5 segundos antes del siguiente intento...")
                    time.sleep(5)
                    # Volver a la página de login para reintentar
                    page.goto(LOGIN_URL, timeout=30000)
                    time.sleep(2)

        if not success:
            logger.error("\n❌ LOGIN FALLÓ en los 3 intentos.")
            logger.error("Revisá los screenshots debug_login_*.png para diagnosticar.")
            context.close()
            sys.exit(1)

        context.close()


if __name__ == "__main__":
    main()
