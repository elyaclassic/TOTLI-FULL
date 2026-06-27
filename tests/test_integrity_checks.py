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
            discount_percent REAL DEFAULT 0, discount_amount REAL DEFAULT 0,
            payment_type TEXT, parent_order_id INTEGER
        );
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER,
            warehouse_id INTEGER, quantity REAL, price REAL, total REAL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY, name TEXT, type TEXT
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
    cur.execute("INSERT INTO products (id,name,type) VALUES (1,'Tayyor halva','tayyor')")
    cur.execute("INSERT INTO products (id,name,type) VALUES (2,'Saryog','hom_ashyo')")
    # order1: Vozvrat(7) dan tayyor mahsulot -> shubhali
    cur.execute("INSERT INTO orders (id,type,status) VALUES (1,'sale','delivered')")
    cur.execute("INSERT INTO order_items (order_id,product_id,warehouse_id) VALUES (1,1,7)")
    # order2: Xom ashyo(1) dan TAYYOR mahsulot -> shubhali
    cur.execute("INSERT INTO orders (id,type,status) VALUES (2,'sale','completed')")
    cur.execute("INSERT INTO order_items (order_id,product_id,warehouse_id) VALUES (2,1,1)")
    # order3: tayyor mahsulot ombori(5) -> toza
    cur.execute("INSERT INTO orders (id,type,status) VALUES (3,'sale','completed')")
    cur.execute("INSERT INTO order_items (order_id,product_id,warehouse_id) VALUES (3,1,5)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 2, f"2 noto'g'ri kutilgan, topildi {count}"


def test_wrong_warehouse_raw_material_excluded():
    """Xom ashyo (hom_ashyo) mahsulot Xom ashyo ombordan (wh1) sotilsa -> LEGITIM."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (id,name,type) VALUES (2,'Saryog','hom_ashyo')")
    cur.execute("INSERT INTO orders (id,type,status) VALUES (1,'sale','delivered')")
    cur.execute("INSERT INTO order_items (order_id,product_id,warehouse_id) VALUES (1,2,1)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 0, f"xom ashyo wh1 sotuvi legitim (false positive emas), topildi {count}"


def test_wrong_warehouse_raw_from_vozvrat_still_flagged():
    """Xom ashyo bo'lsa ham Vozvrat(7) dan sotuv shubhali bo'lib qoladi."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (id,name,type) VALUES (2,'Saryog','hom_ashyo')")
    cur.execute("INSERT INTO orders (id,type,status) VALUES (1,'sale','delivered')")
    cur.execute("INSERT INTO order_items (order_id,product_id,warehouse_id) VALUES (1,2,7)")
    count, msg = ic.check_sale_from_wrong_warehouse(cur)
    assert count == 1, f"Vozvrat(7) sotuvi xom ashyo bo'lsa ham shubhali, topildi {count}"


def test_wrong_warehouse_clean():
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO products (id,name,type) VALUES (1,'Tayyor','tayyor')")
    cur.execute("INSERT INTO orders (id,type,status) VALUES (1,'sale','completed')")
    cur.execute("INSERT INTO order_items (order_id,product_id,warehouse_id) VALUES (1,1,5)")
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


def test_partner_balance_drift_detects(db, sample_partner):
    sample_partner.balance = 999999
    db.add(sample_partner); db.commit()
    count, msg = ic.check_partner_balance_drift_orm(db)
    assert count >= 1, f"drift kutilgan, topildi {count}"
    assert msg and "balans" in msg.lower()


def test_partner_balance_drift_clean(db, sample_partner):
    from app.services.partner_balance_service import compute_partner_balance
    sample_partner.balance = compute_partner_balance(db, sample_partner.id)
    db.add(sample_partner); db.commit()
    count, msg = ic.check_partner_balance_drift_orm(db)
    assert count == 0


# --- False-positive exclude testlari (2026-06-12) ---

def test_null_price_type_employee_advance_excluded():
    """Xodim mahsulot xaridi (employee_advance) narx turisiz ishlaydi — NULL normal."""
    conn = _mem_db()
    cur = conn.cursor()
    # employee_advance + price_type NULL -> false positive, chiqarilishi kerak
    cur.execute("INSERT INTO orders (id,type,status,price_type_id,payment_type) VALUES (1,'sale','completed',NULL,'employee_advance')")
    # oddiy sotuv + NULL -> haqiqiy
    cur.execute("INSERT INTO orders (id,type,status,price_type_id,payment_type) VALUES (2,'sale','completed',NULL,'naqd')")
    count, msg = ic.check_null_price_type(cur)
    assert count == 1, f"faqat oddiy sotuv (1) kutilgan, topildi {count}"


def test_agent_debt_employee_advance_excluded():
    """Xodim xaridi debt=0 TO'G'RI (qarz EmployeeAdvance'da) — chiqariladi."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,total,paid,debt,payment_type) VALUES (1,'sale','completed',1000,0,0,'employee_advance')")
    count, msg = ic.check_agent_debt_desync(cur)
    assert count == 0, f"xodim xaridi chiqarilishi kerak, topildi {count}"


def test_agent_debt_agent_confirmed_excluded():
    """Agent confirmed/out_for_delivery debt=0 TO'G'RI (qarz yetkazishda) — chiqariladi."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,type,status,source,total,paid,debt) VALUES (1,'sale','confirmed','agent',1000,0,0)")
    cur.execute("INSERT INTO orders (id,type,status,source,total,paid,debt) VALUES (2,'sale','out_for_delivery','agent',500,0,0)")
    count, msg = ic.check_agent_debt_desync(cur)
    assert count == 0, f"agent confirmed/out_for_delivery chiqarilishi kerak, topildi {count}"


# --- Обмен phantom debt (2026-06-26, #402 holati) ---

def test_obmen_phantom_debt_detects():
    """Child sotuv delivered + parent qaytarish muallaq (confirmed) = phantom debt."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,number,type,status) VALUES (1,'AGT-020','return_sale','confirmed')")
    cur.execute("INSERT INTO orders (id,number,type,status,parent_order_id) VALUES (2,'AGT-021','sale','delivered',1)")
    count, msg = ic.check_obmen_phantom_debt(cur)
    assert count == 1, f"1 phantom debt kutilgan, topildi {count}"
    assert msg and "phantom" in msg.lower()


def test_obmen_phantom_debt_clean_both_delivered():
    """Parent qaytarish ham delivered — to'g'ri yakunlangan Обмен, drift yo'q."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,number,type,status) VALUES (1,'AGT-020','return_sale','delivered')")
    cur.execute("INSERT INTO orders (id,number,type,status,parent_order_id) VALUES (2,'AGT-021','sale','delivered',1)")
    count, msg = ic.check_obmen_phantom_debt(cur)
    assert count == 0 and msg is None


def test_obmen_phantom_debt_cancelled_child_excluded():
    """Child sotuv CANCELLED — zararsiz (balansga ta'sir 0), chiqariladi (#388/#148 holati)."""
    conn = _mem_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO orders (id,number,type,status) VALUES (1,'AGT-001','return_sale','confirmed')")
    cur.execute("INSERT INTO orders (id,number,type,status,parent_order_id) VALUES (2,'AGT-002','sale','cancelled',1)")
    count, msg = ic.check_obmen_phantom_debt(cur)
    assert count == 0, f"cancelled child chiqarilishi kerak, topildi {count}"
