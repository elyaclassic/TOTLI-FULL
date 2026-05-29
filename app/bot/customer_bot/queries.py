from sqlalchemy import func as sa_func

from app.models.database import Order, OrderItem, Payment, Partner

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


def balance_text(partner):
    bal = partner.balance or 0
    if bal > 0:
        return f"Qarzingiz: <b>{fmt_money(bal)}</b> so'm"
    if bal < 0:
        return f"Avans qoldig'ingiz: <b>{fmt_money(-bal)}</b> so'm"
    return "Qarzdorlik yo'q"


def order_status_label(status):
    return _STATUS_LABELS.get(status, status or "")


def recent_orders(db, partner_id, limit=10):
    return (
        db.query(Order)
        .filter(Order.partner_id == partner_id, Order.type == "sale")
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
