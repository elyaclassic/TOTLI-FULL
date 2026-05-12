"""Yetkazish kuni flow testlari."""
from datetime import datetime, date
import pytest
from sqlalchemy import text


def test_orders_has_delivery_columns(db):
    """orders jadvalida delivery_date va dispatched_at ustunlar bo'lishi kerak."""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(orders)")).fetchall()]
    assert "delivery_date" in cols
    assert "dispatched_at" in cols


def test_order_status_constants():
    """Order modelida 6 ta yangi status nomli (+ legacy completed) konstanta bo'lishi kerak."""
    from app.models.database import Order
    assert Order.STATUS_DRAFT == "draft"
    assert Order.STATUS_CONFIRMED == "confirmed"
    assert Order.STATUS_OUT_FOR_DELIVERY == "out_for_delivery"
    assert Order.STATUS_DELIVERED == "delivered"
    assert Order.STATUS_CANCELLED == "cancelled"
    assert "out_for_delivery" in Order.VALID_STATUSES
    assert "delivered" in Order.VALID_STATUSES


from sqlalchemy import text as _sa_text


def test_confirm_only_changes_status_no_stock_no_balance(db):
    """confirm draft -> confirmed bo'lib, stock va balance o'zgarmaydi."""
    from app.models.database import Order, Partner, Stock, Product, Warehouse

    p = Partner(name="Test", balance=0, code="P_C1")
    w = Warehouse(name="WH", is_active=True)
    pr = Product(name="Prod", is_active=True, sale_price=10000)
    db.add_all([p, w, pr]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=100)
    db.add(s); db.flush()

    o = Order(
        number="AGT-T-C1", date=datetime.now(), type="sale",
        partner_id=p.id, warehouse_id=w.id,
        total=10000, debt=10000, paid=0, status="draft",
    )
    db.add(o); db.flush()

    # Atomik claim simulation (confirm endpoint logikasi)
    r = db.execute(
        _sa_text("UPDATE orders SET status='confirmed' "
                 "WHERE id=:id AND type='sale' AND status='draft'"),
        {"id": o.id},
    )
    db.commit()
    db.refresh(o); db.refresh(s); db.refresh(p)

    assert r.rowcount == 1
    assert o.status == "confirmed"
    assert s.quantity == 100, "Stock confirm paytida o'zgarmasligi kerak"
    assert p.balance == 0, "Balance confirm paytida o'zgarmasligi kerak"
    assert o.previous_partner_balance is None
