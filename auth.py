"""
auth.py — Login a Amazon Vendor Central con TOTP
"""

import time
import logging
import pyotp
from playwright.sync_api import Page, TimeoutError as PWTimeout

from config import EMAIL, PASSWORD, TOTP_SECRET, ACCOUNT_NAME

logger = logging.getLogger(__name__)


def get_otp_code() -> str:
    totp = pyotp.TOTP(TOTP_SECRET)
    code = totp.now()
    logger.info(f"OTP generado: {code} (válido por {30 - int(time.time()) % 30}s más)")
    return code


def is_logged_in(page: Page) -> bool:
    try:
        page.goto("https://vendorcentral.amazon.com/hz/vendor/members/homepage", timeout=20000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        time.sleep(3)
        # Si redirige al login, no estamos logueados
        if "signin" in page.url or "ap/signin" in page.url or "login" in page.url.lower():
            return False
        # Si aparece contenido de vendor central
        if "vendorcentral.amazon.com" in page.url and "signin" not in page.url:
            logger.info("Sesión activa detectada.")
            return True
    except Exception as e:
        logger.warning(f"Error chequeando sesión: {e}")
    return False


def login(page: Page) -> bool:
    logger.info("Iniciando login en Amazon Vendor Central...")

    try:
        # Ir directo a homepage, Amazon redirige al login solo
        page.goto("https://vendorcentral.amazon.com", timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(3)

        logger.info(f"URL actual: {page.url}")

        # ── Paso 1: Email ────────────────────────────────────────────────────
        # Amazon puede mostrar email en un paso separado o junto con password
        email_selectors = [
            '#ap_email',
            'input[name="email"]',
            'input[type="email"]',
            'input[id="ap_email"]',
        ]

        email_input = None
        for selector in email_selectors:
            try:
                el = page.locator(selector)
                el.wait_for(timeout=8000, state="visible")
                email_input = el
                logger.info(f"Campo email encontrado: {selector}")
                break
            except Exception:
                continue

        if not email_input:
            logger.error("No se encontró campo de email. Screenshot guardado.")
            page.screenshot(path="debug_login.png")
            return False

        email_input.click()
        email_input.fill(EMAIL)
        time.sleep(1)

        # Buscar botón Continue o Sign In
        for btn_sel in ['#continue', 'input[id="continue"]', 'input[type="submit"]']:
            try:
                btn = page.locator(btn_sel)
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    page.wait_for_load_state("domcontentloaded", timeout=10000)
                    time.sleep(2)
                    break
            except Exception:
                continue

        logger.info(f"URL tras email: {page.url}")

        # ── Paso 2: Password ─────────────────────────────────────────────────
        pwd_selectors = ['#ap_password', 'input[name="password"]', 'input[type="password"]']
        pwd_input = None
        for selector in pwd_selectors:
            try:
                el = page.locator(selector)
                el.wait_for(timeout=8000, state="visible")
                pwd_input = el
                logger.info(f"Campo password encontrado: {selector}")
                break
            except Exception:
                continue

        if not pwd_input:
            logger.error("No se encontró campo de password.")
            page.screenshot(path="debug_password.png")
            return False

        pwd_input.click()
        pwd_input.fill(PASSWORD)
        time.sleep(1)

        # Click en Sign In
        for btn_sel in ['#signInSubmit', 'input[id="signInSubmit"]', 'input[type="submit"]', 'button[type="submit"]']:
            try:
                btn = page.locator(btn_sel)
                if btn.count() > 0 and btn.is_visible():
                    btn.click()
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    time.sleep(3)
                    break
            except Exception:
                continue

        logger.info(f"URL tras password: {page.url}")

        # ── Paso 3: OTP ──────────────────────────────────────────────────────
        otp_selectors = [
            'input[name="otpCode"]',
            '#auth-mfa-otpcode',
            'input[autocomplete="one-time-code"]',
            'input[id="auth-mfa-otpcode"]',
        ]

        for selector in otp_selectors:
            try:
                el = page.locator(selector)
                el.wait_for(timeout=5000, state="visible")
                logger.info(f"Campo OTP encontrado: {selector}")
                code = get_otp_code()
                el.fill(code)
                time.sleep(1)

                # No recordar dispositivo
                try:
                    remember = page.locator('#auth-mfa-remember-device')
                    if remember.count() > 0 and remember.is_checked():
                        remember.uncheck()
                except Exception:
                    pass

                # Submit OTP
                for submit_sel in ['#auth-signin-button', 'input[id="auth-signin-button"]', 'input[type="submit"]', 'button[type="submit"]']:
                    try:
                        s = page.locator(submit_sel)
                        if s.count() > 0 and s.is_visible():
                            s.click()
                            page.wait_for_load_state("domcontentloaded", timeout=15000)
                            time.sleep(3)
                            break
                    except Exception:
                        continue
                break
            except Exception:
                continue

        logger.info(f"URL tras OTP: {page.url}")

        # ── Verificación ─────────────────────────────────────────────────────
        if "signin" in page.url or "ap/signin" in page.url:
            logger.error("Seguimos en sign-in después del login.")
            page.screenshot(path="debug_after_login.png")
            return False

        logger.info("Login exitoso.")
        return True

    except PWTimeout as e:
        logger.error(f"Timeout durante login: {e}")
        page.screenshot(path="debug_timeout.png")
        return False
    except Exception as e:
        logger.error(f"Error en login: {e}")
        raise