"""orders jadvaliga payment_type ustunini qo'shish (POS to'lov turi: naqd, plastik)."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "totli_holva.db")
if not os.path.exists(DB_PATH):
    DB_PATH = "totli_holva.db"

def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cur.fetchall()]
    if "payment_type" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN payment_type VARCHAR(20)")
        conn.commit()
        print("orders.payment_type qo'shildi.")
    else:
        print("payment_type allaqachon mavjud.")
    conn.close()

if __name__ == "__main__":
    main()
