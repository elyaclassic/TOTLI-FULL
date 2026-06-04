"""Audit H3 + H5 + H6 fix testlari.

H3: obmen (return_sale) yetkazish FAILED bo'lsa, bog'langan child sale draft ham
    'cancelled' bo'lishi kerak (delivered yo'liga simmetrik). Yetim draft qolmasin.
H5: next_doc_number helper — MAX(suffix)+1 (count()+1 / id+1 race/reuse fix).
H6: _production_revert_one asl stock harakatlaridan NET ko'zgu qiladi —
    production_items/retseptdan emas. Ombor/miqdor asimmetriyasi bartaraf.
"""
import asyncio
import json
from datetime import datetime

from app.routes.api_driver_ops import driver_delivery_status
from app.utils.auth import create_session_token
from app.utils.doc_number import next_doc_number


# ============ H5 ============

def test_h5_next_doc_number_sequential_and_gap_resilient(db):
    from app.models.database import Payment, CashRegister
    cr = CashRegister(name="C", payment_type="naqd", is_active=True)
    db.add(cr); db.flush()
    pref = "DLV-20260604-"

    # bo'sh -> 0001
    assert next_doc_number(db, Payment, pref) == pref + "0001"

    for n in ["0001", "0002", "0003"]:
        db.add(Payment(number=pref + n, date=datetime(2026, 6, 4), type="income",
                       amount=1, cash_register_id=cr.id))
    db.flush()
    assert next_doc_number(db, Payment, pref) == pref + "0004"

    # GAP: 0002 o'chirilsa ham 0004 (MAX+1, count()+1 EMAS -> dublikat bo'lmaydi)
    db.query(Payment).filter(Payment.number == pref + "0002").delete()
    db.flush()
    assert next_doc_number(db, Payment, pref) == pref + "0004", \
        "O'chirilgan gap raqamni takrorlamasligi kerak (MAX-based)"

    # boshqa prefiks izolyatsiyasi
    assert next_doc_number(db, Payment, "KK-20260604-") == "KK-20260604-0001"


def test_h5_next_doc_number_mixed_width(db):
    """Eski 3-xonali + yangi 4-xonali suffikslar aralash bo'lsa ham raqamli MAX."""
    from app.models.database import Payment, CashRegister
    cr = CashRegister(name="C2", payment_type="naqd", is_active=True)
    db.add(cr); db.flush()
    pref = "PAY-20260604-"
    for n in ["008", "0009", "0010"]:
        db.add(Payment(number=pref + n, date=datetime(2026, 6, 4), type="income",
                       amount=1, cash_register_id=cr.id))
    db.flush()
    assert next_doc_number(db, Payment, pref) == pref + "0011"


# ============ H3 ============

def _mk_driver(db):
    from app.models.database import Driver
    drv = Driver(code="DR_H3", full_name="Drv", is_active=True, employee_id=9301)
    db.add(drv); db.flush()
    return drv, create_session_token(drv.employee_id, "driver")


def test_h3_failed_return_sale_cancels_child_draft(db):
    """return_sale FAILED -> parent cancelled VA child sale draft cancelled."""
    from app.models.database import Order, Partner, Driver, Delivery
    drv, token = _mk_driver(db)
    p = Partner(name="P", balance=0, code="P_H3")
    db.add(p); db.flush()

    parent = Order(
        number="RET-H3", date=datetime.now(), type="return_sale",
        partner_id=p.id, total=0, debt=0, paid=0, status="out_for_delivery",
        pending_driver_id=drv.id,
    )
    db.add(parent); db.flush()
    child = Order(
        number="SALE-H3", date=datetime.now(), type="sale",
        partner_id=p.id, parent_order_id=parent.id,
        total=50000, debt=50000, paid=0, status="draft",
    )
    db.add(child); db.flush()
    d = Delivery(number="DLV-H3", driver_id=drv.id, order_id=parent.id, status="in_progress")
    db.add(d); db.commit()

    res = asyncio.run(driver_delivery_status(
        delivery_id=d.id, status="failed",
        latitude=None, longitude=None, notes="",
        items=None, naqd=0, plastik=0, token=token, db=db,
    ))

    db.refresh(parent); db.refresh(child)
    assert res.get("success") is True, f"{res}"
    assert parent.status == "cancelled"
    assert child.status == "cancelled", \
        f"Obmen failed bo'lsa child sale draft cancelled bo'lishi kerak, hozir: {child.status}"


# ============ H6 ============

def test_h6_revert_mirrors_movements_not_production_items(db):
    """Revert asl consumption/output harakatlaridan qaytaradi — production_items
    (xato/tahrirlangan) qiymatdan EMAS. Ombor ham asl movement ombori."""
    from app.models.database import (
        Production, ProductionItem, Recipe, Stock, Product, Warehouse,
    )
    from app.routes.production import _production_revert_one
    from app.services.stock_service import create_stock_movement

    raw_wh = Warehouse(name="Xom", is_active=True)
    out_wh = Warehouse(name="Tayyor", is_active=True)
    raw_pr = Product(name="Shakar", is_active=True)
    out_pr = Product(name="Holva", is_active=True)
    db.add_all([raw_wh, out_wh, raw_pr, out_pr]); db.flush()

    rec = Recipe(product_id=out_pr.id, name="Holva retsept", is_active=True)
    db.add(rec); db.flush()

    # Pre-completion stock
    s_raw = Stock(warehouse_id=raw_wh.id, product_id=raw_pr.id, quantity=100)
    s_out = Stock(warehouse_id=out_wh.id, product_id=out_pr.id, quantity=0)
    db.add_all([s_raw, s_out]); db.flush()

    prod = Production(
        number="PR-H6", recipe_id=rec.id,
        warehouse_id=raw_wh.id, output_warehouse_id=out_wh.id,
        quantity=10, status="completed",
    )
    db.add(prod); db.flush()

    # Completion harakatlari: 30 xom iste'mol (raw_wh), 10 tayyor ishlab chiqarildi (out_wh)
    create_stock_movement(db=db, warehouse_id=raw_wh.id, product_id=raw_pr.id,
                          quantity_change=-30, operation_type="production_consumption",
                          document_type="Production", document_id=prod.id, document_number=prod.number)
    create_stock_movement(db=db, warehouse_id=out_wh.id, product_id=out_pr.id,
                          quantity_change=+10, operation_type="production_output",
                          document_type="Production", document_id=prod.id, document_number=prod.number)
    db.flush()
    db.refresh(s_raw); db.refresh(s_out)
    assert s_raw.quantity == 70 and s_out.quantity == 10  # post-completion holat

    # production_items ATAYLAB XATO (999) — revert buni ISHLATMASLIGI kerak
    db.add(ProductionItem(production_id=prod.id, product_id=raw_pr.id, quantity=999))
    db.commit()

    err = _production_revert_one(db, prod)
    db.commit()  # real kodda caller commit qiladi (autoflush=False fixture artefaktidan qochish)
    db.refresh(s_raw); db.refresh(s_out); db.refresh(prod)

    assert err is None, f"Revert muvaffaqiyatli bo'lishi kerak: {err}"
    assert s_raw.quantity == 100, f"Xom ashyo asl 100 ga qaytishi kerak (movement -30 ko'zgu), hozir {s_raw.quantity}"
    assert s_out.quantity == 0, f"Tayyor mahsulot 0 ga qaytishi kerak (movement +10 ko'zgu), hozir {s_out.quantity}"
    assert prod.status == "draft"


def test_h6_revert_refused_when_output_sold(db):
    """Tayyor mahsulot sotilgan (stock yetmaydi) bo'lsa revert RAD etiladi, status o'zgarmaydi."""
    from app.models.database import (
        Production, Recipe, Stock, Product, Warehouse,
    )
    from app.routes.production import _production_revert_one
    from app.services.stock_service import create_stock_movement

    raw_wh = Warehouse(name="Xom2", is_active=True)
    out_wh = Warehouse(name="Tayyor2", is_active=True)
    raw_pr = Product(name="Shakar2", is_active=True)
    out_pr = Product(name="Holva2", is_active=True)
    db.add_all([raw_wh, out_wh, raw_pr, out_pr]); db.flush()
    rec = Recipe(product_id=out_pr.id, name="R2", is_active=True)
    db.add(rec); db.flush()
    s_raw = Stock(warehouse_id=raw_wh.id, product_id=raw_pr.id, quantity=70)
    s_out = Stock(warehouse_id=out_wh.id, product_id=out_pr.id, quantity=10)
    db.add_all([s_raw, s_out]); db.flush()
    prod = Production(number="PR-H6b", recipe_id=rec.id, warehouse_id=raw_wh.id,
                      output_warehouse_id=out_wh.id, quantity=10, status="completed")
    db.add(prod); db.flush()
    create_stock_movement(db=db, warehouse_id=raw_wh.id, product_id=raw_pr.id,
                          quantity_change=-30, operation_type="production_consumption",
                          document_type="Production", document_id=prod.id, document_number=prod.number)
    create_stock_movement(db=db, warehouse_id=out_wh.id, product_id=out_pr.id,
                          quantity_change=+10, operation_type="production_output",
                          document_type="Production", document_id=prod.id, document_number=prod.number)
    db.commit()
    # Tayyor mahsulot sotildi: out stock 10 -> 2 (revert uchun yetmaydi)
    s_out.quantity = 2
    db.commit()

    err = _production_revert_one(db, prod)
    db.refresh(prod)
    assert err is not None, "Output sotilган bo'lsa revert rad etilishi kerak"
    assert prod.status == "completed", "Rad etilganda status o'zgarmasligi kerak"
