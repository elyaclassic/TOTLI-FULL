"""Muhit o'zgaruvchilari — loyiha ildizidan .env o'qiladi."""
import os
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()

# polling = mahalliy sinov (kompyuter yoqilguncha ishlaydi)
# webhook = bulut / server (kompyuter o'chsa ham ishlaydi — HTTPS URL kerak)
BOT_MODE = os.environ.get("BOT_MODE", "polling").strip().lower()

# Webhook: to'liq domen, oxirida / bo'lmasin. Masalan: https://xxx.onrender.com
WEBHOOK_BASE_URL = os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
# Telegram POST manzili (HTTPS domen + bu yo'l)
WEBHOOK_PATH = os.environ.get("WEBHOOK_PATH", "/webhook/telegram").strip()
if not WEBHOOK_PATH.startswith("/"):
    WEBHOOK_PATH = "/" + WEBHOOK_PATH

# Telegram tavsiya qiladi — tasodifiy uzun qator (BotFather emas, o'zingiz generatsiya qiling)
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip() or None

HOST = os.environ.get("HOST", "0.0.0.0").strip()
# Render / Fly / Railway odatda PORT beradi
PORT = int(os.environ.get("PORT", "8080"))

# Polling: bir kompyuterda faqat bitta jarayon (getUpdates konfliktini oldini olish)
BOT_LOCK_PORT = int(os.environ.get("BOT_LOCK_PORT", "47891"))

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
# Whisper: bo'sh qoldirsangiz til avtomatik aniqlanadi
_wlang = os.environ.get("WHISPER_LANGUAGE", "uz").strip()
WHISPER_LANGUAGE: str | None = _wlang if _wlang else None

GOOGLE_SHEETS_CREDENTIALS_JSON = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
# Jadval varag'i nomi (Google Sheets da)
GOOGLE_SHEET_WORKSHEET = os.environ.get("GOOGLE_SHEET_WORKSHEET", "Sheet1").strip() or "Sheet1"
