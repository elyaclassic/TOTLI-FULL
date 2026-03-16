"""users jadvaliga department_id va warehouse_id qo'shish (sotuvchi bo'limi/ombori)."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
if not os.path.exists(DB_PATH):
    DB_PATH = "totli_holva.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cur.fetchall()]
    for col, ref in [("department_id", "departments(id)"), ("warehouse_id", "warehouses(id)")]:
        if col not in columns:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER REFERENCES {ref}")
            conn.commit()
            print(f"users.{col} qo'shildi.")
        else:
            print(f"{col} allaqachon mavjud.")
    conn.close()

if __name__ == "__main__":
    main()
