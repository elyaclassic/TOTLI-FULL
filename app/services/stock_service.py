"""Ombor harakati (StockMovement) yaratish va o'chirish."""
from datetime import datetime
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import AuditLog, Stock, StockMovement


class NegativeStockError(Exception):
    """Sale/Production movement stock'ni manfiy qildi — operatsiya bekor."""

    def __init__(self, warehouse_id, product_id, current_qty, change, new_qty):
        self.warehouse_id = warehouse_id
        self.product_id = product_id
        self.current_qty = current_qty
        self.change = change
        self.new_qty = new_qty
        super().__init__(
            f"Stock manfiy bo'lardi: wh={warehouse_id} prod={product_id} "
            f"{current_qty} + {change} = {new_qty}"
        )


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
    strict_negative: bool = False,
):
    """Har bir operatsiya uchun StockMovement yozuvini yaratish.
    Bitta (warehouse, product) uchun bir nechta Stock row bo'lsa — birlashtiradi
    va eski rowlar bilan bog'liq StockMovement larni yangi row.id ga ko'chiradi.

    strict_negative=True bo'lsa: agar movement stock.quantity'ni manfiy qilsa
    NegativeStockError raise qilinadi (sale, production_consumption uchun).
    Default False — revert/adjustment/initial_balance uchun manfiy ruxsat etiladi.
    """
    # Donalik mahsulotda kasrli quantity_change ni round qilish (validator)
    try:
        from app.models.database import Product, Unit
        prod_unit = db.query(Unit.code).join(Product, Product.unit_id == Unit.id).filter(Product.id == product_id).scalar()
        if prod_unit == "ta" and abs(quantity_change - round(quantity_change)) > 0.001:
            try:
                print(f"[Stock VALIDATOR] dona-mahsulotda kasr round qilindi: "
                      f"prod={product_id} chg={quantity_change} -> {round(quantity_change)} "
                      f"({operation_type}/{document_number})", flush=True)
            except Exception:
                pass
            quantity_change = float(round(quantity_change))
    except Exception:
        pass

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
        # D5 audit fix: strict_negative=True bo'lsa va stock manfiy bo'lardi → REJECT
        # (sale, production_consumption uchun ishlatiladi)
        if strict_negative and new_qty < -_STOCK_EPSILON:
            raise NegativeStockError(
                warehouse_id, product_id,
                float(stock.quantity or 0), float(quantity_change), new_qty,
            )
        # Manfiy bo'lsa loglash (audit trail uchun), revert/adjustment ruxsat
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


def apply_return_stock_addition(db: Session, order, current_user, note_prefix: str = "Qaytarish",
                                user_id: int = None) -> None:
    """Return order itemlari uchun "return_sale" StockMovementlarini yaratadi (stock kirim).

    Vozvrat omborga (yoki order.warehouse_id ga) qaytgan tovar kiradi. Stock check
    kerak emas — bu kirim hujjati.

    user_id: agar berilsa, current_user.id o'rniga shu ishlatiladi (haydovchi
    kontekstida current_user yo'q — Driver.employee_id beriladi)."""
    from datetime import datetime as _dt
    if user_id is None and current_user is not None:
        user_id = current_user.id
    valid_items = [it for it in order.items if it.product_id and (it.quantity or 0) > 0]
    for it in valid_items:
        wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
        if not wh_id:
            continue
        create_stock_movement(
            db=db,
            warehouse_id=wh_id,
            product_id=it.product_id,
            quantity_change=+float(it.quantity or 0),
            operation_type="return_sale",
            document_type="Sale",
            document_id=order.id,
            document_number=order.number,
            user_id=user_id,
            note=f"{note_prefix}: {order.number}",
            created_at=order.date or _dt.now(),
        )


def compute_missing_items(db: Session, order) -> list:
    """Order itemlari uchun ombordagi yetishmaydigan miqdorni hisoblaydi.

    Foydalanuvchi waiting_production status sababini bilishi uchun ishlatiladi.

    Qaytaradi: [{product, product_id, need, have, missing, warehouse_id}, ...]
    """
    from app.models.database import Stock
    missing = []
    for it in (order.items or []):
        if not it.product_id or not (it.quantity or 0) > 0:
            continue
        wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
        if not wh_id:
            continue
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id, Stock.product_id == it.product_id
        ).first()
        have = float(stock.quantity or 0) if stock else 0.0
        need = float(it.quantity or 0)
        gap = need - have
        if gap > 0.01:
            pname = it.product.name if it.product else f"#{it.product_id}"
            missing.append({
                "product": pname,
                "product_id": it.product_id,
                "need": need,
                "have": have,
                "missing": gap,
                "warehouse_id": wh_id,
            })
    return missing


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
            strict_negative=True,  # D5 audit fix: sale stock'ni manfiy qilolmaydi
        )


def compute_stock_quantity(db: Session, warehouse_id: int, product_id: int) -> float:
    """Kanonik qoldiq = shu (wh, product) uchun barcha movement quantity_change yig'indisi."""
    return float(
        db.query(func.coalesce(func.sum(StockMovement.quantity_change), 0.0))
        .filter(
            StockMovement.warehouse_id == warehouse_id,
            StockMovement.product_id == product_id,
        )
        .scalar() or 0.0
    )


def _stock_movement_count(db: Session, warehouse_id: int, product_id: int) -> int:
    return db.query(StockMovement).filter(
        StockMovement.warehouse_id == warehouse_id,
        StockMovement.product_id == product_id,
    ).count()


def reconcile_stock(db: Session, warehouse_id: int, product_id: int, *,
                    reason: str, actor: str = None) -> tuple:
    """stocks.quantity = compute_stock_quantity (kanonik). Dublikat row'larni 1 ga
    birlashtiradi. move_count=0 (faqat initial) bo'lsa TEGMAYDI. commit qilmaydi.
    Qaytaradi: (old, new).
    """
    rows = db.query(Stock).filter(
        Stock.warehouse_id == warehouse_id,
        Stock.product_id == product_id,
    ).all()
    if len(rows) > 1:
        total = sum(float(r.quantity or 0) for r in rows)
        keep = rows[0]; keep.quantity = total
        old_ids = [r.id for r in rows[1:]]
        if old_ids:
            db.query(StockMovement).filter(StockMovement.stock_id.in_(old_ids)).update(
                {StockMovement.stock_id: keep.id}, synchronize_session=False)
        for r in rows[1:]:
            db.delete(r)
        db.flush()
        stock = keep
    elif len(rows) == 1:
        stock = rows[0]
    else:
        stock = None

    old = float(stock.quantity or 0) if stock else 0.0

    if _stock_movement_count(db, warehouse_id, product_id) == 0:
        return (old, old)

    new = compute_stock_quantity(db, warehouse_id, product_id)
    if stock is None:
        stock = Stock(warehouse_id=warehouse_id, product_id=product_id, quantity=new)
        db.add(stock); db.flush()
    else:
        stock.quantity = new
    db.add(AuditLog(
        user_name=actor or "system",
        action="reconcile",
        entity_type="stock",
        entity_id=product_id,
        entity_number=f"wh{warehouse_id}/p{product_id}",
        details=f"reason={reason}; {old:.3f} -> {new:.3f}; delta={new - old:+.3f}",
    ))
    return (old, new)
