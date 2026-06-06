"""Faza 2-C: reservation UI helper testlari."""
from datetime import datetime


def _waiting_order(db, wh_id, pid, qty, date, number):
    from app.models.database import Order, OrderItem
    o = Order(number=number, date=date, type="sale", source="agent",
              status="waiting_production", warehouse_id=wh_id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pid, quantity=qty))
    db.flush()
    return o


def test_get_all_reservations_empty(db):
    from app.services.stock_reservation import get_all_reservations
    assert get_all_reservations(db) == {}


def test_get_all_reservations_sums_by_wh_pid(db, sample_warehouse, sample_product):
    from app.services.stock_reservation import get_all_reservations
    _waiting_order(db, sample_warehouse.id, sample_product.id, 25, datetime(2026, 6, 4), "W1")
    _waiting_order(db, sample_warehouse.id, sample_product.id, 5, datetime(2026, 6, 5), "W2")
    db.commit()
    m = get_all_reservations(db)
    assert m.get((sample_warehouse.id, sample_product.id)) == 30.0


def test_get_all_reservations_ignores_non_waiting(db, sample_warehouse, sample_product):
    from app.models.database import Order, OrderItem
    from app.services.stock_reservation import get_all_reservations
    o = Order(number="C1", date=datetime(2026, 6, 4), type="sale", source="agent",
              status="confirmed", warehouse_id=sample_warehouse.id)
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=sample_product.id, quantity=10))
    db.commit()
    assert get_all_reservations(db) == {}
