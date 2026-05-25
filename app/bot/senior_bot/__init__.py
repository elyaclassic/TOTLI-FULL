"""TOTLI BI Senior Assistant Bot.

Telegram gruppa bot — Anthropic Claude API orqali, 11 ekspert nuqtai
nazaridan TOTLI BI loyihasi savol-javobi.

Foydalanish: main.py'da `await start_senior_bot()` chaqiriladi (Stop event'da
`stop_senior_bot()`). Token va sozlamalar .env'da.
"""
from app.bot.senior_bot.bot import start_senior_bot, stop_senior_bot

__all__ = ["start_senior_bot", "stop_senior_bot"]
