"""
Dashboard v2 — "Editorial Cockpit"
Parallel route: hozirgi `/` (home.py) tegmaydi.
Faqat admin/manager kira oladi. URL: /dashboard/v2
"""
from datetime import datetime, timedelta
import calendar
import traceback

from fastapi import APIRouter, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db, User, Product, Partner, Order, Stock,
    Employee, Production, Recipe, Attendance, SessionLocal,
)
from app.deps import require_auth
from app.utils.production_order import recipe_kg_per_unit
from app.services.realtime_bus import bus
from app.utils.auth import get_user_from_token
from app.deps import _extract_user_id

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

    # ====== F3 widget'lar (row-2): yetkazish, top mahsulot, top agent, inkasatsiya ======
    widgets = {
        "delivery_count": 0,
        "top_product_name": "—",
        "top_product_qty": 0,
        "top_agent_name": "—",
        "top_agent_sum": 0.0,
        "cash_collected": 0.0,
        "cash_transfers_count": 0,
    }
    try:
        from app.models.database import Delivery as _Delivery, OrderItem as _OI, Agent as _Agent, CashTransfer as _CT
        widgets["delivery_count"] = db.query(_Delivery).filter(_Delivery.created_at >= today_start).count()

        # Top mahsulot bugun
        top_prod = (
            db.query(_OI.product_id, func.sum(_OI.quantity).label("qty"))
            .join(Order, Order.id == _OI.order_id)
            .filter(Order.type == "sale", Order.date >= today_start)
            .group_by(_OI.product_id)
            .order_by(func.sum(_OI.total).desc())
            .first()
        )
        if top_prod and top_prod[0]:
            pr = db.query(Product).filter(Product.id == top_prod[0]).first()
            widgets["top_product_name"] = (pr.name if pr else "—")[:18]
            widgets["top_product_qty"] = float(top_prod[1] or 0)

        # Top agent bugun
        top_agent = (
            db.query(Order.agent_id, func.sum(Order.total).label("summa"))
            .filter(Order.source == "agent", Order.date >= today_start, Order.agent_id != None)
            .group_by(Order.agent_id)
            .order_by(func.sum(Order.total).desc())
            .first()
        )
        if top_agent and top_agent[0]:
            ag = db.query(_Agent).filter(_Agent.id == top_agent[0]).first()
            widgets["top_agent_name"] = (ag.full_name if ag else "—")[:18]
            widgets["top_agent_sum"] = float(top_agent[1] or 0)

        # Bugungi inkasatsiya
        cash_q = db.query(_CT).filter(_CT.date >= today_start).all()
        widgets["cash_transfers_count"] = len(cash_q)
        widgets["cash_collected"] = sum(float(c.amount or 0) for c in cash_q)
    except Exception as e:
        print(f"[Dashboard v2] Widget stats xato: {e}")

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
        "widgets": widgets,
    })


@router.get("/api/dashboard/v2/drilldown")
async def dashboard_v2_drilldown(
    kind: str = "sales",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """KPI cards drill-down — bitta universal endpoint.
    kind in: sales|production|debt|stock.
    Response: {title, summary, headers, rows, link}
    """
    role = (getattr(current_user, "role", None) or "").strip().lower()
    if role not in ("admin", "manager", "rahbar", "raxbar", "menejer"):
        return {"title": "Ruxsat yo'q", "summary": "", "headers": [], "rows": [], "link": None}

    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    LIMIT = 50

    def money(v):
        try:
            return f"{float(v or 0):,.0f}".replace(",", " ")
        except (ValueError, TypeError):
            return "0"

    if kind == "sales":
        orders = (
            db.query(Order)
            .options(joinedload(Order.partner), joinedload(Order.user))
            .filter(Order.type == "sale", Order.date >= today_start)
            .order_by(Order.date.desc())
            .limit(LIMIT)
            .all()
        )
        total_sum = sum(float(o.total or 0) for o in orders)
        rows = []
        for o in orders:
            rows.append([
                o.date.strftime("%H:%M") if o.date else "-",
                o.number or "-",
                (o.partner.name if o.partner else "Naqd mijoz")[:30],
                (o.user.username if o.user else "-"),
                money(o.total),
                o.status or "-",
            ])
        return {
            "title": "Bugungi sotuvlar",
            "summary": f"{len(orders)} ta · {money(total_sum)} so'm",
            "headers": ["Vaqt", "Raqam", "Mijoz", "Sotuvchi", "Summa", "Status"],
            "rows": rows,
            "link": {"url": "/sales", "label": "Sotuvlar sahifasi →"},
        }

    if kind == "production":
        productions = (
            db.query(Production)
            .options(joinedload(Production.recipe), joinedload(Production.operator))
            .filter(Production.date >= today_start)
            .order_by(Production.date.desc())
            .limit(LIMIT)
            .all()
        )
        rows = []
        total_qty = 0.0
        for p in productions:
            qty = float(p.quantity or 0)
            total_qty += qty
            rows.append([
                p.date.strftime("%H:%M") if p.date else "-",
                p.number or "-",
                (p.recipe.name if p.recipe else "-")[:35],
                f"{qty:g}",
                (p.operator.full_name if p.operator else "-"),
                p.status or "-",
            ])
        return {
            "title": "Bugungi ishlab chiqarish",
            "summary": f"{len(productions)} ta · {total_qty:g} dona",
            "headers": ["Vaqt", "Raqam", "Retsept", "Miqdor", "Operator", "Status"],
            "rows": rows,
            "link": {"url": "/production/orders", "label": "Production sahifasi →"},
        }

    if kind == "debt":
        partners = (
            db.query(Partner)
            .filter(Partner.is_active == True, Partner.balance < 0)
            .order_by(Partner.balance.asc())
            .limit(LIMIT)
            .all()
        )
        total_debt = sum(float(p.balance or 0) for p in partners)
        rows = []
        for p in partners:
            rows.append([
                (p.name or "-")[:35],
                p.phone or "-",
                money(abs(float(p.balance or 0))),
                (p.address or "-")[:30],
            ])
        return {
            "title": "Qarzdor mijozlar",
            "summary": f"{len(partners)} ta · {money(abs(total_debt))} so'm jami qarz",
            "headers": ["Mijoz", "Telefon", "Qarz (so'm)", "Manzil"],
            "rows": rows,
            "link": {"url": "/partners", "label": "Mijozlar sahifasi →"},
        }

    if kind == "stock":
        from sqlalchemy import or_ as _or
        # Min_stock'dan past yoki min_stock yo'q va < 10
        low_stocks = (
            db.query(Stock)
            .options(joinedload(Stock.product), joinedload(Stock.warehouse))
            .join(Product)
            .filter(
                Stock.quantity > 0,
                _or(
                    (Product.min_stock != None) & (Stock.quantity < Product.min_stock),
                    (Product.min_stock == None) & (Stock.quantity < 10),
                ),
            )
            .order_by(Stock.quantity)
            .limit(LIMIT)
            .all()
        )
        rows = []
        for ls in low_stocks:
            unit = "kg"
            try:
                if ls.product and getattr(ls.product, "unit", None):
                    unit = ls.product.unit.name or "kg"
            except Exception:
                pass
            min_st = getattr(ls.product, "min_stock", None) if ls.product else None
            rows.append([
                (ls.product.name if ls.product else "?")[:35],
                (ls.warehouse.name if ls.warehouse else "-")[:25],
                f"{float(ls.quantity or 0):g} {unit}",
                (f"{float(min_st):g}" if min_st else "—"),
            ])
        return {
            "title": "Ombor ogohliklari",
            "summary": f"{len(low_stocks)} ta tovar past zaxirada",
            "headers": ["Mahsulot", "Ombor", "Qoldiq", "Min. me'yor"],
            "rows": rows,
            "link": {"url": "/qoldiqlar", "label": "Qoldiqlar sahifasi →"},
        }

    if kind == "delivery":
        from app.models.database import Delivery as _Delivery, Driver as _Driver
        deliveries = (
            db.query(_Delivery)
            .options(joinedload(_Delivery.driver) if hasattr(_Delivery, "driver") else None)
            .filter(_Delivery.created_at >= today_start)
            .order_by(_Delivery.created_at.desc())
            .limit(LIMIT)
            .all()
        )
        # driver_id -> driver name kesh
        driver_ids = list({d.driver_id for d in deliveries if d.driver_id})
        drivers_map = {}
        if driver_ids:
            for dr in db.query(_Driver).filter(_Driver.id.in_(driver_ids)).all():
                drivers_map[dr.id] = dr.full_name
        rows = []
        for d in deliveries:
            rows.append([
                d.created_at.strftime("%H:%M") if d.created_at else "-",
                d.number or d.order_number or "-",
                drivers_map.get(d.driver_id, "—"),
                (d.delivery_address or "-")[:35],
                d.status or "-",
            ])
        return {
            "title": "Bugungi yetkazishlar",
            "summary": f"{len(deliveries)} ta yetkazish",
            "headers": ["Vaqt", "Raqam", "Haydovchi", "Manzil", "Status"],
            "rows": rows,
            "link": {"url": "/delivery", "label": "Yetkazishlar sahifasi →"},
        }

    if kind == "top_products":
        from app.models.database import OrderItem as _OI
        from sqlalchemy import func as _func
        # Bugungi sotuvlarda mahsulot bo'yicha jami quantity va summa
        results = (
            db.query(
                _OI.product_id,
                _func.sum(_OI.quantity).label("qty"),
                _func.sum(_OI.total).label("summa"),
            )
            .join(Order, Order.id == _OI.order_id)
            .filter(Order.type == "sale", Order.date >= today_start)
            .group_by(_OI.product_id)
            .order_by(_func.sum(_OI.total).desc())
            .limit(LIMIT)
            .all()
        )
        # Product nomlari
        prod_ids = [r[0] for r in results if r[0]]
        prods_map = {}
        if prod_ids:
            for p in db.query(Product).filter(Product.id.in_(prod_ids)).all():
                prods_map[p.id] = p.name
        rows = []
        for rank, r in enumerate(results, 1):
            rows.append([
                f"#{rank}",
                prods_map.get(r[0], "?")[:35],
                f"{float(r[1] or 0):g}",
                money(r[2]),
            ])
        total_revenue = sum(float(r[2] or 0) for r in results)
        return {
            "title": "Top sotilayotgan mahsulotlar",
            "summary": f"{len(results)} ta mahsulot · {money(total_revenue)} so'm",
            "headers": ["Reyting", "Mahsulot", "Miqdor", "Tushum (so'm)"],
            "rows": rows,
            "link": {"url": "/products", "label": "Mahsulotlar sahifasi →"},
        }

    if kind == "top_agents":
        from app.models.database import Agent as _Agent
        from sqlalchemy import func as _func
        results = (
            db.query(
                Order.agent_id,
                _func.count(Order.id).label("cnt"),
                _func.sum(Order.total).label("summa"),
            )
            .filter(
                Order.source == "agent",
                Order.date >= today_start,
                Order.agent_id != None,
            )
            .group_by(Order.agent_id)
            .order_by(_func.sum(Order.total).desc())
            .limit(LIMIT)
            .all()
        )
        agent_ids = [r[0] for r in results if r[0]]
        agents_map = {}
        if agent_ids:
            for a in db.query(_Agent).filter(_Agent.id.in_(agent_ids)).all():
                agents_map[a.id] = a.full_name
        rows = []
        for rank, r in enumerate(results, 1):
            rows.append([
                f"#{rank}",
                agents_map.get(r[0], "?")[:30],
                f"{int(r[1] or 0)} ta",
                money(r[2]),
            ])
        total_revenue = sum(float(r[2] or 0) for r in results)
        return {
            "title": "Bugungi faol agentlar",
            "summary": f"{len(results)} ta agent · {money(total_revenue)} so'm",
            "headers": ["Reyting", "Agent", "Buyurtma", "Summa (so'm)"],
            "rows": rows,
            "link": {"url": "/supervisor/agent-orders", "label": "Agent buyurtmalari →"},
        }

    if kind == "cash":
        from app.models.database import CashTransfer as _CT, CashRegister as _CR
        transfers = (
            db.query(_CT)
            .filter(_CT.date >= today_start)
            .order_by(_CT.date.desc())
            .limit(LIMIT)
            .all()
        )
        # CashRegister nomlari
        reg_ids = set()
        for t in transfers:
            if t.from_cash_id:
                reg_ids.add(t.from_cash_id)
            if t.to_cash_id:
                reg_ids.add(t.to_cash_id)
        regs_map = {}
        if reg_ids:
            for r in db.query(_CR).filter(_CR.id.in_(list(reg_ids))).all():
                regs_map[r.id] = r.name
        rows = []
        for t in transfers:
            rows.append([
                t.date.strftime("%H:%M") if t.date else "-",
                t.number or "-",
                regs_map.get(t.from_cash_id, "-")[:20],
                regs_map.get(t.to_cash_id, "-")[:20],
                money(t.amount),
                t.status or "-",
            ])
        total = sum(float(t.amount or 0) for t in transfers)
        return {
            "title": "Bugungi inkasatsiya",
            "summary": f"{len(transfers)} ta o'tkazma · {money(total)} so'm",
            "headers": ["Vaqt", "Raqam", "Qaerdan", "Qayerga", "Summa", "Status"],
            "rows": rows,
            "link": {"url": "/cash-transfers", "label": "Kassa o'tkazmalari →"},
        }

    return {"title": "Noma'lum kind", "summary": "", "headers": [], "rows": [], "link": None}


# ====== F4: WebSocket real-time KPI ======

@router.websocket("/ws/dashboard/v2")
async def dashboard_v2_ws(websocket: WebSocket):
    """Real-time KPI broadcast — admin/manager only.
    Cookie auth (browser standard handshake): session_token cookie tekshiriladi.
    """
    # Cookie auth — manual tekshiruv (WebSocket'da Depends ishlamaydi standart yo'l bilan)
    cookies = websocket.cookies
    session_token = cookies.get("session_token")
    if not session_token:
        await websocket.close(code=1008, reason="Login talab qilindi")
        return
    user_data = get_user_from_token(session_token)
    if not user_data:
        await websocket.close(code=1008, reason="Session muddati tugadi")
        return
    user_id = _extract_user_id(user_data)
    if not user_id:
        await websocket.close(code=1008, reason="Invalid session")
        return
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            await websocket.close(code=1008, reason="Foydalanuvchi yo'q")
            return
        role = (getattr(user, "role", None) or "").strip().lower()
        if role not in ("admin", "manager", "rahbar", "raxbar", "menejer"):
            await websocket.close(code=1008, reason="Ruxsat yo'q")
            return
    finally:
        db.close()

    await bus.connect(websocket)
    try:
        # Ping/pong va idle keep-alive — client istalgan vaqt yuborishi mumkin
        while True:
            msg = await websocket.receive_text()
            # Echo ping uchun
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        bus.disconnect(websocket)
