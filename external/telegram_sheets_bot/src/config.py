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
# auto = kalit bo'lsa OpenAI, yo'q bo'lsa lokal faster-whisper (bepul)
# local = faqat lokal | openai = faqat OpenAI API
TRANSCRIBE_BACKEND = os.environ.get("TRANSCRIBE_BACKEND", "auto").strip().lower()
# Lokal model: tiny < base < small < medium (small — o'zbek uchun yaxshiroq, sekinroq)
WHISPER_LOCAL_MODEL = os.environ.get("WHISPER_LOCAL_MODEL", "small").strip() or "small"
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
WHISPER_BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "8"))

# Modelga kontekst: o'zbek ismlar/so'zlar (lotin) — noto'g'ri eshitishni kamaytiradi
# Bo'sh qator berib o'chirish: WHISPER_INITIAL_PROMPT=
_ip = os.environ.get("WHISPER_INITIAL_PROMPT")
if _ip is None:
    WHISPER_INITIAL_PROMPT = (
        "O'zbek tilida nutq, lotin alifbosi. Ismlar: Akmal, Aziz, Dilshod, Jasur, Madina. "
        "So'zlar: salom, rahmat, ha, yo'q, men, siz, bu, uchun, qanday, nega."
    )
else:
    WHISPER_INITIAL_PROMPT = _ip.strip() or None

# Modelga qo'shimcha kalit so'zlar (vergul yoki bo'shliq bilan)
_h = os.environ.get("WHISPER_HOTWORDS", "Akmal, Aziz, Dilshod, Salom, rahmat, o'zbek").strip()
WHISPER_HOTWORDS: str | None = _h if _h else None

# Whisper: bo'sh qoldirsangiz til avtomatik aniqlanadi
_wlang = os.environ.get("WHISPER_LANGUAGE", "uz").strip()
WHISPER_LANGUAGE: str | None = _wlang if _wlang else None

GOOGLE_SHEETS_CREDENTIALS_JSON = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
GOOGLE_SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "").strip()
# Bot yozadigan varoq (Operatsiyalar jadvali)
GOOGLE_SHEET_OPERATIONS_WORKSHEET = (
    os.environ.get("GOOGLE_SHEET_OPERATIONS_WORKSHEET", "Operatsiyalar").strip() or "Operatsiyalar"
)
