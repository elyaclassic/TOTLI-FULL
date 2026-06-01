"""Partner balans — manba-hujjatlardan qayta quriladigan kesh (recompute pattern).

Kanonik formula = reports._build_partner_movements yopilish balansi.
Belgi: musbat = mijoz bizga qarzdor; manfiy = biz partnerga qarzdormiz.
"""
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import (
    Partner, Order, Payment, Purchase,
    PartnerBalanceDoc, PartnerBalanceDocItem, PurchaseReturn,
)
from app.services.currency_service import get_rate

logger = logging.getLogger(__name__)


def _payment_amount_uzs(db: Session, payment: Payment) -> float:
    """To'lov summasini so'mda qaytaradi. USD kassa bo'lsa kurs bilan aylantiradi."""
    amt = float(payment.amount or 0)
    cr = payment.cash_register
    currency = (getattr(cr, "currency", None) or "UZS") if cr else "UZS"
    if currency == "UZS":
        return amt
    on_date = payment.date.date() if payment.date else None
    rate = get_rate(db, currency, "UZS", on_date)
    if not rate or rate <= 0:
        logger.warning(
            "partner_balance: %s to'lov #%s uchun %s->UZS kurs topilmadi, xom amount ishlatildi",
            currency, getattr(payment, "id", "?"), currency,
        )
        return amt
    return amt * rate


def compute_partner_balance(db: Session, partner_id: int) -> float:
    """Partner balansini hujjatlardan qayta hisoblaydi (kanonik haqiqat).

    faqat confirmed (to'lov uchun status NULL ham), cancelled/draft chiqarib.
    """
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        return 0.0

    total = 0.0

    for o in db.query(Order).filter(
        Order.partner_id == partner_id,
        Order.type.in_(["sale", "return_sale"]),
        Order.status.notin_(["cancelled", "draft"]),
    ):
        if o.type == "sale":
            total += float(o.total or 0)
        else:
            total -= float(o.total or 0)

    for p in db.query(Payment).filter(
        Payment.partner_id == partner_id,
        or_(Payment.status == "confirmed", Payment.status.is_(None)),
    ):
        amt = _payment_amount_uzs(db, p)
        if p.type == "income":
            total -= amt
        else:
            total += amt

    for p in db.query(Purchase).filter(
        Purchase.partner_id == partner_id,
        Purchase.status == "confirmed",
    ):
        total -= float((p.total or 0) + (p.total_expenses or 0))

    for item in (
        db.query(PartnerBalanceDocItem)
        .join(PartnerBalanceDoc, PartnerBalanceDocItem.doc_id == PartnerBalanceDoc.id)
        .filter(
            PartnerBalanceDocItem.partner_id == partner_id,
            PartnerBalanceDoc.status == "confirmed",
        )
    ):
        total += float(item.balance or 0)

    for d in db.query(PurchaseReturn).filter(
        PurchaseReturn.partner_id == partner_id,
        PurchaseReturn.status == "confirmed",
    ):
        total += float(d.total or 0)

    return total
