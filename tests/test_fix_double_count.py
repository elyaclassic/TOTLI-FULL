"""scripts/fix_double_count_20260516.py uchun real-DB testlar (mock yo'q).

conftest `db` fixture (in-memory SQLite) ishlatiladi.
"""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest

from app.models.database import Order, OrderItem, Stock, Product, StockMovement
from app.services.stock_service import create_stock_movement

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fix_double_count_20260516.py"


@pytest.fixture
def bf():
    spec = importlib.util.spec_from_file_location("fix_double_count_20260516", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_product(db, name="MAYDA PISTA 400gr"):
    p = Product(name=name, code=f"T-{name[:6]}", is_active=True)
    db.add(p)
    db.flush()
    return p


def _mk_order(db, number, prod, qty, wh=3):
    o = Order(number=number, type="sale", status="delivered", warehouse_id=wh)
    db.add(o)
    db.flush()
    db.add(OrderItem(order_id=o.id, product_id=prod.id, warehouse_id=wh,
                      quantity=qty, price=1000, total=qty * 1000))
    db.flush()
    return o


def _dblfix_count(db, order_id):
    return db.query(StockMovement).filter(
        StockMovement.document_type == "Sale",
        StockMovement.document_id == order_id,
        StockMovement.operation_type == "sale_revert",
        StockMovement.note.like("%DBLFIX-20260516%"),
    ).count()


def _sale_net(db, order_id, pid, wh):
    rows = db.query(StockMovement.quantity_change).filter(
        StockMovement.document_type == "Sale",
        StockMovement.document_id == order_id,
        StockMovement.product_id == pid,
        StockMovement.warehouse_id == wh,
    ).all()
    return sum(float(r[0] or 0) for r in rows)


def _stock_qty(db, wh, pid):
    s = db.query(Stock).filter(Stock.warehouse_id == wh,
                               Stock.product_id == pid).first()
    return float(s.quantity) if s else None


def test_clean_double_corrected_and_idempotent(db, bf):
    wh = 3
    prod = _mk_product(db)
    db.add(Stock(warehouse_id=wh, product_id=prod.id, quantity=100.0))
    db.flush()
    order = _mk_order(db, "AGT-20260502-012", prod, 20, wh)

    # DUBLIKAT chegirim: ikkita -20 sale movement (double-confirm izi)
    for _ in range(2):
        create_stock_movement(
            db, warehouse_id=wh, product_id=prod.id, quantity_change=-20,
            operation_type="sale", document_type="Sale",
            document_id=order.id, document_number=order.number,
            created_at=datetime.now(),
        )
    db.flush()
    assert _stock_qty(db, wh, prod.id) == 60.0  # 100 - 40
    assert _sale_net(db, order.id, prod.id, wh) == -40.0  # 2 * expected(-20)

    rep = bf.run(db, apply=True)

    statuses = {r["status"] for r in rep if r["product_id"] == prod.id}
    assert "FIXED" in statuses

    fixmv = db.query(StockMovement).filter(
        StockMovement.document_id == order.id,
        StockMovement.operation_type == "sale_revert",
        StockMovement.note.like("%DBLFIX-20260516%"),
    ).all()
    assert len(fixmv) == 1
    assert fixmv[0].quantity_change == 20.0  # +ortiqcha

    assert _stock_qty(db, wh, prod.id) == 80.0  # 60 + 20 = bitta -20 dan keyingi
    assert _sale_net(db, order.id, prod.id, wh) == -20.0  # == expected

    # Idempotency: qayta ishga tushir → yangi DBLFIX yo'q
    bf.run(db, apply=True)
    assert _dblfix_count(db, order.id) == 1
    assert _stock_qty(db, wh, prod.id) == 80.0


def test_non_double_skipped(db, bf):
    wh = 3
    prod = _mk_product(db, name="BARGELIK 400gr")
    db.add(Stock(warehouse_id=wh, product_id=prod.id, quantity=100.0))
    db.flush()
    order = _mk_order(db, "AGT-20260508-006", prod, 20, wh)

    # Faqat BITTA to'g'ri sale -20 (doubled emas)
    create_stock_movement(
        db, warehouse_id=wh, product_id=prod.id, quantity_change=-20,
        operation_type="sale", document_type="Sale",
        document_id=order.id, document_number=order.number,
        created_at=datetime.now(),
    )
    db.flush()
    assert _stock_qty(db, wh, prod.id) == 80.0

    rep = bf.run(db, apply=True)

    rows = [r for r in rep if r["product_id"] == prod.id]
    assert rows and all(r["status"].startswith("SKIP") for r in rows)
    assert _dblfix_count(db, order.id) == 0
    assert _stock_qty(db, wh, prod.id) == 80.0  # o'zgarmadi
    assert _sale_net(db, order.id, prod.id, wh) == -20.0


def test_dry_run_writes_nothing(db, bf):
    wh = 3
    prod = _mk_product(db, name="KESHULIK 400gr")
    db.add(Stock(warehouse_id=wh, product_id=prod.id, quantity=100.0))
    db.flush()
    order = _mk_order(db, "AGT-20260502-012", prod, 20, wh)

    for _ in range(2):
        create_stock_movement(
            db, warehouse_id=wh, product_id=prod.id, quantity_change=-20,
            operation_type="sale", document_type="Sale",
            document_id=order.id, document_number=order.number,
            created_at=datetime.now(),
        )
    db.flush()
    assert _stock_qty(db, wh, prod.id) == 60.0

    rep = bf.run(db, apply=False)

    rows = [r for r in rep if r["product_id"] == prod.id]
    assert rows and all(r["status"] == "WILL_FIX" for r in rows)
    assert _dblfix_count(db, order.id) == 0
    assert _stock_qty(db, wh, prod.id) == 60.0  # yozilmadi
