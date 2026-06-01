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


from datetime import date
from app.models.database import CashRegister, ExchangeRate


def test_compute_converts_usd_expense_payment(db):
    p = _partner(db)
    usd = CashRegister(name="Asosiy $", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", rate=12000, effective_date=date(2026,1,1)))
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed",
                   amount=100, cash_register_id=usd.id, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 1200000.0


def test_compute_uzs_payment_not_converted(db):
    p = _partner(db)
    uzs = CashRegister(name="Naqd", payment_type="naqd", currency="UZS", is_active=True, opening_balance=0)
    db.add(uzs); db.flush()
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed",
                   amount=50000, cash_register_id=uzs.id, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 50000.0


def test_compute_usd_no_rate_uses_raw_amount(db):
    p = _partner(db)
    usd = CashRegister(name="Asosiy $", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed",
                   amount=100, cash_register_id=usd.id, date=datetime(2026,6,1)))
    db.commit()
    assert compute_partner_balance(db, p.id) == 100.0


from app.models.database import AuditLog


def test_recompute_sets_balance_and_returns_old_new(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=999)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=datetime(2026,6,1)))
    db.commit()
    old, new = recompute_partner_balance(db, p.id, reason="sale_confirm")
    db.commit()
    assert old == 999.0
    assert new == 100000.0
    db.refresh(p)
    assert p.balance == 100000.0


def test_recompute_writes_audit_log(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=50000, date=datetime(2026,6,1)))
    db.commit()
    recompute_partner_balance(db, p.id, reason="sale_confirm", ref="S-0001", actor="admin")
    db.commit()
    logs = db.query(AuditLog).filter(AuditLog.entity_type == "partner_balance").all()
    assert len(logs) == 1
    assert logs[0].entity_id == p.id
    assert logs[0].action == "recompute"
    assert "sale_confirm" in (logs[0].details or "")
    assert logs[0].entity_number == "S-0001"


def test_recompute_idempotent(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=70000, date=datetime(2026,6,1)))
    db.commit()
    recompute_partner_balance(db, p.id, reason="x"); db.commit()
    old, new = recompute_partner_balance(db, p.id, reason="x"); db.commit()
    assert old == new == 70000.0


def test_recompute_confirm_revert_confirm_no_drift(db):
    from app.services.partner_balance_service import recompute_partner_balance
    p = _partner(db, balance=0)
    o = Order(partner_id=p.id, type="sale", status="confirmed", total=80000, date=datetime(2026,6,1))
    db.add(o); db.commit()
    recompute_partner_balance(db, p.id, reason="confirm"); db.commit()
    db.refresh(p); assert p.balance == 80000.0
    o.status = "cancelled"; db.commit()
    recompute_partner_balance(db, p.id, reason="revert"); db.commit()
    db.refresh(p); assert p.balance == 0.0
    o.status = "confirmed"; db.commit()
    recompute_partner_balance(db, p.id, reason="reconfirm"); db.commit()
    db.refresh(p); assert p.balance == 80000.0


def test_reconciliation_closing_equals_compute(db):
    from app.routes.reports import _build_partner_movements
    from datetime import datetime as _dt
    p = _partner(db)
    db.add(Order(partner_id=p.id, type="sale", status="confirmed", total=100000, date=_dt(2026,6,1)))
    db.add(Payment(partner_id=p.id, type="income", status="confirmed", amount=30000, date=_dt(2026,6,1)))
    db.add(Purchase(partner_id=p.id, status="confirmed", total=20000, total_expenses=0, date=_dt(2026,6,1)))
    db.commit()
    rows, od, oc = _build_partner_movements(db, p.id, _dt(2026,1,1), _dt(2026,12,31), period_only=False)
    closing = sum(float(r["debit"]) - float(r["credit"]) for r in rows)
    assert abs(closing - compute_partner_balance(db, p.id)) < 0.01


def test_reconciliation_closing_equals_compute_with_usd(db):
    from app.routes.reports import _build_partner_movements
    from datetime import datetime as _dt, date as _d
    from app.models.database import CashRegister, ExchangeRate
    p = _partner(db)
    usd = CashRegister(name="$", payment_type="naqd", currency="USD", is_active=True, opening_balance=0)
    db.add(usd); db.flush()
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", rate=12000, effective_date=_d(2026,1,1)))
    db.add(Payment(partner_id=p.id, type="expense", status="confirmed", amount=100, cash_register_id=usd.id, date=_dt(2026,6,1)))
    db.commit()
    rows, od, oc = _build_partner_movements(db, p.id, _dt(2026,1,1), _dt(2026,12,31), period_only=False)
    closing = sum(float(r["debit"]) - float(r["credit"]) for r in rows)
    assert abs(closing - compute_partner_balance(db, p.id)) < 0.01
    assert abs(closing - 1200000.0) < 0.01
