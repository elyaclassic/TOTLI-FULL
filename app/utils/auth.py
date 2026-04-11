"""
Autentifikatsiya va xavfsizlik funksiyalari
"""
import os
import secrets
from datetime import datetime
from typing import Optional
from itsdangerous import URLSafeTimedSerializer
import bcrypt
import hashlib

# Session management — SECRET_KEY .env faylidan o'qiladi (majburiy)
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY env o'zgaruvchisi o'rnatilmagan. "
        ".env faylida SECRET_KEY ni o'rnating yoki yangi kalit yarating: "
        "python -c \"import secrets; print(secrets.token_hex(32))\""
    )
if os.getenv("PRODUCTION", "").lower() in ("1", "true", "yes") and "change-in-production" in SECRET_KEY:
    raise RuntimeError(
        "Production rejimida vaqtinchalik SECRET_KEY ishlatilmoqda. "
        ".env faylida yangi tasodifiy kalit o'rnating."
    )
SESSION_SERIALIZER = URLSafeTimedSerializer(SECRET_KEY)
# B4 (Y8): Session muddati — env orqali sozlanadi, default 7 kun.
# Oldin 30 kun edi — mobil token leak xavfi uchun qisqartirildi.
# Web foydalanuvchilar kunlik cookie bilan ishlaydi (routes/auth.py max_age=86400),
# bu o'zgarish asosan mobil ilovaga ta'sir qiladi.
try:
    _session_days = int(os.getenv("SESSION_MAX_AGE_DAYS", "7"))
except ValueError:
    _session_days = 7
SESSION_MAX_AGE = 86400 * max(1, _session_days)

def _legacy_hash(password: str) -> str:
    """Eski SHA256 hash (migratsiya)"""
    return hashlib.sha256(password.encode()).hexdigest()


def hash_password(password: str) -> str:
    """Parolni hash qilish (bcrypt)"""
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def is_legacy_hash(hashed_password: str) -> bool:
    """True agar parol bcrypt da emas (SHA256 yoki oddiy matn) — login da bcrypt ga yangilash kerak."""
    if not hashed_password:
        return False
    if hashed_password.startswith("$2") or hashed_password.startswith("$2a") or hashed_password.startswith("$2b"):
        return False
    return True


def hash_pin(pin: str) -> str:
    """Agent PIN'ini bcrypt bilan hashlash (B3).
    PIN 4-8 raqamli bo'lishi kerak — validatsiya chaqiruvchida.
    """
    pin_bytes = pin.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pin_bytes, salt).decode("utf-8")


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Agent PIN'ini tekshirish."""
    if not hashed_pin or not plain_pin:
        return False
    if not (hashed_pin.startswith("$2") or hashed_pin.startswith("$2a") or hashed_pin.startswith("$2b")):
        return False
    try:
        return bcrypt.checkpw(plain_pin.encode("utf-8")[:72], hashed_pin.encode("utf-8"))
    except Exception:
        return False


def validate_pin_format(pin: str) -> Optional[str]:
    """PIN format tekshiruvi. Xato bo'lsa xabar qaytaradi, OK bo'lsa None."""
    if not pin:
        return "PIN bo'sh bo'lmasligi kerak"
    if not pin.isdigit():
        return "PIN faqat raqamlardan iborat bo'lishi kerak"
    if len(pin) < 4 or len(pin) > 8:
        return "PIN 4 dan 8 ta raqamgacha bo'lishi kerak"
    # Juda oddiy PIN'lar rad etiladi
    if pin in ("0000", "1111", "2222", "3333", "4444", "5555", "6666", "7777", "8888", "9999",
               "1234", "4321", "12345", "54321", "123456", "654321"):
        return "Juda oddiy PIN. Boshqa kombinatsiya tanlang."
    return None


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Parolni tekshirish (bcrypt yoki eski SHA256 — migratsiya uchun).
    Plaintext parollar qabul qilinmaydi: migrations/migrate_plaintext_passwords.py ni ishlatib migrasiya qiling.
    """
    if not hashed_password:
        return False
    if hashed_password.startswith("$2") or hashed_password.startswith("$2a") or hashed_password.startswith("$2b"):
        pwd_bytes = plain_password.encode("utf-8")[:72]
        try:
            return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))
        except Exception:
            return False
    if len(hashed_password) == 64 and all(c in "0123456789abcdef" for c in hashed_password.lower()):
        return _legacy_hash(plain_password) == hashed_password
    # Noma'lum format — ruxsat yo'q
    return False


def create_session_token(user_id: int, user_type: str = "user") -> str:
    """Session token yaratish"""
    data = {
        "user_id": user_id,
        "user_type": user_type,
        "created_at": datetime.now().isoformat()
    }
    return SESSION_SERIALIZER.dumps(data)


def verify_session_token(token: str) -> Optional[dict]:
    """Session token tekshirish"""
    try:
        data = SESSION_SERIALIZER.loads(token, max_age=SESSION_MAX_AGE)
        return data
    except Exception:
        return None


def get_user_from_token(token: str) -> Optional[dict]:
    """Token dan foydalanuvchi ma'lumotlarini olish"""
    return verify_session_token(token)


def generate_csrf_token() -> str:
    """CSRF token yaratish (har sahifa yoki session uchun)"""
    return secrets.token_hex(32)


def verify_csrf_token(received: Optional[str], expected: Optional[str]) -> bool:
    """CSRF token tekshirish (vaqtincha va xavfsiz taqqoslash)"""
    if not expected or not received:
        return False
    return secrets.compare_digest(received.strip(), expected.strip())
