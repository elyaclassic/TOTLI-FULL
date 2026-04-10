"""Telegram orqali avtomatik bildirish yuborish"""
import asyncio
from datetime import date, datetime, timedelta
from typing import Optional

from aiogram import Bot

from app.bot.config import BOT_TOKEN, NOTIFY_CHAT_IDS, REALTIME_CHAT_IDS
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
            try:
                loop.run_until_complete(send_notify(text))
            finally:
                loop.close()
        except Exception as e:
            import traceback
            print(f"[TG Notify] thread xato: {e}", flush=True)
            traceback.print_exc()

    # Tekshirish: hozirda asyncio loop ishlayaptimi
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        # Async context (FastAPI/uvicorn) — thread orqali yuborish
        t = threading.Thread(target=_send_in_thread, daemon=False)
        t.start()
        t.join(timeout=15)
    else:
        # Sync context — to'g'ridan-to'g'ri
        _send_in_thread()



async def _send_to_chats(text: str, chat_ids: list):
    """Berilgan chat_ids larga xabar yuborish"""
    from aiogram.client.default import DefaultBotProperties
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    try:
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id, text, parse_mode="HTML")
            except Exception as e:
                print(f"[TG Notify] Xato ({chat_id}): {e}")
    finally:
        await bot.session.close()


def _send_to_chats_sync(text: str, chat_ids: list):
    """Sync versiya"""
    import threading
    def _run():
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(_send_to_chats(text, chat_ids))
            finally:
                loop.close()
        except Exception as e:
            import traceback
            print(f"[TG Notify] thread xato: {e}", flush=True)
            traceback.print_exc()

    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        t = threading.Thread(target=_run, daemon=False)
        t.start()
        t.join(timeout=15)
    else:
        _run()


# ============= REAL-TIME BILDIRISHNOMALAR (ELYA CLASSIC uchun) =============
def notify_new_sale(order_number: str, partner_name: str, total: float, paid: float):
    text = (
        f"🛒 <b>Yangi sotuv</b>\n\n"
        f"Buyurtma: <b>{order_number}</b>\n"
        f"Mijoz: {partner_name}\n"
        f"Summa: <b>{fmt(total)}</b> so'm\n"
        f"To'langan: {fmt(paid)} so'm"
    )
    _send_to_chats_sync(text, REALTIME_CHAT_IDS)


def notify_big_sale(order_number: str, partner_name: str, total: float):
    text = (
        f"💎 <b>Katta sotuv!</b>\n\n"
        f"Buyurtma: <b>{order_number}</b>\n"
        f"Mijoz: {partner_name}\n"
        f"Summa: <b>{fmt(total)}</b> so'm"
    )
    _send_to_chats_sync(text, REALTIME_CHAT_IDS)


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
    _send_to_chats_sync(text, REALTIME_CHAT_IDS)


def notify_expense(doc_number: str, total: float, description: str = ""):
    text = (
        f"📉 <b>Harajat tasdiqlandi</b>\n\n"
        f"Hujjat: {doc_number}\n"
        f"Summa: <b>{fmt(total)}</b> so'm"
    )
    if description:
        text += f"\n{description}"
    _send_to_chats_sync(text, REALTIME_CHAT_IDS)


# ============= KUNLIK YAKUNIY HISOBOT (@RD2197 uchun) =============
def send_daily_summary():
    """Kechqurun kunlik yakuniy hisobot — savdo, ishlab chiqarish, harajat, to'lov, davomat, kam qoldiq"""
    from app.models.database import Production, Recipe, ExpenseDoc, Payment as PaymentModel
    db = SessionLocal()
    try:
        today = date.today()
        start_dt = datetime.combine(today, datetime.min.time())
        end_dt = datetime.combine(today, datetime.max.time())

        # === SAVDO ===
        sales = db.query(Order).filter(
            Order.type == "sale",
            Order.status.in_(["confirmed", "completed"]),
            Order.date >= start_dt, Order.date <= end_dt,
        ).all()
        sale_total = sum(o.total or 0 for o in sales)
        sale_paid = sum(o.paid or 0 for o in sales)
        sale_debt = sum(o.debt or 0 for o in sales)

        # Katta sotuvlar (10 mln+)
        big_sales = [o for o in sales if (o.total or 0) >= 10_000_000]

        # === ISHLAB CHIQARISH ===
        prods = db.query(Production).filter(
            Production.status == "completed",
            Production.date >= start_dt, Production.date <= end_dt,
        ).all()
        prod_lines = []
        for pr in prods:
            recipe = db.query(Recipe).filter(Recipe.id == pr.recipe_id).first()
            p = db.query(Product).filter(Product.id == recipe.product_id).first() if recipe else None
            name = p.name if p else "?"
            prod_lines.append(f"  {name}: {fmt(pr.quantity or 0)}")

        # === HARAJATLAR ===
        expenses = db.query(ExpenseDoc).filter(
            ExpenseDoc.status == "confirmed",
            ExpenseDoc.date >= start_dt, ExpenseDoc.date <= end_dt,
        ).all()
        expense_total = sum(e.total_amount or 0 for e in expenses)

        # === PUL KIRIM (qarz to'lovlari) ===
        debt_payments = db.query(PaymentModel).filter(
            PaymentModel.type == "income",
            PaymentModel.category == "sale",
            PaymentModel.status == "confirmed",
            PaymentModel.date >= start_dt, PaymentModel.date <= end_dt,
        ).all()
        # Faqat savdo bilan bog'liq bo'lmagan to'lovlar (alohida qarz to'lovlari)
        standalone_payments = [p for p in debt_payments if not p.order_id]
        payment_total = sum(p.amount or 0 for p in standalone_payments)

        # === DAVOMAT ===
        att_count = db.query(Attendance).filter(
            Attendance.date == today,
            Attendance.check_in.isnot(None),
        ).count()
        total_emps = db.query(Employee).filter(
            Employee.is_active == True,
            Employee.hikvision_id.isnot(None),
            Employee.hikvision_id != "",
        ).count()
        # Kelmaganlar
        present_ids = set()
        for a in db.query(Attendance).filter(Attendance.date == today, Attendance.check_in.isnot(None)).all():
            present_ids.add(a.employee_id)
        absent_names = []
        for e in db.query(Employee).filter(Employee.is_active == True, Employee.hikvision_id.isnot(None), Employee.hikvision_id != "").all():
            if e.id not in present_ids:
                absent_names.append(e.full_name)

        # === KAM QOLDIQ ===
        low_items = (
            db.query(Product.name, Stock.quantity, Product.min_stock)
            .join(Stock, Stock.product_id == Product.id)
            .filter(Stock.quantity < Product.min_stock, Product.is_active == True, Product.min_stock > 0)
            .order_by(Stock.quantity)
            .limit(10)
            .all()
        )

        # === JAMI QARZ ===
        total_debt = db.query(Order).filter(
            Order.type == "sale", Order.debt > 0,
        ).with_entities(func_sum(Order.debt)).scalar() or 0

        # === XABAR TUZISH ===
        text = f"<b>Kunlik hisobot — {today.strftime('%d.%m.%Y')}</b>\n"

        # Savdo
        text += f"\n<b>Savdo:</b>\n"
        text += f"  Buyurtmalar: {len(sales)} ta\n"
        text += f"  Summa: <b>{fmt(sale_total)}</b> so'm\n"
        text += f"  To'langan: {fmt(sale_paid)} so'm\n"
        if sale_debt > 0:
            text += f"  Bugungi qarz: {fmt(sale_debt)} so'm\n"
        if big_sales:
            text += f"  Katta sotuvlar: {len(big_sales)} ta (10 mln+)\n"

        # Qarz to'lovlari
        if standalone_payments:
            text += f"\n<b>Qarz to'lovlari:</b>\n"
            text += f"  {len(standalone_payments)} ta, jami: <b>{fmt(payment_total)}</b> so'm\n"

        # Ishlab chiqarish
        if prods:
            text += f"\n<b>Ishlab chiqarish:</b> {len(prods)} ta\n"
            for line in prod_lines[:8]:
                text += f"{line}\n"
            if len(prod_lines) > 8:
                text += f"  ... va yana {len(prod_lines) - 8} ta\n"

        # Harajatlar
        if expenses:
            text += f"\n<b>Harajatlar:</b>\n"
            text += f"  {len(expenses)} ta, jami: <b>{fmt(expense_total)}</b> so'm\n"

        # Davomat
        text += f"\n<b>Davomat:</b> {att_count}/{total_emps}\n"
        if absent_names:
            text += f"  Kelmaganlar: {', '.join(absent_names[:5])}"
            if len(absent_names) > 5:
                text += f" +{len(absent_names) - 5}"
            text += "\n"

        # Kam qoldiq
        if low_items:
            text += f"\n<b>Kam qoldiq:</b> {len(low_items)} ta\n"
            for item in low_items[:5]:
                text += f"  {item.name}: <b>{fmt(item.quantity)}</b> (min: {fmt(item.min_stock)})\n"
            if len(low_items) > 5:
                text += f"  ... va yana {len(low_items) - 5} ta\n"

        # Jami qarz
        text += f"\n<b>Jami qarzdorlik:</b> {fmt(total_debt)} so'm"

        send_notify_sync(text)
    except Exception as e:
        print(f"[TG Notify] daily summary xato: {e}")
    finally:
        db.close()


# sqlalchemy func.sum import
from sqlalchemy import func as func_sum
