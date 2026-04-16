"""Bot konfiguratsiyasi — env reload 2026-04-16 (BOT_ADMIN_PIN)"""
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

# ===== Bot ichidan operatsiya (kirim / harajat / o'tkazma) =====
# Faqat shu Telegram ID'lar ma'lumot kirityish huquqiga ega
OPS_CHAT_IDS = [1340383182, 1057546370]  # @elya_classic + @RD2197 (rahbar)

# PIN kod (.env da BOT_ADMIN_PIN o'rnating, default 1234)
BOT_ADMIN_PIN = os.environ.get("BOT_ADMIN_PIN", "1234")

# PIN muvaffaqiyatli kiritilgandan keyin qancha soat faol (shundan keyin qayta PIN)
BOT_PIN_SESSION_HOURS = int(os.environ.get("BOT_PIN_SESSION_HOURS", "12"))
