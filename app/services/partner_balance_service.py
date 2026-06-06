"""Partner balans — manba-hujjatlardan qayta quriladigan kesh (recompute pattern).

Kanonik formula = reports._build_partner_movements yopilish balansi.
Belgi: musbat = mijoz bizga qarzdor; manfiy = biz partnerga qarzdormiz.
"""
import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.database import (
    AuditLog, Partner, Order, Payment, Purchase,
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
        # H4: sana kursi yo'q — eng yaqin (eng erta) mavjud kursga fallback.
        # XOM summani SO'M deb OLMAYMIZ ($100 -> 100 so'm bug edi).
        from app.models.database import ExchangeRate
        er = (
            db.query(ExchangeRate)
            .filter(ExchangeRate.from_currency == currency, ExchangeRate.to_currency == "UZS")
            .order_by(ExchangeRate.effective_date.asc(), ExchangeRate.id.asc())
            .first()
        )
        rate = float(er.rate or 0) if er else 0.0
    if not rate or rate <= 0:
        # Hech qanday kurs yo'q — to'lovni 0 deb olamiz (xom summa EMAS) + baland log.
        logger.error(
            "partner_balance: %s to'lov #%s uchun %s->UZS kurs UMUMAN yo'q — 0 deb olindi (KURS KIRITING!)",
            currency, getattr(payment, "id", "?"), currency,
        )
        return 0.0
    return amt * rate


def compute_partner_balance(db: Session, partner_id: int) -> float:
    """Partner balansini hujjatlardan qayta hisoblaydi (kanonik haqiqat).

    faqat confirmed (to'lov uchun status NULL ham), cancelled/draft chiqarib.
    """
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        return 0.0

    total = 0.0

    # Agent buyurtmalarida mijoz qarzi YETKAZISHDA yoziladi (delivery_routes.py oqimi:
    # confirm -> dispatch -> driver "Yetkazdim"). Shu sababli confirmed/out_for_delivery
    # holatdagi agent orderlar HALI qarz emas — faqat delivered/completed sanaladi.
    # Oddiy (POS/web) sotuvlar gating'siz: ular completed/delivered holatda yoziladi.
    AGENT_DEBT_STATUSES = ("delivered", "completed")
    # populate_existing(): raw SQL `UPDATE orders SET status=...` (driver "Yetkazdim",
    # POS confirm) ORM identity-map'ni yangilamaydi → stale status bilan order hisobga
    # olinmay qolardi (manfiy drift). populate_existing query natijasini DB'dan fresh
    # o'qib identity-map obyektlarini yangilaydi. Chaqiruvchilar recompute'dan oldin
    # flush qiladi, shuning uchun yo'qoladigan o'zgarish yo'q.
    for o in db.query(Order).populate_existing().filter(
        Order.partner_id == partner_id,
        Order.type.in_(["sale", "return_sale"]),
        Order.status.notin_(["cancelled", "draft"]),
    ):
        if (o.source == "agent") and (o.status not in AGENT_DEBT_STATUSES):
            continue
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


def recompute_partner_balance(db: Session, partner_id: int, *, reason: str,
                              ref: str = None, actor: str = None) -> tuple:
    """Partner balansini qayta hisoblab set qiladi + audit log yozadi.

    db.commit() CHAQIRMAYDI — chaqiruvchining tranzaksiyasiga qo'shiladi (atomik).
    Qaytaradi: (old_balance, new_balance).
    """
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        return (0.0, 0.0)
    old = float(partner.balance or 0)
    new = compute_partner_balance(db, partner_id)
    partner.balance = new
    db.add(AuditLog(
        user_name=actor or "system",
        action="recompute",
        entity_type="partner_balance",
        entity_id=partner_id,
        entity_number=ref,
        details=f"reason={reason}; {old:.2f} -> {new:.2f}; delta={new - old:+.2f}",
    ))
    return (old, new)
