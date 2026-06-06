"""Faza 2-A: transfer/konversiya band himoyasi testlari."""
from datetime import datetime


def _waiting_order(db, wh_id, pid, qty, date, number):
    from app.models.database import Order, OrderItem
    o = Order(number=number, date=date, type="sale", source="agent",
              status="waiting_production", warehouse_id=wh_id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty))
    db.flush()
    return o


def test_available_at_date_no_cutoff_subtracts_reservation(db, sample_warehouse, sample_product, sample_stock):
    """cutoff=None → joriy stock − band."""
    from app.services.stock_reservation import get_available_stock_at_date
    _waiting_order(db, sample_warehouse.id, sample_product.id, 30, datetime(2026, 6, 4), "W1")
    assert get_available_stock_at_date(db, sample_warehouse.id, sample_product.id) == 70.0


def test_available_at_date_no_reservation_equals_physical(db, sample_warehouse, sample_product, sample_stock):
    """Band yo'q bo'lsa → jismoniy qoldiq (xulq o'zgarmaydi)."""
    from app.services.stock_reservation import get_available_stock_at_date
    assert get_available_stock_at_date(db, sample_warehouse.id, sample_product.id) == 100.0
