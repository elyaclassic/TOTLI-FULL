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
    # Parol: .env dan ADMIN_DEFAULT_PASSWORD yoki dev uchun default
    admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD", "admin123")
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
    print("Password: ( .env ADMIN_DEFAULT_PASSWORD yoki default )")

db.close()
