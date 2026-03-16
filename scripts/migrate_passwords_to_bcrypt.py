"""
SHA256 → bcrypt migratsiya hisoboti.
Parollar login paytida avtomatik bcrypt ga yangilanadi (auth.py, api_routes.py).
Bu skript faqat qancha foydalanuvchi hali legacy hash da ekanini ko'rsatadi.
Ishga tushirish: python -m scripts.migrate_passwords_to_bcrypt (loyiha ildizidan)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models.database import SessionLocal, User
from app.utils.auth import is_legacy_hash

def main():
    db = SessionLocal()
    try:
        users = db.query(User).all()
        legacy = [u for u in users if u.password_hash and is_legacy_hash(u.password_hash)]
        bcrypt_count = len(users) - len(legacy)
        print(f"Jami foydalanuvchilar: {len(users)}")
        print(f"Bcrypt da: {bcrypt_count}")
        print(f"Legacy (SHA256/oddiy) — keyingi login da yangilanadi: {len(legacy)}")
        if legacy:
            for u in legacy:
                print(f"  - {u.username} (id={u.id})")
    finally:
        db.close()

if __name__ == "__main__":
    main()
