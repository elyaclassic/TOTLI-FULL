"""
Payment service — to'lov operatsiyalari uchun atomik wrapper'lar.

Tier C3 minimal: Tier B audit (X6) topilmasiga javoban.
Hozirgi holda finance_payment_delete inline ishlatadi, bu service
kelajakda ko'proq payment operatsiyalari uchun ishlatiladi.
"""
from sqlalchemy.orm import Session

from app.models.database import Payment, CashRegister
from app.services.document_service import DocumentError


def delete_payment_atomic(db: Session, payment: Payment) -> dict:
    """
    To'lovni atomik o'chirish va kassa balansini qayta hisoblash.

    1. Faqat cancelled statusdagi to'lovlar o'chiriladi (confirmed rad etiladi)
    2. Kassa balansi _sync_cash_balance orqali yangilanadi
    3. Atomik: xato bo'lsa rollback

    Bizness xatolarida DocumentError ko'taradi.
    """
    if getattr(payment, "status", "confirmed") == "confirmed":
        raise DocumentError(
            "Tasdiqlangan to'lovni o'chirish mumkin emas. Avval tasdiqni bekor qiling."
        )

    cash_id = payment.cash_register_id
    try:
        db.delete(payment)
        db.flush()
        # Kassa balansini qayta hisoblash
        if cash_id:
            from app.routes.finance import _sync_cash_balance
            _sync_cash_balance(db, cash_id)
        db.commit()
        return {"ok": True, "cash_register_id": cash_id}
    except Exception:
        db.rollback()
        raise


def cancel_payment_atomic(db: Session, payment: Payment) -> dict:
    """
    To'lovni atomik bekor qilish (status='cancelled').

    O'chirmaydi — audit trail saqlanadi. Kassa balansi avtomatik yangilanadi
    chunki _cash_balance_formula() faqat confirmed to'lovlarni hisoblaydi.
    """
    cash_id = payment.cash_register_id
    try:
        payment.status = "cancelled"
        db.flush()
        if cash_id:
            from app.routes.finance import _sync_cash_balance
            _sync_cash_balance(db, cash_id)
        db.commit()
        return {"ok": True, "status": "cancelled", "cash_register_id": cash_id}
    except Exception:
        db.rollback()
        raise
