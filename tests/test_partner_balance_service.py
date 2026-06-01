from datetime import datetime
from app.models.database import (
    Partner, Order, Payment, Purchase,
    PartnerBalanceDoc, PartnerBalanceDocItem, PurchaseReturn,
)
from app.services.partner_balance_service import compute_partner_balance


def _partner(db, balance=0):
    p = Partner(name="P", phone="+1", balance=balance, credit_limit=0, is_active=True)
    db.add(p); db.commit(); db.refresh(p)
    return p


def test_compute_empty_partner_is_zero(db):
    p = _partner(db, balance=999)
    assert compute_partner_balance(db, p.id) == 0.0


def test_compute_sale_adds_total(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026, 6, 1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 100000.0


def test_compute_return_sale_subtracts(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026,6,1)))
    db.add(Order(partner_id=p.id, type="return_sale", status="confirmed", total=30000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 70000.0


def test_compute_income_payment_subtracts(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026,6,1)))
    db.add(Payment(partner_id=p.id, type="income", status="confirmed", amount=40000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 60000.0


def test_compute_expense_payment_adds(db):
    p = _partner(db)
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed", amount=50000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 50000.0


def test_compute_purchase_subtracts_total_plus_expenses(db):
    p = _partner(db)
    db.add(Purchase(partner_id=p.id, status="confirmed", total=80000, total_expenses=5000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == -85000.0


def test_compute_balance_doc_signed(db):
    p = _partner(db)
    doc = PartnerBalanceDoc(number="KNT-1", status="confirmed", date=datetime(2026,6,1))
    db.add(doc); db.flush()
    db.add(PartnerBalanceDocItem(doc_id=doc.id, partner_id=p.id, balance=-200000))
    db.commit()
    assert compute_partner_balance(db, p.id) == -200000.0


def test_compute_purchase_return_adds(db):
    p = _partner(db)
    db.add(Purchase(partner_id=p.id, status="confirmed", total=80000, total_expenses=0, date=datetime(2026,6,1)))
    db.add(PurchaseReturn(partner_id=p.id, status="confirmed", total=20000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == -60000.0


def test_compute_ignores_cancelled_and_draft(db):
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="cancelled", total=100000, date=datetime(2026,6,1)))
    db.add(Order(partner_id=p.id, type="sale", status="draft", total=100000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 0.0


def test_compute_includes_null_status_payment(db):
    p = _partner(db)
    db.add(Payment(partner_id=p.id, type="expense", status=None, amount=10000, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 10000.0
