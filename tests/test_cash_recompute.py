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
