"""waiting_production buyurtmalar tomonidan band qilingan stock.

Band hech qayerda SAQLANMAYDI — har safar waiting_production statusdagi
buyurtmalardan hisoblanadi. Buyurtma statusi o'zgarsa band avtomatik
yo'qoladi → drift mumkin emas.
"""
from sqlalchemy import func, or_, and_

from app.models.database import Order, OrderItem, Stock

# Band ustidan o'tish (reservation override) qila oladigan rollar — MARKAZLASHTIRILGAN.
# Helper (reservation_override) VA template'lar (app/core.py Jinja global `user_can_override`)
# shu yagona ro'yxatdan foydalanadi — rol o'zgarsa faqat shu yerni yangilang.
OVERRIDE_ROLES = ("admin", "manager", "menejer", "rahbar", "raxbar")


def user_can_override(current_user) -> bool:
    """Foydalanuvchi reservation override qila oladimi (faqat rol bo'yicha; force'siz).
    Template'larda Jinja global sifatida ishlatiladi."""
    role = getattr(current_user, "role", None) if current_user else None
    return role in OVERRIDE_ROLES


def get_reserved_quantity(db, warehouse_id, product_id, before_order=None) -> float:
    """waiting_production buyurtmalar band qilgan miqdor (wh+pid bo'yicha).

    before_order berilsa — faqat o'sha buyurtmadan ESKI waiting buyurtmalar
    hisoblanadi (FIFO seniority). O'zini hisobga olmaydi.
    """
    q = (
        db.query(func.coalesce(func.sum(OrderItem.quantity), 0.0))
        .join(Order, Order.id == OrderItem.order_id)
        .filter(
            Order.status == "waiting_production",
            Order.type == "sale",
            OrderItem.product_id == product_id,
            func.coalesce(OrderItem.warehouse_id, Order.warehouse_id) == warehouse_id,
        )
    )
    if before_order is not None:
        q = q.filter(
            Order.id != before_order.id,
            or_(
                Order.date < before_order.date,
                and_(Order.date == before_order.date, Order.id < before_order.id),
            ),
        )
    return float(q.scalar() or 0.0)


def get_available_stock(db, warehouse_id, product_id, before_order=None) -> float:
    """Iste'mol uchun mavjud = jismoniy qoldiq - band (seniority bo'yicha)."""
    physical = (
        db.query(func.coalesce(func.sum(Stock.quantity), 0.0))
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == product_id)
        .scalar()
    )
    reserved = get_reserved_quantity(db, warehouse_id, product_id, before_order)
    return float(physical or 0.0) - reserved


def get_available_stock_at_date(db, warehouse_id, product_id, cutoff=None) -> float:
    """Berilgan sanadagi (cutoff) mavjud stock − band. cutoff=None → joriy qoldiq.

    Transfer (vaqt-aware) darvozalari uchun: get_stock_at_date sanagacha qoldiqni
    beradi, undan joriy band (waiting_production) ayriladi.
    """
    from app.utils.stock_at_date import get_stock_at_date
    physical = get_stock_at_date(db, warehouse_id, product_id, cutoff=cutoff)
    return float(physical or 0.0) - get_reserved_quantity(db, warehouse_id, product_id)


def get_all_reservations(db) -> dict:
    """Barcha waiting_production band miqdorlari: {(warehouse_id, product_id): qty}.
    Bitta guruhlangan query (per-qator alohida query o'rniga)."""
    wh_expr = func.coalesce(OrderItem.warehouse_id, Order.warehouse_id)
    rows = (
        db.query(
            wh_expr.label("wh"),
            OrderItem.product_id.label("pid"),
            func.coalesce(func.sum(OrderItem.quantity), 0.0).label("qty"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .filter(Order.status == "waiting_production", Order.type == "sale")
        .group_by(wh_expr, OrderItem.product_id)
        .all()
    )
    return {(r.wh, r.pid): float(r.qty or 0) for r in rows}


def get_reserving_orders(db, warehouse_id, product_id):
    """waiting_production (type=sale) buyurtmalar shu (warehouse, product) ni band qilgan.

    Qaytaradi: [(Order, reserved_qty), ...] — sana bo'yicha (FIFO seniority).
    Override dialogi va bounce-signal uchun: KIM bandni egallaганини aniqlaydi.
    """
    rows = (
        db.query(Order, OrderItem.quantity)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(
            Order.status == "waiting_production",
            Order.type == "sale",
            OrderItem.product_id == product_id,
            func.coalesce(OrderItem.warehouse_id, Order.warehouse_id) == warehouse_id,
        )
        .order_by(Order.date, Order.id)
        .all()
    )
    return [(o, float(q or 0)) for (o, q) in rows]


def reserving_orders_hint(db, warehouse_id, product_id, limit=4) -> str:
    """Block xabari uchun qisqa matn: band qilgan buyurtma raqamlari.
    Masalan: 'AGT-20260611-021, AGT-20260612-003 +2'. Band yo'q bo'lsa bo'sh string."""
    orders = get_reserving_orders(db, warehouse_id, product_id)
    if not orders:
        return ""
    nums = [o.number for (o, _q) in orders[:limit]]
    extra = "" if len(orders) <= limit else f" +{len(orders) - limit}"
    return ", ".join(nums) + extra


def notify_reservation_override(db, current_user, entity_label, entity_number, lines, affected_orders) -> None:
    """Band ataylab chetlab o'tilganda:
      1) rahbarlarga Telegram (kim, qaysi hujjat, qaysi band) — fire-and-forget;
      2) ta'sirlangan waiting buyurtmalarga izoh + admin/menejerlarga in-app signal
         (bounce-signal: bu order qayta ishlab chiqarishga tushishi mumkin).

    lines: ["MALINALI: 4 band (AGT-...-021)", ...]
    affected_orders: unikal Order ro'yxati (band egalari).
    Hech qachon asosiy tranzaksiyani buzmaydi (har bo'lak alohida try/except)."""
    from datetime import datetime as _dt
    actor = (getattr(current_user, "username", None) or getattr(current_user, "full_name", None) or "—")
    # 1) Telegram (rahbarlarga)
    try:
        from app.bot.services.notifier import send_notify_sync
        body = (
            f"⚠️ <b>Rezervatsiya (band) chetlab o'tildi</b>\n"
            f"{entity_label}: <b>{entity_number}</b>\n"
            f"Kim: {actor}\n"
            f"Ta'sirlangan band:\n• " + "\n• ".join(lines[:12])
        )
        if affected_orders:
            body += "\n\nBu buyurtmalar qayta «ishlab chiqarishga» tushishi mumkin."
        send_notify_sync(body)
    except Exception:
        pass
    # 2) Bounce-signal: order izohiga + in-app bildirishnoma
    try:
        from app.utils.notifications import create_notification
        from app.models.database import User as _User
        stamp = _dt.now().strftime("%d.%m %H:%M")
        managers = db.query(_User).filter(
            _User.is_active == True, _User.role.in_(["admin", "manager", "menejer", "rahbar", "raxbar"])
        ).all()
        for o in affected_orders:
            try:
                note_add = (f"\n[{stamp}] Band chetlab o'tildi ({entity_number}, {actor}) — "
                            f"tovar boshqa hujjatga ketdi, buyurtma qayta ishlab chiqarishga tushishi mumkin.")
                o.note = (o.note or "") + note_add
            except Exception:
                pass
            for u in managers:
                try:
                    create_notification(
                        db=db,
                        title="Band chetlab o'tildi",
                        message=(f"{entity_number} ({actor}) buyurtma {o.number} uchun band qilingan tovarni oldi. "
                                 f"Bu buyurtma qayta ishlab chiqarishga tushishi mumkin."),
                        notification_type="warning",
                        user_id=u.id,
                        priority="high",
                        action_url=f"/sales/edit/{o.id}",
                        related_entity_type="order",
                        related_entity_id=o.id,
                    )
                except Exception:
                    pass
    except Exception:
        pass


def reservation_override(current_user, force) -> bool:
    """force truthy VA user_can_override (rol) bo'lsa True (band e'tiborga olinmaydi)."""
    if not force:
        return False
    return user_can_override(current_user)


def log_reservation_override(db, current_user, entity_type, entity_number, reserved) -> None:
    """Band ustidan o'tilganda audit log (faqat haqiqiy band chetlab o'tilganda chaqirilsin)."""
    from app.models.database import AuditLog
    db.add(AuditLog(
        user_name=getattr(current_user, "username", None) or "system",
        action="reservation_override",
        entity_type=entity_type,
        entity_number=entity_number,
        details=f"reserved={float(reserved or 0):g} bypassed",
    ))
