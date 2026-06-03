"""Test: recompute_cash_balance funksiyasi (audit yozadigan)."""
from app.models.database import CashRegister, AuditLog
from app.services.finance_service import recompute_cash_balance


def test_recompute_cash_balance_sets_and_audits(db):
    """Kassa balansini formula bo'yicha tiklaydi va AuditLog yozadi."""
    c = CashRegister(name="Test kassa", opening_balance=1000.0, balance=999.0, currency="UZS")
    db.add(c)
    db.flush()

    old, new = recompute_cash_balance(db, c.id, reason="unit_test", ref="X-1", actor="tester")

    assert old == 999.0
    assert new == 1000.0          # opening=1000 + 0 income - 0 expense + 0 transfers
    assert c.balance == 1000.0

    logs = db.query(AuditLog).filter(
        AuditLog.entity_type == "cash_balance",
        AuditLog.entity_id == c.id,
    ).all()
    assert len(logs) == 1
    assert "reason=unit_test" in logs[0].details
    assert logs[0].user_name == "tester"
    assert logs[0].action == "recompute"
    assert logs[0].entity_number == "X-1"


def test_recompute_cash_balance_missing_cash(db):
    """Mavjud bo'lmagan kassa id uchun (0.0, 0.0) qaytaradi."""
    old, new = recompute_cash_balance(db, 99999, reason="test", actor="system")
    assert old == 0.0
    assert new == 0.0


def test_recompute_cash_balance_default_actor(db):
    """actor=None bo'lsa AuditLog.user_name='system' bo'ladi."""
    c = CashRegister(name="Kassa2", opening_balance=500.0, balance=400.0, currency="UZS")
    db.add(c)
    db.flush()

    old, new = recompute_cash_balance(db, c.id, reason="auto")

    assert old == 400.0
    assert new == 500.0
    logs = db.query(AuditLog).filter(AuditLog.entity_id == c.id).all()
    assert logs[0].user_name == "system"
    assert logs[0].entity_number is None


def test_doc_revert_exact_after_income_churn(db):
    """Confirm -> orasiga income -> revert: opening confirm-oldi qiymatiga aniq qaytishi (churn drift YO'Q)."""
    from app.models.database import Payment
    c = CashRegister(name="K", opening_balance=500.0, balance=500.0, currency="UZS")
    db.add(c)
    db.flush()
    opening_before = float(c.opening_balance)

    # Confirm simulyatsiyasi: delta=+200
    prev_opening = float(c.opening_balance or 0)
    c.opening_balance = prev_opening + 200.0
    recompute_cash_balance(db, c.id, reason="t_confirm")
    db.flush()
    assert c.balance == 700.0

    # Orasiga income +300 (orqaga sanali to'lov)
    db.add(Payment(cash_register_id=c.id, type="income", amount=300.0, status="confirmed"))
    db.flush()
    recompute_cash_balance(db, c.id, reason="t_sync")
    assert c.balance == 1000.0     # 700 + 300

    # Revert: opening aniq tiklash
    c.opening_balance = prev_opening
    recompute_cash_balance(db, c.id, reason="t_revert")
    db.flush()
    assert c.opening_balance == opening_before   # 500.0 aniq
    assert c.balance == 800.0                     # opening 500 + income 300 (churn drift YO'Q)
