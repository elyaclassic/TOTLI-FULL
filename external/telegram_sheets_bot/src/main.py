"""
Alohida Telegram bot — TOTLI BI kodiga bog'lanmaydi.

Ishga tushirish (loyiha papkasidan):
  cd external/telegram_sheets_bot
  python -m venv .venv
  .venv\\Scripts\\activate
  pip install -r requirements.txt
  copy env.example .env
  # .env da TELEGRAM_BOT_TOKEN ni to'ldiring
  python -m src.main
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.config import TELEGRAM_BOT_TOKEN
from src.handlers import router as handlers_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN or len(TELEGRAM_BOT_TOKEN) < 30:
        logging.error("TELEGRAM_BOT_TOKEN .env da yo'q yoki qisqa.")
        sys.exit(1)

    bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(handlers_router)

    await bot.delete_webhook(drop_pending_updates=True)
    me = await bot.get_me()
    logging.info("Bot ishga tushdi: @%s", me.username)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
