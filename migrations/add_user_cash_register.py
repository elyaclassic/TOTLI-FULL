"""users jadvaliga cash_register_id qo'shish."""
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
    if "cash_register_id" not in columns:
        cur.execute("ALTER TABLE users ADD COLUMN cash_register_id INTEGER REFERENCES cash_registers(id)")
        conn.commit()
        print("users.cash_register_id qo'shildi.")
    else:
        print("cash_register_id allaqachon mavjud.")
    conn.close()

if __name__ == "__main__":
    main()
