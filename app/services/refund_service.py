"""Qaytarish refund hisoblash — original sotuvning naqd to'lovi va chegirmasiga qarab."""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import Payment


def compute_return_refund(db: Session, sale, returned_lines) -> dict:
    """returned_lines: [(product_id, qty), ...]. Qaytaradi:
    {refund_cash, return_total, refund_cash_register_id, ratio}.
    refund_cash = sotuvning NAQD to'lovi × proporsiya (chegirma avtomatik).
    return_total = sale.total × proporsiya (chegirmali).
    """
    sale_items = {it.product_id: it for it in (sale.items or [])}
    returned_value = 0.0
    for pid, qty in returned_lines:
        it = sale_items.get(pid)
        if it and float(qty or 0) > 0:
            returned_value += float(qty) * float(it.price or 0)
    subtotal = float(sale.subtotal or 0) or float(sale.total or 0)
    ratio = (returned_value / subtotal) if subtotal > 0 else 0.0
    if ratio > 1.0:
        ratio = 1.0
    cash_pays = db.query(Payment).filter(
        Payment.order_id == sale.id,
        Payment.type == "income",
        Payment.payment_type.in_(["cash", "naqd"]),
        or_(Payment.status == "confirmed", Payment.status.is_(None)),
    ).all()
    cash_paid = sum(float(p.amount or 0) for p in cash_pays)
    refund_cash = round(cash_paid * ratio, 2)
    return_total = round(float(sale.total or 0) * ratio, 2)
    refund_cash_register_id = None
    if cash_pays:
        refund_cash_register_id = max(cash_pays, key=lambda p: float(p.amount or 0)).cash_register_id
    return {
        "refund_cash": refund_cash,
        "return_total": return_total,
        "refund_cash_register_id": refund_cash_register_id,
        "ratio": ratio,
    }
