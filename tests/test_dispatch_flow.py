"""Yetkazish kuni flow testlari."""
from datetime import datetime, date
import pytest
from sqlalchemy import text


def test_orders_has_delivery_columns(db):
    """orders jadvalida delivery_date va dispatched_at ustunlar bo'lishi kerak."""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(orders)")).fetchall()]
    assert "delivery_date" in cols
    assert "dispatched_at" in cols
