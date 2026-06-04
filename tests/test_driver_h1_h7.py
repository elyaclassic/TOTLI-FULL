"""H1 + H7 audit fix testlari (haydovchi yetkazish endpoint).

H1: item-update blokida xato bo'lsa, buyurtma JIM 'delivered' bo'lib commit
    bo'lmasligi kerak — atomik rollback + xato qaytishi shart.
H7: is_full_list=False bo'lsa, yuborilmagan (absent) itemlar nollanmasligi kerak
    (qisman ro'yxat hammani o'chirib yubormasin). is_full_list=True/default da
    eski absence-based o'chirish (ilova removeAt orqali) saqlanadi.

Endpoint async — asyncio.run bilan to'g'ridan-to'g'ri chaqiriladi (TestClient
auth setup'isiz). Driver token create_session_token bilan yasaladi.
"""
import asyncio
import json
from datetime import datetime

from app.routes.api_driver_ops import driver_delivery_status
from app.utils.auth import create_session_token


def _mk_driver(db):
    from app.models.database import Driver
    drv = Driver(code="DR_H", full_name="Drv H", is_active=True, employee_id=9001)
    db.add(drv)
    db.flush()
    token = create_session_token(drv.employee_id, "driver")
    return drv, token


def _mk_delivered_order(db, drv, items_spec):
    """out_for_delivery order + Delivery(in_progress) + stock dispatched.

    items_spec: [(name, qty, price, stock_qty), ...]
    """
    from app.models.database import (
        Order, OrderItem, Stock, Product, Warehouse, Partner, Delivery,
    )
    p = Partner(name="P_H", balance=0, code="P_H1")
    w = Warehouse(name="WH_H", is_active=True)
    db.add_all([p, w])
    db.flush()

    total = 0
    products = []
    for name, qty, price, stock_qty in items_spec:
        pr = Product(name=name, is_active=True, sale_price=price)
        db.add(pr)
        db.flush()
        db.add(Stock(warehouse_id=w.id, product_id=pr.id, quantity=stock_qty))
        products.append((pr, qty, price))
        total += qty * price
    db.flush()

    o = Order(
        number="O_H_DLV", date=datetime.now(), type="sale",
        partner_id=p.id, warehouse_id=w.id,
        total=total, debt=total, paid=0, status="out_for_delivery",
        pending_driver_id=drv.id,
    )
    db.add(o)
    db.flush()
    for pr, qty, price in products:
        db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=qty,
                         price=price, total=qty * price, warehouse_id=w.id))
    d = Delivery(number="DLV-H1", driver_id=drv.id, order_id=o.id, status="in_progress")
    db.add(d)
    db.commit()
    return o, d, p, [pr for pr, _, _ in products]


# ---------- H1 ----------

def test_h1_item_update_error_does_not_silently_deliver(db):
    """Item-update blokida xato (float parse) bo'lsa: order 'delivered' BO'LMAYDI,
    rollback bo'ladi, success=False qaytadi."""
    drv, token = _mk_driver(db)
    o, d, p, prods = _mk_delivered_order(db, drv, [("ProdA", 5, 10000, 100)])

    # quantity = noto'g'ri qiymat -> float() ValueError -> inner try
    bad_items = json.dumps([{"product_id": prods[0].id, "quantity": "not-a-number"}])

    res = asyncio.run(driver_delivery_status(
        delivery_id=d.id, status="delivered",
        latitude=None, longitude=None, notes="",
        items=bad_items, naqd=0, plastik=0,
        token=token, db=db,
    ))

    db.refresh(o)
    db.refresh(d)
    assert res.get("success") is False, f"Xato bo'lsa success=False kutilgan, keldi: {res}"
    assert o.status == "out_for_delivery", \
        f"Item-update xatosida order 'delivered' bo'lmasligi kerak, hozir: {o.status}"
    assert d.status != "delivered", "Delivery 'delivered' bo'lmasligi kerak"


def test_h1_valid_item_update_still_delivers(db):
    """Nazorat: to'g'ri item-update bo'lsa yetkazish normal yakunlanadi."""
    drv, token = _mk_driver(db)
    o, d, p, prods = _mk_delivered_order(db, drv, [("ProdA", 5, 10000, 100)])

    good_items = json.dumps([
        {"product_id": prods[0].id, "quantity": 5, "price": 10000, "total": 50000}
    ])

    res = asyncio.run(driver_delivery_status(
        delivery_id=d.id, status="delivered",
        latitude=None, longitude=None, notes="",
        items=good_items, naqd=0, plastik=0,
        token=token, db=db,
    ))

    db.refresh(o)
    assert res.get("success") is True, f"To'g'ri update yetkazilishi kerak: {res}"
    assert o.status == "delivered"


# ---------- H7 ----------

def test_h7_partial_list_does_not_zero_absent_items(db):
    """is_full_list=False: yuborilmagan item NOLLANMAYDI (qisman ro'yxat himoyasi)."""
    from app.models.database import OrderItem
    drv, token = _mk_driver(db)
    o, d, p, prods = _mk_delivered_order(
        db, drv, [("ProdA", 5, 10000, 100), ("ProdB", 3, 20000, 100)])
    prodA, prodB = prods

    # Faqat ProdA yuboriladi (ProdB "absent"), lekin is_full_list=False
    partial = json.dumps([
        {"product_id": prodA.id, "quantity": 5, "price": 10000, "total": 50000}
    ])

    res = asyncio.run(driver_delivery_status(
        delivery_id=d.id, status="delivered",
        latitude=None, longitude=None, notes="",
        items=partial, naqd=0, plastik=0,
        token=token, db=db, is_full_list=False,
    ))

    assert res.get("success") is True, f"{res}"
    itemB = db.query(OrderItem).filter(
        OrderItem.order_id == o.id, OrderItem.product_id == prodB.id).first()
    assert itemB is not None and float(itemB.quantity) == 3, \
        f"is_full_list=False da absent item nollanmasligi kerak, qty={itemB.quantity if itemB else None}"


def test_h7_full_list_still_zeroes_deleted_items(db):
    """is_full_list=True (default): ilova removeAt qilgan (absent) item nollanadi —
    eski/joriy xatti-harakat saqlanadi."""
    from app.models.database import OrderItem
    drv, token = _mk_driver(db)
    o, d, p, prods = _mk_delivered_order(
        db, drv, [("ProdA", 5, 10000, 100), ("ProdB", 3, 20000, 100)])
    prodA, prodB = prods

    # Driver ProdB ni o'chirgan -> ro'yxatda faqat ProdA, is_full_list=True
    full = json.dumps([
        {"product_id": prodA.id, "quantity": 5, "price": 10000, "total": 50000}
    ])

    res = asyncio.run(driver_delivery_status(
        delivery_id=d.id, status="delivered",
        latitude=None, longitude=None, notes="",
        items=full, naqd=0, plastik=0,
        token=token, db=db, is_full_list=True,
    ))

    assert res.get("success") is True, f"{res}"
    itemB = db.query(OrderItem).filter(
        OrderItem.order_id == o.id, OrderItem.product_id == prodB.id).first()
    assert itemB is not None and float(itemB.quantity) == 0, \
        f"is_full_list=True da o'chirilgan item nollanishi kerak, qty={itemB.quantity if itemB else None}"
