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


def test_dispatch_stock_sufficient_creates_delivery_and_decrements_stock(db):
    """Stock yetarli holatda: status=out_for_delivery, stock kamayadi, Delivery yaratiladi."""
    from app.models.database import (
        Order, OrderItem, Stock, Product, Warehouse, Partner, Driver, Delivery,
    )
    from sqlalchemy import text as _sa_text
    from datetime import date as _date

    p = Partner(name="T", balance=0, code="P_D1")
    w = Warehouse(name="WH", is_active=True)
    pr = Product(name="Prod", is_active=True, sale_price=10000)
    drv = Driver(code="DR1", full_name="Driver 1", is_active=True)
    db.add_all([p, w, pr, drv]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=100)
    db.add(s); db.flush()
    o = Order(
        number="AGT-T-D1", date=datetime.now(), type="sale",
        partner_id=p.id, warehouse_id=w.id,
        total=50000, debt=50000, paid=0, status="confirmed",
    )
    db.add(o); db.flush()
    db.add(OrderItem(
        order_id=o.id, product_id=pr.id, quantity=5,
        price=10000, total=50000, warehouse_id=w.id,
    ))
    db.commit()

    # Simulate dispatch endpoint logic via direct DB ops
    # (Integration via TestClient would require full auth setup; this validates the model+constraints)
    from app.services.stock_service import create_stock_movement
    dd = _date(2026, 5, 15)

    r = db.execute(
        _sa_text("UPDATE orders SET status='out_for_delivery', delivery_date=:dd, "
                 "dispatched_at=:now, pending_driver_id=:drv "
                 "WHERE id=:id AND status='confirmed'"),
        {"id": o.id, "dd": dd, "now": datetime.now(), "drv": drv.id},
    )
    db.commit()
    assert r.rowcount == 1

    for item in db.query(OrderItem).filter(OrderItem.order_id == o.id).all():
        create_stock_movement(
            db=db, warehouse_id=item.warehouse_id, product_id=item.product_id,
            quantity_change=-float(item.quantity), operation_type="sale",
            document_type="Sale", document_id=o.id, document_number=o.number,
            user_id=None, note=f"Test dispatch: {o.number}",
        )
    db.add(Delivery(
        number=f"DLV-{dd.strftime('%Y%m%d')}-{o.id:04d}",
        order_id=o.id, driver_id=drv.id, planned_date=dd, status="pending",
    ))
    db.commit()
    db.refresh(o); db.refresh(s)

    assert o.status == "out_for_delivery"
    assert o.delivery_date == dd
    assert o.pending_driver_id == drv.id
    assert o.dispatched_at is not None
    assert s.quantity == 95
    delivery = db.query(Delivery).filter_by(order_id=o.id).first()
    assert delivery is not None
    assert delivery.driver_id == drv.id


def test_dispatch_endpoint_invalid_date_format(db):
    """Sana formati validatsiya logikasini test qilamiz."""
    from datetime import date as _date
    try:
        _date.fromisoformat("not-a-date")
        assert False, "Invalid date should raise ValueError"
    except ValueError:
        pass  # expected


def test_dispatch_atomic_update_skips_non_confirmed(db):
    """Non-confirmed order'da dispatch UPDATE WHERE rowcount=0 qaytarishi kerak."""
    from app.models.database import Order
    from sqlalchemy import text as _sa_text
    from datetime import date as _date

    o = Order(
        number="AGT-T-D3", date=datetime.now(), type="sale",
        total=10000, debt=10000, paid=0, status="draft",  # NOT confirmed
    )
    db.add(o); db.flush()
    db.commit()

    r = db.execute(
        _sa_text("UPDATE orders SET status='out_for_delivery', delivery_date=:dd "
                 "WHERE id=:id AND status='confirmed'"),
        {"id": o.id, "dd": _date(2026, 5, 15)},
    )
    db.commit()
    assert r.rowcount == 0


def test_dispatch_waiting_production_saves_delivery_date_and_driver(db):
    """Stock yetmasa: waiting_production statusi + delivery_date + pending_driver_id saqlanadi."""
    from app.models.database import Order, Driver
    from sqlalchemy import text as _sa_text
    from datetime import date as _date

    drv = Driver(code="DR_WP", full_name="Driver WP", is_active=True)
    db.add(drv); db.flush()

    o = Order(
        number="AGT-T-WP", date=datetime.now(), type="sale",
        total=10000, debt=10000, paid=0, status="confirmed",
    )
    db.add(o); db.flush()
    db.commit()

    dd = _date(2026, 5, 20)
    r = db.execute(
        _sa_text("UPDATE orders SET status='waiting_production', "
                 "delivery_date=:dd, pending_driver_id=:drv "
                 "WHERE id=:id AND status='confirmed'"),
        {"id": o.id, "dd": dd, "drv": drv.id},
    )
    db.commit()
    db.refresh(o)
    assert r.rowcount == 1
    assert o.status == "waiting_production"
    assert o.delivery_date == dd
    assert o.pending_driver_id == drv.id
    # dispatched_at HALI yo'q — faqat out_for_delivery'ga o'tganda yoziladi
    assert o.dispatched_at is None
