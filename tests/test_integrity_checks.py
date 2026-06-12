"""integrity_check.py yangi tekshiruvlari testi."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import integrity_check as ic


def _mem_db():
    """Minimal sxemali in-memory sqlite (sotuv tekshiruvlari uchun)."""
    conn = sqlite3.connect(":memory:")
    conn.executescript('''
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY, number TEXT, type TEXT, status TEXT,
            partner_id INTEGER, warehouse_id INTEGER, price_type_id INTEGER,
            source TEXT, subtotal REAL, total REAL, paid REAL, debt REAL,
            discount_percent REAL DEFAULT 0, discount_amount REAL DEFAULT 0
        );
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
            warehouse_id INTEGER, quantity REAL, price REAL, total REAL
        );
    ''')
    return conn


def test_subtotal_desync_detects_mismatch():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,subtotal,total) VALUES (1,'sale','completed',300,300)")
    cur.execute("INSERT INTO order_items (order_id,quantity,price,total) VALUES (1,1,300,300)")
    cur.execute("INSERT INTO order_items (order_id,quantity,price,total) VALUES (1,1,300,300)")
    count, msg = ic.check_subtotal_desync(cur)
    assert count == 1, f"1 desync kutilgan, topildi {count}"
    assert msg and "subtotal" in msg.lower()


def test_subtotal_desync_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,subtotal,total) VALUES (1,'sale','completed',600,600)")
    cur.execute("INSERT INTO order_items (order_id,quantity,price,total) VALUES (1,1,600,600)")
    count, msg = ic.check_subtotal_desync(cur)
    assert count == 0 and msg is None


def test_wrong_warehouse_detects():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (1,'sale','delivered',7)")
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (2,'sale','completed',1)")
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (3,'sale','completed',5)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 2, f"2 noto'g'ri kutilgan, topildi {count}"


def test_wrong_warehouse_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,warehouse_id) VALUES (1,'sale','completed',5)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 0 and msg is None


def test_null_price_type_detects():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (1,'sale','completed',NULL)")
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (2,'sale','delivered',4)")
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (3,'sale','draft',NULL)")
    count, msg = ic.check_null_price_type(cur)
    assert count == 1, f"1 NULL kutilgan, topildi {count}"


def test_agent_debt_desync_detects():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,source,total,paid,debt) VALUES (1,'sale','delivered','agent',1000,0,0)")
    cur.execute("INSERT INTO orders (id,type,status,source,total,paid,debt) VALUES (2,'sale','delivered','agent',800,300,500)")
    count, msg = ic.check_agent_debt_desync(cur)
    assert count == 1, f"1 desync kutilgan, topildi {count}"
    assert msg and "qarz" in msg.lower()


def test_null_price_type_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,price_type_id) VALUES (1,'sale','completed',4)")
    count, msg = ic.check_null_price_type(cur)
    assert count == 0 and msg is None


def test_agent_debt_desync_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,total,paid,debt) VALUES (1,'sale','delivered',800,300,500)")
    count, msg = ic.check_agent_debt_desync(cur)
    assert count == 0 and msg is None
