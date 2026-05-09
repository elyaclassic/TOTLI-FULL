"""Vaqt-aware Stock qoldiq hisoblash.

stock_movement.quantity_after orqali har sanada Stock holatini topish.
Eski sanaga yoziladigan hujjatlarda (sales/edit, production/confirm,
employee mahsulot xaridi va h.k.) ishlatiladi.

Misol:
    qty = get_stock_at_date(db, warehouse_id=3, product_id=49, cutoff=datetime(2026, 4, 11, 23, 59, 59))
    # qty = shu sanagacha bo'lgan oxirgi movement.quantity_after

Batch versiyasi:
    qty_map = get_stock_at_date_batch(db, warehouse_id=3, product_ids=[1, 2, 3], cutoff=...)
    # qty_map = {1: 100.0, 2: 50.0, 3: 0.0}
"""
from datetime import datetime
from typing import Optional, Iterable

from sqlalchemy import func as sqla_func
from sqlalchemy.orm import Session

from app.models.database import Stock, StockMovement


def get_stock_at_date(
    db: Session,
    warehouse_id: int,
    product_id: int,
    cutoff: Optional[datetime] = None,
) -> float:
    """Berilgan sanagacha (cutoff inclusive) Stock qoldigi.

    cutoff=None bo'lsa hozirgi Stock.quantity qaytariladi (default).
    Aks holda stock_movement.quantity_after dan oxirgi qiymat olinadi.

    Tarix yo'q bo'lsa (movement bo'sh), 0.0 qaytariladi.
    """
    if cutoff is None:
        rows = db.query(Stock).filter(
            Stock.warehouse_id == warehouse_id,
            Stock.product_id == product_id,
        ).all()
        return sum(float(s.quantity or 0) for s in rows)

    last_mv_id = (
        db.query(sqla_func.max(StockMovement.id))
        .filter(
            StockMovement.warehouse_id == warehouse_id,
            StockMovement.product_id == product_id,
            StockMovement.created_at <= cutoff,
        )
        .scalar()
    )
    if not last_mv_id:
        return 0.0
    mv = db.query(StockMovement).filter(StockMovement.id == last_mv_id).first()
    return float(mv.quantity_after or 0) if mv else 0.0


def get_stock_at_date_batch(
    db: Session,
    warehouse_id: int,
    product_ids: Iterable[int],
    cutoff: Optional[datetime] = None,
) -> dict:
    """Bir nechta mahsulot uchun batch qoldiq.

    Returns: {product_id: quantity} mapping.
    """
    pids = list(product_ids)
    if not pids:
        return {}

    if cutoff is None:
        rows = (
            db.query(Stock.product_id, sqla_func.coalesce(sqla_func.sum(Stock.quantity), 0))
            .filter(
                Stock.warehouse_id == warehouse_id,
                Stock.product_id.in_(pids),
            )
            .group_by(Stock.product_id)
            .all()
        )
        return {pid: float(q or 0) for pid, q in rows}

    max_id_rows = (
        db.query(
            StockMovement.product_id,
            sqla_func.max(StockMovement.id).label("mid"),
        )
        .filter(
            StockMovement.warehouse_id == warehouse_id,
            StockMovement.product_id.in_(pids),
            StockMovement.created_at <= cutoff,
        )
        .group_by(StockMovement.product_id)
        .all()
    )
    max_ids = [r.mid for r in max_id_rows if r.mid]
    if not max_ids:
        return {}
    result: dict = {}
    for mv in db.query(StockMovement).filter(StockMovement.id.in_(max_ids)).all():
        result[mv.product_id] = float(mv.quantity_after or 0)
    return result
