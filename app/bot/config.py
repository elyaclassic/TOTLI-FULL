"""Bot konfiguratsiyasi"""
import os

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8714179312:AAFnrhexvBlslAWGVQewnigUogEKJPD2Y0I")

# Ruxsat etilgan rollar
ALLOWED_ROLES = ("admin", "manager", "rahbar", "raxbar")

# Bildirish yuboriladi shu chat ID larga
NOTIFY_CHAT_IDS = [1340383182]
