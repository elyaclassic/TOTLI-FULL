"""
Agent Dashboard v2 — "Dark Cockpit Mobile"
Parallel route: /dashboard/agent/v2 — eski /dashboard/agent tegmaydi.
Mobile-first: bottom nav, FAB, touch-first.
"""
from datetime import datetime, timedelta
import traceback

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db, User, Agent, Visit, Partner, Order, AgentLocation,
)
from app.deps import require_auth

router = APIRouter(tags=["agent_v2"])


@router.get("/dashboard/agent/v2", response_class=HTMLResponse)
async def agent_dashboard_v2(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Dark Cockpit Mobile dashboard for agents."""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    role = (getattr(current_user, "role", None) or "").strip().lower()
    if role not in ("agent", "driver", "admin", "manager"):
        return RedirectResponse(url="/", status_code=303)

    today = datetime.now().date()
    month_ago = today - timedelta(days=30)

    # Agent — try by user_id, fallback to first active
    agent = db.query(Agent).filter(Agent.user_id == current_user.id).first()
    if not agent:
        agent = db.query(Agent).filter(Agent.is_active == True).first()

    agent_info = {
        "name": agent.full_name if agent else "Agent topilmadi",
        "region": (agent.region if agent else None) or "Noma'lum",
        "phone": (agent.phone if agent else None) or "",
        "id": agent.id if agent else 0,
    }

    kpi = {
        "today_sales": 0.0,
        "today_orders": 0,
        "visits_completed": 0,
        "visits_total": 0,
        "visits_percent": 0,
        "target_total": 25_000_000,
        "month_sales": 0.0,
        "target_percent": 0,
    }
    schedule = []
    recent_orders = []
    customers = []

    if agent:
        try:
            # Visits today
            today_visits = db.query(func.count(Visit.id)).filter(
                Visit.agent_id == agent.id,
                func.date(Visit.visit_date) == today,
            ).scalar() or 0
            completed_visits = db.query(func.count(Visit.id)).filter(
                Visit.agent_id == agent.id,
                func.date(Visit.visit_date) == today,
                Visit.status == "visited",
            ).scalar() or 0
            kpi["visits_total"] = today_visits
            kpi["visits_completed"] = completed_visits
            kpi["visits_percent"] = int(completed_visits / today_visits * 100) if today_visits > 0 else 0

            # Today's sales (orders by this agent's region/partners — approximation)
            today_sales = db.query(func.coalesce(func.sum(Order.total), 0)).filter(
                func.date(Order.created_at) == today,
                Order.status.in_(("completed", "delivered", "confirmed")),
            ).scalar() or 0
            kpi["today_sales"] = float(today_sales)
            kpi["today_orders"] = db.query(func.count(Order.id)).filter(
                func.date(Order.created_at) == today,
            ).scalar() or 0

            # Monthly target progress
            month_sales = db.query(func.coalesce(func.sum(Order.total), 0)).filter(
                func.date(Order.created_at) >= month_ago,
                Order.status.in_(("completed", "delivered")),
            ).scalar() or 0
            kpi["month_sales"] = float(month_sales)
            kpi["target_percent"] = int(month_sales / kpi["target_total"] * 100) if kpi["target_total"] > 0 else 0

            # Today's schedule from visits (with partner info)
            visits_today = db.query(Visit, Partner).join(
                Partner, Visit.partner_id == Partner.id, isouter=True
            ).filter(
                Visit.agent_id == agent.id,
                func.date(Visit.visit_date) == today,
            ).order_by(Visit.check_in_time.asc().nulls_last()).all()

            for v, p in visits_today:
                schedule.append({
                    "partner_id": p.id if p else 0,
                    "name": (p.name if p else "?"),
                    "address": (p.address if p else "—"),
                    "phone": (p.phone if p else ""),
                    "time": v.check_in_time.strftime("%H:%M") if v.check_in_time else "—",
                    "status": v.status,
                    "completed": v.status == "visited",
                    "balance": float(p.balance) if p and p.balance else 0,
                })

            # Recent orders (last 7 days, this agent's partners)
            recent_q = db.query(Order, Partner).join(
                Partner, Order.partner_id == Partner.id, isouter=True
            ).filter(
                func.date(Order.created_at) >= today - timedelta(days=7),
            ).order_by(Order.created_at.desc()).limit(8).all()

            for o, p in recent_q:
                recent_orders.append({
                    "id": o.id,
                    "number": o.number or f"S-{o.id:04d}",
                    "customer": (p.name if p else "—"),
                    "total": float(o.total or 0),
                    "status": o.status,
                    "date": o.created_at.strftime("%d/%m %H:%M") if o.created_at else "",
                })

            # Top customers (partners with recent orders, sorted by activity)
            cust_q = db.query(
                Partner,
                func.coalesce(func.sum(Order.total), 0).label("total_sum"),
                func.count(Order.id).label("orders_count"),
                func.max(Order.created_at).label("last_at"),
            ).join(
                Order, Partner.id == Order.partner_id
            ).filter(
                func.date(Order.created_at) >= month_ago,
            ).group_by(Partner.id).order_by(func.max(Order.created_at).desc()).limit(8).all()

            for p, total_sum, orders_count, last_at in cust_q:
                customers.append({
                    "id": p.id,
                    "name": p.name,
                    "phone": p.phone or "",
                    "address": p.address or "—",
                    "total_sum": float(total_sum or 0),
                    "orders_count": int(orders_count or 0),
                    "balance": float(p.balance or 0),
                    "last_at": last_at.strftime("%d/%m") if last_at else "",
                })

        except Exception as e:
            print(f"[Agent v2] Data fetch xato: {e}")
            print(traceback.format_exc())

    return templates.TemplateResponse("agents/dashboard_v2.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Agent Dashboard",
        "agent": agent_info,
        "kpi": kpi,
        "schedule": schedule,
        "recent_orders": recent_orders,
        "customers": customers,
    })
