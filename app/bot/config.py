"""Bot konfiguratsiyasi"""
import os

# Hisobot bot tokeni — .env faylidan o'qiladi (TELEGRAM_BOT_TOKEN)
# Bu majburiy: env yo'q bo'lsa hisobot bot ishlamaydi (warning bo'lib chiqadi).
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

if not BOT_TOKEN:
    import logging
    logging.getLogger(__name__).warning(
        "TELEGRAM_BOT_TOKEN env o'zgaruvchisi o'rnatilmagan — hisobot bot ishga tushmaydi. "
        ".env faylida TELEGRAM_BOT_TOKEN ni o'rnating."
    )

# Ruxsat etilgan rollar
ALLOWED_ROLES = ("admin", "manager", "rahbar", "raxbar")

# Faqat shu Telegram ID lar botdan foydalana oladi
# Yangi odam qo'shish uchun shu ro'yxatga ID qo'shing
ALLOWED_CHAT_IDS = [1340383182, 1057546370]

# Kunlik yakuniy hisobot (kechqurun 21:00)
NOTIFY_CHAT_IDS = [1057546370]  # @RD2197 — rahbar

# Har bir hodisada alohida xabar (real-time)
REALTIME_CHAT_IDS = [1340383182]  # @elya_classic — ELYA CLASSIC
