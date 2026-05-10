"""Yetkazish kuni flow testlari."""
from datetime import datetime, date
import pytest
from sqlalchemy import text


def test_orders_has_delivery_columns(db):
    """orders jadvalida delivery_date va dispatched_at ustunlar bo'lishi kerak."""
    cols = [row[1] for row in db.execute(text("PRAGMA table_info(orders)")).fetchall()]
    assert "delivery_date" in cols
    assert "dispatched_at" in cols


def test_order_status_constants():
    """Order modelida 6 ta yangi status nomli (+ legacy completed) konstanta bo'lishi kerak."""
    from app.models.database import Order
    assert Order.STATUS_DRAFT == "draft"
    assert Order.STATUS_CONFIRMED == "confirmed"
    assert Order.STATUS_OUT_FOR_DELIVERY == "out_for_delivery"
    assert Order.STATUS_DELIVERED == "delivered"
    assert Order.STATUS_CANCELLED == "cancelled"
    assert "out_for_delivery" in Order.VALID_STATUSES
    assert "delivered" in Order.VALID_STATUSES
