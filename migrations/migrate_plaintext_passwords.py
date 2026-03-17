"""
Migratsiya: plaintext parollarni bcrypt ga o'tkazish.

Ishlatish:
    python migrations/migrate_plaintext_passwords.py

Bu skript:
1. User jadvalidagi barcha plaintext parollarni topadi
2. Ularni vaqtincha kuchli parol bilan bcrypt ga almashtiradi
3. Natijani ekranga chiqaradi (admin parolni foydalanuvchiga etkazishi kerak)
"""
import os
import sys
import secrets
import string

# Loyiha root ni PATH ga qo'shamiz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import SessionLocal
from app.utils.auth import hash_password


def _is_bcrypt(h: str) -> bool:
    return bool(h) and h.startswith("$2")


def _is_sha256(h: str) -> bool:
    return bool(h) and len(h) == 64 and all(c in "0123456789abcdef" for c in h.lower())


def _generate_temp_password(length: int = 12) -> str:
    """Kuchli vaqtincha parol yaratish."""
    chars = string.ascii_letters + string.digits + "!@#$"
    while True:
        pwd = "".join(secrets.choice(chars) for _ in range(length))
        # Kamida bitta katta harf, kichik harf, raqam va belgi
        if (any(c.isupper() for c in pwd) and
                any(c.islower() for c in pwd) and
                any(c.isdigit() for c in pwd)):
            return pwd


def migrate():
    db = SessionLocal()
    try:
        from app.models.database import User
        users = db.query(User).all()

        plaintext_users = [
            u for u in users
            if u.password_hash and not _is_bcrypt(u.password_hash) and not _is_sha256(u.password_hash)
        ]

        if not plaintext_users:
            print("[OK] Plaintext parolli foydalanuvchilar topilmadi. Hamma narsa xavfsiz.")
            return

        print(f"\n[!] {len(plaintext_users)} ta foydalanuvchida plaintext parol topildi:\n")
        print(f"{'ID':<6} {'Username':<20} {'Vaqtincha parol'}")
        print("-" * 50)

        for user in plaintext_users:
            temp_password = _generate_temp_password()
            user.password_hash = hash_password(temp_password)
            print(f"{user.id:<6} {(user.username or ''):<20} {temp_password}")

        db.commit()
        print("\n[OK] Barcha plaintext parollar bcrypt ga o'tkazildi.")
        print("[!]  Yuqoridagi vaqtincha parollarni tegishli foydalanuvchilarga xavfsiz yo'l bilan yuboring.")
        print("     Foydalanuvchilar birinchi kirishda parollarini o'zgartirishlari kerak.\n")

    except Exception as e:
        db.rollback()
        print(f"\n[XATO] {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
