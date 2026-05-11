# Amazon Vendor Central — Sales Scraper
### Honey Can Do HK Limited | Enero → Mayo 2026

---

## ¿Qué hace este sistema?

Descarga automáticamente los reportes **Sales** de Amazon Vendor Central
día por día, con todos los filtros que usa Oscar manualmente:

| Filtro | Valor |
|---|---|
| Time frame | Daily |
| View By | ASIN |
| Distributor View | Sourcing |
| Columnas | Todas (26/26) |
| Formato | Excel (.xlsx) |

Los archivos quedan en la carpeta `output/` con el nombre:
```
SALES_20260101_HoneyCanDoHK.xlsx
SALES_20260102_HoneyCanDoHK.xlsx
...
```

---

## Requisitos

- Windows 10/11
- Python 3.11 o superior → https://www.python.org/downloads/
- Google Chrome instalado

---

## Instalación (una sola vez)

Abrí una terminal (CMD o PowerShell) en la carpeta del proyecto y ejecutá:

```bash
# 1. Instalar dependencias Python
pip install -r requirements.txt

# 2. Instalar el navegador Chromium de Playwright
python -m playwright install chromium
```

---

## Configuración

### Paso 1: Credenciales
Abrí `config.py` y completá:

```python
EMAIL    = "tu_email@ejemplo.com"
PASSWORD = "tu_password_aqui"
TOTP_SECRET = "XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # ← Ver abajo cómo obtenerlo
```

### Paso 2: Cómo obtener el TOTP_SECRET

El TOTP_SECRET es la **seed key** de tu autenticador. Es el código que
escaneás con el QR cuando configurás el 2FA por primera vez.

**Opción A — Si usás Google Authenticator en Android:**
1. Abrí Google Authenticator
2. Tocá los 3 puntitos → "Transferir cuentas" → "Exportar cuentas"
3. Usá una app como "Authenticator Export Decoder" para ver las seeds
   → https://github.com/beemdevelopment/Aegis (alternativa más fácil)

**Opción B — Si usás Authy:**
1. Authy Desktop → Settings → Advanced → Enable "Backup Password"
2. Una vez respaldado podés ver las seeds con herramientas de exportación

**Opción C — Configurar de nuevo el 2FA en Amazon:**
1. Ir a Amazon Vendor Central → Settings → Login & security → 2FA
2. Elegir "Authenticator App"
3. Cuando te muestre el QR, hacé clic en "Can't scan the barcode?"
4. Te muestra el código alfanumérico → ese es tu TOTP_SECRET

**Formato:** El secret es una cadena de letras mayúsculas y números,
típicamente 32 caracteres. Ejemplo: `JBSWY3DPEHPK3PXP`

### Paso 3: Verificar el OTP
Antes de correr el scraper, verificá que el secret sea correcto:

```bash
python test_otp.py
```

Deberías ver el mismo código de 6 dígitos que tu app autenticadora.

---

## Uso

```bash
python main.py
```

El navegador Chrome se va a abrir y podés ver todo lo que hace.
Los archivos Excel se van guardando en `output/` a medida que se descargan.

### Resumir una descarga interrumpida
Si el proceso se corta, simplemente volvé a correr `python main.py`.
El sistema **saltea automáticamente** los archivos que ya existen en `output/`.

---

## Parámetros ajustables en config.py

| Parámetro | Default | Descripción |
|---|---|---|
| `START_DATE` | 2026-01-01 | Fecha de inicio |
| `END_DATE` | 2026-05-04 | Fecha de fin |
| `MAX_QUEUE` | 4 | Reportes simultáneos (no subir de 5) |
| `POLL_INTERVAL_SEC` | 30 | Cada cuántos segundos chequea si están listos |
| `DELAY_BETWEEN_REQUESTS` | (8, 15) | Delay aleatorio entre requests (seg) |
| `HEADLESS` | False | True = sin ventana visible |

---

## Estructura de archivos

```
amazon_scraper/
├── config.py          ← Editá esto con tus credenciales
├── main.py            ← Entry point, corré esto
├── auth.py            ← Login + OTP
├── downloader.py      ← Lógica de descarga
├── test_otp.py        ← Verificar que el TOTP funciona
├── requirements.txt   ← Dependencias
├── scraper.log        ← Log de ejecución (se crea al correr)
├── chrome_profile/    ← Perfil Chrome con sesión guardada (se crea solo)
└── output/            ← Acá quedan los Excel descargados
    ├── SALES_20260101_HoneyCanDoHK.xlsx
    ├── SALES_20260102_HoneyCanDoHK.xlsx
    └── ...
```

---

## Solución de problemas

### "No se pudo iniciar sesión"
- Verificá email y password en config.py
- Corré `python test_otp.py` para confirmar que el TOTP es correcto
- La primera vez puede pedir que confirmes el login desde otro dispositivo

### El script se traba o no encuentra los botones
- Amazon cambió su UI → avisame y ajusto los selectores
- Probá con `HEADLESS = False` para ver qué está pasando

### "Has superado el límite"
- El sistema espera automáticamente, pero si pasa seguido, aumentá
  `DELAY_BETWEEN_REQUESTS` a `(20, 35)` en config.py

### Sesión expirada / pide OTP cada vez
- Esto es normal las primeras veces. Después de 1-2 logins exitosos,
  la sesión queda guardada en `chrome_profile/` y no te lo vuelve a pedir.

---

## Notas importantes

- **No corras dos instancias** del script al mismo tiempo para la misma cuenta
- Los reportes de Amazon tienen **2 días de lag**: el día de hoy y ayer
  no tienen data. Por eso `END_DATE` está en 2026-05-04
- Si Amazon actualiza su interfaz, avisame para actualizar los selectores
