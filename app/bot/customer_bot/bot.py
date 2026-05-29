import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.customer_bot.config import BOT_TOKEN
from app.bot.customer_bot.handlers import router

logger = logging.getLogger(__name__)


async def run_polling():
    if not BOT_TOKEN:
        logger.error("CUSTOMER_BOT_TOKEN yo'q — mijoz bot ishga tushmaydi")
        return
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Mijoz bot polling boshlandi")
    await dp.start_polling(bot)
