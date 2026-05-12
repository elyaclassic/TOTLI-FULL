"""Revert balance fix testlari (audit B)."""
import pytest
from datetime import datetime
from app.models.database import Order, Partner


def test_revert_delivered_returns_balance(db):
    """delivered order revert qilinsa, partner.balance previous'ga qaytariladi."""
    p = Partner(name="Test", balance=0, code="P9999")
    db.add(p); db.flush()
    o = Order(
        number="AGT-T-001", date=datetime.now(), type="sale",
        partner_id=p.id, total=100000, debt=100000, paid=0,
        status="delivered", previous_partner_balance=0,
    )
    db.add(o); db.flush()
    p.balance = 100000
    db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 0, "delivered revert balansi previous'ga qaytarishi kerak"


def test_revert_completed_returns_balance(db):
    """Legacy completed status uchun ham balance qaytariladi."""
    p = Partner(name="Test", balance=0, code="P9998")
    db.add(p); db.flush()
    o = Order(
        number="AGT-T-002", date=datetime.now(), type="sale",
        partner_id=p.id, total=50000, debt=50000, paid=0,
        status="completed", previous_partner_balance=0,
    )
    db.add(o); db.flush()
    p.balance = 50000
    db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 0


def test_revert_confirmed_no_balance_change(db):
    """confirmed status — balance hali yozilmagan, qaytarmaslik kerak."""
    p = Partner(name="Test", balance=50000, code="P9997")
    db.add(p); db.flush()
    o = Order(
        number="AGT-T-003", date=datetime.now(), type="sale",
        partner_id=p.id, total=100000, debt=100000, paid=0,
        status="confirmed", previous_partner_balance=50000,
    )
    db.add(o); db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 50000, "confirmed status balanceni o'zgartirmasligi kerak"


def test_revert_out_for_delivery_no_balance_change(db):
    """out_for_delivery — balance hali yozilmagan."""
    p = Partner(name="Test", balance=30000, code="P9996")
    db.add(p); db.flush()
    o = Order(
        number="AGT-T-004", date=datetime.now(), type="sale",
        partner_id=p.id, total=80000, debt=80000, paid=0,
        status="out_for_delivery", previous_partner_balance=30000,
    )
    db.add(o); db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 30000


def test_revert_delivered_null_snapshot_falls_back_to_debt_subtract(db):
    """Legacy migrated order (previous_partner_balance=NULL) revert qilinsa, debt ayiriladi."""
    p = Partner(name="Legacy", balance=50000, code="P_LEG")
    db.add(p); db.flush()
    o = Order(
        number="AGT-LEG-1", date=datetime.now(), type="sale",
        partner_id=p.id, total=30000, debt=30000, paid=0,
        status="delivered", previous_partner_balance=None,  # migrated, no snapshot
    )
    db.add(o); db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 20000, "NULL snapshot legacy fallback: balance -= debt"


def test_revert_delivered_zero_debt_null_snapshot_no_change(db):
    """debt=0 + previous_partner_balance=NULL — balans o'zgarmaydi (else branch'ga kirmaydi)."""
    p = Partner(name="Zero", balance=10000, code="P_Z1")
    db.add(p); db.flush()
    o = Order(
        number="AGT-Z-1", date=datetime.now(), type="sale",
        partner_id=p.id, total=20000, debt=0, paid=20000,  # to'liq to'langan
        status="delivered", previous_partner_balance=None,
    )
    db.add(o); db.flush()

    from app.routes.sales import _revert_balance_if_needed
    _revert_balance_if_needed(db, o, p)

    assert p.balance == 10000, "Zero debt: o'zgarmaydi"
