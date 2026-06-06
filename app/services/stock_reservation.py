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
