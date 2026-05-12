"""Supervisor uchun yetkazish dashboard — bugun/ertaga/kechikkanlar/production."""
from datetime import date as _date, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.core import templates
from app.models.database import get_db, Order, User, Driver
from app.deps import require_admin_or_manager


router = APIRouter(tags=["sales-deliveries"])


@router.get("/sales/deliveries", response_class=HTMLResponse)
async def deliveries_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    today = _date.today()
    tomorrow = today + timedelta(days=1)

    base = db.query(Order).options(
        joinedload(Order.partner),
        joinedload(Order.items),
    )

    today_orders = base.filter(
        Order.status == "out_for_delivery",
        Order.delivery_date == today,
    ).order_by(Order.delivery_date, Order.id).all()

    tomorrow_orders = base.filter(
        Order.status == "out_for_delivery",
        Order.delivery_date == tomorrow,
    ).order_by(Order.delivery_date, Order.id).all()

    overdue = base.filter(
        Order.status == "out_for_delivery",
        Order.delivery_date < today,
    ).order_by(Order.delivery_date, Order.id).all()

    waiting = base.filter(
        Order.status == "waiting_production",
    ).order_by(Order.delivery_date, Order.id).all()

    # Driver nomlarini lookup uchun
    driver_ids = {o.pending_driver_id for o in (today_orders + tomorrow_orders + overdue + waiting) if o.pending_driver_id}
    drivers_map = {}
    if driver_ids:
        for d in db.query(Driver).filter(Driver.id.in_(driver_ids)).all():
            drivers_map[d.id] = d

    return templates.TemplateResponse("sales/deliveries.html", {
        "request": request,
        "current_user": current_user,
        "today_orders": today_orders,
        "tomorrow_orders": tomorrow_orders,
        "overdue": overdue,
        "waiting": waiting,
        "drivers_map": drivers_map,
        "today": today,
        "page_title": "Yetkazishlar",
    })
