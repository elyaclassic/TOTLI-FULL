"""Mijoz Telegram boti — mustaqil jarayon (socket singleton lock).

Ishga tushirish: python scripts/customer_bot_standalone.py
"""
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("customer_bot")

LOCK_PORT = int(os.environ.get("CUSTOMER_BOT_LOCK_PORT", "47893"))


def _acquire_singleton():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        logger.error(f"Port {LOCK_PORT} band — bot allaqachon ishlamoqda. Chiqish.")
        sys.exit(1)


def main():
    _lock = _acquire_singleton()  # noqa: F841 — GC bo'lmasligi uchun ushlab turamiz
    from app.bot.customer_bot.bot import run_polling
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
