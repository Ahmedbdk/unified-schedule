"""Run one unattended refresh and retain bounded local logs."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys


def main():
    project = Path(__file__).resolve().parents[2]
    logs = project / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("unified_schedule.scheduled")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(logs / "sync.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        logger.info("Début de l'actualisation automatique.")
        result = subprocess.run(
            [sys.executable, "-m", "unified_schedule.sync", "--non-interactive"],
            cwd=project, capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=_child_environment(), check=False,
        )
        for line in result.stdout.splitlines():
            logger.info(line)
        for line in result.stderr.splitlines():
            logger.error(line)
        if result.returncode:
            logger.error("Échec (code %s). Consultez les lignes précédentes. Si la session Workforce a expiré, relancez workforce --login manuellement.", result.returncode)
        else:
            logger.info("Actualisation automatique terminée avec succès.")
        return result.returncode
    except OSError:
        logger.exception("Impossible de démarrer l'actualisation.")
        return 1
    finally:
        logger.removeHandler(handler)
        handler.close()


def _child_environment():
    import os
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


if __name__ == "__main__":
    raise SystemExit(main())
