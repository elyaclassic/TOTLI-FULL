"""
Agentlar — ro'yxat, qo'shish, tafsilot.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db,
    Agent,
    AgentCall,
    AgentLocation,
    AgentSms,
    Order,
    OrderItem,
    Partner,
    Product,
    ProductPrice,
    User,
    Visit,
    Warehouse,
)
from app.deps import require_auth, require_admin, require_admin_or_manager

router = APIRouter(tags=["agents"])


@router.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    agents = db.query(Agent).all()
    today = datetime.now().date()
    agent_ids = [a.id for a in agents]

    # Oxirgi lokatsiya — har agent uchun bitta query (N+1 o'rniga)
    latest_loc_ids = (
        db.query(func.max(AgentLocation.id))
        .filter(AgentLocation.agent_id.in_(agent_ids))
        .group_by(AgentLocation.agent_id)
        .subquery()
    )
    locations = db.query(AgentLocation).filter(AgentLocation.id.in_(latest_loc_ids)).all()
    loc_map = {loc.agent_id: loc for loc in locations}

    # Bugungi vizitlar soni — bitta GROUP BY query
    visits_counts = (
        db.query(Visit.agent_id, func.count(Visit.id).label("cnt"))
        .filter(Visit.agent_id.in_(agent_ids), Visit.visit_date >= today)
        .group_by(Visit.agent_id)
        .all()
    )
    visits_map = {row.agent_id: row.cnt for row in visits_counts}

    for agent in agents:
        agent.last_location = loc_map.get(agent.id)
        agent.today_visits = visits_map.get(agent.id, 0)
    return templates.TemplateResponse("agents/list.html", {
        "request": request,
        "agents": agents,
        "current_user": current_user,
        "page_title": "Agentlar",
    })


@router.post("/agents/add")
async def agent_add(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    region: str = Form(""),
    telegram_id: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    last_agent = db.query(Agent).order_by(Agent.id.desc()).first()
    code = f"AG{str((last_agent.id if last_agent else 0) + 1).zfill(3)}"
    agent = Agent(
        code=code,
        full_name=full_name,
        phone=phone,
        region=region,
        telegram_id=telegram_id,
        is_active=True,
    )
    db.add(agent)
    db.commit()
    return RedirectResponse(url="/agents", status_code=303)


@router.get("/agent", response_class=HTMLResponse)
async def agent_app(request: Request):
    """Mobile agent app — token auth done client-side via localStorage."""
    return templates.TemplateResponse("agents/app.html", {
        "request": request,
        "page_title": "Agent App",
    })


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
async def agent_detail(
    request: Request,
    agent_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")

    from datetime import datetime, timedelta
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        d_from = datetime.strptime(date_from, "%Y-%m-%d") if date_from else today
    except (ValueError, TypeError):
        d_from = today
    try:
        d_to = (datetime.strptime(date_to, "%Y-%m-%d") if date_to else today).replace(hour=23, minute=59, second=59)
    except (ValueError, TypeError):
        d_to = today.replace(hour=23, minute=59, second=59)
    locations = (
        db.query(AgentLocation)
        .filter(AgentLocation.agent_id == agent_id)
        .order_by(AgentLocation.recorded_at.desc())
        .limit(50)
        .all()
    )
    visits = (
        db.query(Visit)
        .options(joinedload(Visit.partner), joinedload(Visit.photos))
        .filter(Visit.agent_id == agent_id)
        .order_by(Visit.visit_date.desc())
        .limit(30)
        .all()
    )
    orders = (
        db.query(Order)
        .filter(
            Order.agent_id == agent_id,
            Order.date >= d_from,
            Order.date <= d_to,
            Order.parent_order_id.is_(None),  # Obmen child (sale) yashirilgan, parent ko'rsatiladi
        )
        .order_by(Order.id.desc())
        .all()
    )
    # Har parent uchun child sale (obmen) topish: order.id -> child Order
    exchange_children: dict[int, Order] = {}
    if orders:
        parent_ids = [o.id for o in orders if o.type == "return_sale"]
        if parent_ids:
            for ch in db.query(Order).filter(Order.parent_order_id.in_(parent_ids)).all():
                exchange_children[ch.parent_order_id] = ch
    calls = (
        db.query(AgentCall)
        .filter(AgentCall.agent_id == agent_id)
        .order_by(AgentCall.called_at.desc())
        .limit(50)
        .all()
    )
    sms_list = (
        db.query(AgentSms)
        .filter(AgentSms.agent_id == agent_id)
        .order_by(AgentSms.sent_at.desc())
        .limit(50)
        .all()
    )
    # Bugungi buyurtmalar — har doim hisoblanadi (filter sanasidan qat'iy nazar)
    today_start = today
    today_end = today.replace(hour=23, minute=59, second=59)
    today_q = db.query(
        func.count(Order.id),
        func.coalesce(func.sum(Order.total), 0),
    ).filter(
        Order.agent_id == agent_id,
        Order.date >= today_start,
        Order.date <= today_end,
        Order.parent_order_id.is_(None),
        Order.status != "cancelled",
    ).first()
    today_orders_count = int(today_q[0] or 0)
    today_orders_total = float(today_q[1] or 0)

    # Tasdiqlash modali uchun haydovchilar (faol)
    from app.models.database import Driver, Delivery
    drivers = db.query(Driver).filter(Driver.is_active == True).order_by(Driver.full_name).all()

    # Har order uchun haydovchi nomini olish (Delivery.driver_id orqali)
    # Obmen parent uchun ham child sale ning haydovchisini ko'rsatish
    order_drivers = {}
    if orders:
        # Parent ID lar + child sale ID lar (obmen uchun)
        order_ids = [o.id for o in orders]
        child_to_parent = {}  # child.id -> parent.id (obmen pari uchun)
        for parent_id, ch in exchange_children.items():
            order_ids.append(ch.id)
            child_to_parent[ch.id] = parent_id
        deliveries = db.query(Delivery).filter(Delivery.order_id.in_(order_ids)).all()
        driver_map = {d.id: d.full_name for d in db.query(Driver).filter(Driver.id.in_([dl.driver_id for dl in deliveries if dl.driver_id])).all()}
        for dl in deliveries:
            if dl.driver_id and dl.driver_id in driver_map:
                if dl.order_id not in order_drivers:
                    order_drivers[dl.order_id] = driver_map[dl.driver_id]
                # Obmen child uchun parent ID ga ham yozish (panelda parent ko'rinadi)
                parent_id = child_to_parent.get(dl.order_id)
                if parent_id and parent_id not in order_drivers:
                    order_drivers[parent_id] = driver_map[dl.driver_id]

    return templates.TemplateResponse("agents/detail.html", {
        "request": request,
        "agent": agent,
        "locations": locations,
        "visits": visits,
        "orders": orders,
        "exchange_children": exchange_children,
        "calls": calls,
        "sms_list": sms_list,
        "drivers": drivers,
        "order_drivers": order_drivers,
        "today_orders_count": today_orders_count,
        "today_orders_total": today_orders_total,
        "current_user": current_user,
        "page_title": f"Agent: {agent.full_name}",
        "date_from": d_from.strftime("%Y-%m-%d"),
        "date_to": d_to.strftime("%Y-%m-%d"),
    })


DEFAULT_AGENT_PRICE_TYPE_ID = 4


def _resolve_agent_price_type_id(partner: Partner) -> int:
    if partner is not None and getattr(partner, "price_type_id", None):
        return int(partner.price_type_id)
    return DEFAULT_AGENT_PRICE_TYPE_ID


@router.get("/agents/{agent_id}/order/new", response_class=HTMLResponse)
async def agent_order_new_form(
    request: Request,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")

    partners = (
        db.query(Partner)
        .filter(Partner.agent_id == agent.id, Partner.is_active == True)
        .order_by(Partner.name)
        .all()
    )
    products = (
        db.query(Product)
        .filter(
            Product.is_active == True,
            Product.is_for_agent == True,
        )
        .order_by(Product.name)
        .all()
    )
    return templates.TemplateResponse("agents/new_order.html", {
        "request": request,
        "agent": agent,
        "partners": partners,
        "products": products,
        "current_user": current_user,
        "page_title": f"Yangi buyurtma — {agent.full_name}",
    })


@router.post("/agents/{agent_id}/order/create")
async def agent_order_create(
    request: Request,
    agent_id: int,
    partner_id: int = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")

    partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
    if not partner:
        return RedirectResponse(url=f"/agents/{agent.id}/order/new?error=partner_mismatch", status_code=303)

    form = await request.form()
    product_ids = [int(x) for x in form.getlist("product_id") if str(x).strip().isdigit()]
    quantities_raw = form.getlist("quantity")

    warehouse = db.query(Warehouse).filter(Warehouse.name.ilike("%tayyor mahsulot%"), Warehouse.is_active == True).first()
    if not warehouse:
        warehouse = db.query(Warehouse).filter(Warehouse.is_active == True).first()
    if not warehouse:
        return RedirectResponse(url=f"/agents/{agent.id}/order/new?error=no_warehouse", status_code=303)

    price_type_id = _resolve_agent_price_type_id(partner)
    partner_discount = float(partner.discount_percent or 0)

    subtotal = 0.0
    order_items: list[OrderItem] = []
    for idx, pid in enumerate(product_ids):
        try:
            qty = float(quantities_raw[idx])
        except (ValueError, TypeError, IndexError):
            continue
        if qty <= 0:
            continue
        prod = db.query(Product).filter(
            Product.id == pid, Product.is_active == True, Product.is_for_agent == True,
        ).first()
        if not prod:
            continue
        pp = db.query(ProductPrice).filter(
            ProductPrice.product_id == pid, ProductPrice.price_type_id == price_type_id,
        ).first()
        price = float(pp.sale_price) if pp and pp.sale_price is not None else 0.0
        line_total = qty * price
        subtotal += line_total
        order_items.append(OrderItem(
            product_id=pid,
            quantity=qty,
            price=price,
            discount_percent=partner_discount,
            total=line_total * (1 - partner_discount / 100),
            warehouse_id=warehouse.id,
        ))

    if not order_items:
        return RedirectResponse(url=f"/agents/{agent.id}/order/new?error=no_items", status_code=303)

    today = datetime.now()
    prefix = f"AGT-{today.strftime('%Y%m%d')}"
    last = db.query(Order).filter(Order.number.like(f"{prefix}%")).order_by(Order.id.desc()).first()
    try:
        seq = int(last.number.split("-")[-1]) + 1 if last and last.number else 1
    except Exception:
        seq = 1
    order_number = f"{prefix}-{seq:03d}"

    discount_amount = subtotal * partner_discount / 100
    total = subtotal - discount_amount
    order = Order(
        number=order_number,
        date=today,
        type="sale",
        partner_id=partner.id,
        warehouse_id=warehouse.id,
        user_id=current_user.id,
        agent_id=agent.id,
        source="agent",
        price_type_id=price_type_id,
        subtotal=subtotal,
        discount_percent=partner_discount,
        discount_amount=discount_amount,
        total=total,
        paid=0,
        debt=total,
        status="draft",
        note=f"Admin tomonidan agent nomidan: {agent.code} — {agent.full_name}" + (f". {note}" if note else ""),
    )
    db.add(order)
    db.flush()
    for oi in order_items:
        oi.order_id = order.id
        db.add(oi)
    db.commit()
    return RedirectResponse(url=f"/sales/edit/{order.id}?created=1", status_code=303)
