#!/usr/bin/env python3
"""
Bazaga payments.status ustunini qo'shish (confirmed, cancelled).
Ishga tushiring: python add_payment_status_column.py
"""
import os
import sqlite3

_root = os.path.dirname(os.path.abspath(__file__))
_db_path = os.path.join(_root, "totli_holva.db")

def main():
    if not os.path.isfile(_db_path):
        print(f"Baza fayli topilmadi: {_db_path}")
        return 1
    conn = sqlite3.connect(_db_path)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(payments)")
    columns = [row[1] for row in cur.fetchall()]
    if "status" in columns:
        print("payments.status allaqachon mavjud. Hech narsa qilinmadi.")
        conn.close()
        return 0
    cur.execute("ALTER TABLE payments ADD COLUMN status VARCHAR(20) DEFAULT 'confirmed'")
    conn.commit()
    conn.close()
    print("OK: payments jadvaliga status ustuni qo'shildi.")
    return 0

if __name__ == "__main__":
    exit(main())
