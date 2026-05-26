"""
Dashboard v2 — "Editorial Cockpit"
Parallel route: hozirgi `/` (home.py) tegmaydi.
Faqat admin/manager kira oladi. URL: /dashboard/v2
"""
from datetime import datetime, timedelta
import calendar
import traceback

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db, User, Product, Partner, Order, Stock,
    Employee, Production, Recipe, Attendance,
)
from app.deps import require_auth
from app.utils.production_order import recipe_kg_per_unit

router = APIRouter(tags=["dashboard_v2"])


@router.get("/dashboard/v2", response_class=HTMLResponse)
async def dashboard_v2(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Editorial Cockpit dashboard. Faqat admin/manager."""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    role = (getattr(current_user, "role", None) or "").strip().lower()
    if role not in ("admin", "manager"):
        return RedirectResponse(url="/", status_code=303)

    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())

    stats = {
        "today_sales": 0.0,
        "today_orders": 0,
        "today_production": 0.0,
        "today_tayyor_kg": 0.0,
        "today_yarim_tayyor_kg": 0.0,
        "total_debt": 0.0,
    }
    monthly_sales = []
    low_stock_items = []
    pending_orders = []
    completed_orders = []
    in_progress_count = 0
    today_staff = []
    low_stock_count = 0
    overdue_debts_count = 0

    try:
        # Bugungi sotuvlar
        today_sales_list = db.query(Order).filter(
            Order.type == "sale",
            Order.date >= today_start,
        ).all()
        stats["today_sales"] = sum((s.total or 0) for s in today_sales_list)
        stats["today_orders"] = len(today_sales_list)

        # Bugungi ishlab chiqarish (kg)
        today_productions = db.query(Production).options(
            joinedload(Production.recipe).joinedload(Recipe.product),
            joinedload(Production.output_warehouse),
            joinedload(Production.production_items),
        ).filter(
            Production.date >= today_start,
            Production.status == "completed",
        ).all()
        tayyor_kg = 0.0
        yarim_tayyor_kg = 0.0
        for p in today_productions:
            out_wh_name = (getattr(p.output_warehouse, "name", None) or "").lower()
            is_yarim = "yarim" in out_wh_name
            is_qiyom = p.recipe and "qiyom" in (getattr(p.recipe, "name", None) or "").lower()
            if is_yarim:
                if not is_qiyom:
                    yarim_tayyor_kg += sum(float(pi.quantity or 0) for pi in (p.production_items or []))
            else:
                tayyor_kg += recipe_kg_per_unit(p.recipe) * float(p.quantity or 0)
        stats["today_tayyor_kg"] = tayyor_kg
        stats["today_yarim_tayyor_kg"] = yarim_tayyor_kg
        stats["today_production"] = tayyor_kg + yarim_tayyor_kg

        # Mijoz qarzi (faqat haqiqiy savdo qarzlari)
        sale_debtor_ids = [
            r[0] for r in db.query(Order.partner_id).filter(
                Order.type == "sale", Order.debt > 0, Order.partner_id.isnot(None),
            ).distinct().all() if r and r[0]
        ]
        if sale_debtor_ids:
            debtors = db.query(Partner).filter(
                Partner.id.in_(sale_debtor_ids), Partner.balance > 0
            ).all()
            stats["total_debt"] = sum((p.balance or 0) for p in debtors)

        # Kechiktirilgan qarzlar (7 kundan ortiq)
        overdue_cutoff = datetime.now() - timedelta(days=7)
        overdue_debts_count = (
            db.query(Order.partner_id)
            .filter(
                Order.type == "sale",
                Order.debt > 0,
                Order.partner_id.isnot(None),
                Order.created_at < overdue_cutoff,
            )
            .distinct()
            .count()
        )

        # Oxirgi 6 oy sotuvlari — sparkline uchun
        now = datetime.now()
        for i in range(5, -1, -1):
            m = now.month - i
            y = now.year
            while m <= 0:
                m += 12; y -= 1
            m_start = datetime(y, m, 1)
            m_end = datetime(y, m, calendar.monthrange(y, m)[1], 23, 59, 59)
            total = db.query(func.coalesce(func.sum(Order.total), 0)).filter(
                Order.type == "sale",
                Order.date >= m_start,
                Order.date <= m_end,
            ).scalar() or 0
            month_names_uz = ["Yan", "Fev", "Mar", "Apr", "May", "Iyn",
                              "Iyl", "Avg", "Sen", "Okt", "Noy", "Dek"]
            monthly_sales.append({
                "month": month_names_uz[m - 1],
                "total": float(total),
            })

        # Kam qolgan tovarlar (top 6)
        low_stocks = db.query(Stock).options(joinedload(Stock.product)).join(Product).filter(
            Stock.quantity > 0,
            Stock.quantity < 10,
        ).order_by(Stock.quantity).limit(6).all()
        for ls in low_stocks:
            unit_name = "kg"
            try:
                if ls.product and getattr(ls.product, "unit", None):
                    unit_name = ls.product.unit.name or "kg"
            except Exception:
                pass
            low_stock_items.append({
                "name": ls.product.name if ls.product else "?",
                "qty": float(ls.quantity or 0),
                "unit": unit_name,
            })

        # Low stock count (min_stock + threshold)
        low_by_min = db.query(Stock).join(Product).filter(
            Product.min_stock > 0,
            Stock.quantity < Product.min_stock,
        ).count()
        low_by_threshold = db.query(Stock).join(Product).filter(
            (Product.min_stock == None) | (Product.min_stock <= 0),
            Stock.quantity > 0,
            Stock.quantity < 10,
        ).count()
        low_stock_count = low_by_min + low_by_threshold

        # Kutilayotgan buyurtmalar (draft)
        pending_orders = db.query(Order).options(joinedload(Order.partner)).filter(
            Order.type == "sale",
            Order.status == "draft",
        ).order_by(Order.created_at.desc()).limit(8).all()

        # Bugun tugatilganlar
        completed_orders = db.query(Order).options(joinedload(Order.partner)).filter(
            Order.type == "sale",
            Order.status.in_(("completed", "delivered")),
            Order.date >= today_start,
        ).order_by(Order.created_at.desc()).limit(8).all()

        # Ishlab chiqarish — jarayonda
        in_progress_count = db.query(Production).filter(
            Production.status.in_(["draft", "in_progress"])
        ).count()

        # Bugun ishda bo'lgan xodimlar
        now_dt = datetime.now()
        today_att = db.query(Attendance).filter(
            Attendance.date == today,
            Attendance.status == "present",
        ).all()
        present_att = []
        for a in today_att:
            if not a.check_in:
                continue
            if a.check_out and a.check_in:
                diff_min = (a.check_out - a.check_in).total_seconds() / 60.0
                if diff_min >= 5:
                    continue
            if now_dt.hour >= 19:
                continue
            present_att.append(a)
        emp_ids = list({a.employee_id for a in present_att if a.employee_id})
        emp_map = {}
        if emp_ids:
            for emp in db.query(Employee).filter(
                Employee.id.in_(emp_ids), Employee.is_active == True
            ).all():
                emp_map[emp.id] = emp
        for a in present_att:
            emp = emp_map.get(a.employee_id)
            if emp:
                today_staff.append({
                    "id": emp.id,
                    "name": emp.full_name or emp.code or "",
                    "position": emp.position or "",
                    "check_in": a.check_in.strftime("%H:%M") if a.check_in else "",
                    "photo": a.event_snapshot_path or "",
                })

    except Exception as e:
        print(f"[Dashboard v2] Statistika xato: {e}")
        print(traceback.format_exc())

    return templates.TemplateResponse("dashboard_v2/admin.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Dashboard v2",
        "stats": stats,
        "monthly_sales": monthly_sales,
        "low_stock_items": low_stock_items,
        "low_stock_count": low_stock_count,
        "overdue_debts_count": overdue_debts_count,
        "pending_orders": pending_orders,
        "completed_orders": completed_orders,
        "in_progress_count": in_progress_count,
        "today_staff": today_staff,
    })
