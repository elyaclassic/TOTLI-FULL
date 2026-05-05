"""
Oy yopish (Period Close) — davr yopish, snapshot, qayta ochish.
"""
import json
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db, User, ClosedPeriod, Stock, CashRegister, Partner, Order, Purchase,
    ExpenseDoc, Payment, Warehouse, Product,
)
from app.deps import require_admin

router = APIRouter(prefix="/admin/periods", tags=["periods"])


@router.get("", response_class=HTMLResponse)
async def period_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    periods = db.query(ClosedPeriod).order_by(ClosedPeriod.period.desc()).all()
    now = datetime.now()
    current_period = now.strftime("%Y-%m")
    # Oxirgi 6 oy
    months = []
    for i in range(6):
        m = now.month - i
        y = now.year
        while m <= 0:
            m += 12
            y -= 1
        period_str = f"{y:04d}-{m:02d}"
        closed = next((p for p in periods if p.period == period_str), None)
        months.append({"period": period_str, "closed": closed})
    return templates.TemplateResponse("reports/periods.html", {
        "request": request,
        "months": months,
        "current_user": current_user,
        "page_title": "Davr yopish",
    })


@router.post("/close")
async def period_close(
    request: Request,
    period: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    existing = db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first()
    if existing:
        return RedirectResponse(url="/reports/periods?error=already_closed", status_code=303)

    # Yopishdan oldin tekshiruv — draft hujjatlar
    year, month = int(period[:4]), int(period[5:7])
    start = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end = f"{year + 1:04d}-01-01"
    else:
        end = f"{year:04d}-{month + 1:02d}-01"

    draft_sales = db.query(func.count(Order.id)).filter(
        Order.type == "sale", Order.status == "draft",
        Order.date >= start, Order.date < end,
    ).scalar() or 0
    draft_purchases = db.query(func.count(Purchase.id)).filter(
        Purchase.status == "draft",
        Purchase.date >= start, Purchase.date < end,
    ).scalar() or 0
    if draft_sales + draft_purchases > 0:
        return RedirectResponse(
            url=f"/reports/periods?error=drafts&drafts_sales={draft_sales}&drafts_purchases={draft_purchases}",
            status_code=303,
        )

    # Snapshot — stock qoldiqlari
    stocks = db.query(Stock).filter(Stock.quantity > 0.001).all()
    stock_snap = {}
    for s in stocks:
        wid = str(s.warehouse_id)
        if wid not in stock_snap:
            stock_snap[wid] = {}
        stock_snap[wid][str(s.product_id)] = round(s.quantity, 3)

    # Snapshot — kassa balanslari
    cash_regs = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    cash_snap = {}
    for cr in cash_regs:
        inc = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.cash_register_id == cr.id, Payment.type == "income",
            Payment.status == "confirmed",
        ).scalar()
        exp = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.cash_register_id == cr.id, Payment.type == "expense",
            Payment.status == "confirmed",
        ).scalar()
        cash_snap[str(cr.id)] = round(float(inc) - float(exp), 2)

    # Snapshot — mijoz qarzlari
    partners = db.query(Partner).filter(Partner.balance != 0).all()
    debt_snap = {str(p.id): round(float(p.balance or 0), 2) for p in partners}

    cp = ClosedPeriod(
        period=period,
        closed_at=datetime.now(),
        closed_by=current_user.id,
        note=note or None,
        snapshot_stock=json.dumps(stock_snap, ensure_ascii=False),
        snapshot_cash=json.dumps(cash_snap, ensure_ascii=False),
        snapshot_partner_debt=json.dumps(debt_snap, ensure_ascii=False),
    )
    db.add(cp)
    db.commit()
    return RedirectResponse(url="/reports/periods?success=closed", status_code=303)


@router.post("/reopen")
async def period_reopen(
    request: Request,
    period: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    cp = db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first()
    if not cp:
        return RedirectResponse(url="/reports/periods?error=not_found", status_code=303)
    db.delete(cp)
    db.commit()
    return RedirectResponse(url="/reports/periods?success=reopened", status_code=303)


def is_period_closed(db: Session, date) -> bool:
    """Berilgan sana yopilgan davrga tegishli ekanini tekshiradi."""
    if not date:
        return False
    if isinstance(date, str):
        period = date[:7]
    else:
        period = date.strftime("%Y-%m")
    return db.query(ClosedPeriod).filter(ClosedPeriod.period == period).first() is not None
