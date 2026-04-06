"""Bot konfiguratsiyasi"""
import os

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8714179312:AAFnrhexvBlslAWGVQewnigUogEKJPD2Y0I")

# Ruxsat etilgan rollar
ALLOWED_ROLES = ("admin", "manager", "rahbar", "raxbar")

# Faqat shu Telegram ID lar botdan foydalana oladi
# Yangi odam qo'shish uchun shu ro'yxatga ID qo'shing
ALLOWED_CHAT_IDS = [1340383182, 1057546370]

# Kunlik yakuniy hisobot (kechqurun 21:00)
NOTIFY_CHAT_IDS = [1057546370]  # @RD2197 — rahbar

# Har bir hodisada alohida xabar (real-time)
REALTIME_CHAT_IDS = [1340383182]  # @elya_classic — ELYA CLASSIC
