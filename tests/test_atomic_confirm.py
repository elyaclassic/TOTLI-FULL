"""Atomik confirm test (audit A — stock 2x oldini olish).

Sales confirm endpoint UPDATE WHERE status='draft' pattern bilan ishlaydi:
ikkinchi so'rov rowcount=0 oladi va return qilinadi.
"""
import pytest
from datetime import datetime
from sqlalchemy import text
from app.models.database import Order


def test_atomic_update_where_only_first_succeeds(db):
    """UPDATE WHERE status='draft' patterni: faqat 1-chi UPDATE muvaffaqiyatli."""
    o = Order(
        number="AGT-T-A1", date=datetime.now(), type="sale",
        total=100000, debt=100000, paid=0, status="draft",
    )
    db.add(o); db.flush()

    r1 = db.execute(
        text("UPDATE orders SET status='confirmed' "
             "WHERE id=:id AND type='sale' AND status='draft'"),
        {"id": o.id},
    )
    r2 = db.execute(
        text("UPDATE orders SET status='confirmed' "
             "WHERE id=:id AND type='sale' AND status='draft'"),
        {"id": o.id},
    )
    db.commit()

    assert r1.rowcount == 1, "Birinchi UPDATE muvaffaqiyatli (status='draft' edi)"
    assert r2.rowcount == 0, "Ikkinchi UPDATE rad etiladi (status allaqachon 'confirmed')"


def test_atomic_update_where_skips_non_draft(db):
    """confirmed/cancelled order'da UPDATE WHERE status='draft' rowcount=0 qaytaradi."""
    o = Order(
        number="AGT-T-A2", date=datetime.now(), type="sale",
        total=50000, debt=50000, paid=0, status="confirmed",  # allaqachon confirmed
    )
    db.add(o); db.flush()

    r = db.execute(
        text("UPDATE orders SET status='confirmed' "
             "WHERE id=:id AND type='sale' AND status='draft'"),
        {"id": o.id},
    )
    db.commit()

    assert r.rowcount == 0, "Non-draft order claim UPDATE'i rad etilishi kerak"
