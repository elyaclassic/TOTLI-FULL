"""
API — driver mobil ilova (deliveries, status, stats, location).

Tier C2 4-bosqich: api_routes.py dan ajratib olindi.
4 endpoint + 1 helper (_driver_from_token), ~270 qator.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.orm import Session
from sqlalchemy import func as sa_func

from app.models.database import (
    get_db, Driver, Delivery, Order, Partner, CashRegister, Payment, DriverLocation,
)
from app.utils.auth import get_user_from_token
from app.services.stock_service import create_stock_movement
from app.logging_config import get_logger
from app.constants import QUERY_LIMIT_DEFAULT, QUERY_LIMIT_HISTORY

logger = get_logger("api_driver_ops")

router = APIRouter(prefix="/api", tags=["api-driver"])


def _driver_from_token(token: str, db: Session):
    """Token dan driver olish."""
    if not token:
        return None
    user_data = get_user_from_token(token)
    if not user_data or user_data.get("user_type") != "driver":
        return None
    user_id = user_data["user_id"]
    # Avval employee_id orqali
    driver = db.query(Driver).filter(Driver.employee_id == user_id, Driver.is_active == True).first()
    if not driver:
        # Agar user_id == driver.id bo'lsa (eski token)
        driver = db.query(Driver).filter(Driver.id == user_id, Driver.is_active == True).first()
    return driver


@router.get("/driver/deliveries")
async def driver_deliveries(request: Request, token: str = None, date: str = None, db: Session = Depends(get_db)):
    """Haydovchiga tayinlangan yetkazishlar ro'yxati. date=YYYY-MM-DD bo'lsa shu kunniki."""
    try:
        tk = token or (request.headers.get("Authorization", "")[7:] if request.headers.get("Authorization", "").startswith("Bearer ") else None)
        driver = _driver_from_token(tk, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        q = db.query(Delivery).filter(Delivery.driver_id == driver.id)
        if date:
            try:
                d = datetime.strptime(date, "%Y-%m-%d").date()
                # Yetkazilmagan (pending/picked_up/in_progress) — har doim ko'rinadi.
                # Tugatilgan/bekor qilingan — faqat tanlangan kun ichida bo'lsa.
                from sqlalchemy import or_, and_
                q = q.filter(
                    or_(
                        Delivery.status.in_(["pending", "picked_up", "in_progress"]),
                        and_(
                            Delivery.status.in_(["delivered", "cancelled"]),
                            sa_func.date(Delivery.created_at) == d,
                        ),
                    )
                )
            except ValueError:
                pass
        deliveries = q.order_by(Delivery.created_at.desc()).limit(QUERY_LIMIT_DEFAULT).all()
        result = []
        for d in deliveries:
            order = db.query(Order).filter(Order.id == d.order_id).first() if d.order_id else None
            partner = None
            if order and order.partner_id:
                partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
            # Buyurtma mahsulotlari
            items = []
            if order:
                for oi in order.items:
                    prod = oi.product
                    items.append({
                        "product_id": oi.product_id,  # Bug fix: ishonchli ID — nom o'rniga
                        "name": prod.name if prod else f"#{oi.product_id}",
                        "quantity": float(oi.quantity or 0),
                        "price": float(oi.price or 0),
                        "total": float(oi.total or 0),
                    })
            # Lokatsiya — delivery da bo'lsa delivery dan, yo'qsa partner dan
            lat = d.latitude
            lng = d.longitude
            if not lat and partner:
                lat = partner.latitude
            if not lng and partner:
                lng = partner.longitude
            result.append({
                "id": d.id,
                "number": d.number,
                "order_number": d.order_number or (order.number if order else ""),
                "delivery_address": d.delivery_address or (partner.address if partner else ""),
                "partner_name": partner.name if partner else "",
                "partner_phone": partner.phone if partner else "",
                "partner_phone2": partner.phone2 if partner and partner.phone2 else "",
                "partner_address": partner.address if partner else "",
                "landmark": partner.landmark if partner else "",
                "status": d.status or "pending",
                "planned_date": d.planned_date.isoformat() if d.planned_date else "",
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else "",
                "notes": d.notes or "",
                "total": float(order.total or 0) if order else 0,
                "paid": float(order.paid or 0) if order else 0,
                "debt": max(float(order.total or 0) - float(order.paid or 0), 0) if order else 0,
                "latitude": lat,
                "longitude": lng,
                "items": items,
            })
        return {"success": True, "deliveries": result}
    except Exception as e:
        logger.error(f"Driver deliveries error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/driver/delivery/{delivery_id}/status")
async def driver_delivery_status(
    delivery_id: int,
    status: str = Form(...),
    latitude: float = Form(None),
    longitude: float = Form(None),
    notes: str = Form(""),
    items: str = Form(None),
    naqd: float = Form(0),
    plastik: float = Form(0),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    """Haydovchi yetkazish statusini yangilaydi"""
    try:
        driver = _driver_from_token(token, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        delivery = db.query(Delivery).filter(
            Delivery.id == delivery_id,
            Delivery.driver_id == driver.id,
        ).first()
        if not delivery:
            return {"success": False, "error": "Yetkazish topilmadi"}

        allowed_statuses = ["pending", "picked_up", "in_progress", "delivered", "failed"]
        new_status = (status or "").strip()
        if new_status not in allowed_statuses:
            return {"success": False, "error": "Noto'g'ri status"}

        delivery.status = new_status
        if notes:
            delivery.notes = (delivery.notes or "") + "\n" + notes if delivery.notes else notes

        # Haydovchi o'zgartirgan itemlarni yangilash
        # Bug fix: avval product_id orqali topish (ishonchli), keyin name orqali fallback
        if items and delivery.order_id:
            try:
                modified_items = json.loads(items)
                order = db.query(Order).filter(Order.id == delivery.order_id).first()
                if order:
                    for mi in modified_items:
                        new_qty = float(mi.get("quantity", 0))
                        # Total: yuborilgan bo'lsa shu, aks holda qty * price
                        if mi.get("total") is not None:
                            new_total = float(mi.get("total") or 0)
                        else:
                            new_total = new_qty * float(mi.get("price") or 0)
                        pid = mi.get("product_id")
                        item_name = (mi.get("name") or "").strip()
                        target_oi = None
                        # 1) product_id orqali (ishonchli)
                        if pid:
                            try:
                                pid = int(pid)
                                target_oi = next((oi for oi in order.items if oi.product_id == pid), None)
                            except (ValueError, TypeError):
                                pass
                        # 2) name orqali fallback
                        if not target_oi and item_name:
                            target_oi = next((oi for oi in order.items if oi.product and (oi.product.name or "").strip() == item_name), None)
                        if target_oi:
                            old_qty = float(target_oi.quantity or 0)
                            diff = old_qty - new_qty
                            target_oi.quantity = new_qty
                            target_oi.total = new_total
                            if diff > 0.001 and order.status == "confirmed":
                                wh_id = target_oi.warehouse_id or order.warehouse_id
                                if wh_id and target_oi.product_id:
                                    create_stock_movement(
                                        db=db,
                                        warehouse_id=wh_id,
                                        product_id=target_oi.product_id,
                                        quantity_change=+diff,
                                        operation_type="delivery_partial",
                                        document_type="Sale",
                                        document_id=order.id,
                                        document_number=order.number,
                                        user_id=getattr(driver, 'employee_id', None),
                                        note=f"Yetkazilmagan qoldiq qaytarish: {target_oi.product.name if target_oi.product else ''} ({diff:.0f} dona)",
                                        created_at=datetime.now(),
                                    )
                    order.total = sum(float(oi.total or 0) for oi in order.items)
                    order.subtotal = order.total
                    order.debt = max(0.0, order.total - float(order.paid or 0))
            except Exception as e:
                logger.warning(f"Items update xatosi: {e}")

        if new_status == "failed" and delivery.order_id:
            order = db.query(Order).filter(Order.id == delivery.order_id).first()
            if order and order.status == "confirmed" and not (order.paid or 0) > 0:
                for it in order.items:
                    wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
                    if not wh_id or not it.product_id or not (it.quantity or 0) > 0:
                        continue
                    create_stock_movement(
                        db=db,
                        warehouse_id=wh_id,
                        product_id=it.product_id,
                        quantity_change=+float(it.quantity or 0),
                        operation_type="delivery_failed",
                        document_type="Sale",
                        document_id=order.id,
                        document_number=order.number,
                        user_id=getattr(driver, 'employee_id', None),
                        note=f"Yetkazish muvaffaqiyatsiz: {order.number}",
                        created_at=datetime.now(),
                    )
                order.status = "cancelled"

        if new_status == "delivered":
            delivery.delivered_at = datetime.now()
            if latitude:
                delivery.latitude = latitude
            if longitude:
                delivery.longitude = longitude

            # To'lovlarni yaratish (naqd va/yoki plastik)
            order = db.query(Order).filter(Order.id == delivery.order_id).first() if delivery.order_id else None
            partner_id = order.partner_id if order else None
            total_paid = (naqd or 0) + (plastik or 0)

            for pay_type, pay_amount in [("naqd", naqd or 0), ("plastik", plastik or 0)]:
                if pay_amount <= 0:
                    continue
                cash_register = db.query(CashRegister).filter(
                    CashRegister.payment_type == pay_type,
                    CashRegister.is_active == True,
                ).first()
                if not cash_register:
                    cash_register = db.query(CashRegister).filter(CashRegister.is_active == True).first()
                if cash_register:
                    last_p = db.query(Payment).order_by(Payment.id.desc()).first()
                    next_num = (last_p.id + 1) if last_p else 1
                    p_number = f"DLV-{datetime.now().strftime('%Y%m%d')}-{next_num:04d}"
                    partner_name = order.partner.name if order and order.partner else ""
                    payment = Payment(
                        number=p_number,
                        date=datetime.now(),
                        type="income",
                        cash_register_id=cash_register.id,
                        partner_id=partner_id,
                        order_id=delivery.order_id,  # D3 audit fix: order link saqlanadi (FIFO o'rniga aniq order)
                        amount=pay_amount,
                        payment_type=pay_type,
                        category="delivery",
                        description=f"Yetkazish to'lovi ({pay_type}): {partner_name}, #{delivery.number or delivery.id}",
                        user_id=getattr(driver, 'employee_id', None),
                        status="pending",  # Haydovchi mijozdan oldi, admin tasdiqlashi kerak (inkassatsiya)
                    )
                    db.add(payment)

            # Buyurtma qarzini YANGILAMAYMIZ — Payment 'pending' status'da, admin tasdiqlaganidan
            # keyin (/supervisor/agent-payments/confirm-driver/{id}) order.paid yangilanadi.
            # Demak hozir mijoz hisobida qarz qoladi, haydovchida pul.
            # Order yetkazildi → "completed" statusga o'tkazish
            if order and order.status not in ("completed", "cancelled"):
                order.status = "completed"

        db.commit()
        try:
            from app.bot.services.audit_watchdog import audit_delivery_status
            audit_delivery_status(delivery.id, new_status, getattr(driver, "full_name", "") or getattr(driver, "code", "—"))
        except Exception:
            pass
        return {"success": True, "status": delivery.status}
    except Exception as e:
        db.rollback()
        logger.error(f"Delivery status update error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.get("/driver/stats")
async def driver_stats(request: Request, token: str = None, db: Session = Depends(get_db)):
    """Haydovchi statistikasi"""
    try:
        tk = token or (request.headers.get("Authorization", "")[7:] if request.headers.get("Authorization", "").startswith("Bearer ") else None)
        driver = _driver_from_token(tk, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}

        today = datetime.now().date()
        pending = db.query(Delivery).filter(Delivery.driver_id == driver.id, Delivery.status.in_(["pending", "picked_up"])).count()
        in_progress = db.query(Delivery).filter(Delivery.driver_id == driver.id, Delivery.status == "in_progress").count()
        today_delivered = db.query(Delivery).filter(
            Delivery.driver_id == driver.id,
            Delivery.status == "delivered",
            sa_func.date(Delivery.delivered_at) == today,
        ).count()
        total = db.query(Delivery).filter(Delivery.driver_id == driver.id).count()

        return {
            "success": True,
            "driver": {"id": driver.id, "code": driver.code, "full_name": driver.full_name},
            "stats": {
                "pending": pending,
                "in_progress": in_progress,
                "today_delivered": today_delivered,
                "total": total,
            },
        }
    except Exception as e:
        logger.error(f"Driver stats error: {e}")
        return {"success": False, "error": "Server xatosi"}


@router.post("/driver/location")
async def driver_location_update(
    latitude: float = Form(...),
    longitude: float = Form(...),
    accuracy: float = Form(None),
    battery: int = Form(None),
    token: str = Form(...),
    db: Session = Depends(get_db),
):
    """Haydovchi lokatsiyasini yangilash"""
    try:
        driver = _driver_from_token(token, db)
        if not driver:
            return {"success": False, "error": "Invalid token"}
        location = DriverLocation(
            driver_id=driver.id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            battery=battery,
        )
        db.add(location)
        db.commit()
        return {"success": True, "location_id": location.id}
    except Exception as e:
        db.rollback()
        return {"success": False, "error": "Server xatosi"}
