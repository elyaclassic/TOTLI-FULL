"""user_departments, user_warehouses, user_cash_registers jadvalarini yaratish va mavjud ma'lumotlarni ko'chirish."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
if not os.path.exists(DB_PATH):
    DB_PATH = "totli_holva.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Jadval mavjudligini tekshirish
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_departments'")
    if cur.fetchone():
        print("user_departments allaqachon mavjud.")
    else:
        cur.execute("""
            CREATE TABLE user_departments (
                user_id INTEGER NOT NULL REFERENCES users(id),
                department_id INTEGER NOT NULL REFERENCES departments(id),
                PRIMARY KEY (user_id, department_id)
            )
        """)
        print("user_departments yaratildi.")

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_warehouses'")
    if cur.fetchone():
        print("user_warehouses allaqachon mavjud.")
    else:
        cur.execute("""
            CREATE TABLE user_warehouses (
                user_id INTEGER NOT NULL REFERENCES users(id),
                warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                PRIMARY KEY (user_id, warehouse_id)
            )
        """)
        print("user_warehouses yaratildi.")

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_cash_registers'")
    if cur.fetchone():
        print("user_cash_registers allaqachon mavjud.")
    else:
        cur.execute("""
            CREATE TABLE user_cash_registers (
                user_id INTEGER NOT NULL REFERENCES users(id),
                cash_register_id INTEGER NOT NULL REFERENCES cash_registers(id),
                PRIMARY KEY (user_id, cash_register_id)
            )
        """)
        print("user_cash_registers yaratildi.")

    # Mavjud users jadvalidan department_id, warehouse_id, cash_register_id ni ko'chirish
    cur.execute("PRAGMA table_info(users)")
    cols = [r[1] for r in cur.fetchall()]
    if "department_id" in cols:
        cur.execute("""
            INSERT OR IGNORE INTO user_departments (user_id, department_id)
            SELECT id, department_id FROM users WHERE department_id IS NOT NULL AND department_id > 0
        """)
        print("user_departments ga mavjud ma'lumotlar ko'chirildi.")
    if "warehouse_id" in cols:
        cur.execute("""
            INSERT OR IGNORE INTO user_warehouses (user_id, warehouse_id)
            SELECT id, warehouse_id FROM users WHERE warehouse_id IS NOT NULL AND warehouse_id > 0
        """)
        print("user_warehouses ga mavjud ma'lumotlar ko'chirildi.")
    if "cash_register_id" in cols:
        cur.execute("""
            INSERT OR IGNORE INTO user_cash_registers (user_id, cash_register_id)
            SELECT id, cash_register_id FROM users WHERE cash_register_id IS NOT NULL AND cash_register_id > 0
        """)
        print("user_cash_registers ga mavjud ma'lumotlar ko'chirildi.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    main()
