"""Ombor harakati (StockMovement) yaratish va o'chirish."""
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.database import Stock, StockMovement


def create_stock_movement(
    db: Session,
    warehouse_id: int,
    product_id: int,
    quantity_change: float,
    operation_type: str,
    document_type: str,
    document_id: int,
    document_number: str = None,
    user_id: int = None,
    note: str = None,
    created_at=None,
):
    """Har bir operatsiya uchun StockMovement yozuvini yaratish.
    Chiqim (quantity_change < 0) bo'lganda avval bitta ombor+mahsulot uchun barcha Stock qatorlarini birlashtiradi."""
    rows = db.query(Stock).filter(
        Stock.warehouse_id == warehouse_id,
        Stock.product_id == product_id
    ).all()
    if len(rows) > 1:
        total = sum(float(r.quantity or 0) for r in rows)
        keep = rows[0]
        keep.quantity = total
        keep.updated_at = datetime.now()
        for r in rows[1:]:
            db.delete(r)
        db.flush()
        stock = keep
    elif len(rows) == 1:
        stock = rows[0]
    else:
        stock = None

    if stock:
        stock.quantity = (stock.quantity or 0) + quantity_change
        if stock.quantity < 0:
            stock.quantity = 0
        stock.updated_at = datetime.now()
        stock_id = stock.id
        quantity_after = stock.quantity
    else:
        quantity_after = quantity_change if quantity_change > 0 else 0
        stock = Stock(
            warehouse_id=warehouse_id,
            product_id=product_id,
            quantity=quantity_after
        )
        db.add(stock)
        db.flush()
        stock_id = stock.id

    movement = StockMovement(
        stock_id=stock_id,
        warehouse_id=warehouse_id,
        product_id=product_id,
        operation_type=operation_type,
        document_type=document_type,
        document_id=document_id,
        document_number=document_number,
        quantity_change=quantity_change,
        quantity_after=quantity_after,
        user_id=user_id,
        note=note
    )
    if created_at:
        movement.created_at = created_at
    db.add(movement)
    return movement


def delete_stock_movements_for_document(db: Session, document_type: str, document_id: int) -> int:
    """Hujjat tasdiqi bekor qilinganda shu hujjatga tegishli StockMovement yozuvlarini o'chiradi."""
    deleted = db.query(StockMovement).filter(
        StockMovement.document_type == document_type,
        StockMovement.document_id == document_id,
    ).delete(synchronize_session=False)
    return deleted
