from datetime import date as _date

from sqlalchemy import func as sa_func

from app.models.database import Order, Partner, Payment
from app.bot.customer_bot.phone import normalize_phone

_STATUS_LABELS = {
    "draft": "Qoralama",
    "confirmed": "Qabul qilindi",
    "waiting_production": "Ishlab chiqarishda",
    "out_for_delivery": "Yo'lda",
    "delivered": "Yetkazildi",
    "completed": "Yetkazildi",
    "cancelled": "Bekor qilindi",
}


def fmt_money(amount):
    return f"{int(round(amount or 0)):,}".replace(",", " ")


def balance_text(partner, own=True):
    bal = partner.balance or 0
    if bal > 0:
        word = "Qarzingiz" if own else "Qarzi"
        return f"💰 {word}: <b>{fmt_money(bal)}</b> so'm"
    if bal < 0:
        word = "Avans qoldig'ingiz" if own else "Avans qoldig'i"
        return f"💰 {word}: <b>{fmt_money(-bal)}</b> so'm"
    return "✅ Qarzdorlik yo'q"


def order_status_label(status):
    return _STATUS_LABELS.get(status, status or "")


def recent_orders(db, partner_id, limit=10):
    return (
        db.query(Order)
        .filter(
            Order.partner_id == partner_id,
            Order.type == "sale",
            Order.status != "draft",
        )
        .order_by(Order.date.desc(), Order.id.desc())
        .limit(limit)
        .all()
    )


def statement(db, partner_id, date_from, date_to):
    """date_from/date_to — datetime.date. Tashkent local vaqt: sa_func.date ishlatamiz."""
    orders = (
        db.query(Order)
        .filter(
            Order.partner_id == partner_id,
            Order.type == "sale",
            Order.status.notin_(["draft", "cancelled"]),
            sa_func.date(Order.date) >= date_from,
            sa_func.date(Order.date) <= date_to,
        )
        .order_by(Order.date.asc())
        .all()
    )
    payments = (
        db.query(Payment)
        .filter(
            Payment.partner_id == partner_id,
            Payment.type == "income",
            Payment.status == "confirmed",
            sa_func.date(Payment.date) >= date_from,
            sa_func.date(Payment.date) <= date_to,
        )
        .order_by(Payment.date.asc())
        .all()
    )
    return {
        "orders": orders,
        "payments": payments,
        "total_orders": sum(o.total or 0 for o in orders),
        "total_paid": sum(p.amount or 0 for p in payments),
    }


def search_partners(db, query, limit=10):
    """Aktiv partnerlarni nom (case-insensitive) yoki telefon (normalized) bo'yicha qidirish."""
    q = (query or "").strip()
    if not q:
        return []
    name_matches = db.query(Partner).filter(
        Partner.is_active == True,  # noqa: E712
        Partner.name.ilike(f"%{q}%"),
    ).limit(limit).all()
    norm = normalize_phone(q)
    result = list(name_matches)
    seen = {p.id for p in result}
    if norm:
        for p in db.query(Partner).filter(Partner.is_active == True).all():  # noqa: E712
            if p.id in seen:
                continue
            if normalize_phone(p.phone) == norm or normalize_phone(p.phone2) == norm:
                result.append(p)
                seen.add(p.id)
                if len(result) >= limit:
                    break
    return result[:limit]


def parse_date_uz(text):
    """'15.05.2026' / '15.5.2026' / '2026-05-15' / '15/05/2026' -> date yoki None."""
    s = (text or "").strip()
    for sep in (".", "/", "-"):
        parts = s.split(sep)
        if len(parts) == 3:
            try:
                a, b, c = (int(x) for x in parts)
            except ValueError:
                continue
            try:
                if len(parts[0]) == 4:  # yyyy-mm-dd
                    year = a
                    result = _date(a, b, c)
                else:                   # dd.mm.yyyy
                    year = c
                    result = _date(c, b, a)
                if not (2000 <= year <= 2100):
                    return None
                return result
            except ValueError:
                return None
    return None
