from datetime import datetime
from app.models.database import Order, OrderItem, Payment, Partner, CashRegister, Product, Unit
from app.services.refund_service import compute_return_refund


def _setup_sale(db, *, items, total, subtotal, cash_amount, cash_register_id=1, paid=None):
    u = Unit(name="kg"); db.add(u); db.flush()
    p = Partner(name="Mijoz", phone="+1", balance=0, is_active=True); db.add(p); db.flush()
    cr = CashRegister(id=cash_register_id, name="Naqd", payment_type="naqd", is_active=True, opening_balance=0)
    db.add(cr); db.flush()
    sale = Order(number="S-1", type="sale", status="completed", partner_id=p.id,
                 total=total, subtotal=subtotal, paid=paid if paid is not None else total, debt=0,
                 date=datetime(2026, 6, 2))
    db.add(sale); db.flush()
    for pid, qty, price in items:
        pr = db.query(Product).filter(Product.id == pid).first()
        if not pr:
            pr = Product(id=pid, name=f"P{pid}", unit_id=u.id, is_active=True); db.add(pr); db.flush()
        db.add(OrderItem(order_id=sale.id, product_id=pid, quantity=qty, price=price, total=qty*price))
    if cash_amount > 0:
        db.add(Payment(number="PAY-1", type="income", payment_type="cash", status="confirmed",
                       order_id=sale.id, partner_id=p.id, cash_register_id=cash_register_id,
                       amount=cash_amount, date=datetime(2026, 6, 2)))
    db.commit(); db.refresh(sale)
    return sale


def test_full_cash_return_refunds_paid(db):
    sale = _setup_sale(db, items=[(1, 3, 170000), (2, 1, 10000)], total=500000, subtotal=520000, cash_amount=500000)
    r = compute_return_refund(db, sale, [(1, 3), (2, 1)])
    assert r["ratio"] == 1.0
    assert r["refund_cash"] == 500000.0
    assert r["return_total"] == 500000.0
    assert r["refund_cash_register_id"] == 1


def test_partial_cash_return_proportional(db):
    sale = _setup_sale(db, items=[(1, 4, 100000)], total=400000, subtotal=400000, cash_amount=400000)
    r = compute_return_refund(db, sale, [(1, 1)])
    assert r["ratio"] == 0.25
    assert r["refund_cash"] == 100000.0
    assert r["return_total"] == 100000.0


def test_debt_sale_no_cash_refund(db):
    sale = _setup_sale(db, items=[(1, 2, 100000)], total=200000, subtotal=200000, cash_amount=0, paid=0)
    r = compute_return_refund(db, sale, [(1, 2)])
    assert r["refund_cash"] == 0.0
    assert r["return_total"] == 200000.0
    assert r["refund_cash_register_id"] is None


def test_zero_subtotal_safe(db):
    sale = _setup_sale(db, items=[(1, 1, 0)], total=0, subtotal=0, cash_amount=0, paid=0)
    r = compute_return_refund(db, sale, [(1, 1)])
    assert r["ratio"] == 0.0
    assert r["refund_cash"] == 0.0
