"""
Yetkazib berish — haydovchilar, yetkazishlar, xarita, supervayzer.
"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from app.core import templates
from app.models.database import (
    get_db,
    Driver,
    DriverLocation,
    Delivery,
    Agent,
    AgentLocation,
    Visit,
    Partner,
    PartnerLocation,
    Order,
    User,
    AgentPayment,
    Payment,
    CashRegister,
    Product,
    Stock,
)
from app.deps import require_admin, require_admin_or_manager
from app.services.stock_service import create_stock_movement, delete_stock_movements_for_document
from app.constants import QUERY_LIMIT_DEFAULT, QUERY_LIMIT_HISTORY
from urllib.parse import quote
from sqlalchemy.orm import joinedload
from sqlalchemy import func
from app.logging_config import get_logger

logger = get_logger("delivery_routes")
router = APIRouter(tags=["delivery"])


@router.get("/delivery", response_class=HTMLResponse)
async def delivery_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    drivers = db.query(Driver).all()
    today = datetime.now().date()
    driver_ids = [d.id for d in drivers]
    # Batch loadlar (3N -> 3 ta umumiy query)
    last_loc_map: dict = {}
    today_count_map: dict = {}
    pending_count_map: dict = {}
    if driver_ids:
        # Oxirgi DriverLocation per driver — MAX(id) GROUP BY + load
        max_loc_ids = [
            r.max_id for r in
            db.query(DriverLocation.driver_id, func.max(DriverLocation.id).label("max_id"))
            .filter(DriverLocation.driver_id.in_(driver_ids))
            .group_by(DriverLocation.driver_id).all()
            if r.max_id
        ]
        if max_loc_ids:
            for loc in db.query(DriverLocation).filter(DriverLocation.id.in_(max_loc_ids)).all():
                last_loc_map[loc.driver_id] = loc
        # Bugungi yetkazishlar soni
        for r in (
            db.query(Delivery.driver_id, func.count(Delivery.id).label("cnt"))
            .filter(Delivery.driver_id.in_(driver_ids), Delivery.created_at >= today)
            .group_by(Delivery.driver_id).all()
        ):
            today_count_map[r.driver_id] = r.cnt
        # Pending yetkazishlar soni
        for r in (
            db.query(Delivery.driver_id, func.count(Delivery.id).label("cnt"))
            .filter(Delivery.driver_id.in_(driver_ids), Delivery.status == "pending")
            .group_by(Delivery.driver_id).all()
        ):
            pending_count_map[r.driver_id] = r.cnt
    for driver in drivers:
        driver.last_location = last_loc_map.get(driver.id)
        driver.today_deliveries = today_count_map.get(driver.id, 0)
        driver.pending_deliveries = pending_count_map.get(driver.id, 0)
    deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).limit(50).all()
    return templates.TemplateResponse("delivery/list.html", {
        "request": request,
        "current_user": current_user,
        "drivers": drivers,
        "deliveries": deliveries,
        "page_title": "Yetkazib berish",
    })


@router.post("/drivers/add")
async def driver_add(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    vehicle_number: str = Form(""),
    vehicle_type: str = Form(""),
    telegram_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    last_driver = db.query(Driver).order_by(Driver.id.desc()).first()
    code = f"DR{str((last_driver.id if last_driver else 0) + 1).zfill(3)}"
    driver = Driver(
        code=code,
        full_name=full_name,
        phone=phone,
        vehicle_number=vehicle_number,
        vehicle_type=vehicle_type,
        telegram_id=telegram_id,
        is_active=True,
    )
    db.add(driver)
    db.commit()
    return RedirectResponse(url="/delivery", status_code=303)


@router.get("/delivery/{driver_id}", response_class=HTMLResponse)
async def driver_detail(
    request: Request,
    driver_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if not driver:
        raise HTTPException(status_code=404, detail="Haydovchi topilmadi")
    locations = (
        db.query(DriverLocation)
        .filter(DriverLocation.driver_id == driver_id)
        .order_by(DriverLocation.recorded_at.desc())
        .limit(100)
        .all()
    )
    deliveries = (
        db.query(Delivery)
        .filter(Delivery.driver_id == driver_id)
        .order_by(Delivery.created_at.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse("delivery/detail.html", {
        "request": request,
        "current_user": current_user,
        "driver": driver,
        "locations": locations,
        "deliveries": deliveries,
        "page_title": f"Haydovchi: {driver.full_name}",
        "yandex_maps_apikey": _get_yandex_apikey(),
    })


@router.get("/map", response_class=HTMLResponse)
async def map_view(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    agent_markers = []
    for agent in agents:
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            agent_markers.append({
                "id": agent.id,
                "name": agent.full_name,
                "type": "agent",
                "lat": last_loc.latitude,
                "lng": last_loc.longitude,
                "time": last_loc.recorded_at.strftime("%H:%M"),
            })
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    driver_markers = []
    for driver in drivers:
        last_loc = (
            db.query(DriverLocation)
            .filter(DriverLocation.driver_id == driver.id)
            .order_by(DriverLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            driver_markers.append({
                "id": driver.id,
                "name": driver.full_name,
                "type": "driver",
                "lat": last_loc.latitude,
                "lng": last_loc.longitude,
                "time": last_loc.recorded_at.strftime("%H:%M"),
                "vehicle": driver.vehicle_number,
            })
    # Agent dict (id -> name)
    agent_dict = {a.id: a.full_name for a in agents}
    # Partner mijozlar + agent statistika
    all_partners = db.query(Partner).filter(Partner.is_active == True).all()
    # Agent bo'yicha mijozlar soni (jami va xaritadagi)
    agent_partner_total = {}
    for p in all_partners:
        aid = p.agent_id or 0
        agent_partner_total[aid] = agent_partner_total.get(aid, 0) + 1

    partner_markers = []
    agent_partner_on_map = {}
    seen_ids = set()
    # 1) Partner.latitude/longitude dan
    for p in all_partners:
        if p.latitude and p.longitude:
            aid = p.agent_id or 0
            agent_partner_on_map[aid] = agent_partner_on_map.get(aid, 0) + 1
            seen_ids.add(p.id)
            partner_markers.append({
                "id": p.id, "name": p.name, "type": "partner",
                "lat": p.latitude, "lng": p.longitude,
                "address": p.address or "",
                "agent_id": aid,
                "agent_name": agent_dict.get(aid, "Tayinlanmagan"),
            })
    # 2) PartnerLocation dan (Partner.lat bo'sh bo'lganlar)
    partner_locations = db.query(PartnerLocation).all()
    for loc in partner_locations:
        if loc.partner_id in seen_ids or not loc.latitude or not loc.longitude:
            continue
        partner = db.query(Partner).filter(Partner.id == loc.partner_id).first()
        if partner:
            aid = partner.agent_id or 0
            agent_partner_on_map[aid] = agent_partner_on_map.get(aid, 0) + 1
            seen_ids.add(partner.id)
            partner_markers.append({
                "id": loc.partner_id, "name": partner.name, "type": "partner",
                "lat": loc.latitude, "lng": loc.longitude,
                "address": loc.address or partner.address or "",
                "agent_id": aid,
                "agent_name": agent_dict.get(aid, "Tayinlanmagan"),
            })
    # Agent ro'yxati (chap panel uchun)
    agent_list = []
    for a in agents:
        on_map = agent_partner_on_map.get(a.id, 0)
        total = agent_partner_total.get(a.id, 0)
        if total > 0:
            agent_list.append({"id": a.id, "name": a.full_name, "on_map": on_map, "total": total})
    # Tayinlanmagan
    unassigned_on_map = agent_partner_on_map.get(0, 0)
    unassigned_total = agent_partner_total.get(0, 0)
    try:
        from app.config.maps_config import MAP_PROVIDER
        map_provider = MAP_PROVIDER
    except Exception:
        map_provider = "yandex"
    try:
        from app.config.maps_config import YANDEX_MAPS_API_KEY
        yandex_apikey = YANDEX_MAPS_API_KEY or ""
    except Exception:
        yandex_apikey = ""
    return templates.TemplateResponse("map/index.html", {
        "request": request,
        "current_user": current_user,
        "agents": agents,
        "drivers": drivers,
        "partner_locations": partner_locations,
        "agent_markers": agent_markers,
        "driver_markers": driver_markers,
        "partner_markers": partner_markers,
        "region_markers": [],
        "map_provider": map_provider,
        "yandex_maps_apikey": yandex_apikey,
        "agent_list": agent_list,
        "unassigned_on_map": unassigned_on_map,
        "unassigned_total": unassigned_total,
        "page_title": "Xarita",
    })


@router.get("/supervisor", response_class=HTMLResponse)
async def supervisor_dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_admin_or_manager)):
    today = datetime.now().date()
    total_agents = db.query(Agent).filter(Agent.is_active == True).count()
    active_agents = 0
    for agent in db.query(Agent).filter(Agent.is_active == True).all():
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id, AgentLocation.recorded_at >= today)
            .first()
        )
        if last_loc:
            active_agents += 1
    today_visits = db.query(Visit).filter(Visit.visit_date >= today).count()
    today_orders = db.query(Order).filter(Order.type == "sale", Order.date >= today).all()
    today_sales_sum = sum(o.total for o in today_orders)
    total_drivers = db.query(Driver).filter(Driver.is_active == True).count()
    pending_deliveries = db.query(Delivery).filter(Delivery.status == "pending").count()
    today_delivered = (
        db.query(Delivery)
        .filter(Delivery.status == "delivered", Delivery.delivered_at >= today)
        .count()
    )
    agent_stats = []
    for agent in db.query(Agent).filter(Agent.is_active == True).all():
        visits = db.query(Visit).filter(Visit.agent_id == agent.id, Visit.visit_date >= today).count()
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        agent_stats.append({
            "agent": agent,
            "visits": visits,
            "last_seen": last_loc.recorded_at if last_loc else None,
            "is_online": last_loc and (datetime.now() - last_loc.recorded_at).seconds < 600 if last_loc else False,
        })
    agent_stats.sort(key=lambda x: x["visits"], reverse=True)
    # O'tgan hafta vizitlar
    from datetime import timedelta
    week_ago = today - timedelta(days=7)
    visits_week = db.query(Visit).filter(Visit.visit_date >= week_ago).count()
    # Yo'ldagi yetkazishlar
    in_transit = db.query(Delivery).filter(Delivery.status.in_(["pending", "in_transit"])).count()
    stats = {
        "total_agents": total_agents,
        "active_agents": active_agents,
        "today_visits": today_visits,
        "visits_today": today_visits,
        "visits_week": visits_week,
        "today_orders": len(today_orders),
        "today_sales": today_sales_sum,
        "total_drivers": total_drivers,
        "pending_deliveries": pending_deliveries,
        "today_delivered": today_delivered,
        "delivered_today": today_delivered,
        "in_transit": in_transit,
    }
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    # Agent va driver markerlar (mini xarita uchun)
    agent_markers = []
    for agent in agents:
        last_loc = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            agent.last_location = last_loc
            agent.is_online = (datetime.now() - last_loc.recorded_at).total_seconds() < 600
            if last_loc.latitude is not None and last_loc.longitude is not None:
                agent_markers.append({
                    "id": agent.id,
                    "name": agent.full_name,
                    "type": "agent",
                    "lat": float(last_loc.latitude),
                    "lng": float(last_loc.longitude),
                    "time": last_loc.recorded_at.strftime("%H:%M"),
                })
        else:
            agent.is_online = False
    driver_markers = []
    for driver in drivers:
        last_loc = (
            db.query(DriverLocation)
            .filter(DriverLocation.driver_id == driver.id)
            .order_by(DriverLocation.recorded_at.desc())
            .first()
        )
        if last_loc:
            driver.last_location = last_loc
            if last_loc.latitude is not None and last_loc.longitude is not None:
                driver_markers.append({
                    "id": driver.id,
                    "name": driver.full_name,
                    "type": "driver",
                    "lat": float(last_loc.latitude),
                    "lng": float(last_loc.longitude),
                    "time": last_loc.recorded_at.strftime("%H:%M"),
                    "vehicle": driver.vehicle_number or "",
                })
    recent_visits = db.query(Visit).filter(Visit.visit_date >= today).order_by(Visit.visit_date.desc()).limit(20).all()
    recent_deliveries = db.query(Delivery).order_by(Delivery.created_at.desc()).limit(10).all()
    # Agent buyurtmalari (bugungi)
    agent_orders = (
        db.query(Order)
        .filter(Order.source == "agent", Order.date >= today)
        .order_by(Order.created_at.desc())
        .limit(20)
        .all()
    )

    # Oylik savdo rejasi widget (joriy oy)
    from app.models.database import SalesPlan
    month_start = today.replace(day=1)
    current_period = today.strftime("%Y-%m")
    sales_plan = db.query(SalesPlan).filter(SalesPlan.period == current_period).first()
    plan_amount = float(sales_plan.amount) if sales_plan else 0.0
    sales_plan_rows = []
    for agent in agents:
        sold = db.query(func.coalesce(func.sum(Order.total), 0)).filter(
            Order.agent_id == agent.id,
            Order.source == "agent",
            Order.type == "sale",  # return_sale (obmen qaytarish) rejaga kirmasin
            Order.status.in_(("confirmed", "completed", "waiting_production", "delivered")),
            Order.date >= month_start,
        ).scalar() or 0.0
        sold = float(sold)
        pct = round((sold / plan_amount * 100), 1) if plan_amount > 0 else 0.0
        sales_plan_rows.append({"agent": agent, "sold": sold, "percent": pct})
    sales_plan_rows.sort(key=lambda x: x["sold"], reverse=True)

    return templates.TemplateResponse("supervisor/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "stats": stats,
        "agents": agents,
        "drivers": drivers,
        "agent_markers": agent_markers,
        "driver_markers": driver_markers,
        "agent_stats": agent_stats[:10],
        "recent_visits": recent_visits,
        "recent_deliveries": recent_deliveries,
        "agent_orders": agent_orders,
        "agent_payments": [p for p in _get_pending_agent_payments(db)],
        "sales_plan_amount": plan_amount,
        "sales_plan_period": current_period,
        "sales_plan_rows": sales_plan_rows,
        "yandex_maps_apikey": _get_yandex_apikey(),
        "page_title": "Supervayzer",
        "now": datetime.now(),
    })


@router.get("/supervisor/agent-orders", response_class=HTMLResponse)
async def supervisor_agent_orders(
    request: Request,
    status: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmalari alohida sahifa — tasdiqlash va yetkazishga berish."""
    q = db.query(Order).filter(Order.source == "agent").options(
        joinedload(Order.partner), joinedload(Order.items)
    )
    if status and status != "all":
        q = q.filter(Order.status == status)
    orders = q.order_by(Order.created_at.desc()).limit(100).all()
    # Topilma 2A: waiting_production buyurtma uchun qaysi Production (qaysi mahsulot) ko'rsatilsin
    from app.models.database import Production as _Production, Stock as _Stock
    production_info = {}
    missing_items = {}  # {order_id: [{product, need, have, missing}]}
    _wp_orders = [o for o in orders if o.status == "waiting_production"]
    _wp_ids = [o.id for o in _wp_orders]
    if _wp_ids:
        for p in db.query(_Production).options(joinedload(_Production.recipe)).filter(
            _Production.order_id.in_(_wp_ids)
        ).all():
            rn = getattr(getattr(p, "recipe", None), "name", None) or "—"
            production_info.setdefault(p.order_id, []).append(
                f"{p.number} · {rn} · {float(p.quantity or 0):g} · {p.status}"
            )
        # Yetishmayotgan mahsulotlarni hisoblash (har order uchun)
        for o in _wp_orders:
            missing = []
            for it in (o.items or []):
                if not it.product_id or not (it.quantity or 0) > 0:
                    continue
                wh_id = it.warehouse_id or o.warehouse_id
                if not wh_id:
                    continue
                stock = db.query(_Stock).filter(
                    _Stock.warehouse_id == wh_id, _Stock.product_id == it.product_id
                ).first()
                have = float(stock.quantity or 0) if stock else 0.0
                need = float(it.quantity or 0)
                gap = need - have
                if gap > 0.01:
                    pname = it.product.name if it.product else f"#{it.product_id}"
                    missing.append({"product": pname, "need": need, "have": have, "missing": gap})
            if missing:
                missing_items[o.id] = missing
    drivers = db.query(Driver).filter(Driver.is_active == True).all()
    agents = db.query(Agent).filter(Agent.is_active == True).all()
    draft_count = db.query(func.count(Order.id)).filter(Order.source == "agent", Order.status == "draft").scalar() or 0
    waiting_count = db.query(func.count(Order.id)).filter(Order.source == "agent", Order.status == "waiting_production").scalar() or 0
    return templates.TemplateResponse("supervisor/agent_orders.html", {
        "request": request,
        "current_user": current_user,
        "orders": orders,
        "drivers": drivers,
        "agents": agents,
        "current_status": status,
        "draft_count": draft_count,
        "waiting_count": waiting_count,
        "production_info": production_info,
        "missing_items": missing_items,
        "page_title": "Agent buyurtmalari",
    })


@router.post("/supervisor/agent-orders/confirm/{order_id}")
async def supervisor_confirm_agent_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmasini tasdiqlash — faqat status o'zgaradi.

    Yangi flow (POS bilan moslashtirilgan, 2026-05-12):
      1) confirm  → status='confirmed' (stock/balance/Delivery TEGMAYDI)
      2) dispatch (/sales/{id}/dispatch) → stock chiqarish + Delivery yaratish
      3) driver "Yetkazdim" → partner balance + delivered

    return_sale (obmen qaytarish) ham endi oddiy sotuv kabi dispatch → driver
    oqimidan o'tadi. Qaytgan tovar jismonan haydovchi "Yetkazdim" bosganda keladi
    (apply_return_stock_addition shu yerda emas, api_driver_ops.py da chaqiriladi).
    """
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    if order.status not in ("draft",):
        return RedirectResponse(url="/supervisor/agent-orders?error=already_confirmed", status_code=303)

    # D4 audit fix: agent buyurtma tasdiqlashda kredit limit tekshiruvi (soft guard).
    # Balance dispatch/delivered bosqichida yoziladi, lekin foydalanuvchini erta ogohlantirish uchun
    # qoldirilgan.
    if order.type != "return_sale" and order.partner_id and float(order.debt or 0) > 0:
        from app.services.partner_credit import check_credit_limit
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        ok, err = check_credit_limit(partner, float(order.debt or 0))
        if not ok:
            return RedirectResponse(
                url="/supervisor/agent-orders?error=" + quote(err),
                status_code=303,
            )

    # Atomik UPDATE WHERE — double-confirm xavfini oldini olish.
    from sqlalchemy import text as _text
    claim = db.execute(
        _text("UPDATE orders SET status='confirmed' WHERE id=:id AND source='agent' AND status='draft'"),
        {"id": order_id},
    )
    if claim.rowcount == 0:
        return RedirectResponse(url="/supervisor/agent-orders?error=already_confirmed", status_code=303)
    db.refresh(order)

    # Oddiy sotuv VA obmen (return_sale): faqat status va user_id.
    # Stock/balance/Delivery — dispatch bosqichida; obmen qaytgan tovar kirimi
    # haydovchi "Yetkazdim" bosganda (api_driver_ops.py) amalga oshiriladi.
    order.user_id = current_user.id
    # Obmen child (yangi sotuv) ham birga tasdiqlanadi — dispatch UI tugmasi
    # ex_child.status=='confirmed' shartiga bog'liq (agents/detail.html).
    # b881e3c'da bu blok early-return va apply_return_stock_addition bilan birga
    # noto'g'ri o'chirilgan edi (regressiya, 2 orphan: AGT-20260518-005,
    # AGT-20260519-011); endi tiklandi.
    if order.type == "return_sale":
        db.execute(
            _text("UPDATE orders SET status='confirmed', user_id=:uid "
                  "WHERE parent_order_id=:pid AND type='sale' AND status='draft'"),
            {"uid": current_user.id, "pid": order.id},
        )
    db.commit()
    try:
        from app.services.realtime_bus import publish_event
        publish_event("order_board")
    except Exception:
        pass
    try:
        from app.bot.services.audit_watchdog import audit_agent_order_confirm
        audit_agent_order_confirm(order.id)
    except Exception:
        pass
    return RedirectResponse(url="/supervisor/agent-orders", status_code=303)


@router.post("/supervisor/agent-orders/reject/{order_id}")
async def supervisor_reject_agent_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmasini bekor qilish."""
    # Race condition oldini olish
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").with_for_update().first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    # Bug 1 — paid > 0 bo'lgan orderni darhol bekor qilish taqiqlanadi (refund kerak)
    if (order.paid or 0) > 0:
        referer = request.headers.get("referer", "/supervisor/agent-orders")
        sep = "&" if "?" in referer else "?"
        return RedirectResponse(
            url=f"{referer}{sep}error=paid_block&detail=" + quote(
                f"Bu buyurtmaga {order.paid:,.0f} so'm to'lov qabul qilingan. Avval refund qiling, keyin bekor qilish mumkin."
            ),
            status_code=303,
        )
    # Agar tasdiqlangan bo'lsa — stock qaytarish + yetkazishni ham bekor qilish
    if order.status == "confirmed":
        for it in order.items:
            if not it.product_id or not (it.quantity or 0) > 0:
                continue
            wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
            if not wh_id:
                continue
            create_stock_movement(
                db=db,
                warehouse_id=wh_id,
                product_id=it.product_id,
                quantity_change=+float(it.quantity or 0),
                operation_type="sale_revert",
                document_type="Sale",
                document_id=order.id,
                document_number=order.number,
                user_id=current_user.id if current_user else None,
                note=f"Agent buyurtma bekor (reject): {order.number}",
                created_at=datetime.now(),
            )
        from app.models.database import Delivery as DeliveryModel
        # Bug 6 — failed delivery ham cancelled bo'lsin
        for delivery in db.query(DeliveryModel).filter(
            DeliveryModel.order_id == order.id,
            DeliveryModel.status.in_(["pending", "in_progress", "failed"]),
        ).all():
            delivery.status = "cancelled"
    order.status = "cancelled"
    # Site 1: delivery_revert — recompute partner balance after order cancelled
    if order.partner_id:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, order.partner_id,
            reason="delivery_revert",
            ref=order.number,
            actor=current_user.username if current_user else None,
        )
    db.commit()
    referer = request.headers.get("referer", "/supervisor/agent-orders")
    return RedirectResponse(url=referer, status_code=303)


@router.post("/supervisor/agent-orders/delete/{order_id}")
async def supervisor_delete_agent_order(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent buyurtmasini o'chirish (faqat bekor qilingan yoki draft).
    Obmen juftligi (return_sale + parent_order_id'li child sale) avtomatik birga o'chiriladi.
    """
    from app.models.database import OrderItem as OI, Delivery as DeliveryModel
    order = db.query(Order).filter(Order.id == order_id, Order.source == "agent").first()
    if not order:
        return RedirectResponse(url="/supervisor/agent-orders?error=not_found", status_code=303)
    if order.status == "confirmed":
        return RedirectResponse(
            url="/supervisor/agent-orders?error=confirmed_delete&detail=" + quote("Tasdiqlangan buyurtmani to'g'ridan-to'g'ri o'chirib bo'lmaydi. Avval bekor qiling."),
            status_code=303,
        )

    # Obmen juftligini topish (FK constraint uchun ikkalasini birga o'chirish kerak)
    to_delete = [order]
    if order.type == "return_sale":
        # Parent ret_order: child sale topib qo'shish
        child = db.query(Order).filter(Order.parent_order_id == order.id, Order.type == "sale").first()
        if child:
            if child.status not in ("draft", "cancelled"):
                return RedirectResponse(
                    url="/supervisor/agent-orders?error=obmen_pair&detail=" + quote(
                        f"Bu obmen juftligi: child {child.number} status='{child.status}'. Avval ikkalasini bekor qiling."
                    ),
                    status_code=303,
                )
            to_delete.append(child)
    elif order.parent_order_id:
        # Child sale: parent ret_order topib qo'shish (agar mavjud bo'lsa va ham cancelled bo'lsa)
        parent = db.query(Order).filter(Order.id == order.parent_order_id).first()
        if parent and parent.status in ("draft", "cancelled"):
            to_delete.append(parent)
        elif parent:
            return RedirectResponse(
                url="/supervisor/agent-orders?error=obmen_pair&detail=" + quote(
                    f"Bu obmen yangi sotuvi: parent {parent.number} status='{parent.status}'. Avval ikkalasini bekor qiling."
                ),
                status_code=303,
            )

    for o in to_delete:
        if o.status == "cancelled":
            delete_stock_movements_for_document(db, "Sale", o.id)
        db.query(DeliveryModel).filter(DeliveryModel.order_id == o.id).delete()
        db.query(OI).filter(OI.order_id == o.id).delete()

    # Sale child avval o'chirilsin (FK constraint), keyin parent ret_order.
    # SQLAlchemy executemany ni oldini olish uchun flush() har biri uchun chaqiriladi.
    to_delete.sort(key=lambda o: 0 if o.parent_order_id else 1)
    for o in to_delete:
        db.delete(o)
        db.flush()  # Majburiy: SQLAlchemy batch deletes ni qilmasin
    db.commit()
    return RedirectResponse(url="/supervisor/agent-orders", status_code=303)


def _get_yandex_apikey():
    try:
        from app.config.maps_config import YANDEX_MAPS_API_KEY
        return YANDEX_MAPS_API_KEY or ""
    except Exception:
        return ""


def _get_pending_agent_payments(db):
    payments = db.query(AgentPayment).filter(AgentPayment.status == "pending").order_by(AgentPayment.id.desc()).limit(20).all()
    for p in payments:
        p._agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first()
    return payments


# ==========================================
# SUPERVISOR: AGENT TO'LOVLARI (INKASSATSIYA)
# ==========================================

@router.get("/supervisor/agent-payments", response_class=HTMLResponse)
async def supervisor_agent_payments(
    request: Request,
    status: str = "all",
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent va Haydovchi to'lovlari ro'yxati — supervisor tasdiqlash uchun."""
    # Sana filtri (default: so'nggi 30 kun — supervisor inkasatsiya darchasi)
    from datetime import datetime as _dt, date as _date, timedelta as _td
    today = _date.today()
    default_from = today - _td(days=30)
    try:
        d_from = _dt.strptime(date_from, "%Y-%m-%d").date() if date_from else default_from
    except (ValueError, TypeError):
        d_from = default_from
    try:
        d_to = _dt.strptime(date_to, "%Y-%m-%d").date() if date_to else today
    except (ValueError, TypeError):
        d_to = today
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    q = db.query(AgentPayment).filter(
        func.date(AgentPayment.created_at) >= d_from,
        func.date(AgentPayment.created_at) <= d_to,
    ).order_by(AgentPayment.id.desc())
    if status == "pending":
        q = q.filter(AgentPayment.status == "pending")
    elif status == "confirmed":
        q = q.filter(AgentPayment.status == "confirmed")
    elif status == "cancelled":
        q = q.filter(AgentPayment.status == "cancelled")
    payments = q.limit(QUERY_LIMIT_DEFAULT).all()
    for p in payments:
        p._agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first()

    # Haydovchi to'lovlari (Payment.category='delivery') — sana filtri bilan
    from app.models.database import Payment as _Payment
    dq = db.query(_Payment).filter(
        _Payment.category == "delivery",
        func.date(_Payment.date) >= d_from,
        func.date(_Payment.date) <= d_to,
    ).order_by(_Payment.id.desc())
    if status == "confirmed":
        dq = dq.filter(_Payment.status == "confirmed")
    driver_payments = dq.limit(QUERY_LIMIT_DEFAULT).all()
    for p in driver_payments:
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first() if p.partner_id else None
        # Description'dan delivery raqamini chiqarib olish va Driver topish
        p._driver = None
        if p.user_id:
            from app.models.database import Driver as _Driver
            p._driver = (
                db.query(_Driver)
                .filter((_Driver.employee_id == p.user_id) | (_Driver.id == p.user_id))
                .first()
            )

    # Haydovchi qarz balansi: har haydovchi qo'lida qancha pul (pending)
    from sqlalchemy import func as _func
    from app.models.database import Driver as _Driver
    pending_q = (
        db.query(
            _Payment.user_id,
            _func.sum(_Payment.amount).label("total"),
            _func.count(_Payment.id).label("cnt"),
        )
        .filter(_Payment.category == "delivery", _Payment.status == "pending", _Payment.user_id != None)
        .group_by(_Payment.user_id)
        .all()
    )
    driver_balances = []
    for user_id, total, cnt in pending_q:
        drv = (
            db.query(_Driver)
            .filter((_Driver.employee_id == user_id) | (_Driver.id == user_id))
            .first()
        )
        driver_balances.append({
            "driver_name": drv.full_name if drv else f"user#{user_id}",
            "driver_code": drv.code if drv else "",
            "amount": float(total or 0),
            "count": int(cnt or 0),
        })
    driver_balances.sort(key=lambda x: -x["amount"])
    total_pending = sum(d["amount"] for d in driver_balances)

    # Tanlangan davr jamisi (filtered driver_payments uchun)
    range_total = sum(float(p.amount or 0) for p in driver_payments)
    range_pending = sum(float(p.amount or 0) for p in driver_payments if p.status == "pending")
    range_confirmed = sum(float(p.amount or 0) for p in driver_payments if p.status == "confirmed")

    # Agent va Driver to'lovlari uchun jamlamalar (umumiy + to'lov turi bo'yicha)
    def _breakdown(items):
        bd = {}
        for it in items:
            key = (it.payment_type or "—").lower()
            bd[key] = bd.get(key, 0.0) + float(it.amount or 0)
        return bd

    agent_total = sum(float(p.amount or 0) for p in payments)
    agent_count = len(payments)
    agent_confirmed = sum(float(p.amount or 0) for p in payments if p.status == "confirmed")
    agent_pending = sum(float(p.amount or 0) for p in payments if p.status == "pending")
    agent_by_type = _breakdown(payments)
    driver_by_type = _breakdown(driver_payments)

    return templates.TemplateResponse("supervisor/agent_payments.html", {
        "request": request,
        "payments": payments,
        "driver_payments": driver_payments,
        "driver_balances": driver_balances,
        "total_pending": total_pending,
        "status_filter": status,
        "date_from": d_from.isoformat(),
        "date_to": d_to.isoformat(),
        "today_iso": today.isoformat(),
        "range_total": range_total,
        "range_pending": range_pending,
        "range_confirmed": range_confirmed,
        "agent_total": agent_total,
        "agent_count": agent_count,
        "agent_confirmed": agent_confirmed,
        "agent_pending": agent_pending,
        "agent_by_type": agent_by_type,
        "driver_by_type": driver_by_type,
        "current_user": current_user,
    })


@router.get("/supervisor/agent-payments/export")
async def supervisor_agent_payments_export(
    request: Request,
    status: str = "all",
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent va Haydovchi to'lovlarini Excel'ga eksport qilish."""
    import io
    from datetime import datetime as _dt, date as _date, timedelta as _td
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    today = _date.today()
    default_from = today - _td(days=30)
    try:
        d_from = _dt.strptime(date_from, "%Y-%m-%d").date() if date_from else default_from
    except (ValueError, TypeError):
        d_from = default_from
    try:
        d_to = _dt.strptime(date_to, "%Y-%m-%d").date() if date_to else today
    except (ValueError, TypeError):
        d_to = today
    if d_from > d_to:
        d_from, d_to = d_to, d_from

    q = db.query(AgentPayment).filter(
        func.date(AgentPayment.created_at) >= d_from,
        func.date(AgentPayment.created_at) <= d_to,
    ).order_by(AgentPayment.id.desc())
    if status in ("pending", "confirmed", "cancelled"):
        q = q.filter(AgentPayment.status == status)
    ap_rows = q.all()
    for p in ap_rows:
        p._agent = db.query(Agent).filter(Agent.id == p.agent_id).first()
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first()

    from app.models.database import Payment as _Payment, Driver as _Driver
    dq = db.query(_Payment).filter(
        _Payment.category == "delivery",
        func.date(_Payment.date) >= d_from,
        func.date(_Payment.date) <= d_to,
    ).order_by(_Payment.id.desc())
    if status == "confirmed":
        dq = dq.filter(_Payment.status == "confirmed")
    dp_rows = dq.all()
    for p in dp_rows:
        p._partner = db.query(Partner).filter(Partner.id == p.partner_id).first() if p.partner_id else None
        p._driver = None
        if p.user_id:
            p._driver = (
                db.query(_Driver)
                .filter((_Driver.employee_id == p.user_id) | (_Driver.id == p.user_id))
                .first()
            )

    status_label_map = {
        "pending": "Kutilmoqda",
        "confirmed": "Tasdiqlangan",
        "cancelled": "Rad etilgan",
    }
    type_label_map = {"naqd": "Naqd", "plastik": "Plastik", "perechisleniye": "Perechisleniye"}

    wb = Workbook()
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    bold_font = Font(bold=True)
    total_fill = PatternFill(start_color="E7E6E6", end_color="E7E6E6", fill_type="solid")

    # --- Sheet 1: Agent to'lovlari ---
    ws1 = wb.active
    ws1.title = "Agent to'lovlari"
    ws1["A1"] = f"Agent to'lovlari (inkassatsiya) — {d_from} dan {d_to} gacha"
    ws1["A1"].font = Font(bold=True, size=14)
    ws1.merge_cells("A1:H1")
    headers1 = ["#", "Sana", "Agent", "Mijoz", "Kod", "Summa (so'm)", "Tur", "Status", "Izoh"]
    for col, h in enumerate(headers1, 1):
        cell = ws1.cell(row=3, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    ap_total = 0.0
    ap_by_type = {}
    for i, p in enumerate(ap_rows, 1):
        agent_name = p._agent.full_name if p._agent else f"Agent #{p.agent_id}"
        partner_name = p._partner.name if p._partner else ""
        partner_code = p._partner.code if p._partner else ""
        amount = float(p.amount or 0)
        ptype = type_label_map.get(p.payment_type, p.payment_type or "")
        st = status_label_map.get(p.status, p.status or "")
        ws1.append([
            i,
            p.created_at.strftime("%d.%m.%Y %H:%M") if p.created_at else "",
            agent_name,
            partner_name,
            partner_code,
            amount,
            ptype,
            st,
            p.notes or "",
        ])
        ap_total += amount
        ap_by_type[ptype] = ap_by_type.get(ptype, 0.0) + amount

    last_row = 3 + len(ap_rows) + 1
    ws1.cell(row=last_row, column=1, value=f"JAMI: {len(ap_rows)} ta").font = bold_font
    ws1.cell(row=last_row, column=6, value=ap_total).font = bold_font
    for col in range(1, 10):
        ws1.cell(row=last_row, column=col).fill = total_fill
    row_n = last_row + 1
    for ptype, amount in ap_by_type.items():
        ws1.cell(row=row_n, column=5, value=f"{ptype}:").font = bold_font
        ws1.cell(row=row_n, column=6, value=amount).font = bold_font
        row_n += 1

    widths1 = [6, 18, 22, 30, 10, 16, 16, 16, 30]
    for col, w in enumerate(widths1, 1):
        ws1.column_dimensions[chr(64 + col)].width = w

    # --- Sheet 2: Haydovchi to'lovlari ---
    ws2 = wb.create_sheet("Haydovchi to'lovlari")
    ws2["A1"] = f"Haydovchi to'lovlari (yetkazish davomida) — {d_from} dan {d_to} gacha"
    ws2["A1"].font = Font(bold=True, size=14)
    ws2.merge_cells("A1:I1")
    headers2 = ["#", "Hujjat raqami", "Sana", "Haydovchi", "Mijoz", "Kod", "Summa (so'm)", "Tur", "Status"]
    for col, h in enumerate(headers2, 1):
        cell = ws2.cell(row=3, column=col, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    dp_total = 0.0
    dp_by_type = {}
    for i, p in enumerate(dp_rows, 1):
        driver_name = p._driver.full_name if p._driver else "—"
        partner_name = p._partner.name if p._partner else ""
        partner_code = p._partner.code if p._partner else ""
        amount = float(p.amount or 0)
        ptype = type_label_map.get(p.payment_type, p.payment_type or "")
        st = status_label_map.get(p.status, p.status or "")
        ws2.append([
            i,
            p.number or "",
            p.date.strftime("%d.%m.%Y %H:%M") if p.date else "",
            driver_name,
            partner_name,
            partner_code,
            amount,
            ptype,
            st,
        ])
        dp_total += amount
        dp_by_type[ptype] = dp_by_type.get(ptype, 0.0) + amount

    last_row = 3 + len(dp_rows) + 1
    ws2.cell(row=last_row, column=1, value=f"JAMI: {len(dp_rows)} ta").font = bold_font
    ws2.cell(row=last_row, column=7, value=dp_total).font = bold_font
    for col in range(1, 10):
        ws2.cell(row=last_row, column=col).fill = total_fill
    row_n = last_row + 1
    for ptype, amount in dp_by_type.items():
        ws2.cell(row=row_n, column=6, value=f"{ptype}:").font = bold_font
        ws2.cell(row=row_n, column=7, value=amount).font = bold_font
        row_n += 1

    widths2 = [6, 20, 18, 22, 30, 10, 16, 16, 16]
    for col, w in enumerate(widths2, 1):
        ws2.column_dimensions[chr(64 + col)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"agent_payments_{d_from}_{d_to}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/supervisor/agent-payments/confirm/{payment_id}")
async def supervisor_confirm_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini tasdiqlash — mijoz qarzidan ayirish va kassaga kirim qilish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if ap.status != "pending":
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)

    # Atomik UPDATE WHERE — double-confirm xavfini oldini olish
    from sqlalchemy import text as _text
    claim = db.execute(
        _text("UPDATE agent_payments SET status='confirmed', confirmed_by=:uid, confirmed_at=:at "
              "WHERE id=:id AND status='pending'"),
        {"id": payment_id, "uid": current_user.id, "at": datetime.now()}
    )
    if claim.rowcount == 0:
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)
    db.refresh(ap)

    # 2. Mijoz partner'ini olish (keyinroq recompute + notify uchun)
    partner = db.query(Partner).filter(Partner.id == ap.partner_id).first()

    # 3. Tegishli kassaga kirim qilish — payment_type bo'yicha qat'iy moslashtirish
    pay_type_map = {
        "naqd": "naqd",
        "plastik": "plastik",
        "perechisleniye": "perechisleniye",
        "click": "click",
        "terminal": "terminal",
    }
    ap_pay_type = (ap.payment_type or "").lower().strip()
    cash_type = pay_type_map.get(ap_pay_type)
    if not cash_type:
        db.rollback()
        return RedirectResponse(
            url="/supervisor/agent-payments?error=" + quote(
                f"Noma'lum to'lov turi: {ap.payment_type!r}. Admin bilan bog'laning."
            ),
            status_code=303,
        )
    cash_register = db.query(CashRegister).filter(
        CashRegister.payment_type == cash_type,
        CashRegister.is_active == True,
        CashRegister.currency == "UZS",
    ).order_by(CashRegister.id.asc()).first()
    if not cash_register:
        db.rollback()
        return RedirectResponse(
            url="/supervisor/agent-payments?error=" + quote(
                f"'{cash_type}' turidagi faol kassa topilmadi. Avval kassa yarating."
            ),
            status_code=303,
        )

    last_payment = db.query(Payment).order_by(Payment.id.desc()).first()
    next_num = (last_payment.id + 1) if last_payment else 1
    payment_number = f"AGT-{datetime.now().strftime('%Y%m%d')}-{next_num:04d}"

    payment = Payment(
        number=payment_number,
        date=datetime.now(),
        type="income",
        cash_register_id=cash_register.id,
        partner_id=ap.partner_id,
        amount=float(ap.amount or 0),
        payment_type=ap.payment_type,
        category="agent_collection",
        description=(
            f"Agent inkassatsiya: {partner.name if partner else ''}"
            + (f" — {ap.notes}" if ap.notes else "")
            + f" [AP#{ap.id}]"
        ),
        user_id=current_user.id,
        status="confirmed",
    )
    db.add(payment)
    logger.info(
        f"AP#{ap.id} confirmed: payment_type={ap_pay_type!r} -> kassa#{cash_register.id} ({cash_register.name!r}), amount={ap.amount}"
    )

    # 4. Buyurtmalar qarzini kamaytirish (FIFO — eng eski buyurtmadan boshlab)
    remaining = float(ap.amount or 0)
    if remaining > 0:
        debt_orders = (
            db.query(Order)
            .filter(Order.partner_id == ap.partner_id, Order.debt > 0, Order.type == "sale")
            .order_by(Order.date.asc())
            .all()
        )
        for order in debt_orders:
            if remaining <= 0:
                break
            order_debt = float(order.debt or 0)
            if order_debt <= 0:
                continue
            pay_this = min(remaining, order_debt)
            order.paid = float(order.paid or 0) + pay_this
            order.debt = order_debt - pay_this
            remaining -= pay_this

    # Site 2: agent_payment_confirm — recompute after Payment added + FIFO debt reduction
    if ap.partner_id:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, ap.partner_id,
            reason="agent_payment_confirm",
            ref=payment_number,
            actor=current_user.username if current_user else None,
        )

    db.commit()
    try:
        if partner is not None:
            from app.bot.customer_bot.notify import notify_customer, msg_agent_payment
            _agent = db.query(Agent).filter(Agent.id == ap.agent_id).first()
            notify_customer(ap.partner_id, msg_agent_payment(
                _agent.code if _agent else "", _agent.full_name if _agent else "",
                ap.amount, partner.balance))
    except Exception:
        pass
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/supervisor/agent-payments/reject/{payment_id}")
async def supervisor_reject_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini rad etish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if ap.status != "pending":
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)
    ap.status = "cancelled"
    ap.confirmed_by = current_user.id
    ap.confirmed_at = datetime.now()
    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/supervisor/agent-payments/confirm-driver/{payment_id}")
async def supervisor_confirm_driver_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Haydovchi yetkazish to'lovini tasdiqlash (inkassatsiya).

    Haydovchi mijozdan pul olib pending status bilan yaratgan. Admin tasdiqlasa:
    - Payment.status='confirmed'
    - Order.paid += amount, Order.debt -= amount (mijoz balansi kamayadi)
    """
    from sqlalchemy import text as _text
    p = db.query(Payment).filter(Payment.id == payment_id, Payment.category == "delivery").first()
    if not p:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if p.status != "pending":
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)

    # Atomik UPDATE WHERE + Payment.date'ni tasdiqlangan vaqtga ko'chirish.
    # created_at original audit izi sifatida o'zgarmaydi (haydovchi pul olgan vaqt).
    now = datetime.now()
    claim = db.execute(
        _text("UPDATE payments SET status='confirmed', date=:now "
              "WHERE id=:id AND status='pending' AND category='delivery'"),
        {"id": payment_id, "now": now},
    )
    if claim.rowcount == 0:
        return RedirectResponse(url="/supervisor/agent-payments?error=already_processed", status_code=303)
    db.refresh(p)

    # Order.paid yangilash — D3 audit fix: avval Payment.order_id (aniq order),
    # so'ng FIFO fallback (eski yozuvlar yoki order_id NULL bo'lsa)
    remaining = float(p.amount or 0)
    if remaining > 0 and p.partner_id:
        # 1) Payment.order_id bor bo'lsa, avval shu orderga qo'llash
        if p.order_id:
            target = db.query(Order).filter(Order.id == p.order_id).first()
            if target and float(target.debt or 0) > 0:
                target_debt = float(target.debt or 0)
                applied = min(target_debt, remaining)
                target.paid = float(target.paid or 0) + applied
                target.debt = target_debt - applied
                remaining -= applied
        # 2) Qoldiq bo'lsa FIFO bilan boshqa qarz orderlariga
        if remaining > 0:
            debt_orders = (
                db.query(Order)
                .filter(Order.partner_id == p.partner_id, Order.debt > 0, Order.type == "sale")
                .filter(Order.id != (p.order_id or 0))  # asosiy order ikki marta hisoblanmasin
                .order_by(Order.date.asc())
                .all()
            )
            for order in debt_orders:
                if remaining <= 0:
                    break
                order_debt = float(order.debt or 0)
                applied = min(order_debt, remaining)
                order.paid = float(order.paid or 0) + applied
                order.debt = order_debt - applied
                remaining -= applied

    # Site 3: driver payment confirm — recompute after Payment confirmed + order.paid updated
    if p.partner_id:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, p.partner_id,
            reason="agent_payment_confirm",
            ref=getattr(p, "number", None),
            actor=current_user.username if current_user else None,
        )

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments?info=" + quote("Haydovchi to'lovi tasdiqlandi"), status_code=303)


# ============================================================
# 2026-05-26: Haydovchi (delivery) Payment uchun revert/delete/edit
# AgentPayment uchun mavjud, Payment.delivery uchun yo'q edi.
# ============================================================

@router.post("/supervisor/agent-payments/revert-driver/{payment_id}")
async def supervisor_revert_driver_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Tasdiqlangan haydovchi to'lovini bekor qilish — Order.paid, Partner.balance qaytariladi.

    Status pending'ga qaytadi (qaytadan tasdiqlash mumkin).
    """
    p = db.query(Payment).filter(Payment.id == payment_id, Payment.category == "delivery").first()
    if not p:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if p.status != "confirmed":
        return RedirectResponse(url="/supervisor/agent-payments?error=not_confirmed", status_code=303)

    amount = float(p.amount or 0)

    # 1. Order.paid kamaytirish, debt qaytarish
    if p.order_id:
        order = db.query(Order).filter(Order.id == p.order_id).first()
        if order:
            order.paid = max(0.0, float(order.paid or 0) - amount)
            order.debt = float(order.debt or 0) + amount

    # 3. Payment status -> pending (payment no longer counted by recompute)
    p.status = "pending"

    # Site 4: driver payment cancel — recompute after Payment set to pending + order.debt restored
    if p.partner_id:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, p.partner_id,
            reason="agent_payment_cancel",
            ref=getattr(p, "number", None),
            actor=current_user.username if current_user else None,
        )

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments?info=" + quote("To'lov bekor qilindi"), status_code=303)


@router.post("/supervisor/agent-payments/delete-driver/{payment_id}")
async def supervisor_delete_driver_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Haydovchi to'lovini o'chirish.

    QOIDA (2026-05-26): Tasdiqlangan to'lov to'g'ridan-to'g'ri o'chirilmaydi.
    Avval `revert-driver` (bekor qilish), so'ng pending bo'lganda o'chirish mumkin.
    Bu xavfsizlik qoidasi — tasodifan tasdiqlangan hujjatni o'chirib qo'yish oldini oladi.
    """
    p = db.query(Payment).filter(Payment.id == payment_id, Payment.category == "delivery").first()
    if not p:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)

    if p.status == "confirmed":
        return RedirectResponse(
            url="/supervisor/agent-payments?error=" + quote("Tasdiqlangan to'lovni o'chirib bo'lmaydi. Avval 'Bekor qilish' tugmasini bosing."),
            status_code=303,
        )

    db.delete(p)
    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments?info=" + quote("To'lov o'chirildi"), status_code=303)


@router.post("/supervisor/agent-payments/edit-driver/{payment_id}")
async def supervisor_edit_driver_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Haydovchi to'lovini tahrirlash — yangi summa va to'lov turi.

    Tasdiqlangan to'lov uchun ham ishlaydi (avval revert qilib eski summani qaytaradi,
    keyin yangi summa bilan qayta tasdiqlaydi).
    """
    form = await request.form()
    new_amount = float(form.get("amount") or 0)
    new_pay_type = (form.get("payment_type") or "naqd").strip().lower()
    if new_amount <= 0:
        return RedirectResponse(url="/supervisor/agent-payments?error=invalid_amount", status_code=303)

    p = db.query(Payment).filter(Payment.id == payment_id, Payment.category == "delivery").first()
    if not p:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)

    old_amount = float(p.amount or 0)
    was_confirmed = p.status == "confirmed"

    # Agar confirmed edi: avval eski summa effektni qaytarish (order.paid/debt adjusted)
    if was_confirmed:
        if p.order_id:
            order = db.query(Order).filter(Order.id == p.order_id).first()
            if order:
                order.paid = max(0.0, float(order.paid or 0) - old_amount)
                order.debt = float(order.debt or 0) + old_amount

    # Yangi qiymatlarni yozish
    p.amount = new_amount
    p.payment_type = new_pay_type

    # Cash register'ni yangi pay_type'ga moslash (naqd vs plastik kassa)
    cr = db.query(CashRegister).filter(
        CashRegister.payment_type == new_pay_type,
        CashRegister.is_active == True,
    ).first()
    if cr:
        p.cash_register_id = cr.id

    # Agar confirmed edi: yangi summa bilan qayta qo'llash (order.paid/debt)
    if was_confirmed:
        if p.order_id:
            order = db.query(Order).filter(Order.id == p.order_id).first()
            if order:
                applied = min(float(order.debt or 0), new_amount)
                order.paid = float(order.paid or 0) + applied
                order.debt = max(0.0, float(order.debt or 0) - applied)

    # Site 5: driver payment edit — single recompute after all amount/order updates
    if p.partner_id and was_confirmed:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, p.partner_id,
            reason="agent_payment_edit",
            ref=getattr(p, "number", None),
            actor=current_user.username if current_user else None,
        )

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments?info=" + quote("To'lov tahrirlandi"), status_code=303)


@router.post("/supervisor/agent-payments/revert/{payment_id}")
async def supervisor_revert_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Tasdiqlangan to'lovni bekor qilish — kassadan chiqarish, mijoz qarzini qaytarish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    if ap.status != "confirmed":
        return RedirectResponse(url="/supervisor/agent-payments?error=not_confirmed", status_code=303)

    # 1. Tegishli Payment ni o'chirish (agar yaratilgan bo'lsa)
    # AGT- raqamli to'lovlarni topish
    payments = db.query(Payment).filter(
        Payment.partner_id == ap.partner_id,
        Payment.amount == float(ap.amount or 0),
        Payment.category == "agent_collection",
    ).all()
    for p in payments:
        db.delete(p)

    # 2. Statusni pending ga qaytarish
    ap.status = "pending"
    ap.confirmed_by = None
    ap.confirmed_at = None

    # Site 6: agent payment cancel — recompute after Payment deleted + status pending
    if ap.partner_id:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, ap.partner_id,
            reason="agent_payment_cancel",
            ref=None,
            actor=current_user.username if current_user else None,
        )

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/supervisor/agent-payments/delete/{payment_id}")
async def supervisor_delete_agent_payment(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini o'chirish."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)

    # Agar tasdiqlangan bo'lsa — avval Payment'larni o'chirish, so'ng recompute
    partner_id_for_recompute = None
    if ap.status == "confirmed":
        partner_id_for_recompute = ap.partner_id
        payments = db.query(Payment).filter(
            Payment.partner_id == ap.partner_id,
            Payment.amount == float(ap.amount or 0),
            Payment.category == "agent_collection",
        ).all()
        for p in payments:
            db.delete(p)

    db.delete(ap)

    # Site 7: agent payment delete — recompute after Payment deleted + ap deleted
    if partner_id_for_recompute:
        from app.services.partner_balance_service import recompute_partner_balance
        db.flush()
        recompute_partner_balance(
            db, partner_id_for_recompute,
            reason="agent_payment_delete",
            ref=None,
            actor=current_user.username if current_user else None,
        )

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.get("/supervisor/agent-payments/edit/{payment_id}", response_class=HTMLResponse)
async def supervisor_edit_agent_payment_form(
    request: Request,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini tahrirlash formasi."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)
    ap._agent = db.query(Agent).filter(Agent.id == ap.agent_id).first()
    ap._partner = db.query(Partner).filter(Partner.id == ap.partner_id).first()
    return templates.TemplateResponse("supervisor/agent_payment_edit.html", {
        "request": request,
        "current_user": current_user,
        "payment": ap,
        "page_title": f"To'lov tahrirlash #{ap.id}",
    })


@router.post("/supervisor/agent-payments/edit/{payment_id}")
async def supervisor_edit_agent_payment_save(
    request: Request,
    payment_id: int,
    amount: float = Form(None),
    payment_type: str = Form(None),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Agent to'lovini saqlash."""
    ap = db.query(AgentPayment).filter(AgentPayment.id == payment_id).first()
    if not ap:
        return RedirectResponse(url="/supervisor/agent-payments?error=not_found", status_code=303)

    if ap.status == "pending":
        # Pending — amount, type, notes tahrirlash mumkin
        if amount is not None and amount > 0:
            ap.amount = amount
        if payment_type in ("naqd", "plastik", "perechisleniye"):
            ap.payment_type = payment_type
        ap.notes = notes
    else:
        # Confirmed/cancelled — faqat notes tahrirlash mumkin
        ap.notes = notes

    db.commit()
    return RedirectResponse(url="/supervisor/agent-payments", status_code=303)


@router.post("/delivery/add-driver")
async def add_driver(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(None),
    vehicle_type: str = Form(None),
    vehicle_number: str = Form(None),
    telegram_id: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    last_driver = db.query(Driver).order_by(Driver.id.desc()).first()
    code = f"DR{str((last_driver.id if last_driver else 0) + 1).zfill(3)}"
    driver = Driver(
        code=code,
        full_name=full_name,
        phone=phone,
        vehicle_type=vehicle_type,
        vehicle_number=vehicle_number,
        telegram_id=telegram_id,
        is_active=True,
    )
    db.add(driver)
    db.commit()
    return RedirectResponse(url="/delivery", status_code=303)


@router.post("/delivery/add-order")
async def add_delivery_order(
    request: Request,
    driver_id: int = Form(...),
    order_number: str = Form(...),
    delivery_address: str = Form(...),
    notes: str = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    # Yetkazish raqami generatsiya: DLV-YYYYMMDD-NNN
    today = datetime.now()
    prefix = f"DLV-{today.strftime('%Y%m%d')}"
    last = db.query(Delivery).filter(Delivery.number.like(f"{prefix}%")).order_by(Delivery.id.desc()).first()
    if last and last.number:
        try:
            seq = int(last.number.split("-")[-1]) + 1
        except Exception:
            seq = 1
    else:
        seq = 1
    delivery_number = f"{prefix}-{seq:03d}"
    # order_id topish (agar mavjud bo'lsa)
    order = db.query(Order).filter(Order.number == order_number).first()
    delivery = Delivery(
        number=delivery_number,
        driver_id=driver_id,
        order_id=order.id if order else None,
        order_number=order_number,
        delivery_address=delivery_address,
        planned_date=today,
        notes=notes,
        status="pending",
    )
    db.add(delivery)
    db.commit()
    return RedirectResponse(url=f"/delivery/{driver_id}", status_code=303)
