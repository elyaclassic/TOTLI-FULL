"""Revert balance — recompute pattern testlari (snapshot mexanizmi olib tashlandi).

Eski model: _revert_balance_if_needed previous_partner_balance snapshot'ga qaytarardi.
Yangi model: order.status -> draft/cancelled, keyin recompute (formula draft/cancelled'ni
hisobga olmaydi -> balans o'zini to'g'rilaydi).
"""
from datetime import datetime
from app.models.database import Order, Partner
from app.services.partner_balance_service import recompute_partner_balance


def test_revert_delivered_sale_removes_balance(db):
    """delivered sotuv draft'ga o'tkazilib recompute qilinsa, balans 0 ga qaytadi."""
    p = Partner(name="Test", balance=0, code="P9999")
    db.add(p); db.flush()
    o = Order(number="AGT-T-001", date=datetime.now(), type="sale",
              partner_id=p.id, total=100000, debt=100000, paid=0, status="delivered")
    db.add(o); db.flush()
    recompute_partner_balance(db, p.id, reason="confirm"); db.commit()
    db.refresh(p)
    assert p.balance == 100000

    o.status = "draft"; db.flush()
    recompute_partner_balance(db, p.id, reason="sale_revert"); db.commit()
    db.refresh(p)
    assert p.balance == 0


def test_revert_then_reconfirm_no_drift(db):
    """confirm -> revert(draft) -> reconfirm(delivered): balans aynan tiklanadi (drift yo'q)."""
    p = Partner(name="Test2", balance=0, code="P9998")
    db.add(p); db.flush()
    o = Order(number="AGT-T-002", date=datetime.now(), type="sale",
              partner_id=p.id, total=50000, debt=50000, paid=0, status="delivered")
    db.add(o); db.flush()
    recompute_partner_balance(db, p.id, reason="confirm"); db.commit()
    db.refresh(p); assert p.balance == 50000
    o.status = "draft"; db.flush()
    recompute_partner_balance(db, p.id, reason="revert"); db.commit()
    db.refresh(p); assert p.balance == 0
    o.status = "delivered"; db.flush()
    recompute_partner_balance(db, p.id, reason="reconfirm"); db.commit()
    db.refresh(p); assert p.balance == 50000


def test_revert_cancelled_excluded_from_balance(db):
    """cancelled sotuv balansga kirmaydi."""
    p = Partner(name="Test3", balance=0, code="P9997")
    db.add(p); db.flush()
    o = Order(number="AGT-T-003", date=datetime.now(), type="sale",
              partner_id=p.id, total=80000, debt=80000, paid=0, status="cancelled")
    db.add(o); db.flush()
    recompute_partner_balance(db, p.id, reason="confirm"); db.commit()
    db.refresh(p)
    assert p.balance == 0


def test_revert_confirmed_status_counts(db):
    """confirmed (draft/cancelled emas) sotuv balansga kiradi."""
    p = Partner(name="Test4", balance=0, code="P9996")
    db.add(p); db.flush()
    o = Order(number="AGT-T-004", date=datetime.now(), type="sale",
              partner_id=p.id, total=30000, debt=30000, paid=0, status="confirmed")
    db.add(o); db.flush()
    recompute_partner_balance(db, p.id, reason="confirm"); db.commit()
    db.refresh(p)
    assert p.balance == 30000
