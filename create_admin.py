"""
Admin foydalanuvchini yaratish.
Parol: .env da ADMIN_DEFAULT_PASSWORD yoki default (faqat dev).
"""
import os
from app.models.database import get_db, User, init_db
from app.utils.auth import hash_password

# Database yaratish
init_db()

# Database session
db = next(get_db())

# Admin foydalanuvchini tekshirish
admin = db.query(User).filter(User.username == "admin").first()

if admin:
    print("[!] Admin foydalanuvchisi allaqachon mavjud!")
    print(f"Username: {admin.username}")
    print(f"Is Active: {admin.is_active}")
else:
    admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD")
    if not admin_password:
        print("[XATO] ADMIN_DEFAULT_PASSWORD environment o'zgaruvchisi o'rnatilmagan!")
        print("  .env fayliga qo'shing: ADMIN_DEFAULT_PASSWORD=kuchli_parol")
        db.close()
        raise SystemExit(1)
    admin = User(
        username="admin",
        password_hash=hash_password(admin_password),
        full_name="Administrator",
        role="admin",
        is_active=True
    )
    db.add(admin)
    db.commit()
    print("[OK] Admin foydalanuvchisi yaratildi!")
    print("Username: admin")
    print("Password: (ADMIN_DEFAULT_PASSWORD dan olindi)")

db.close()
