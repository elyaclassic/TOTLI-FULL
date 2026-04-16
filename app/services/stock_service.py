"""Ombor harakati (StockMovement) yaratish va o'chirish."""
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.database import Stock, StockMovement

# Float noise chegarasi — shu qiymatdan kichik absolute qiymatlar 0 ga tushadi
_STOCK_EPSILON = 1e-6


def clamp_stock_qty(value) -> float:
    """Float arifmetikasi residuini 0 ga yaxlitlash, manfiyni 0 ga clamp.
    Misol: -1.4e-14 → 0, -0.5 → 0, 3.14159 → 3.14159.
    ESLATMA: Yangi kod epsilon_clean_qty dan foydalanishi kerak — bu funksiya
    faqat legacy chaqiruvlar uchun qoldirilgan."""
    v = float(value or 0)
    if v < 0:
        return 0.0
    if abs(v) < _STOCK_EPSILON:
        return 0.0
    return v


def epsilon_clean_qty(value) -> float:
    """Float noise tozalash — manfiy qiymatlarni saqlaydi.
    -1.4e-14 → 0, 3.14e-10 → 0, -0.5 → -0.5, 3.14 → 3.14"""
    v = float(value or 0)
    if abs(v) < _STOCK_EPSILON:
        return 0.0
    return v


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
    Bitta (warehouse, product) uchun bir nechta Stock row bo'lsa — birlashtiradi
    va eski rowlar bilan bog'liq StockMovement larni yangi row.id ga ko'chiradi."""
    rows = db.query(Stock).filter(
        Stock.warehouse_id == warehouse_id,
        Stock.product_id == product_id
    ).all()
    if len(rows) > 1:
        total = sum(float(r.quantity or 0) for r in rows)
        keep = rows[0]
        keep.quantity = total
        keep.updated_at = datetime.now()
        old_ids = [r.id for r in rows[1:]]
        # Eski rowlarga bog'liq movementlarni keep ga ko'chirish (orphan oldini olish)
        if old_ids:
            db.query(StockMovement).filter(StockMovement.stock_id.in_(old_ids)).update(
                {StockMovement.stock_id: keep.id}, synchronize_session=False
            )
        for r in rows[1:]:
            db.delete(r)
        db.flush()
        stock = keep
    elif len(rows) == 1:
        stock = rows[0]
    else:
        stock = None

    if stock:
        new_qty = (stock.quantity or 0) + quantity_change
        # Manfiy bo'lsa loglash (audit trail uchun), lekin clamp QILINMAYDI —
        # manfiy qoldiq ma'lumot buzilishini yashirmasligi va revert+reconfirm
        # oqimi to'g'ri ishlashi uchun saqlanadi.
        if new_qty < -0.001:
            try:
                print(f"[Stock NEGATIVE] wh={warehouse_id} prod={product_id} "
                      f"hozir={stock.quantity} change={quantity_change} -> {new_qty} "
                      f"({operation_type}/{document_number})", flush=True)
            except Exception:
                pass
        new_qty = epsilon_clean_qty(new_qty)
        stock.quantity = new_qty
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


def apply_sale_stock_deduction(db: Session, order, current_user, note_prefix: str = "Sotuv") -> None:
    """Order itemlari uchun "sale" StockMovementlarini yaratadi (stock chiqim).
    sales.py va delivery_routes.py:supervisor_confirm_agent_order o'rtasidagi DRY uchun.

    Eslatma: caller bu funksiyani chaqirgunga qadar ombor yetishmovchiligini tekshirgan
    bo'lishi kerak — bu funksiya faqat movement yaratadi, validation qilmaydi."""
    from datetime import datetime as _dt
    valid_items = [it for it in order.items if it.product_id and (it.quantity or 0) > 0]
    for it in valid_items:
        wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
        if not wh_id:
            continue
        create_stock_movement(
            db=db,
            warehouse_id=wh_id,
            product_id=it.product_id,
            quantity_change=-float(it.quantity or 0),
            operation_type="sale",
            document_type="Sale",
            document_id=order.id,
            document_number=order.number,
            user_id=current_user.id if current_user else None,
            note=f"{note_prefix}: {order.number}",
            created_at=order.date or _dt.now(),
        )
