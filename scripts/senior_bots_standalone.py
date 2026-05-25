"""SENIOR_BOT_GROUP botlari — mustaqil jarayon (Yordamchim + 11 ekspert).

Nega: avval botlar uvicorn startup task ichida edi — server reload/crash
bo'lsa jim o'lardi, watchdog ko'rmasdi, avtotiklanish yo'q edi. Endi alohida
jarayon: socket-lock (ikki polling konflikti yo'q), alohida log
(observability), watchdog jarayon-tirikligini biladi.

NAMUNA: external/telegram_sheets_bot/src/main.py (socket singleton lock).

Ishlatish: D:\\TOTLI BI dan
    python scripts/senior_bots_standalone.py
(odatda scripts/_senior_bots_runner.bat orqali yashirin oynada)

MUHIM: uvicorn ichida BOTS_IN_PROCESS=1 bo'lmasligi kerak — aks holda
bir token ikki getUpdates → Telegram 409 "terminated by other getUpdates".
"""
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("senior_bots_standalone")

LOCK_PORT = int(os.environ.get("SENIOR_BOTS_LOCK_PORT", "47892"))
_lock_sock: socket.socket | None = None


def _acquire_singleton() -> None:
    """127.0.0.1:LOCK_PORT band bo'lsa — boshqa nusxa ishlayapti, chiqamiz."""
    global _lock_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)  # netstat LISTENING ko'rsatsin (start.bat/deploy tekshiruvi)
    except OSError:
        s.close()
        log.error(
            "Senior botlar allaqachon ishlamoqda (port %s). Ikkinchi nusxa "
            "ishga tushmaydi (Telegram 409 oldini olish). "
            "netstat -ano | findstr :%s",
            LOCK_PORT, LOCK_PORT,
        )
        sys.exit(1)
    _lock_sock = s


async def _amain() -> None:
    from app.bot.senior_bot import start_senior_bot
    from app.bot.expert_bots import start_expert_bots

    await start_senior_bot()
    await start_expert_bots()
    log.info(
        "[Senior Bots Standalone] Yordamchim + ekspertlar ishga tushdi "
        "(lock port %s, cwd=%s)", LOCK_PORT, os.getcwd(),
    )
    # start_*() polling'ni asyncio task qilib qo'yadi — loop'ni tirik tutamiz.
    while True:
        await asyncio.sleep(3600)


def main() -> None:
    _acquire_singleton()
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt — to'xtadi")


if __name__ == "__main__":
    main()
