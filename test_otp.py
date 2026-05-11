"""
test_otp.py — Verificá que tu TOTP_SECRET es correcto ANTES de correr el scraper.

Uso:
    python test_otp.py

Deberías ver el mismo código de 6 dígitos que muestra tu app autenticadora.
Si no coincide, revisá el TOTP_SECRET en config.py.
"""

import time
import pyotp
from config import TOTP_SECRET


def test_totp():
    if TOTP_SECRET == "TU_SEED_KEY_TOTP_AQUI":
        print("❌  Todavía no pusiste tu TOTP_SECRET en config.py")
        print("    Abrí config.py y reemplazá TU_SEED_KEY_TOTP_AQUI con tu seed key.")
        return

    totp = pyotp.TOTP(TOTP_SECRET)
    code = totp.now()
    remaining = 30 - int(time.time()) % 30

    print(f"✓  Código OTP actual : {code}")
    print(f"   Válido por         : {remaining} segundos más")
    print()
    print("→  Compará este código con el que muestra tu app autenticadora.")
    print("   Si coinciden, tu TOTP_SECRET está bien configurado.")


if __name__ == "__main__":
    test_totp()
