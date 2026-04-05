"""
Alohida Telegram bot — TOTLI BI kodiga bog'lanmaydi.

Mahalliy (sinov):
  BOT_MODE=polling — kompyuter yoqilguncha ishlaydi

Bulut (kompyuter o'chsa ham):
  BOT_MODE=webhook + WEBHOOK_BASE_URL — Docker yoki PaaS ga joylang

Ishga tushirish:
  cd external/telegram_sheets_bot
  python -m venv .venv && .venv\\Scripts\\activate
  pip install -r requirements.txt
  copy env.example .env
  python -m src.main
"""
import asyncio
import logging
import socket
import sys

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from src.config import (
    BOT_LOCK_PORT,
    BOT_MODE,
    HOST,
    PORT,
    TELEGRAM_BOT_TOKEN,
    WEBHOOK_BASE_URL,
    WEBHOOK_PATH,
    WEBHOOK_SECRET,
)
from src.handlers import router as handlers_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)

# Bir kompyuterda ikkinchi polling ni ishga tushirmaslik (TelegramConflictError oldini olish)
_POLLING_LOCK_SOCK: socket.socket | None = None


def _acquire_polling_singleton() -> None:
    """127.0.0.1:BOT_LOCK_PORT band bo'lsa — boshqa bot jarayoni allaqachon ishlayapti."""
    global _POLLING_LOCK_SOCK
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", BOT_LOCK_PORT))
    except OSError:
        s.close()
        logging.error(
            "Polling allaqachon ishlamoqda (bir token — bir jarayon). "
            "Boshqa terminal / run.bat / Task Scheduler dagi nusxani to'xtating. "
            "Task Manager: python.exe; yoki: netstat -ano | findstr :%s",
            BOT_LOCK_PORT,
        )
        sys.exit(1)
    _POLLING_LOCK_SOCK = s


def _build_bot_dp() -> tuple[Bot, Dispatcher]:
    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(handlers_router)
    return bot, dp


async def _run_polling() -> None:
    bot, dp = _build_bot_dp()
    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    logging.info("Polling: @%s (mahalliy — kompyuter o'chsa to'xtaydi)", me.username)
    await dp.start_polling(bot)


def _run_webhook() -> None:
    if not WEBHOOK_BASE_URL:
        logging.error("BOT_MODE=webhook uchun WEBHOOK_BASE_URL kerak (masalan https://app.onrender.com)")
        sys.exit(1)

    bot, dp = _build_bot_dp()
    app = web.Application()

    async def health(_request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/", health)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        handle_in_background=True,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)

    setup_application(app, dp, bot=bot)

    full_url = f"{WEBHOOK_BASE_URL}{WEBHOOK_PATH}"

    async def _set_webhook(_app: web.Application) -> None:
        await bot.set_webhook(
            url=full_url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        me = await bot.get_me()
        logging.info("Webhook o'rnatildi: %s | @%s", full_url, me.username)

    async def _delete_webhook(_app: web.Application) -> None:
        await bot.delete_webhook()

    # Dispatcher startup avval, keyin Telegram webhook
    app.on_startup.append(_set_webhook)
    app.on_shutdown.append(_delete_webhook)

    logging.info("HTTP %s:%s — webhook rejimi (bulutda doim ishlaydi)", HOST, PORT)
    web.run_app(app, host=HOST, port=PORT)


def main() -> None:
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 30:
        logging.error("TELEGRAM_BOT_TOKEN .env da yo'q yoki qisqa.")
        sys.exit(1)

    if BOT_MODE == "webhook":
        _run_webhook()
    else:
        _acquire_polling_singleton()
        asyncio.run(_run_polling())


if __name__ == "__main__":
    main()
