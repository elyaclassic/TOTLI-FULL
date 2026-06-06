"""Stock reservation (waiting_production band) testlari."""
from datetime import datetime


def _waiting_order(db, wh_id, pid, qty, date, number, status="waiting_production"):
    """Helper: bitta itemli waiting buyurtma yaratadi."""
    from app.models.database import Order, OrderItem
    o = Order(number=number, date=date, type="sale", source="agent",
              status=status, warehouse_id=wh_id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty))
    db.flush()
    return o


def test_no_waiting_orders_reserved_zero(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id) == 0.0


def test_reserved_sums_waiting_basket(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    _waiting_order(db, sample_warehouse.id, sample_product.id, 10, datetime(2026, 6, 4), "W1")
    _waiting_order(db, sample_warehouse.id, sample_product.id, 5, datetime(2026, 6, 5), "W2")
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id) == 15.0


def test_reserved_ignores_non_waiting_status(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    _waiting_order(db, sample_warehouse.id, sample_product.id, 7, datetime(2026, 6, 4), "C1", status="confirmed")
    _waiting_order(db, sample_warehouse.id, sample_product.id, 3, datetime(2026, 6, 4), "D1", status="draft")
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id) == 0.0


def test_before_order_excludes_self_and_newer(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_reserved_quantity
    o1 = _waiting_order(db, sample_warehouse.id, sample_product.id, 10, datetime(2026, 6, 4), "W1")
    o2 = _waiting_order(db, sample_warehouse.id, sample_product.id, 5, datetime(2026, 6, 5), "W2")
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id, before_order=o2) == 10.0
    assert get_reserved_quantity(db, sample_warehouse.id, sample_product.id, before_order=o1) == 0.0


def test_available_subtracts_reservation(db, sample_warehouse, sample_product, sample_stock):
    from app.services.stock_reservation import get_available_stock
    _waiting_order(db, sample_warehouse.id, sample_product.id, 30, datetime(2026, 6, 4), "W1")
    assert get_available_stock(db, sample_warehouse.id, sample_product.id) == 70.0


def test_available_before_order_excludes_self(db, sample_warehouse, sample_product, sample_stock):
    from app.services.stock_reservation import get_available_stock
    o1 = _waiting_order(db, sample_warehouse.id, sample_product.id, 30, datetime(2026, 6, 4), "W1")
    assert get_available_stock(db, sample_warehouse.id, sample_product.id, before_order=o1) == 100.0
