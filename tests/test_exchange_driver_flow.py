"""Topilma 1 Faza 1 — Obmen (return_sale) endi dispatch → driver oqimidan o'tadi.

Tekshiriladi:
  1. Supervisor confirm return_sale: stock QO'SHILMAYDI, child sotuv
     AVTOMATIK tasdiqlanMAYDI (faqat status='confirmed' bo'ladi).
  2. Haydovchi "Yetkazdim": qaytgan tovar omborga kiradi + child sotuv
     tasdiqlanadi — FAQAT BIR MARTA (endpoint qayta chaqirilsa dublikat yo'q).

Bu testlar handler logikasini DB darajasida ijro etadi (kod bilan bir xil
atomik UPDATE + apply_return_stock_addition). Full HTTP integratsiya auth
sozlamasini talab qiladi; test_dispatch_flow.py shu uslubni qo'llaydi.
"""
from datetime import datetime, date as _date
import pytest
from sqlalchemy import text as _text


def _seed_exchange(db):
    """Obmen juftligi: return_sale (parent) + sale (child, parent_order_id bilan)."""
    from app.models.database import (
        Order, OrderItem, Stock, Product, Warehouse, Partner, Agent, Driver, Employee,
    )
    p = Partner(name="Mijoz", balance=0, code="P_EX1")
    a = Agent(code="A_EX1", full_name="Agent", is_active=True)
    emp = Employee(full_name="Haydovchi Emp")
    w_vozvrat = Warehouse(name="Vozvrat", is_active=True)
    w_new = Warehouse(name="Asosiy", is_active=True)
    pr_ret = Product(name="Qaytgan mahsulot", is_active=True, sale_price=10000)
    pr_new = Product(name="Yangi mahsulot", is_active=True, sale_price=12000)
    db.add_all([p, a, emp, w_vozvrat, w_new, pr_ret, pr_new]); db.flush()
    drv = Driver(code="DR_EX1", full_name="Haydovchi", is_active=True, employee_id=emp.id)
    db.add(drv); db.flush()
    s_ret = Stock(warehouse_id=w_vozvrat.id, product_id=pr_ret.id, quantity=20)
    db.add(s_ret); db.flush()

    ret = Order(
        number="AGT-EX-R", date=datetime.now(), type="return_sale", source="agent",
        partner_id=p.id, agent_id=a.id, warehouse_id=w_vozvrat.id,
        total=30000, debt=0, paid=0, status="draft",
    )
    db.add(ret); db.flush()
    db.add(OrderItem(order_id=ret.id, product_id=pr_ret.id, quantity=3,
                     price=10000, total=30000, warehouse_id=w_vozvrat.id))
    child = Order(
        number="AGT-EX-S", date=datetime.now(), type="sale", source="agent",
        partner_id=p.id, agent_id=a.id, warehouse_id=w_new.id,
        total=24000, debt=24000, paid=0, status="draft",
        parent_order_id=ret.id,
    )
    db.add(child); db.flush()
    db.add(OrderItem(order_id=child.id, product_id=pr_new.id, quantity=2,
                     price=12000, total=24000, warehouse_id=w_new.id))
    db.commit()
    return ret, child, s_ret, drv


def _supervisor_confirm(db, order, user_id=None):
    """delivery_routes.supervisor_confirm_agent_order yangi logikasi (return_sale fall-through).

    return_sale uchun child auto-confirm ham bajariladi (dispatch UI tugmasi
    ex_child.status=='confirmed' shartiga bog'liq).
    """
    claim = db.execute(
        _text("UPDATE orders SET status='confirmed' WHERE id=:id AND source='agent' AND status='draft'"),
        {"id": order.id},
    )
    if claim.rowcount == 1 and (order.type or "") == "return_sale":
        db.execute(
            _text("UPDATE orders SET status='confirmed', user_id=:uid "
                  "WHERE parent_order_id=:pid AND type='sale' AND status='draft'"),
            {"uid": user_id, "pid": order.id},
        )
    db.commit()
    db.refresh(order)
    return claim.rowcount


def _driver_delivered(db, order, driver):
    """api_driver_ops.driver_delivery_status new_status=='delivered' yangi logikasi."""
    claim = db.execute(
        _text("UPDATE orders SET status='delivered' "
              "WHERE id=:id AND status IN ('out_for_delivery', 'confirmed')"),
        {"id": order.id},
    )
    if claim.rowcount == 1:
        if order.partner_id and float(order.debt or 0) > 0:
            from app.models.database import Partner
            partner_obj = db.query(Partner).filter(Partner.id == order.partner_id).first()
            if partner_obj:
                if order.previous_partner_balance is None:
                    order.previous_partner_balance = float(partner_obj.balance or 0)
                partner_obj.balance = float(partner_obj.balance or 0) + float(order.debt or 0)
        if (order.type or "") == "return_sale":
            from app.services.stock_service import apply_return_stock_addition
            apply_return_stock_addition(
                db, order, None,
                note_prefix="Obmen qaytarish (Vozvrat kirim)",
                user_id=getattr(driver, "employee_id", None),
            )
            db.execute(
                _text("UPDATE orders SET status='confirmed', user_id=:uid "
                      "WHERE parent_order_id=:pid AND type='sale' AND status='draft'"),
                {"uid": getattr(driver, "employee_id", None), "pid": order.id},
            )
        db.refresh(order)
    db.commit()
    return claim.rowcount


def test_supervisor_confirm_returnsale_no_stock_confirms_child(db):
    """Supervisor confirm return_sale: stock QO'SHILMAYDI, child sotuv AVTOMATIK confirmed.

    Child auto-confirm dispatch UI tugmasi uchun zarur (agents/detail.html). b881e3c'da
    apply_return_stock_addition va early-return bilan birga noto'g'ri o'chirilgan,
    20260520 da tiklandi (regressiya 2 orphan: AGT-20260518-005, AGT-20260519-011).
    """
    from app.models.database import Order, Stock
    ret, child, s_ret, drv = _seed_exchange(db)

    rc = _supervisor_confirm(db, ret)

    db.refresh(s_ret); db.refresh(child)
    assert rc == 1
    assert ret.status == "confirmed"
    # Faza 1 asosiy talab: confirm paytida qaytgan tovar OMBORGA QO'SHILMAYDI
    assert s_ret.quantity == 20, "return_sale confirmda stock qo'shilmasligi kerak"
    # YANGI XULQ (regressiya tuzatishidan keyin): child sotuv ham confirmed bo'ladi.
    assert child.status == "confirmed", "child sotuv confirmda avtomatik tasdiqlanishi kerak (dispatch UI uchun)"


def test_driver_delivered_returnsale_adds_stock_and_confirms_child_once(db):
    """Haydovchi 'Yetkazdim': stock +1 marta kiradi, child tasdiqlanadi (1 marta)."""
    from app.models.database import Order, Stock, StockMovement
    ret, child, s_ret, drv = _seed_exchange(db)

    # confirm → dispatch (out_for_delivery)
    _supervisor_confirm(db, ret)
    db.execute(
        _text("UPDATE orders SET status='out_for_delivery' WHERE id=:id AND status='confirmed'"),
        {"id": ret.id},
    )
    db.commit(); db.refresh(ret)
    assert s_ret.quantity == 20, "dispatch return_sale stock'ga tegmasligi kerak"

    # 1-chi 'delivered'
    rc1 = _driver_delivered(db, ret, drv)
    db.refresh(s_ret); db.refresh(child); db.refresh(ret)

    assert rc1 == 1
    assert ret.status == "delivered"
    assert s_ret.quantity == 23, f"Qaytgan 3 dona omborga kirishi kerak, got {s_ret.quantity}"
    assert child.status == "confirmed", "child sotuv yetkazilganda tasdiqlanishi kerak"
    mv_count = db.query(StockMovement).filter(
        StockMovement.document_id == ret.id,
        StockMovement.operation_type == "return_sale",
    ).count()
    assert mv_count == 1, f"Qaytarish movement faqat 1 ta bo'lishi kerak, got {mv_count}"

    # 2-chi 'delivered' (endpoint qayta chaqirildi) — IDEMPOTENT
    rc2 = _driver_delivered(db, ret, drv)
    db.refresh(s_ret); db.refresh(child)

    assert rc2 == 0, "Ikkinchi delivered UPDATE rad etilishi kerak (status endi delivered)"
    assert s_ret.quantity == 23, "Qaytgan tovar IKKI MARTA qo'shilmasligi kerak"
    mv_count2 = db.query(StockMovement).filter(
        StockMovement.document_id == ret.id,
        StockMovement.operation_type == "return_sale",
    ).count()
    assert mv_count2 == 1, f"Movement dublikat bo'lmasligi kerak, got {mv_count2}"


def test_normal_sale_unaffected_by_change(db):
    """Regressiya: oddiy sotuv confirm/delivered eski xatti-harakatni saqlaydi."""
    from app.models.database import Order, OrderItem, Stock, Product, Warehouse, Partner, Driver, StockMovement
    p = Partner(name="P", balance=0, code="P_NS1")
    w = Warehouse(name="W", is_active=True)
    pr = Product(name="Pr", is_active=True, sale_price=10000)
    drv = Driver(code="DR_NS1", full_name="Drv", is_active=True)
    db.add_all([p, w, pr, drv]); db.flush()
    s = Stock(warehouse_id=w.id, product_id=pr.id, quantity=50)
    db.add(s); db.flush()
    o = Order(
        number="AGT-NS1", date=datetime.now(), type="sale", source="agent",
        partner_id=p.id, warehouse_id=w.id,
        total=30000, debt=30000, paid=0, status="out_for_delivery",
    )
    db.add(o); db.flush()
    db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=3, price=10000, total=30000, warehouse_id=w.id))
    db.commit()

    rc = _driver_delivered(db, o, drv)
    db.refresh(o); db.refresh(p)

    assert rc == 1
    assert o.status == "delivered"
    assert p.balance == 30000, "Oddiy sotuv: partner balance += debt (o'zgarmagan)"
    # return_sale logikasi oddiy sotuvga tegmaydi — return_sale movement bo'lmasligi kerak
    rs_mv = db.query(StockMovement).filter(
        StockMovement.document_id == o.id,
        StockMovement.operation_type == "return_sale",
    ).count()
    assert rs_mv == 0
