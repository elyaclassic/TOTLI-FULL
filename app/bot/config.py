"""Bot konfiguratsiyasi"""
import os

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8714179312:AAFnrhexvBlslAWGVQewnigUogEKJPD2Y0I")

# Ruxsat etilgan rollar
ALLOWED_ROLES = ("admin", "manager", "rahbar", "raxbar")

# Faqat shu Telegram ID lar botdan foydalana oladi
# Yangi odam qo'shish uchun shu ro'yxatga ID qo'shing
ALLOWED_CHAT_IDS = [1340383182, 1057546370]

# Bildirish yuboriladi shu chat ID larga
NOTIFY_CHAT_IDS = [1340383182, 1057546370]
