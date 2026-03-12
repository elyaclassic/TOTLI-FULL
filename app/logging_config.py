"""
Logging sozlamalari — fayl + konsol, rotation.
"""
import os
import logging
from logging.handlers import RotatingFileHandler

# Loyiha ildizi (main.py yonida)
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if "app" in ROOT_DIR:
    ROOT_DIR = os.path.dirname(ROOT_DIR)
LOGS_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOGS_DIR, "totli_holva.log")
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5


def setup_logging(
    log_file: str = LOG_FILE,
    max_bytes: int = MAX_BYTES,
    backup_count: int = BACKUP_COUNT,
    level: int = logging.INFO,
) -> None:
    """Logging ni sozlash: fayl (rotation) + konsol."""
    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)
    # Eski handlerlarni tozalash (qayta chaqirilganda dublikat yozuvlarning oldini olish)
    for h in list(root.handlers):
        root.removeHandler(h)
    # Fayl handler (rotation)
    try:
        fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
    except Exception:
        pass
    # Konsol
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    root.addHandler(ch)


def get_logger(name: str) -> logging.Logger:
    """Modul uchun logger olish."""
    return logging.getLogger(name)
