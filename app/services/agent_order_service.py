"""
Agent buyurtmalari uchun service: waiting_production → out_for_delivery avtomatik o'tish.

Production tugagach (status='completed') chaqiriladi: barcha waiting_production
buyurtmalarni tekshiradi, stok yetib va driver tanlangan bo'lsa avtomatik
out_for_delivery ga o'tkazib delivery yaratadi.

Balance YOZILMAYDI — bu faqat driver "Yetkazdim" bosgach yoziladi.
Driver tanlanmagan bo'lsa transition bo'lmaydi — supervisor /dispatch dan tanlashi kerak.
"""
from datetime import datetime
from typing import List, Dict, Any
from sqlalchemy import text as _text
from sqlalchemy.orm import Session

from app.models.database import Order, Stock, Delivery, Partner, Product
from app.services.stock_service import apply_sale_stock_deduction


def try_confirm_waiting_orders(db: Session) -> List[Dict[str, Any]]:
    """waiting_production statusdagi agent buyurtmalarini tekshirib, yetganlarini auto-dispatch qiladi.

    Shartlar:
      - Stok yetadi
      - pending_driver_id tanlangan (NULL bo'lsa skip)

    Qaytaradi: o'tkazilganlar haqida axborot ([{order_id, order_number, driver_id, total}]).
    Balance YOZILMAYDI (driver Yetkazdim'gacha kutiladi).
    """
    promoted: List[Dict[str, Any]] = []
    waiting = (
        db.query(Order)
        .filter(Order.source == "agent", Order.status == "waiting_production")
        .order_by(Order.date)
        .all()
    )
    if not waiting:
        return promoted

    for order in waiting:
        try:
            # Driver tanlanmagan bo'lsa skip (supervisor /dispatch dan tanlashi kerak)
            if not order.pending_driver_id:
                continue

            valid_items = [it for it in order.items if it.product_id and (it.quantity or 0) > 0]
            if not valid_items:
                continue

            # Stok yetganligini tekshirish
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
                have = float(stock.quantity or 0) if stock else 0.0
                need = float(it.quantity or 0)
                if have + 1e-6 < need:
                    enough = False
                    break
            if not enough:
                continue

            # Atomik o'tish — race condition oldini olish
            now = datetime.now()
            r = db.execute(
                _text(
                    "UPDATE orders SET status='out_for_delivery', dispatched_at=:now "
                    "WHERE id=:id AND status='waiting_production'"
                ),
                {"id": order.id, "now": now},
            )
            if r.rowcount != 1:
                continue

            # Stok kamaytirish — harakat sanasi YO'LGA CHIQQAN lahza (now), order.date emas
            apply_sale_stock_deduction(db, order, None, note_prefix="Auto-dispatch (production tayyor)",
                                       movement_date=now)

            # Delivery yaratish
            partner = db.query(Partner).filter(Partner.id == order.partner_id).first() if order.partner_id else None
            planned_date = order.delivery_date or now
            prefix = f"DLV-{now.strftime('%Y%m%d')}"
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
                planned_date=planned_date,
                notes=f"Mijoz: {partner.name if partner else ''}, Tel: {partner.phone if partner else ''}",
                status="pending",
            )
            db.add(delivery)
            db.commit()

            promoted.append({
                "order_id": order.id,
                "order_number": order.number,
                "driver_id": order.pending_driver_id,
                "total": float(order.total or 0),
            })

            # Telegram bildirish
            try:
                from app.bot.services.notifier import notify_order_ready_for_delivery
                notify_order_ready_for_delivery(order.number, order.pending_driver_id)
            except Exception:
                pass
        except Exception as e:
            db.rollback()
            print(f"[try_confirm_waiting_orders] order={order.id} xato: {e}", flush=True)
    return promoted
