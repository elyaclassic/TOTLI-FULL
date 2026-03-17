"""
Bosh sahifa va /info redirect.
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import (
    get_db, User, Product, Partner, Order, Stock,
    CashRegister, Employee, Production,
)
from app.deps import get_current_user, require_auth

router = APIRouter(tags=["home"])


# Bosh sahifa faqat admin va manager uchun; qolganlar o'z rol sahifasiga (tezkor ishlab chiqarish = /production)
_ROLE_HOME = {
    "agent": "/dashboard/agent",
    "driver": "/dashboard/agent",
    "production": "/production",
    "qadoqlash": "/production",
    "sotuvchi": "/sales/pos",
    "rahbar": "/production",
    "raxbar": "/production",
    "operator": "/production",
}


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Bosh sahifa - faqat admin va rahbar (manager) ko'radi; boshqalar o'z role sahifasiga yo'naltiriladi."""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    role = (getattr(current_user, "role", None) or "").strip().lower()
    if role not in ("admin", "manager"):
        redirect_url = _ROLE_HOME.get(role, "/production/orders")
        return RedirectResponse(url=redirect_url, status_code=303)
    error = request.query_params.get("error")
    try:
        stats = {
            "tayyor_count": db.query(Product).filter(Product.type == "tayyor").count(),
            "yarim_tayyor_count": db.query(Product).filter(Product.type == "yarim_tayyor").count(),
            "hom_ashyo_count": db.query(Product).filter(Product.type == "hom_ashyo").count(),
            "partners_count": db.query(Partner).count(),
            "employees_count": db.query(Employee).count(),
            "products_count": db.query(Product).filter(Product.is_active == True).count(),
            "materials_count": db.query(Product).filter(Product.type == "hom_ashyo", Product.is_active == True).count(),
        }
        today = datetime.now().date()
        today_start = datetime.combine(today, datetime.min.time())
        today_sales = db.query(Order).filter(Order.type == "sale", Order.date >= today_start).all()
        stats["today_sales"] = sum(s.total for s in today_sales)
        stats["today_orders"] = len(today_sales)
        today_productions = db.query(Production).filter(
            Production.date >= today_start,
            Production.status == "completed",
        ).all()
        stats["today_production"] = sum(p.quantity for p in today_productions if p.quantity)
        debtors = db.query(Partner).filter(Partner.balance > 0).all()
        stats["total_debt"] = sum(p.balance for p in debtors)
        recent_sales = (
            db.query(Order)
            .filter(Order.type == "sale")
            .order_by(Order.created_at.desc())
            .limit(10)
            .all()
        )
        low_stock_count = db.query(Stock).join(Product).filter(Stock.quantity < Product.min_stock).count()
        birthday_today_count = 0
        try:
            md = today.strftime("%m-%d")
            for e in db.query(Employee).filter(Employee.birth_date.isnot(None), Employee.is_active == True).all():
                if e.birth_date and e.birth_date.strftime("%m-%d") == md:
                    birthday_today_count += 1
        except Exception:
            # birth_date ustuni mavjud emas bo'lishi mumkin (eski bazalar)
            pass
        overdue_cutoff = datetime.now() - timedelta(days=7)
        overdue_debts_count = db.query(Order).filter(
            Order.type == "sale",
            Order.debt > 0,
            Order.created_at < overdue_cutoff,
        ).count()
    except Exception as e:
        import traceback
        print(f"[Home] Statistika yuklashda xato: {e}")
        print(traceback.format_exc())
        stats = {
            "tayyor_count": 0, "yarim_tayyor_count": 0, "hom_ashyo_count": 0,
            "partners_count": 0, "employees_count": 0, "products_count": 0, "materials_count": 0,
            "today_sales": 0, "today_orders": 0, "total_debt": 0, "today_production": 0,
        }
        recent_sales = []
        low_stock_count = 0
        birthday_today_count = 0
        overdue_debts_count = 0
        if not error:
            error = "Statistika yuklanmadi"
    return templates.TemplateResponse("index.html", {
        "request": request,
        "stats": stats,
        "current_user": current_user,
        "page_title": "Bosh sahifa",
        "error": error,
        "recent_sales": recent_sales,
        "low_stock_count": low_stock_count,
        "birthday_today_count": birthday_today_count,
        "overdue_debts_count": overdue_debts_count,
    })


@router.get("/info")
async def info_index(request: Request, current_user: User = Depends(require_auth)):
    """Ma'lumotlar - /info/units ga yo'naltirish"""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url="/info/units", status_code=303)
