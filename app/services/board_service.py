"""Buyurtma board snapshot — agent yetkazish buyurtmalarini bosqich bo'yicha guruhlaydi.
Sof read-only. Spec: docs/superpowers/specs/2026-06-04-order-board-design.md"""
from datetime import date
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session, joinedload

from app.models.database import Order, Delivery

ACTIVE_STATUSES = (
    Order.STATUS_CONFIRMED,
    Order.STATUS_WAITING_PRODUCTION,
    Order.STATUS_OUT_FOR_DELIVERY,
)
COLUMNS = (*ACTIVE_STATUSES, Order.STATUS_DELIVERED)


def _stage_since(o):
    if o.status == Order.STATUS_OUT_FOR_DELIVERY and getattr(o, "dispatched_at", None):
        return o.dispatched_at
    return o.date


def build_board_snapshot(db: Session) -> dict:
    today = date.today()
    orders = (
        db.query(Order)
        .options(joinedload(Order.partner), joinedload(Order.items))
        .filter(
            Order.source == "agent",
            Order.type == "sale",
            or_(
                Order.status.in_(ACTIVE_STATUSES),
                and_(
                    Order.status == Order.STATUS_DELIVERED,
                    func.date(Order.delivery_date) == today,
                ),
            ),
        )
        .order_by(Order.delivery_date.asc(), Order.id.asc())
        .all()
    )
    driver_by_order = {}
    oids = [o.id for o in orders if o.status == Order.STATUS_OUT_FOR_DELIVERY]
    if oids:
        for d in (
            db.query(Delivery).options(joinedload(Delivery.driver))
            .filter(Delivery.order_id.in_(oids)).all()
        ):
            if d.driver:
                driver_by_order[d.order_id] = d.driver.full_name or d.driver.code or ""

    cols = {c: [] for c in COLUMNS}
    for o in orders:
        dd = o.delivery_date
        overdue = bool(o.status in ACTIVE_STATUSES and dd and dd <= today)
        _ss = _stage_since(o)
        card = {
            "id": o.id,
            "number": o.number or "",
            "partner": (o.partner.name if o.partner else "—"),
            "total": float(o.total or 0),
            "items_count": len(o.items),
            "status": o.status,
            "delivery_date": dd.isoformat() if dd else None,
            "driver": driver_by_order.get(o.id, ""),
            "overdue": overdue,
            "stage_since": _ss.isoformat() if _ss else None,
        }
        if o.status in cols:
            cols[o.status].append(card)
    return cols
