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


def test_transfer_blocked_when_all_reserved(db, sample_warehouse, sample_product, sample_stock):
    """Order 569 ssenariysi: butun stock band → transfer uchun mavjud 0 (bloklanadi)."""
    from app.services.stock_reservation import get_available_stock_at_date
    _waiting_order(db, sample_warehouse.id, sample_product.id, 100, datetime(2026, 6, 4), "AGT")
    avail = get_available_stock_at_date(db, sample_warehouse.id, sample_product.id)
    assert avail == 0.0
    assert avail + 1e-6 < 1.0   # 1 dona transfer ham bloklanadi


def test_transfer_allowed_for_unreserved_surplus(db, sample_warehouse, sample_product, sample_stock):
    """Qisman band: 100 stock, 60 band → 40 transfer o'tadi, 41 bloklanadi."""
    from app.services.stock_reservation import get_available_stock_at_date
    _waiting_order(db, sample_warehouse.id, sample_product.id, 60, datetime(2026, 6, 4), "AGT")
    avail = get_available_stock_at_date(db, sample_warehouse.id, sample_product.id)
    assert avail == 40.0
    assert not (avail + 1e-6 < 40.0)   # 40 o'tadi
    assert avail + 1e-6 < 41.0          # 41 bloklanadi
