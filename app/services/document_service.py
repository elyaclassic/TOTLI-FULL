"""
Hujjat operatsiyalari — atomik commit/rollback bilan.

Bu yerda biznes logikasi markazlashtiriladi:
- confirm_purchase_atomic() — tovar kirimini tasdiqlash
- revert_purchase_atomic() — tasdiqlashni bekor qilish

Kelajakda qo'shiladi:
- delete_document_fully() — hujjat + stock movement + payment birga o'chirish (B2)
- confirm_sale_atomic() / revert_sale_atomic() — sotuv uchun

Dizayn printsipi:
1. Har operatsiya try/except/rollback ichida
2. Biznes xatosi → DocumentError (HTTP emas — route qayta ishlaydi)
3. db.commit() faqat bitta joyda, operatsiya oxirida
4. Post-commit side-effects (notification, audit) — chaqiruvchi route hal qiladi
"""
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.database import (
    Stock, Purchase, PurchaseItem, PurchaseExpense, Product, Partner, User,
    Order, OrderItem, Payment,
)
from app.services.stock_service import create_stock_movement, delete_stock_movements_for_document
from app.utils.audit import log_action


class DocumentError(Exception):
    """Biznes logikasi xatosi (400 Bad Request analog).
    Route bu xatoni ushlab HTTPException ga aylantiradi."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def confirm_purchase_atomic(
    db: Session,
    purchase: Purchase,
    current_user: User,
    client_host: Optional[str] = None,
) -> None:
    """
    Tovar kirimini atomik tasdiqlash:
    1. Holatni tekshirish (draft bo'lishi shart)
    2. Har item uchun: o'rtacha tannarxni hisoblash, stock movement yaratish
    3. Partner balansini yangilash
    4. Status = confirmed
    5. Audit log
    6. Bitta commit (xato bo'lsa rollback)

    Biznes xatolarida DocumentError ko'taradi.
    SQL xatolarida SQLAlchemyError ko'taradi (rollback bilan).
    """
    # --- Validatsiya (transaction boshlanmasdan oldin) ---
    if purchase.status != "draft":
        raise DocumentError("Faqat qoralama holatidagi kirimlarni tasdiqlash mumkin")
    if not purchase.items:
        raise DocumentError("Tasdiqlash uchun kamida bitta mahsulot qo'shing.")

    try:
        total_expenses = purchase.total_expenses or 0
        items_total = purchase.total or 0

        for item in purchase.items:
            # Avval eski qoldiqni olish (tasdiqlashdan oldin)
            stock = db.query(Stock).filter(
                Stock.warehouse_id == purchase.warehouse_id,
                Stock.product_id == item.product_id,
            ).first()

            product = db.query(Product).filter(Product.id == item.product_id).first()
            if product:
                # Xarajatlar ulushini hisoblash
                expense_share_per_unit = 0.0
                if total_expenses > 0 and items_total > 0 and item.total and item.quantity:
                    expense_share = (item.total / items_total) * total_expenses
                    expense_share_per_unit = expense_share / item.quantity

                # Yangi narx (xarajatlar bilan)
                new_cost_per_unit = item.price + expense_share_per_unit
                new_total_cost = item.quantity * new_cost_per_unit

                # Eski qoldiq va narx
                old_quantity = stock.quantity if stock else 0.0
                old_price = product.purchase_price if product.purchase_price else 0.0

                # O'rtacha tannarxni hisoblash
                if old_quantity > 0 and old_price > 0:
                    old_total_cost = old_quantity * old_price
                    total_quantity = old_quantity + item.quantity
                    total_cost = old_total_cost + new_total_cost
                    average_cost = total_cost / total_quantity if total_quantity > 0 else new_cost_per_unit
                else:
                    average_cost = new_cost_per_unit

                # Mahsulotning o'rtacha tannarxini yangilash
                product.purchase_price = average_cost

            # Qoldiqni yangilash — create_stock_movement o'zi stock.quantity ni
            # o'zgartiradi (double-count bo'lmasin)
            create_stock_movement(
                db=db,
                warehouse_id=purchase.warehouse_id,
                product_id=item.product_id,
                quantity_change=+item.quantity,
                operation_type="purchase",
                document_type="Purchase",
                document_id=purchase.id,
                document_number=purchase.number,
                user_id=current_user.id if current_user else None,
                note=f"Xarid kirim: {purchase.number}",
                created_at=purchase.date,
            )

        # --- Status o'zgartirish ---
        purchase.status = "confirmed"

        # --- Partner balansini yangilash ---
        total_with_expenses = items_total + total_expenses
        if purchase.partner_id:
            partner = db.query(Partner).filter(Partner.id == purchase.partner_id).first()
            if partner:
                partner.balance -= total_with_expenses

        # --- Audit log ---
        log_action(
            db,
            user=current_user,
            action="confirm",
            entity_type="purchase",
            entity_id=purchase.id,
            entity_number=purchase.number,
            details=f"Summa: {total_with_expenses:,.0f}",
            ip_address=client_host or "",
        )

        # --- Yagona commit ---
        db.commit()

    except DocumentError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def delete_sale_fully(
    db: Session,
    order: Order,
) -> dict:
    """
    Sotuvni atomik o'chirish (Order, type='sale'):
    1. Holat tekshirish (draft → soft cancel; cancelled/waiting → hard delete)
    2. Hard delete'da: to'lov bog'langan bo'lsa REJECT qilinadi (orphan oldini olish)
    3. OrderItem, StockMovement, Order — bir vaqtda o'chiriladi
    4. Atomik commit

    Qaytadi: {"mode": "soft_cancelled" | "hard_deleted"}

    Bu funksiya K4 (orphan payment) bug'ini tuzatadi:
    - Oldin: sales.py:765 Payment.order_id → None (silent orphan)
    - Oldin: stock_movements hech qachon o'chirilmasdi (silent orphan)
    - Endi: to'lov bor bo'lsa error, yo'q bo'lsa barchasi bir paketda o'chadi
    """
    if order.status not in ("draft", "cancelled", "waiting_production"):
        raise DocumentError(
            "Faqat qoralama yoki bekor qilingan sotuvni o'chirish mumkin. Avval tasdiqni bekor qiling."
        )

    if order.status == "draft":
        # Soft cancel — faqat status o'zgaradi, hech narsa o'chmaydi
        try:
            order.status = "cancelled"
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {"mode": "soft_cancelled", "payments_deleted": 0, "movements_deleted": 0}

    # --- Hard delete yo'li ---
    # Oldin to'lovlar borligini tekshirish (orphan oldini olish)
    payment_count = (
        db.query(Payment).filter(Payment.order_id == order.id).count()
    )
    if payment_count > 0:
        raise DocumentError(
            f"Bu sotuv {payment_count} ta to'lov bilan bog'langan. "
            "Avval Moliya sahifasidan to'lovlarni o'chiring, so'ngra sotuvni o'chiring."
        )

    try:
        # 1. OrderItem'larni o'chirish
        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete(synchronize_session=False)

        # 2. StockMovement'larni o'chirish (oldin bu qadam tushirib qoldirilgan edi)
        movements_deleted = delete_stock_movements_for_document(db, "Order", order.id)

        # 3. Order'ning o'zini o'chirish
        db.query(Order).filter(Order.id == order.id).delete(synchronize_session=False)

        db.commit()
        return {
            "mode": "hard_deleted",
            "payments_deleted": 0,
            "movements_deleted": movements_deleted,
        }
    except Exception:
        db.rollback()
        raise


def delete_purchase_fully(
    db: Session,
    purchase: Purchase,
) -> dict:
    """
    Tovar kirimini atomik o'chirish (hard delete).

    Faqat 'draft' holatdagi purchase o'chirilishi mumkin. 'confirmed' bo'lsa —
    avval revert_purchase_atomic() chaqirilishi shart.

    Bolalar: PurchaseExpense va PurchaseItem. Purchase modelida cascade yo'q va
    SQLite'da FK=OFF — shuning uchun explicit o'chirish kerak, aks holda
    silent orphan yozuvlar qoladi.

    Atomik: barchasi bitta transaction, xato bo'lsa rollback.
    """
    if purchase.status != "draft":
        raise DocumentError(
            "Faqat qoralama holatidagi kirimni o'chirish mumkin. Avval tasdiqni bekor qiling."
        )

    try:
        # 1. PurchaseExpense'larni o'chirish
        db.query(PurchaseExpense).filter(
            PurchaseExpense.purchase_id == purchase.id
        ).delete(synchronize_session=False)

        # 2. PurchaseItem'larni o'chirish
        db.query(PurchaseItem).filter(
            PurchaseItem.purchase_id == purchase.id
        ).delete(synchronize_session=False)

        # 3. Purchase'ni o'chirish
        db.query(Purchase).filter(Purchase.id == purchase.id).delete(synchronize_session=False)

        db.commit()
        return {"mode": "hard_deleted", "items_deleted": True, "expenses_deleted": True}
    except Exception:
        db.rollback()
        raise


def revert_purchase_atomic(
    db: Session,
    purchase: Purchase,
    current_user: User,
) -> None:
    """
    Tovar kirimining tasdiqlashni atomik bekor qilish:
    1. Holatni tekshirish (confirmed bo'lishi shart)
    2. Qoldiq yetarliligini tekshirish (barcha itemlar)
    3. Har item uchun: -quantity movement yaratish
    4. Partner balansini qaytarish
    5. Status = draft
    6. Bitta commit

    Biznes xatolarida DocumentError ko'taradi.
    """
    if purchase.status != "confirmed":
        raise DocumentError("Faqat tasdiqlangan kirimning tasdiqini bekor qilish mumkin.")

    # --- Avval qoldiq yetarliligini tekshirish (barcha itemlar uchun) ---
    for item in purchase.items:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == purchase.warehouse_id,
            Stock.product_id == item.product_id,
        ).first()
        if not stock:
            raise DocumentError("Ombor qoldig'i topilmadi.")
        if (stock.quantity or 0) < item.quantity:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            name = prod.name if prod else f"#{item.product_id}"
            raise DocumentError(f"Ombor qoldig'i yetarli emas: {name}")

    try:
        # --- Stock movement orqali qaytarish ---
        for item in purchase.items:
            create_stock_movement(
                db=db,
                warehouse_id=purchase.warehouse_id,
                product_id=item.product_id,
                quantity_change=-item.quantity,
                operation_type="purchase_revert",
                document_type="Purchase",
                document_id=purchase.id,
                document_number=f"{purchase.number}-REVERT",
                user_id=current_user.id if current_user else None,
                created_at=purchase.date,
                note=f"Xarid bekor: {purchase.number}",
            )

        # --- Partner balansini qaytarish ---
        total_with_expenses = purchase.total + (purchase.total_expenses or 0)
        if purchase.partner_id:
            partner = db.query(Partner).filter(Partner.id == purchase.partner_id).first()
            if partner:
                partner.balance += total_with_expenses

        # --- Status ---
        purchase.status = "draft"

        # --- Yagona commit ---
        db.commit()

    except Exception:
        db.rollback()
        raise
