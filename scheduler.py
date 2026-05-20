"""
scheduler.py — Mantiene el scraper corriendo y lo dispara a las horas definidas en
               config.SCHEDULE_TIMES (UTC). Diseñado para correr como servicio
               systemd en EC2 o en background en Windows.

Uso:
  python scheduler.py          → corre según config.SCHEDULE_TIMES
  python scheduler.py --now    → ejecuta inmediatamente (para probar)
"""

import logging
import subprocess
import sys
import time
from pathlib import Path

import schedule

import config as cfg

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "scheduler.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent


def run_scraper():
    ts = time.strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"run_{ts}.log"
    logger.info("=" * 55)
    logger.info("  INICIANDO SCRAPER")
    logger.info(f"  Log de esta corrida: {log_file}")
    logger.info("=" * 55)
    try:
        with open(log_file, "w", encoding="utf-8") as f:
            result = subprocess.run(
                [sys.executable, "main.py"],
                stdout=f,
                stderr=subprocess.STDOUT,
                cwd=SCRIPT_DIR,
            )
        if result.returncode == 0:
            logger.info(f"✓ Scraper completado exitosamente. Ver: {log_file}")
        else:
            logger.error(f"✗ Scraper terminó con error (código {result.returncode}). Ver: {log_file}")
    except Exception as e:
        logger.error(f"Error al lanzar scraper: {e}")


def main():
    if "--now" in sys.argv:
        logger.info("Modo --now: ejecutando scraper inmediatamente.")
        run_scraper()
        return

    if not hasattr(cfg, "SCHEDULE_TIMES") or not cfg.SCHEDULE_TIMES:
        logger.error("config.SCHEDULE_TIMES no está definido o está vacío.")
        sys.exit(1)

    for t in cfg.SCHEDULE_TIMES:
        schedule.every().day.at(t).do(run_scraper)
        logger.info(f"Scraper programado para las {t} UTC todos los días.")

    logger.info("Scheduler activo. Esperando próxima ejecución...")
    logger.info(f"Próxima corrida: {schedule.next_run()}")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
