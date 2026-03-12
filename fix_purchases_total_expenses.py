"""
Fix purchases table: add total_expenses column if missing
"""
import sqlite3
import os
from pathlib import Path

# Database faylini topish (totli_holva.db loyiha ildizida)
db_path = Path("totli_holva.db")
if not db_path.exists():
    print(f"Database fayl topilmadi: {db_path.absolute()}")
    exit(1)

print(f"Database: {db_path.absolute()}")

conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Ustun bor-yo'qligini tekshirish
cursor.execute("PRAGMA table_info(purchases)")
columns = [row[1] for row in cursor.fetchall()]

if "total_expenses" not in columns:
    print("total_expenses ustuni yo'q. Qo'shilmoqda...")
    try:
        cursor.execute("ALTER TABLE purchases ADD COLUMN total_expenses REAL DEFAULT 0")
        cursor.execute("UPDATE purchases SET total_expenses = 0 WHERE total_expenses IS NULL")
        conn.commit()
        print("[OK] total_expenses ustuni qo'shildi!")
    except Exception as e:
        print(f"Xatolik: {e}")
        conn.rollback()
else:
    print("[OK] total_expenses ustuni allaqachon mavjud.")

# purchase_expenses jadvalini tekshirish
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='purchase_expenses'")
if not cursor.fetchone():
    print("purchase_expenses jadvali yo'q. Yaratilmoqda...")
    try:
        cursor.execute("""
            CREATE TABLE purchase_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                purchase_id INTEGER,
                name VARCHAR(200),
                amount REAL,
                created_at DATETIME,
                FOREIGN KEY (purchase_id) REFERENCES purchases(id)
            )
        """)
        conn.commit()
        print("[OK] purchase_expenses jadvali yaratildi!")
    except Exception as e:
        print(f"Xatolik: {e}")
        conn.rollback()
else:
    print("[OK] purchase_expenses jadvali allaqachon mavjud.")

conn.close()
print("\nTayyor!")
