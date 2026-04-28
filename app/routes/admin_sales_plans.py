"""
Admin: agent oylik savdo rejasi (sales_plans).

Har oy uchun bitta global qiymat — har agent shu summaga qarshi alohida solishtiriladi.
"""
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.deps import get_db, require_admin
from app.models.database import User, SalesPlan, Order, Agent
from app.template_helpers import templates
from app.logging_config import get_logger

logger = get_logger("admin_sales_plans")
router = APIRouter(tags=["admin-sales-plans"])


def _current_period() -> str:
    return datetime.now().strftime("%Y-%m")


@router.get("/admin/sales-plans", response_class=HTMLResponse)
async def admin_sales_plans_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sales plans ro'yxati + joriy oy ko'rsatkichlari (har agent bo'yicha)."""
    plans = db.query(SalesPlan).order_by(desc(SalesPlan.period)).limit(24).all()
    current = _current_period()
    current_plan = db.query(SalesPlan).filter(SalesPlan.period == current).first()

    # Har agent bo'yicha joriy oy savdo summasi
    today = datetime.now().date()
    month_start = today.replace(day=1)
    agents = db.query(Agent).filter(Agent.is_active == True).order_by(Agent.full_name).all()
    rows = []
    for ag in agents:
        total = db.query(Order).filter(
            Order.agent_id == ag.id,
            Order.source == "agent",
            Order.status.in_(("confirmed", "completed")),
            Order.date >= month_start,
        ).all()
        sold = sum(float(o.total or 0) for o in total)
        target = float(current_plan.amount) if current_plan else 0.0
        pct = round((sold / target * 100), 1) if target > 0 else 0.0
        rows.append({
            "agent": ag,
            "sold": sold,
            "target": target,
            "percent": pct,
            "remaining": max(0.0, target - sold),
        })

    return templates.TemplateResponse("admin/sales_plans.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Agent savdo rejasi",
        "plans": plans,
        "current_period": current,
        "current_plan": current_plan,
        "rows": rows,
    })


@router.post("/admin/sales-plans/save")
async def admin_sales_plans_save(
    request: Request,
    period: str = Form(...),
    amount: float = Form(0),
    note: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """YYYY-MM uchun reja yaratish/yangilash. period unique — mavjud bo'lsa update."""
    period = (period or "").strip()
    if len(period) != 7 or period[4] != "-":
        return RedirectResponse(url="/admin/sales-plans?error=period", status_code=303)
    try:
        # Validatsiya
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        return RedirectResponse(url="/admin/sales-plans?error=period", status_code=303)

    plan = db.query(SalesPlan).filter(SalesPlan.period == period).first()
    if plan:
        plan.amount = float(amount or 0)
        plan.note = (note or "").strip() or None
    else:
        plan = SalesPlan(
            period=period,
            amount=float(amount or 0),
            note=(note or "").strip() or None,
            created_by_user_id=current_user.id,
        )
        db.add(plan)
    db.commit()
    logger.info(f"Sales plan saqlandi: {period} = {amount} so'm (user={current_user.username})")
    return RedirectResponse(url="/admin/sales-plans?saved=1", status_code=303)


@router.post("/admin/sales-plans/delete/{plan_id}")
async def admin_sales_plans_delete(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    plan = db.query(SalesPlan).filter(SalesPlan.id == plan_id).first()
    if plan:
        db.delete(plan)
        db.commit()
        logger.info(f"Sales plan o'chirildi: id={plan_id} period={plan.period}")
    return RedirectResponse(url="/admin/sales-plans?deleted=1", status_code=303)
