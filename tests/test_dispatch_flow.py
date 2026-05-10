"""Yetkazish kuni flow testlari."""
from datetime import datetime, date
import pytest
from sqlalchemy import inspect


def test_orders_has_delivery_columns(db):
    """orders jadvalida delivery_date va dispatched_at ustunlar bo'lishi kerak."""
    inspector = inspect(db.bind)
    cols = [c["name"] for c in inspector.get_columns("orders")]
    assert "delivery_date" in cols
    assert "dispatched_at" in cols
