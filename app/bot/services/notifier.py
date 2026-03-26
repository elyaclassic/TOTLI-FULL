"""Telegram orqali avtomatik bildirish yuborish"""
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from aiogram import Bot

from app.bot.config import BOT_TOKEN, NOTIFY_CHAT_IDS
from app.models.database import (
    SessionLocal, Order, Stock, Product, Employee, Attendance, Partner,
)
from app.bot.services.report_queries import fmt

_bot: Optional[Bot] = None


def _get_bot() -> Bot:
    global _bot
    if _bot is None or _bot.session.closed:
        from aiogram.client.default import DefaultBotProperties
        _bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    return _bot


async def send_notify(text: str):
    """Barcha rahbarlarga bildirish yuborish"""
    from aiogram.client.default import DefaultBotProperties
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        for chat_id in NOTIFY_CHAT_IDS:
            try:
                await bot.send_message(chat_id, text, parse_mode="HTML")
            except Exception as e:
                print(f"[TG Notify] Xato ({chat_id}): {e}")
    finally:
        await bot.session.close()


def send_notify_sync(text: str):
    """Sync koddan chaqirish uchun (route/scheduler ichidan)"""
    import threading

    def _send_in_thread():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(send_notify(text))
            loop.close()
        except Exception as e:
            print(f"[TG Notify] thread xato: {e}")

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # FastAPI/uvicorn ichida — alohida threadda yuborish
            t = threading.Thread(target=_send_in_thread, daemon=True)
            t.start()
        else:
            loop.run_until_complete(send_notify(text))
    except RuntimeError:
        _send_in_thread()


# ============= 1. YANGI SOTUV BUYURTMASI =============
def notify_new_sale(order_number: str, partner_name: str, total: float, paid: float):
    text = (
        f"🛒 <b>Yangi sotuv</b>\n\n"
        f"Buyurtma: <b>{order_number}</b>\n"
        f"Mijoz: {partner_name}\n"
        f"Summa: <b>{fmt(total)}</b> so'm\n"
        f"To'langan: {fmt(paid)} so'm"
    )
    send_notify_sync(text)


# ============= 2. KATTA SUMMA SOTUV =============
def notify_big_sale(order_number: str, partner_name: str, total: float):
    text = (
        f"💎 <b>Katta sotuv!</b>\n\n"
        f"Buyurtma: <b>{order_number}</b>\n"
        f"Mijoz: {partner_name}\n"
        f"Summa: <b>{fmt(total)}</b> so'm"
    )
    send_notify_sync(text)


# ============= 3. QARZDOR TO'LOV =============
def notify_debt_payment(partner_name: str, amount: float, remaining_debt: float):
    text = (
        f"💳 <b>Qarz to'lovi</b>\n\n"
        f"Mijoz: {partner_name}\n"
        f"To'langan: <b>{fmt(amount)}</b> so'm\n"
        f"Qolgan qarz: {fmt(remaining_debt)} so'm"
    )
    send_notify_sync(text)


# ============= 4. XODIM KELMADI (ertalab) =============
def check_absent_employees():
    """Ertalab tekshirish — kim kelmagan"""
    db = SessionLocal()
    try:
        today = date.today()
        present_ids = set()
        atts = db.query(Attendance).filter(
            Attendance.date == today,
            Attendance.check_in.isnot(None),
        ).all()
        for a in atts:
            present_ids.add(a.employee_id)
        all_emps = db.query(Employee).filter(Employee.is_active == True).all()
        absent = []
        for e in all_emps:
            if e.id not in present_ids:
                # Sotuvchilar (hikvision_id yo'q) o'tkazib yuboriladi
                if not getattr(e, "hikvision_id", None):
                    continue
                absent.append(e.full_name)
        if absent:
            text = (
                f"❌ <b>Bugun kelmaganlar</b> ({today.strftime('%d.%m.%Y')})\n\n"
                + "\n".join(f"  • {name}" for name in absent)
                + f"\n\nJami: <b>{len(absent)}</b> ta xodim"
            )
            send_notify_sync(text)
    except Exception as e:
        print(f"[TG Notify] absent check xato: {e}")
    finally:
        db.close()


# ============= 5. KAM QOLGAN TOVAR =============
def check_low_stock_notify():
    """Kam qolgan tovarlarni bildirish"""
    db = SessionLocal()
    try:
        low_items = (
            db.query(Product.name, Stock.quantity, Product.min_stock)
            .join(Stock, Stock.product_id == Product.id)
            .filter(
                Stock.quantity < Product.min_stock,
                Product.is_active == True,
                Product.min_stock > 0,
            )
            .order_by(Stock.quantity)
            .limit(15)
            .all()
        )
        if low_items:
            lines = [f"⚠️ <b>Kam qolgan tovarlar</b>\n"]
            for item in low_items:
                lines.append(f"  • {item.name}: <b>{fmt(item.quantity)}</b> (min: {fmt(item.min_stock)})")
            lines.append(f"\nJami: <b>{len(low_items)}</b> ta")
            send_notify_sync("\n".join(lines))
    except Exception as e:
        print(f"[TG Notify] low stock xato: {e}")
    finally:
        db.close()


# ============= 6. KUNLIK YAKUNIY HISOBOT =============
def send_daily_summary():
    """Kechqurun kunlik yakuniy hisobot"""
    db = SessionLocal()
    try:
        today = date.today()
        start_dt = datetime.combine(today, datetime.min.time())
        end_dt = datetime.combine(today, datetime.max.time())

        # Savdo
        sales = db.query(Order).filter(
            Order.type == "sale",
            Order.status.in_(["confirmed", "completed"]),
            Order.date >= start_dt, Order.date <= end_dt,
        ).all()
        sale_total = sum(o.total or 0 for o in sales)
        sale_paid = sum(o.paid or 0 for o in sales)
        sale_debt = sum(o.debt or 0 for o in sales)

        # Davomat
        att_count = db.query(Attendance).filter(
            Attendance.date == today,
            Attendance.check_in.isnot(None),
        ).count()
        total_emps = db.query(Employee).filter(
            Employee.is_active == True,
            Employee.hikvision_id.isnot(None),
            Employee.hikvision_id != "",
        ).count()

        # Jami qarz
        total_debt = db.query(Order).filter(
            Order.type == "sale", Order.debt > 0,
        ).with_entities(func_sum(Order.debt)).scalar() or 0

        text = (
            f"📊 <b>Kunlik hisobot — {today.strftime('%d.%m.%Y')}</b>\n\n"
            f"💰 <b>Savdo:</b>\n"
            f"  Buyurtmalar: {len(sales)} ta\n"
            f"  Summa: {fmt(sale_total)} so'm\n"
            f"  To'langan: {fmt(sale_paid)} so'm\n"
            f"  Qarz: {fmt(sale_debt)} so'm\n\n"
            f"📋 <b>Davomat:</b>\n"
            f"  Kelgan: {att_count}/{total_emps} xodim\n\n"
            f"📌 <b>Jami qarzdorlik:</b> {fmt(total_debt)} so'm"
        )
        send_notify_sync(text)
    except Exception as e:
        print(f"[TG Notify] daily summary xato: {e}")
    finally:
        db.close()


# ============= 7. ISHLAB CHIQARISH TAYYOR =============
def notify_production_ready(production_number: str, product_name: str, quantity: float, is_semi: bool = False):
    if is_semi:
        text = (
            f"🔶 <b>Qiyom/yarim tayyor yakunlandi</b>\n\n"
            f"Raqam: {production_number}\n"
            f"Mahsulot: {product_name}\n"
            f"Miqdor: {fmt(quantity)}"
        )
    else:
        text = (
            f"✅ <b>Tayyor mahsulot yakunlandi</b>\n\n"
            f"Raqam: {production_number}\n"
            f"Mahsulot: {product_name}\n"
            f"Miqdor: {fmt(quantity)}"
        )
    send_notify_sync(text)


# ============= 8. HARAJAT =============
def notify_expense(doc_number: str, total: float, description: str = ""):
    text = (
        f"📉 <b>Harajat tasdiqlandi</b>\n\n"
        f"Hujjat: {doc_number}\n"
        f"Summa: <b>{fmt(total)}</b> so'm"
    )
    if description:
        text += f"\n{description}"
    send_notify_sync(text)


# ============= 9. PUL KIRIM =============
def notify_payment_income(partner_name: str, amount: float, payment_type: str = ""):
    pt = {"cash": "Naqd", "card": "Karta", "transfer": "O'tkazma"}.get(payment_type, payment_type or "")
    text = (
        f"💵 <b>Pul kirim</b>\n\n"
        f"Mijoz: {partner_name}\n"
        f"Summa: <b>{fmt(amount)}</b> so'm"
    )
    if pt:
        text += f"\nTuri: {pt}"
    send_notify_sync(text)


# sqlalchemy func.sum import
from sqlalchemy import func as func_sum
