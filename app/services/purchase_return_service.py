from sqlalchemy.orm import Session
from sqlalchemy import text
from app.models.database import PurchaseReturn, PurchaseReturnItem, Partner, Stock
from app.services.stock_service import create_stock_movement


class DocumentError(Exception):
    pass


def validate_return(db: Session, doc: PurchaseReturn) -> None:
    partner = db.query(Partner).filter(Partner.id == doc.partner_id).first()
    if not partner or (partner.type not in ("supplier", "both")):
        raise DocumentError("Qaytarish faqat yetkazib beruvchi uchun (mijoz emas)")
    items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == doc.id).all()
    if not items:
        raise DocumentError("Hujjatda qator yo'q")
    for it in items:
        if not it.quantity or it.quantity <= 0:
            raise DocumentError("Miqdor 0 dan katta bo'lishi kerak")
        stock = db.query(Stock).filter(
            Stock.warehouse_id == doc.warehouse_id,
            Stock.product_id == it.product_id,
        ).first()
        have = float(stock.quantity or 0) if stock else 0.0
        if have < float(it.quantity) - 1e-6:
            raise DocumentError(
                f"Omborda yetarli emas (mahsulot {it.product_id}): "
                f"{have:,.2f} mavjud, {it.quantity:,.2f} qaytarilmoqchi"
            )


def confirm_return(db: Session, doc: PurchaseReturn, current_user=None, client_host=None) -> None:
    """Atomik: stock chiqim + yetkazib beruvchi qarzini kamaytirish + audit."""
    validate_return(db, doc)  # FIRST — on failure, status stays 'draft'
    res = db.execute(
        text("UPDATE purchase_returns SET status='confirmed' WHERE id=:id AND status='draft'"),
        {"id": doc.id},
    )
    if res.rowcount == 0:
        db.rollback()
        raise DocumentError("Hujjat allaqachon tasdiqlangan yoki bekor qilingan")
    try:
        items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == doc.id).all()
        for it in items:
            create_stock_movement(
                db=db,
                warehouse_id=doc.warehouse_id,
                product_id=it.product_id,
                quantity_change=-float(it.quantity),
                operation_type="return_purchase",
                document_type="PurchaseReturn",
                document_id=doc.id,
                document_number=doc.number,
                user_id=current_user.id if current_user else None,
                note=f"Yetkazib beruvchiga qaytarish: {doc.number}",
                created_at=doc.date,
            )
        if doc.partner_id:
            partner = db.query(Partner).filter(Partner.id == doc.partner_id).first()
            if partner:
                partner.balance = (partner.balance or 0) + float(doc.total or 0)
        try:
            from app.utils.audit import log_action
            log_action(db, user=current_user, action="confirm",
                       entity_type="purchase_return", entity_id=doc.id,
                       entity_number=doc.number, details=f"Summa: {doc.total:,.0f}",
                       ip_address=client_host or "")
        except Exception:
            pass
        db.commit()
    except DocumentError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def cancel_return(db: Session, doc: PurchaseReturn, current_user=None, client_host=None) -> None:
    """Tasdiqlangan qaytarishni bekor qilish — stock va balansni tiklaydi."""
    res = db.execute(
        text("UPDATE purchase_returns SET status='cancelled' WHERE id=:id AND status='confirmed'"),
        {"id": doc.id},
    )
    if res.rowcount == 0:
        db.rollback()
        raise DocumentError("Faqat tasdiqlangan hujjatni bekor qilish mumkin")
    try:
        items = db.query(PurchaseReturnItem).filter(PurchaseReturnItem.return_id == doc.id).all()
        for it in items:
            create_stock_movement(
                db=db, warehouse_id=doc.warehouse_id, product_id=it.product_id,
                quantity_change=+float(it.quantity), operation_type="return_purchase_revert",
                document_type="PurchaseReturn", document_id=doc.id, document_number=doc.number,
                user_id=current_user.id if current_user else None,
                note=f"Qaytarish bekor qilindi: {doc.number}", created_at=doc.date,
            )
        if doc.partner_id:
            partner = db.query(Partner).filter(Partner.id == doc.partner_id).first()
            if partner:
                partner.balance = (partner.balance or 0) - float(doc.total or 0)
        db.commit()
    except Exception:
        db.rollback()
        raise
