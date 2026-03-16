#!/usr/bin/env python3
"""
Bazaga cash_registers.payment_type ustunini qo'shish.
Migratsiya bajarilmagan bo'lsa, bu skriptni ishga tushiring: python add_cash_register_payment_type_column.py
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
    cur.execute("PRAGMA table_info(cash_registers)")
    columns = [row[1] for row in cur.fetchall()]
    if "payment_type" in columns:
        print("payment_type ustuni allaqachon mavjud. Hech narsa qilinmadi.")
        conn.close()
        return 0
    cur.execute("ALTER TABLE cash_registers ADD COLUMN payment_type VARCHAR(20) NULL")
    conn.commit()
    conn.close()
    print("OK: cash_registers jadvaliga payment_type ustuni qo'shildi.")
    return 0

if __name__ == "__main__":
    exit(main())
