"""waiting_production buyurtmalar tomonidan band qilingan stock.

Band hech qayerda SAQLANMAYDI — har safar waiting_production statusdagi
buyurtmalardan hisoblanadi. Buyurtma statusi o'zgarsa band avtomatik
yo'qoladi → drift mumkin emas.
"""
from sqlalchemy import func, or_, and_

from app.models.database import Order, OrderItem, Stock


def get_reserved_quantity(db, warehouse_id, product_id, before_order=None) -> float:
    """waiting_production buyurtmalar band qilgan miqdor (wh+pid bo'yicha).

    before_order berilsa — faqat o'sha buyurtmadan ESKI waiting buyurtmalar
    hisoblanadi (FIFO seniority). O'zini hisobga olmaydi.
    """
    q = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0.0))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.status == "waiting_production",
            Order.type == "sale",
            OrderItem.product_id == product_id,
            func.coalesce(OrderItem.warehouse_id, Order.warehouse_id) == warehouse_id,
        )
    )
    if before_order is not None:
        q = q.filter(
            Order.id != before_order.id,
            or_(
                Order.date < before_order.date,
                and_(Order.date == before_order.date, Order.id < before_order.id),
            ),
        )
    return float(q.scalar() or 0.0)


def get_available_stock(db, warehouse_id, product_id, before_order=None) -> float:
    """Iste'mol uchun mavjud = jismoniy qoldiq - band (seniority bo'yicha)."""
    physical = (
        db.query(func.coalesce(func.sum(Stock.quantity), 0.0))
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == product_id)
        .scalar()
    )
    reserved = get_reserved_quantity(db, warehouse_id, product_id, before_order)
    return float(physical or 0.0) - reserved


def get_available_stock_at_date(db, warehouse_id, product_id, cutoff=None) -> float:
    """Berilgan sanadagi (cutoff) mavjud stock − band. cutoff=None → joriy qoldiq.

    Transfer (vaqt-aware) darvozalari uchun: get_stock_at_date sanagacha qoldiqni
    beradi, undan joriy band (waiting_production) ayriladi.
    """
    from app.utils.stock_at_date import get_stock_at_date
    physical = get_stock_at_date(db, warehouse_id, product_id, cutoff=cutoff)
    return float(physical or 0.0) - get_reserved_quantity(db, warehouse_id, product_id)


def get_all_reservations(db) -> dict:
    """Barcha waiting_production band miqdorlari: {(warehouse_id, product_id): qty}.
    Bitta guruhlangan query (per-qator alohida query o'rniga)."""
    wh_expr = func.coalesce(OrderItem.warehouse_id, Order.warehouse_id)
    rows = (
        db.query(
            wh_expr.label("wh"),
            OrderItem.product_id.label("pid"),
            func.coalesce(func.sum(OrderItem.quantity), 0.0).label("qty"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == "waiting_production", Order.type == "sale")
        .group_by(wh_expr, OrderItem.product_id)
        .all()
    )
    return {(r.wh, r.pid): float(r.qty or 0) for r in rows}
