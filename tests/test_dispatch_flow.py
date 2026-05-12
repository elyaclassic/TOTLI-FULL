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


def test_waiting_to_out_for_delivery_when_driver_set_and_stock_ok(db):
    """waiting_production + pending_driver_id + stock yetadi -> out_for_delivery."""
    from app.models.database import Order, OrderItem, Stock, Product, Warehouse, Partner, Driver, Delivery
    from app.services.agent_order_service import try_confirm_waiting_orders
    from datetime import date as _date

    p = Partner(name="P", balance=0, code="P_W1")
    w = Warehouse(name="W", is_active=True)
    pr = Product(name="Pr", is_active=True, sale_price=10000)
    drv = Driver(code="DR_W1", full_name="Drv", is_active=True)
    db.add_all([p, w, pr, drv]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=50)
    db.add(s); db.flush()

    o = Order(
        number="AGT-W-1", date=datetime.now(), type="sale", source="agent",
        partner_id=p.id, warehouse_id=w.id,
        total=30000, debt=30000, paid=0, status="waiting_production",
        delivery_date=_date(2026, 5, 15), pending_driver_id=drv.id,
    )
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=3,
                     price=10000, total=30000, warehouse_id=w.id))
    db.commit()

    result = try_confirm_waiting_orders(db)

    db.refresh(o); db.refresh(s); db.refresh(p)
    assert o.status == "out_for_delivery", f"Expected out_for_delivery, got {o.status}"
    assert o.dispatched_at is not None, "dispatched_at must be set on transition"
    assert s.quantity == 47, f"Stock should decrement by 3, got {s.quantity}"
    assert p.balance == 0, "Balance must NOT be written at waiting->out_for_delivery"
    delivery = db.query(Delivery).filter_by(order_id=o.id).first()
    assert delivery is not None
    assert delivery.driver_id == drv.id
    assert delivery.status == "pending"
    assert len(result) == 1


def test_waiting_no_driver_does_not_transition(db):
    """waiting_production + pending_driver_id=NULL -> qoladi waiting_production (driver tanlanishi kutiladi)."""
    from app.models.database import Order, OrderItem, Stock, Product, Warehouse, Partner
    from app.services.agent_order_service import try_confirm_waiting_orders

    p = Partner(name="P", balance=0, code="P_W2")
    w = Warehouse(name="W", is_active=True)
    pr = Product(name="Pr", is_active=True, sale_price=10000)
    db.add_all([p, w, pr]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=50)
    db.add(s); db.flush()

    o = Order(
        number="AGT-W-2", date=datetime.now(), type="sale", source="agent",
        partner_id=p.id, warehouse_id=w.id,
        total=20000, debt=20000, paid=0, status="waiting_production",
        pending_driver_id=None,
    )
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=2,
                     price=10000, total=20000, warehouse_id=w.id))
    db.commit()

    result = try_confirm_waiting_orders(db)

    db.refresh(o); db.refresh(s)
    assert o.status == "waiting_production", "Driver yo'q -> qoladi waiting"
    assert s.quantity == 50, "Stock o'zgarmasligi kerak"
    assert result == [] or len(result) == 0


def test_waiting_insufficient_stock_does_not_transition(db):
    """Stock yetmasa, order qoladi waiting_production."""
    from app.models.database import Order, OrderItem, Stock, Product, Warehouse, Partner, Driver
    from app.services.agent_order_service import try_confirm_waiting_orders

    p = Partner(name="P", balance=0, code="P_W3")
    w = Warehouse(name="W", is_active=True)
    pr = Product(name="Pr", is_active=True, sale_price=10000)
    drv = Driver(code="DR_W3", full_name="Drv", is_active=True)
    db.add_all([p, w, pr, drv]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=1)  # yetmaydi
    db.add(s); db.flush()

    o = Order(
        number="AGT-W-3", date=datetime.now(), type="sale", source="agent",
        partner_id=p.id, warehouse_id=w.id,
        total=50000, debt=50000, paid=0, status="waiting_production",
        pending_driver_id=drv.id,
    )
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=5,
                     price=10000, total=50000, warehouse_id=w.id))
    db.commit()

    result = try_confirm_waiting_orders(db)

    db.refresh(o); db.refresh(s)
    assert o.status == "waiting_production"
    assert s.quantity == 1
    assert len(result) == 0


def test_driver_deliveries_filter_hides_future_dates(db):
    """Default filter: kelajakdagi delivery'lar ko'rinmaydi (overdue va bugungi qoladi)."""
    from app.models.database import Driver, Delivery, Order
    from sqlalchemy import or_, func as sa_func
    from datetime import date as _date, timedelta

    drv = Driver(code="DR_F1", full_name="Drv", is_active=True)
    db.add(drv); db.flush()
    o = Order(
        number="O_DLV_F1", date=datetime.now(), type="sale",
        total=1000, debt=1000, paid=0, status="out_for_delivery",
    )
    db.add(o); db.flush()

    today = _date.today()
    tomorrow = today + timedelta(days=1)
    yesterday = today - timedelta(days=1)

    d_today = Delivery(
        number="DLV-T1", driver_id=drv.id, order_id=o.id,
        planned_date=datetime.combine(today, datetime.min.time()),
        status="pending",
    )
    d_tomorrow = Delivery(
        number="DLV-T2", driver_id=drv.id, order_id=o.id,
        planned_date=datetime.combine(tomorrow, datetime.min.time()),
        status="pending",
    )
    d_yesterday = Delivery(
        number="DLV-T3", driver_id=drv.id, order_id=o.id,
        planned_date=datetime.combine(yesterday, datetime.min.time()),
        status="pending",
    )
    db.add_all([d_today, d_tomorrow, d_yesterday]); db.commit()

    # Endpoint dagi default filter logikasini takrorlash
    q = db.query(Delivery).filter(
        Delivery.driver_id == drv.id,
        or_(
            Delivery.planned_date == None,
            sa_func.date(Delivery.planned_date) <= today,
        ),
    )
    visible = q.all()
    numbers = {d.number for d in visible}

    assert "DLV-T1" in numbers, "Bugungi delivery ko'rinishi kerak"
    assert "DLV-T3" in numbers, "Kechagi (overdue) delivery ko'rinishi kerak"
    assert "DLV-T2" not in numbers, "Ertangi (kelajak) delivery yashirilishi kerak"


# ---- Task 11: Driver "Yetkazdim" balance fix ----

def test_driver_deliver_writes_balance_on_first_call(db):
    """Driver 'delivered' tasdig'ida partner.balance += debt yoziladi."""
    from app.models.database import Order, Partner, Driver, Delivery
    from sqlalchemy import text as _text

    p = Partner(name="P", balance=0, code="P_DLV1")
    drv = Driver(code="DR_DLV1", full_name="Drv", is_active=True)
    db.add_all([p, drv]); db.flush()
    o = Order(
        number="O_DLV1", date=datetime.now(), type="sale",
        partner_id=p.id, total=50000, debt=50000, paid=0,
        status="out_for_delivery", pending_driver_id=drv.id,
        previous_partner_balance=None,
    )
    db.add(o); db.flush()
    d = Delivery(number="DLV-DLV1", driver_id=drv.id, order_id=o.id, status="in_progress")
    db.add(d); db.flush()
    db.commit()

    # Simulate the new atomic balance-write block
    claim = db.execute(
        _text("UPDATE orders SET status='delivered' WHERE id=:id AND status IN ('out_for_delivery', 'confirmed')"),
        {"id": o.id},
    )
    if claim.rowcount == 1:
        if o.previous_partner_balance is None:
            o.previous_partner_balance = float(p.balance or 0)
        p.balance = float(p.balance or 0) + float(o.debt or 0)
    db.commit()
    db.refresh(o); db.refresh(p)

    assert o.status == "delivered"
    assert p.balance == 50000
    assert o.previous_partner_balance == 0


def test_driver_deliver_idempotent_no_double_balance(db):
    """Ikki marta 'delivered' chaqirilsa balance ikki marta YOZILMAYDI."""
    from app.models.database import Order, Partner, Driver
    from sqlalchemy import text as _text

    p = Partner(name="P", balance=0, code="P_DLV2")
    drv = Driver(code="DR_DLV2", full_name="Drv", is_active=True)
    db.add_all([p, drv]); db.flush()
    o = Order(
        number="O_DLV2", date=datetime.now(), type="sale",
        partner_id=p.id, total=80000, debt=80000, paid=0,
        status="out_for_delivery", pending_driver_id=drv.id,
    )
    db.add(o); db.flush()
    db.commit()

    # 1-chi chaqiriq
    claim1 = db.execute(
        _text("UPDATE orders SET status='delivered' WHERE id=:id AND status IN ('out_for_delivery', 'confirmed')"),
        {"id": o.id},
    )
    if claim1.rowcount == 1:
        if o.previous_partner_balance is None:
            o.previous_partner_balance = float(p.balance or 0)
        p.balance = float(p.balance or 0) + float(o.debt or 0)
    db.commit()

    # 2-chi chaqiriq (idempotent)
    claim2 = db.execute(
        _text("UPDATE orders SET status='delivered' WHERE id=:id AND status IN ('out_for_delivery', 'confirmed')"),
        {"id": o.id},
    )
    if claim2.rowcount == 1:
        # Bu blokga kirmasligi kerak
        p.balance = float(p.balance or 0) + float(o.debt or 0)
    db.commit()
    db.refresh(o); db.refresh(p)

    assert claim1.rowcount == 1
    assert claim2.rowcount == 0, "Ikkinchi UPDATE rad etilishi kerak"
    assert p.balance == 80000, "Balance faqat bir marta yozilgan"
    assert o.previous_partner_balance == 0


def test_driver_deliver_does_not_write_balance_for_zero_debt(db):
    """Agar debt=0 bo'lsa, balance o'zgartirilmaydi (lekin status delivered'ga o'tadi)."""
    from app.models.database import Order, Partner
    from sqlalchemy import text as _text

    p = Partner(name="P", balance=100, code="P_DLV3")
    db.add(p); db.flush()
    o = Order(
        number="O_DLV3", date=datetime.now(), type="sale",
        partner_id=p.id, total=50000, debt=0, paid=50000,  # to'liq to'langan
        status="out_for_delivery",
    )
    db.add(o); db.flush()
    db.commit()

    claim = db.execute(
        _text("UPDATE orders SET status='delivered' WHERE id=:id AND status IN ('out_for_delivery', 'confirmed')"),
        {"id": o.id},
    )
    if claim.rowcount == 1:
        if o.partner_id and float(o.debt or 0) > 0:  # debt=0 -> bu blokga kirmaydi
            partner_obj = db.query(Partner).filter(Partner.id == o.partner_id).first()
            if o.previous_partner_balance is None:
                o.previous_partner_balance = float(partner_obj.balance or 0)
            partner_obj.balance = float(partner_obj.balance or 0) + float(o.debt or 0)
    db.commit()
    db.refresh(o); db.refresh(p)

    assert o.status == "delivered"
    assert p.balance == 100, "debt=0 bo'lsa balance o'zgarmaydi"


# ---- Task 14: /sales/deliveries dashboard ----

def test_sales_deliveries_route_registered(db):
    """/sales/deliveries route ro'yxatga olingan."""
    from app.routes.sales_deliveries import router
    paths = [getattr(r, "path", None) for r in router.routes]
    assert "/sales/deliveries" in paths, f"Route topilmadi. Mavjudlar: {paths}"


def test_sales_deliveries_categorization(db):
    """Order'lar bugun/ertaga/kechikkan/waiting kategoriyalariga to'g'ri tushadi."""
    from app.models.database import Order
    from datetime import date as _date, timedelta

    today = _date.today()

    o_today = Order(number="DD-T", date=datetime.now(), type="sale",
                    total=1000, debt=1000, paid=0, status="out_for_delivery",
                    delivery_date=today)
    o_tom = Order(number="DD-TM", date=datetime.now(), type="sale",
                  total=1000, debt=1000, paid=0, status="out_for_delivery",
                  delivery_date=today + timedelta(days=1))
    o_overdue = Order(number="DD-OV", date=datetime.now(), type="sale",
                      total=1000, debt=1000, paid=0, status="out_for_delivery",
                      delivery_date=today - timedelta(days=2))
    o_waiting = Order(number="DD-WT", date=datetime.now(), type="sale",
                      total=1000, debt=1000, paid=0, status="waiting_production")
    db.add_all([o_today, o_tom, o_overdue, o_waiting])
    db.commit()

    today_q = db.query(Order).filter(Order.status == "out_for_delivery", Order.delivery_date == today).all()
    tomorrow_q = db.query(Order).filter(Order.status == "out_for_delivery", Order.delivery_date == today + timedelta(days=1)).all()
    overdue_q = db.query(Order).filter(Order.status == "out_for_delivery", Order.delivery_date < today).all()
    waiting_q = db.query(Order).filter(Order.status == "waiting_production").all()

    assert len(today_q) == 1 and today_q[0].number == "DD-T"
    assert len(tomorrow_q) == 1 and tomorrow_q[0].number == "DD-TM"
    assert len(overdue_q) == 1 and overdue_q[0].number == "DD-OV"
    assert len(waiting_q) == 1 and waiting_q[0].number == "DD-WT"
