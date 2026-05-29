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
