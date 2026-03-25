"""Telegram bot — ishga tushirish va to'xtatish"""
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from app.bot.config import BOT_TOKEN
from app.bot.handlers import start, reports

_bot = None
_dp = None
_task = None


def _create_bot_and_dp():
    global _bot, _dp
    _bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    _dp = Dispatcher()
    _dp.include_router(start.router)
    _dp.include_router(reports.router)
    return _bot, _dp


async def start_bot():
    """Bot polling ni asyncio.Task sifatida ishga tushiradi"""
    global _task
    if not BOT_TOKEN or len(BOT_TOKEN) < 20:
        print("[TG Bot] Token yo'q — bot ishga tushmadi")
        return
    try:
        bot, dp = _create_bot_and_dp()
        # Webhook o'chirish (agar oldin qo'yilgan bo'lsa)
        await bot.delete_webhook(drop_pending_updates=True)
        _task = asyncio.create_task(_run_polling(dp, bot))
        me = await bot.get_me()
        print(f"[TG Bot] @{me.username} ishga tushdi (polling)")
    except Exception as e:
        print(f"[TG Bot] Ishga tushirishda xato: {e}")


async def _run_polling(dp: Dispatcher, bot: Bot):
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[TG Bot] Polling xatosi: {e}")


async def stop_bot():
    global _task, _bot
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    if _bot:
        await _bot.session.close()
        _bot = None
    print("[TG Bot] To'xtatildi")
