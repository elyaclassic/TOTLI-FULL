"""
Agent buyurtmalari uchun service: waiting_production → confirmed avtomatik o'tish.

Production tugagach (status='completed') chaqiriladi: barcha waiting_production
buyurtmalarni tekshiradi, stok yetganlarini avtomatik confirm qilib delivery yaratadi.
"""
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy.orm import Session

from app.models.database import Order, Stock, Delivery, Partner, Product
from app.services.stock_service import apply_sale_stock_deduction


def try_confirm_waiting_orders(db: Session) -> List[Dict[str, Any]]:
    """Waiting_production statusdagi agent buyurtmalarini tekshirib, yetganlarini auto-confirm qiladi.

    Qaytaradi: confirmedlar haqida axborot ([{order_id, order_number, driver_id?}]).
    """
    confirmed = []
    waiting = (
        db.query(Order)
        .filter(Order.source == "agent", Order.status == "waiting_production")
        .order_by(Order.date)  # FIFO
        .all()
    )
    if not waiting:
        return confirmed

    for order in waiting:
        try:
            valid_items = [it for it in order.items if it.product_id and (it.quantity or 0) > 0]
            if not valid_items:
                continue
            # Har item uchun stok tekshirish
            enough = True
            for it in valid_items:
                wh_id = it.warehouse_id if it.warehouse_id else order.warehouse_id
                if not wh_id:
                    enough = False
                    break
                stock = (
                    db.query(Stock)
                    .filter(Stock.warehouse_id == wh_id, Stock.product_id == it.product_id)
                    .first()
                )
                have = float(stock.quantity or 0) if stock else 0
                need = float(it.quantity or 0)
                if have + 1e-6 < need:
                    enough = False
                    break
            if not enough:
                continue
            # Stok yetadi — confirm qilamiz
            apply_sale_stock_deduction(db, order, None, note_prefix="Agent sotuv (auto-confirm production after)")
            order.status = "confirmed"
            db.flush()
            # Driver tanlangan bo'lsa delivery yaratish
            if order.pending_driver_id:
                partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
                today = datetime.now()
                prefix = f"DLV-{today.strftime('%Y%m%d')}"
                last = (
                    db.query(Delivery)
                    .filter(Delivery.number.like(f"{prefix}%"))
                    .order_by(Delivery.id.desc())
                    .first()
                )
                try:
                    seq = int(last.number.split("-")[-1]) + 1 if last and last.number else 1
                except Exception:
                    seq = 1
                delivery = Delivery(
                    number=f"{prefix}-{seq:04d}",
                    driver_id=order.pending_driver_id,
                    order_id=order.id,
                    order_number=order.number,
                    delivery_address=(partner.address or "") if partner else "",
                    latitude=partner.latitude if partner else None,
                    longitude=partner.longitude if partner else None,
                    planned_date=today,
                    notes=f"Mijoz: {partner.name if partner else ''}, Tel: {partner.phone if partner else ''}",
                    status="in_progress",
                )
                db.add(delivery)
            db.commit()
            confirmed.append({
                "order_id": order.id,
                "order_number": order.number,
                "driver_id": order.pending_driver_id,
                "total": float(order.total or 0),
            })
            # Telegram xabar
            try:
                from app.bot.services.notifier import notify_order_ready_for_delivery
                notify_order_ready_for_delivery(order.number, order.pending_driver_id)
            except Exception:
                pass
        except Exception as e:
            db.rollback()
            print(f"[try_confirm_waiting_orders] order={order.id} xato: {e}", flush=True)
    return confirmed
