"""
Finance service — kassa va to'lov operatsiyalari uchun yordamchi funksiyalar.

Tier C3: finance.py dagi _sync_cash_balance va cash_transfer logikasini markazlashtirish.
payment_service.py ham shu moduldan import qiladi (route'dan emas).
"""
from sqlalchemy.orm import Session
from sqlalchemy import or_, func

from app.models.database import CashRegister, CashTransfer, Payment
from app.services.document_service import DocumentError


def cash_balance_formula(db: Session, cash_id: int, as_of_date=None) -> tuple:
    """Kassa balansini formuladan hisoblash: opening + income - expense + transfers_in - transfers_out.

    as_of_date — agar berilsa, shu sana oxirigacha (23:59:59) bo'lgan operatsiyalarni hisoblaydi.
    None bo'lsa — joriy balans.
    """
    from datetime import datetime, time, timedelta
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return (0.0, 0.0, 0.0)
    opening = float(getattr(cash, "opening_balance", None) or 0)
    confirmed = or_(Payment.status == "confirmed", Payment.status.is_(None))

    cutoff = None
    if as_of_date is not None:
        if hasattr(as_of_date, "date"):
            cutoff = datetime.combine(as_of_date.date(), time.max)
        else:
            cutoff = datetime.combine(as_of_date, time.max)

    income_q = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.cash_register_id == cash_id, Payment.type == "income", confirmed
    )
    expense_q = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.cash_register_id == cash_id, Payment.type == "expense", confirmed
    )
    transfer_out_q = db.query(func.coalesce(func.sum(CashTransfer.amount), 0)).filter(
        CashTransfer.from_cash_id == cash_id, CashTransfer.status.in_(("in_transit", "completed"))
    )
    transfer_in_q = db.query(func.coalesce(func.sum(CashTransfer.amount), 0)).filter(
        CashTransfer.to_cash_id == cash_id, CashTransfer.status == "completed"
    )
    if cutoff is not None:
        income_q = income_q.filter(Payment.date <= cutoff)
        expense_q = expense_q.filter(Payment.date <= cutoff)
        transfer_out_q = transfer_out_q.filter(CashTransfer.date <= cutoff)
        transfer_in_q = transfer_in_q.filter(CashTransfer.date <= cutoff)

    income_sum = float(income_q.scalar()) or 0
    expense_sum = float(expense_q.scalar()) or 0
    transfer_out = float(transfer_out_q.scalar()) or 0
    transfer_in = float(transfer_in_q.scalar()) or 0
    return (opening + income_sum - expense_sum + transfer_in - transfer_out, income_sum, expense_sum)


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
            transfer.status = "in_transit"
            transfer.approved_by_user_id = None
            transfer.approved_at = None
            db.flush()
            sync_cash_balance(db, transfer.to_cash_id)
        elif transfer.status == "in_transit":
            transfer.status = "pending"
            transfer.sent_by_user_id = None
            transfer.sent_at = None
            db.flush()
            sync_cash_balance(db, transfer.from_cash_id)
        else:
            raise DocumentError("Bu statusda bekor qilib bo'lmaydi.")

        db.commit()
        return {"ok": True, "status": transfer.status}
    except DocumentError:
        raise
    except Exception:
        db.rollback()
        raise
