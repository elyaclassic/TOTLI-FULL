"""
API — agent mobil ilova (advanced: reports, debts, KPI, reconciliation, tasks, order updates, returns, payments).

Tier C2 6-bosqich (oxirgi): api_routes.py dan ajratib olindi.
12 endpoint, ~865 qator.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func, func

from app.models.database import (
    get_db,
    Agent,
    AgentPayment,
    AgentTask,
    Order,
    OrderItem,
    Partner,
    Payment,
    Product,
    User,
    Visit,
    Warehouse,
)
from app.utils.auth import get_user_from_token
from app.services.stock_service import create_stock_movement
from app.logging_config import get_logger

# Helper'lar (api_agent_ops.py dan ko'chirilgan, mustaqillik uchun takrorlangan)
from app.routes.api_agent_ops import _agent_from_token, _extract_token

logger = get_logger("api_agent_advanced")

router = APIRouter(prefix="/api", tags=["api-agent-advanced"])


@router.get("/agent/partner/{partner_id}/debts")
async def agent_partner_debts(
    request: Request,
    partner_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Kontragentning to'lanmagan buyurtmalari (qarz > 0)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}

        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.agent_id == agent.id,
                Order.debt > 0,
                Order.type == "sale",
            )
            .order_by(Order.date.desc())
            .all()
        )

        debts_list = []
        total_debt = 0.0
        for o in orders:
            debt_val = float(o.debt or 0)
            total_debt += debt_val
            items_list = []
            for item in (o.items or []):
                items_list.append({
                    "name": item.product.name if item.product else "—",
                    "quantity": float(item.quantity or 0),
                    "price": float(item.price or 0),
                    "total": float(item.total or 0),
                })
            debts_list.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y") if o.date else "",
                "total": float(o.total or 0),
                "paid": float(o.paid or 0),
                "debt": debt_val,
                "status": o.status,
                "items": items_list,
            })

        # To'lov tarixi (agent inkassatsiya + yetkazish to'lovlari)
        payments_list = []
        partner_payments = (
            db.query(Payment)
            .filter(Payment.partner_id == partner_id, Payment.type == "income", Payment.status == "confirmed")
            .order_by(Payment.date.desc())
            .limit(20)
            .all()
        )
        for p in partner_payments:
            payments_list.append({
                "number": p.number or "",
                "date": p.date.strftime("%d.%m.%Y %H:%M") if p.date else "",
                "amount": float(p.amount or 0),
                "payment_type": p.payment_type or "",
                "description": p.description or "",
            })

        return {
            "success": True,
            "partner_id": partner_id,
            "partner_name": partner.name,
            "total_debt": total_debt,
            "debts": debts_list,
            "payments": payments_list,
        }
    except Exception as e:
        logger.error(f"agent_partner_debts: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/reports/summary")
async def agent_reports_summary(
    request: Request,
    token: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    """Agent kunlik/davriy hisobot: buyurtmalar, to'lovlar, kontragentlar bo'yicha."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        today = datetime.now().date()
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else today
        except (ValueError, TypeError):
            d_from = today
        try:
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
        except (ValueError, TypeError):
            d_to = today

        # Davriy buyurtmalar
        orders = (
            db.query(Order)
            .filter(
                Order.agent_id == agent.id,
                sa_func.date(Order.date) >= d_from,
                sa_func.date(Order.date) <= d_to,
            )
            .all()
        )

        orders_count = len(orders)
        total_amount = sum(float(o.total or 0) for o in orders)

        # Payment breakdown
        cash_orders = [o for o in orders if (o.payment_type or "").lower() in ("naqd", "cash")]
        transfer_orders = [o for o in orders if (o.payment_type or "").lower() in ("plastik", "transfer", "card", "perechisleniye")]
        credit_orders = [o for o in orders if float(o.debt or 0) > 0]

        payment_breakdown = {
            "cash": {
                "count": len(cash_orders),
                "total": sum(float(o.total or 0) for o in cash_orders),
            },
            "transfer": {
                "count": len(transfer_orders),
                "total": sum(float(o.total or 0) for o in transfer_orders),
            },
            "credit": {
                "count": len(credit_orders),
                "total": sum(float(o.debt or 0) for o in credit_orders),
            },
        }

        # Partner breakdown — top 10 kontragentlar
        partner_totals = {}
        for o in orders:
            pid = o.partner_id
            if pid not in partner_totals:
                p = db.query(Partner).filter(Partner.id == pid).first()
                partner_totals[pid] = {
                    "partner_id": pid,
                    "partner_name": p.name if p else "Noma'lum",
                    "orders_count": 0,
                    "total": 0.0,
                }
            partner_totals[pid]["orders_count"] += 1
            partner_totals[pid]["total"] += float(o.total or 0)

        top_partners = sorted(partner_totals.values(), key=lambda x: x["total"], reverse=True)[:10]

        return {
            "success": True,
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "orders_count": orders_count,
            "total_amount": total_amount,
            "payment_breakdown": payment_breakdown,
            "top_partners": top_partners,
        }
    except Exception as e:
        logger.error(f"agent_reports_summary: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/reconciliation")
async def agent_partner_reconciliation(
    request: Request,
    partner_id: int,
    token: str = None,
    date_from: str = None,
    date_to: str = None,
    db: Session = Depends(get_db),
):
    """Kontragent bilan solishtirma akt (harakat tarixi: debet/kredit/saldo)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}

        today = datetime.now().date()
        try:
            d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else (today - timedelta(days=90))
        except (ValueError, TypeError):
            d_from = today - timedelta(days=90)
        try:
            d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today
        except (ValueError, TypeError):
            d_to = today

        # Davrgacha bo'lgan buyurtmalar va to'lovlar — ochilish qoldig'i
        prior_orders_total = (
            db.query(sa_func.coalesce(sa_func.sum(Order.total), 0))
            .filter(
                Order.partner_id == partner_id,
                Order.agent_id == agent.id,
                Order.type == "sale",
                sa_func.date(Order.date) < d_from,
            )
            .scalar()
        ) or 0

        prior_payments_total = (
            db.query(sa_func.coalesce(sa_func.sum(Payment.amount), 0))
            .filter(
                Payment.partner_id == partner_id,
                Payment.type == "income",
                Payment.status != "cancelled",
                sa_func.date(Payment.date) < d_from,
            )
            .scalar()
        ) or 0

        opening_balance = float(prior_orders_total) - float(prior_payments_total)

        # Davrdagi harakatlar
        movements = []

        # Buyurtmalar (debit)
        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.agent_id == agent.id,
                Order.type == "sale",
                sa_func.date(Order.date) >= d_from,
                sa_func.date(Order.date) <= d_to,
            )
            .order_by(Order.date)
            .all()
        )
        for o in orders:
            movements.append({
                "date": o.date.strftime("%d.%m.%Y %H:%M") if o.date else "",
                "sort_date": o.date.isoformat() if o.date else "",
                "description": f"Sotuv #{o.number}",
                "debit": float(o.total or 0),
                "credit": 0.0,
            })

        # To'lovlar (kredit)
        payments = (
            db.query(Payment)
            .filter(
                Payment.partner_id == partner_id,
                Payment.type == "income",
                Payment.status != "cancelled",
                sa_func.date(Payment.date) >= d_from,
                sa_func.date(Payment.date) <= d_to,
            )
            .order_by(Payment.date)
            .all()
        )
        for p in payments:
            movements.append({
                "date": p.date.strftime("%d.%m.%Y %H:%M") if p.date else "",
                "sort_date": p.date.isoformat() if p.date else "",
                "description": f"To'lov #{p.number}" + (f" ({p.payment_type})" if p.payment_type else ""),
                "debit": 0.0,
                "credit": float(p.amount or 0),
            })

        # Sanaga ko'ra tartiblash
        movements.sort(key=lambda x: x.get("sort_date", ""))

        # Balansni hisoblash
        running_balance = opening_balance
        for m in movements:
            running_balance += m["debit"] - m["credit"]
            m["balance"] = round(running_balance, 2)
            del m["sort_date"]

        closing_balance = running_balance

        return {
            "success": True,
            "partner_id": partner_id,
            "partner_name": partner.name,
            "date_from": d_from.isoformat(),
            "date_to": d_to.isoformat(),
            "opening_balance": round(opening_balance, 2),
            "closing_balance": round(closing_balance, 2),
            "movements": movements,
        }
    except Exception as e:
        logger.error(f"agent_partner_reconciliation: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/kpi")
async def agent_kpi(
    request: Request,
    token: str = None,
    period: str = "daily",
    db: Session = Depends(get_db),
):
    """Agent KPI ko'rsatkichlari: tashriflar, buyurtmalar, yangi klientlar, o'rtacha summa."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        today = datetime.now().date()
        period = (period or "daily").lower()
        if period == "weekly":
            d_from = today - timedelta(days=today.weekday())  # Dushanba
        elif period == "monthly":
            d_from = today.replace(day=1)
        else:
            d_from = today

        # Tashriflar
        visits_done = (
            db.query(Visit)
            .filter(
                Visit.agent_id == agent.id,
                sa_func.date(Visit.visit_date) >= d_from,
                sa_func.date(Visit.visit_date) <= today,
            )
            .count()
        )

        # Rejalashtirilgan tashriflar — agent kontragentlari soni
        visits_planned = db.query(Partner).filter(Partner.agent_id == agent.id, Partner.is_active == True).count()

        # Buyurtmalar
        orders = (
            db.query(Order)
            .filter(
                Order.agent_id == agent.id,
                sa_func.date(Order.date) >= d_from,
                sa_func.date(Order.date) <= today,
            )
            .all()
        )
        orders_count = len(orders)
        orders_total = sum(float(o.total or 0) for o in orders)
        average_order_value = (orders_total / orders_count) if orders_count > 0 else 0

        # Yangi kontragentlar (ushbu davrda qo'shilganlar)
        new_partners = (
            db.query(Partner)
            .filter(
                Partner.agent_id == agent.id,
                Partner.is_active == True,
                sa_func.date(Partner.created_at) >= d_from,
                sa_func.date(Partner.created_at) <= today,
            )
            .count()
        )

        # Foizlar
        visits_pct = round((visits_done / visits_planned * 100), 1) if visits_planned > 0 else 0

        return {
            "success": True,
            "period": period,
            "date_from": d_from.isoformat(),
            "date_to": today.isoformat(),
            "metrics": {
                "visits_done": visits_done,
                "visits_planned": visits_planned,
                "visits_percent": visits_pct,
                "orders_count": orders_count,
                "orders_total": round(orders_total, 2),
                "average_order_value": round(average_order_value, 2),
                "new_partners": new_partners,
            },
        }
    except Exception as e:
        logger.error(f"agent_kpi: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/tasks")
async def agent_tasks_list(
    request: Request,
    token: str = None,
    status: str = None,
    db: Session = Depends(get_db),
):
    """Agent vazifalari ro'yxati."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        q = db.query(AgentTask).filter(AgentTask.agent_id == agent.id)
        if status:
            q = q.filter(AgentTask.status == status)
        tasks = q.order_by(AgentTask.due_date.asc(), AgentTask.priority.desc()).all()

        result = []
        for t in tasks:
            partner_name = ""
            if t.partner_id:
                p = db.query(Partner).filter(Partner.id == t.partner_id).first()
                partner_name = p.name if p else ""
            result.append({
                "id": t.id,
                "title": t.title,
                "description": t.description or "",
                "due_date": t.due_date.isoformat() if t.due_date else None,
                "status": t.status,
                "priority": t.priority,
                "partner_id": t.partner_id,
                "partner_name": partner_name,
                "created_at": t.created_at.isoformat() if t.created_at else "",
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            })

        return {"success": True, "tasks": result}
    except Exception as e:
        logger.error(f"agent_tasks_list: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/tasks/{task_id}/complete")
async def agent_task_complete(
    request: Request,
    task_id: int,
    token: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    """Agent vazifani bajarilgan deb belgilaydi."""
    try:
        tk = _extract_token(request, token)
        agent = _agent_from_token(tk, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        task = db.query(AgentTask).filter(AgentTask.id == task_id, AgentTask.agent_id == agent.id).first()
        if not task:
            return {"success": False, "error": "Vazifa topilmadi"}

        if task.status == "completed":
            return {"success": False, "error": "Vazifa allaqachon bajarilgan"}

        task.status = "completed"
        task.completed_at = datetime.now()
        if notes:
            task.description = (task.description or "") + f"\n[Bajarildi]: {notes}" if task.description else f"[Bajarildi]: {notes}"
        db.commit()

        logger.info(f"Agent task completed: task_id={task_id}, agent={agent.code}")
        return {"success": True, "task_id": task.id, "status": "completed"}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_task_complete: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/completed-orders")
async def agent_partner_completed_orders(
    request: Request,
    partner_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Mijozning completed sotuvlari (vozvrat uchun)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}
        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.type == "sale",
                Order.status == "completed",
            )
            .order_by(Order.date.desc())
            .limit(30)
            .all()
        )
        result = []
        for o in orders:
            items = []
            for it in o.items:
                prod = it.product
                items.append({
                    "product_id": it.product_id,
                    "name": prod.name if prod else f"#{it.product_id}",
                    "quantity": float(it.quantity or 0),
                    "price": float(it.price or 0),
                    "total": float(it.total or 0),
                })
            result.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y") if o.date else "",
                "total": float(o.total or 0),
                "items": items,
            })
        return {"success": True, "orders": result}
    except Exception as e:
        logger.error(f"agent_partner_completed_orders: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/partner/{partner_id}/orders")
async def agent_partner_orders(
    request: Request,
    partner_id: int,
    token: str = None,
    db: Session = Depends(get_db),
):
    """Mijozning barcha buyurtmalari ro'yxati (agent uchun)."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        partner = db.query(Partner).filter(Partner.id == partner_id, Partner.agent_id == agent.id).first()
        if not partner:
            return {"success": False, "error": "Klient topilmadi"}
        orders = (
            db.query(Order)
            .filter(
                Order.partner_id == partner_id,
                Order.type == "sale",
                Order.status.in_(["draft", "confirmed", "completed"]),
            )
            .order_by(Order.id.desc())
            .limit(50)
            .all()
        )
        agent_ids = {o.agent_id for o in orders if o.agent_id}
        user_ids = {o.user_id for o in orders if o.user_id and not o.agent_id}
        agents_map = {a.id: a.full_name for a in db.query(Agent).filter(Agent.id.in_(agent_ids)).all()} if agent_ids else {}
        users_map = {u.id: u.full_name for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}
        result = []
        for o in orders:
            if o.agent_id:
                created_by = agents_map.get(o.agent_id, "Agent")
            elif o.user_id:
                created_by = users_map.get(o.user_id, "Admin")
            else:
                created_by = ""

            items = []
            for it in o.items:
                prod = it.product
                items.append({
                    "product_id": it.product_id,
                    "name": prod.name if prod else f"#{it.product_id}",
                    "quantity": float(it.quantity or 0),
                    "price": float(it.price or 0),
                    "total": float(it.total or 0),
                })

            # 5 daqiqa ichida o'zgartirilishi mumkin
            created_at = o.created_at or o.date
            can_edit = False
            if created_at and o.status == "draft":
                diff = (datetime.now() - created_at).total_seconds()
                can_edit = diff <= 300  # 5 daqiqa

            result.append({
                "id": o.id,
                "number": o.number,
                "date": o.date.strftime("%d.%m.%Y %H:%M") if o.date else "",
                "created_by": created_by,
                "total": float(o.total or 0),
                "paid": float(o.paid or 0),
                "debt": float(o.debt or 0),
                "status": o.status,
                "can_edit": can_edit,
                "items": items,
                "payment_type": o.payment_type or "",
            })
        return {"success": True, "orders": result}
    except Exception as e:
        logger.error(f"agent_partner_orders: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/order/{order_id}/update")
async def agent_order_update(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
):
    """Agent buyurtmani tahrirlaydi (5 daqiqa ichida, faqat draft)."""
    try:
        body = await request.json()
        tok = _extract_token(request, body.get("token"))
        agent = _agent_from_token(tok, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        order = db.query(Order).filter(Order.id == order_id, Order.agent_id == agent.id).first()
        if not order:
            return {"success": False, "error": "Buyurtma topilmadi"}

        if order.status != "draft":
            return {"success": False, "error": "Faqat kutilayotgan buyurtmani o'zgartirish mumkin"}

        # Bekor qilish
        new_status = body.get("status")
        if new_status == "cancelled":
            order.status = "cancelled"
            db.commit()
            logger.info(f"Agent order cancelled: order_id={order.id}, agent={agent.code}")
            return {"success": True, "order_id": order.id}

        created_at = order.created_at or order.date
        if created_at:
            diff = (datetime.now() - created_at).total_seconds()
            if diff > 300:
                return {"success": False, "error": "5 daqiqadan ko'p vaqt o'tdi. Faqat admin o'zgartirishi mumkin"}

        items_data = body.get("items", [])
        payment_type = body.get("payment_type")

        if not items_data:
            return {"success": False, "error": "Mahsulotlar bo'sh"}

        # Eski itemlarni o'chirish
        db.query(OrderItem).filter(OrderItem.order_id == order.id).delete()

        # Yangi itemlar
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        discount_pct = float(partner.discount_percent or 0) if partner else 0

        subtotal = 0
        for it in items_data:
            product_id = int(it.get("product_id", 0))
            qty = float(it.get("qty", 0))
            if product_id <= 0 or qty <= 0:
                continue
            prod = db.query(Product).filter(Product.id == product_id).first()
            if not prod:
                continue
            price = float(prod.sale_price or 0)
            line_total = round(price * qty, 2)
            subtotal += line_total
            db.add(OrderItem(
                order_id=order.id,
                product_id=product_id,
                quantity=qty,
                price=price,
                total=line_total,
            ))

        discount_amount = round(subtotal * discount_pct / 100, 2)
        total = round(subtotal - discount_amount, 2)

        order.subtotal = subtotal
        order.discount_percent = discount_pct
        order.discount_amount = discount_amount
        order.total = total
        order.debt = total
        order.paid = 0
        if payment_type:
            order.payment_type = payment_type

        db.commit()
        logger.info(f"Agent order updated: order_id={order.id}, agent={agent.code}")
        return {"success": True, "order_id": order.id, "total": total}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_order_update: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/agent/return/create")
async def agent_return_create(
    request: Request,
    db: Session = Depends(get_db),
):
    """Agent vozvrat yaratadi. JSON body: {token, order_id, items: [{product_id, qty}]}."""
    try:
        body = await request.json()
        tok = _extract_token(request, body.get("token"))
        agent = _agent_from_token(tok, db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}
        order_id = body.get("order_id")
        items = body.get("items", [])
        if not order_id:
            return {"success": False, "error": "Buyurtma tanlanmadi"}
        if not items:
            return {"success": False, "error": "Mahsulot tanlang"}
        sale = db.query(Order).filter(
            Order.id == int(order_id),
            Order.type == "sale",
            Order.status == "completed",
        ).first()
        if not sale:
            return {"success": False, "error": "Buyurtma topilmadi"}
        # Ombor — vozvrat yoki asl ombor
        sale_wh = db.query(Warehouse).filter(Warehouse.id == sale.warehouse_id).first()
        if sale_wh and "do'kon" in (sale_wh.name or "").lower():
            return_warehouse_id = sale.warehouse_id
        else:
            vozvrat_wh = db.query(Warehouse).filter(
                Warehouse.name.ilike("%vozvrat%"), Warehouse.is_active == True
            ).first()
            return_warehouse_id = vozvrat_wh.id if vozvrat_wh else sale.warehouse_id
        # Raqam generatsiya
        from datetime import date as date_type
        today_start = date_type.today()
        count = db.query(Order).filter(
            Order.type == "return_sale",
            sa_func.date(Order.created_at) == today_start,
        ).count()
        new_number = f"R-{datetime.now().strftime('%Y%m%d')}-{count + 1:04d}"
        # Sotuv itemlari
        sale_items_by_product = {it.product_id: it for it in sale.items}
        return_order = Order(
            number=new_number,
            type="return_sale",
            partner_id=sale.partner_id,
            warehouse_id=return_warehouse_id,
            price_type_id=sale.price_type_id,
            user_id=None,
            agent_id=agent.id,
            source="agent",
            status="completed",
            payment_type=sale.payment_type,
            note=f"Agent vozvrat: {sale.number} (Agent: {agent.code})",
        )
        db.add(return_order)
        db.flush()
        total_return = 0.0
        for it in items:
            pid = int(it["product_id"])
            qty = float(it.get("qty", it.get("quantity", 0)))
            if qty <= 0:
                continue
            sale_item = sale_items_by_product.get(pid)
            if not sale_item:
                continue
            # Sotilgan miqdordan ko'p qaytarish mumkin emas
            if qty > float(sale_item.quantity or 0) + 0.001:
                qty = float(sale_item.quantity or 0)
            price = float(sale_item.price or 0)
            total_row = qty * price
            db.add(OrderItem(
                order_id=return_order.id,
                product_id=pid,
                quantity=qty,
                price=price,
                total=total_row,
            ))
            total_return += total_row
            create_stock_movement(
                db=db,
                warehouse_id=return_warehouse_id,
                product_id=pid,
                quantity_change=+qty,
                operation_type="return_sale",
                document_type="SaleReturn",
                document_id=return_order.id,
                document_number=return_order.number,
                user_id=None,
                note=f"Agent vozvrat: {sale.number} -> {return_order.number}",
                created_at=return_order.date,
            )
        if total_return <= 0:
            db.rollback()
            return {"success": False, "error": "Qaytarish miqdori kiritilmadi"}
        return_order.subtotal = total_return
        return_order.total = total_return
        return_order.paid = total_return
        return_order.debt = 0
        db.commit()
        logger.info(f"Agent return created: {new_number}, agent={agent.code}, sale={sale.number}, total={total_return}")
        return {"success": True, "return_number": new_number, "total": total_return}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_return_create: {e}")
        return {"success": False, "error": "Server xatosi"}


# ==========================================
# AGENT KASSA (inkassatsiya)
# ==========================================

@router.post("/agent/payment/create")
async def agent_payment_create(request: Request, db: Session = Depends(get_db)):
    """Agent mijozdan pul oldi — pending holatda yaratiladi."""
    try:
        body = await request.json()
        agent = _agent_from_token(_extract_token(request, body.get("token")), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        partner_id = int(body.get("partner_id", 0))
        amount = float(body.get("amount", 0))
        payment_type = body.get("payment_type", "naqd")
        notes = body.get("notes", "")

        if partner_id <= 0 or amount <= 0:
            return {"success": False, "error": "Mijoz va summani kiriting"}

        partner = db.query(Partner).filter(Partner.id == partner_id).first()
        if not partner:
            return {"success": False, "error": "Mijoz topilmadi"}

        ap = AgentPayment(
            agent_id=agent.id,
            partner_id=partner_id,
            amount=amount,
            payment_type=payment_type,
            notes=notes,
            status="pending",
        )
        db.add(ap)
        db.commit()
        logger.info(f"Agent payment created: id={ap.id}, agent={agent.code}, partner={partner.name}, amount={amount}")
        return {"success": True, "payment_id": ap.id}
    except Exception as e:
        db.rollback()
        logger.error(f"agent_payment_create: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/agent/payments")
async def agent_payments(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Agent to'lovlari ro'yxati."""
    try:
        agent = _agent_from_token(_extract_token(request, token), db)
        if not agent:
            return {"success": False, "error": "Token noto'g'ri"}

        payments = (
            db.query(AgentPayment)
            .filter(AgentPayment.agent_id == agent.id)
            .order_by(AgentPayment.id.desc())
            .limit(100)
            .all()
        )
        result = []
        for p in payments:
            partner = db.query(Partner).filter(Partner.id == p.partner_id).first()
            result.append({
                "id": p.id,
                "partner_id": p.partner_id,
                "partner_name": partner.name if partner else "",
                "amount": float(p.amount or 0),
                "payment_type": p.payment_type or "naqd",
                "notes": p.notes or "",
                "status": p.status or "pending",
                "created_at": p.created_at.isoformat() if p.created_at else "",
            })
        return {"success": True, "payments": result}
    except Exception as e:
        logger.error(f"agent_payments: {e}")
        return {"success": False, "error": "Server xatosi"}
