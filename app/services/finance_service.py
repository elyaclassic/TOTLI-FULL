"""
Finance service — kassa va to'lov operatsiyalari uchun yordamchi funksiyalar.

Tier C3: finance.py dagi _sync_cash_balance va cash_transfer logikasini markazlashtirish.
payment_service.py ham shu moduldan import qiladi (route'dan emas).
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models.database import CashRegister, CashTransfer, Payment
from app.services.document_service import DocumentError


def cash_balance_formula(db: Session, cash_id: int) -> tuple:
    """Kassa balansini formuladan hisoblash: opening + income - expense."""
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return (0.0, 0.0, 0.0)
    opening = float(getattr(cash, "opening_balance", None) or 0)
    confirmed = or_(Payment.status == "confirmed", Payment.status == None)
    income_sum = float(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.cash_register_id == cash_id, Payment.type == "income", confirmed)
        .scalar()
    ) or 0
    expense_sum = float(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.cash_register_id == cash_id, Payment.type == "expense", confirmed)
        .scalar()
    ) or 0
    return (opening + income_sum - expense_sum, income_sum, expense_sum)


def sync_cash_balance(db: Session, cash_id: int) -> None:
    """Kassa balansini qayta hisoblash va saqlash."""
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return
    computed, _, _ = cash_balance_formula(db, cash_id)
    cash.balance = computed


def delete_cash_transfer_atomic(db: Session, transfer: CashTransfer) -> dict:
    """
    Kassa o'tkazmasi hujjatini atomik o'chirish.

    Faqat pending/draft statusdagi hujjatlar o'chiriladi.
    """
    if transfer.status not in ("pending", "draft"):
        raise DocumentError("Faqat kutilayotgan hujjatni o'chirish mumkin.")
    try:
        db.delete(transfer)
        db.commit()
        return {"ok": True}
    except Exception:
        db.rollback()
        raise


def revert_cash_transfer_atomic(db: Session, transfer: CashTransfer) -> dict:
    """
    Kassa o'tkazmasi tasdiqini atomik bekor qilish.

    completed → in_transit: qabul kassasidan qaytarish
    in_transit → pending: jo'natuvchi kassaga qaytarish
    """
    amount = transfer.amount or 0

    try:
        if transfer.status == "completed":
            to_cash = db.query(CashRegister).filter(CashRegister.id == transfer.to_cash_id).first()
            if to_cash:
                to_cash.balance = (to_cash.balance or 0) - amount
            transfer.status = "in_transit"
            transfer.approved_by_user_id = None
            transfer.approved_at = None
        elif transfer.status == "in_transit":
            from_cash = db.query(CashRegister).filter(CashRegister.id == transfer.from_cash_id).first()
            if from_cash:
                from_cash.balance = (from_cash.balance or 0) + amount
            transfer.status = "pending"
            transfer.sent_by_user_id = None
            transfer.sent_at = None
        else:
            raise DocumentError("Bu statusda bekor qilib bo'lmaydi.")

        db.commit()
        return {"ok": True, "status": transfer.status}
    except DocumentError:
        raise
    except Exception:
        db.rollback()
        raise
