from datetime import datetime

import pytest

from app.models.database import Order
from app.services.sales_metrics import (
    SALE_REALIZED,
    sale_orders_query,
    sale_revenue,
)


def _order(db, *, status, total, date, type_="sale", warehouse_id=None, partner_id=None):
    o = Order(
        type=type_, status=status, total=total, date=date,
        warehouse_id=warehouse_id, partner_id=partner_id,
        number=f"T-{status}-{int(total)}-{date:%Y%m%d%H%M%S}",
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def test_realized_includes_only_four_statuses(db):
    d = datetime(2026, 5, 10)
    for st in ("delivered", "completed", "confirmed", "out_for_delivery"):
        _order(db, status=st, total=100, date=d)
    for st in ("draft", "cancelled", "waiting_production", "pending"):
        _order(db, status=st, total=999, date=d)
    rows = sale_orders_query(
        db, scope="realized", dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
    ).all()
    assert sorted(o.status for o in rows) == ["completed", "confirmed", "delivered", "out_for_delivery"]


def test_all_scope_includes_cancelled(db):
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=100, date=d)
    _order(db, status="cancelled", total=50, date=d)
    rows = sale_orders_query(
        db, scope="all", dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
    ).all()
    assert len(rows) == 2


def test_non_sale_type_excluded(db):
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=100, date=d)
    _order(db, status="completed", total=70, date=d, type_="return_sale")
    assert sale_revenue(db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)) == 100.0


def test_revenue_sums_realized_total(db):
    d = datetime(2026, 5, 10)
    _order(db, status="delivered", total=100, date=d)
    _order(db, status="confirmed", total=200, date=d)
    _order(db, status="cancelled", total=999, date=d)
    _order(db, status="draft", total=999, date=d)
    assert sale_revenue(db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)) == 300.0


def test_date_boundary_inclusive(db):
    _order(db, status="completed", total=10, date=datetime(2026, 5, 1, 0, 0, 0))
    _order(db, status="completed", total=20, date=datetime(2026, 5, 31, 23, 59, 59))
    _order(db, status="completed", total=99, date=datetime(2026, 6, 1, 0, 0, 0))
    assert sale_revenue(
        db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31, 23, 59, 59)
    ) == 30.0


def test_warehouse_filter(db):
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=100, date=d, warehouse_id=1)
    _order(db, status="completed", total=200, date=d, warehouse_id=2)
    assert sale_revenue(
        db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31), warehouse_id=1
    ) == 100.0


def test_empty_range_returns_zero(db):
    assert sale_revenue(
        db, dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
    ) == 0.0


def test_unknown_scope_raises(db):
    with pytest.raises(ValueError):
        sale_orders_query(
            db, scope="bogus", dt_from=datetime(2026, 5, 1), dt_to=datetime(2026, 5, 31)
        )


def test_realized_constant_is_exactly_four(db):
    assert set(SALE_REALIZED) == {"delivered", "completed", "confirmed", "out_for_delivery"}


def test_profit_compute_uses_realized_scope(db):
    from app.routes.reports import _compute_sales_and_cogs
    d = datetime(2026, 5, 10)
    _order(db, status="completed", total=500, date=d)
    _order(db, status="confirmed", total=300, date=d)
    _order(db, status="draft", total=999, date=d)        # realized emas
    _order(db, status="cancelled", total=999, date=d)    # realized emas
    _order(db, status="waiting_production", total=999, date=d)  # realized emas — eski filtr buni xato qo'shardi
    sale_orders, revenue, cogs, sale_items = _compute_sales_and_cogs(
        db, datetime(2026, 5, 1), datetime(2026, 5, 31, 23, 59, 59)
    )
    assert revenue == 800.0
    assert {o.status for o in sale_orders} == {"completed", "confirmed"}


def test_sold_products_status_filter_is_realized(db):
    import inspect
    from app.routes import reports
    src = inspect.getsource(reports.sold_products_report)
    assert 'Order.status.in_(("completed", "delivered"))' not in src
    assert "Order.created_at >= d_from" not in src
    assert "Order.created_at <= d_to" not in src
    assert "SALE_REALIZED" in src
    assert "Order.date >= d_from" in src
