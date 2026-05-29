import logging
from datetime import date, timedelta

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    Message, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery,
)

from app.models.database import SessionLocal, Partner
from app.bot.customer_bot.config import admin_ids
from app.bot.customer_bot import registration as reg
from app.bot.customer_bot import queries as q

logger = logging.getLogger(__name__)
router = Router()


def _contact_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def _menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Buyurtmalarim"), KeyboardButton(text="💰 Qarz/Avans qoldig'i")],
            [KeyboardButton(text="📅 Hisobot"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True,
    )


def _approved_partner(db, tg_id):
    link = reg.get_link_by_telegram(db, tg_id)
    if link and link.status == "approved" and link.partner_id:
        return db.query(Partner).filter(Partner.id == link.partner_id).first()
    return None


@router.message(CommandStart())
async def on_start(message: Message):
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
    finally:
        db.close()
    if p:
        await message.answer(f"Assalomu alaykum, {p.name}!", reply_markup=_menu_kb())
    else:
        await message.answer(
            "👋 Assalomu alaykum!\n\nBu — TOTLI HOLVA mijozlar boti. "
            "Buyurtmalaringiz va qarz/avans qoldig'ingizni kuzatishingiz mumkin.\n\n"
            "Boshlash uchun telefon raqamingizni ulashing 👇",
            reply_markup=_contact_kb(),
        )


@router.message(F.contact)
async def on_contact(message: Message):
    # faqat O'ZINING raqamini qabul qilamiz (boshqa kontaktni emas)
    if message.contact.user_id != message.from_user.id:
        await message.answer("Iltimos, o'zingizning raqamingizni ulashing.")
        return
    phone = message.contact.phone_number
    db = SessionLocal()
    try:
        matches = reg.find_matching_partners(db, phone)
        if not matches:
            await message.answer(
                "❌ Raqamingiz tizimda topilmadi. Iltimos, agentingizga murojaat qiling."
            )
            return
        link = reg.create_pending_link(
            db, message.from_user.id, message.from_user.username,
            message.from_user.full_name, message.contact.phone_number,
        )
        await message.answer(
            f"✅ Raqamingiz qabul qilindi: {phone}\n\n"
            "So'rovingiz administratorga yuborildi. Tasdiqlangach xabar beramiz. ⏳",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[]], resize_keyboard=True),
        )
        # adminlarga tasdiq tugmalari — har admin uchun har kandidat uchun alohida xabar
        for admin in admin_ids():
            for cand in matches:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text=f"✅ {cand.name}",
                        callback_data=f"cbapprove:{link.id}:{cand.id}",
                    ),
                    InlineKeyboardButton(text="❌ Rad", callback_data=f"cbreject:{link.id}"),
                ]])
                await message.bot.send_message(
                    admin,
                    f"🆕 Yangi mijoz so'rovi\nDo'kon: <b>{cand.name}</b>\n"
                    f"Telefon: {phone}\nTelegram: @{message.from_user.username or '—'} ({message.from_user.id})",
                    reply_markup=kb,
                )
    finally:
        db.close()


@router.callback_query(F.data.startswith("cbapprove:"))
async def on_approve(cb: CallbackQuery):
    if cb.from_user.id not in admin_ids():
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    _, link_id, partner_id = cb.data.split(":")
    db = SessionLocal()
    try:
        link = reg.approve_link(db, int(link_id), int(partner_id), cb.from_user.id)
        tg = link.telegram_id
    finally:
        db.close()
    await cb.message.edit_text(cb.message.text + "\n\n✅ TASDIQLANDI")
    try:
        await cb.bot.send_message(
            int(tg), "🎉 Tabriklaymiz, ulandingiz!", reply_markup=_menu_kb()
        )
    except Exception as e:
        logger.warning(f"approve notify fail: {e}")
    await cb.answer("Tasdiqlandi")


@router.callback_query(F.data.startswith("cbreject:"))
async def on_reject(cb: CallbackQuery):
    if cb.from_user.id not in admin_ids():
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    _, link_id = cb.data.split(":")
    db = SessionLocal()
    try:
        link = reg.reject_link(db, int(link_id), cb.from_user.id)
        tg = link.telegram_id
    finally:
        db.close()
    await cb.message.edit_text(cb.message.text + "\n\n❌ RAD ETILDI")
    try:
        await cb.bot.send_message(
            int(tg), "Kechirasiz, so'rovingiz tasdiqlanmadi. Agentingizga murojaat qiling."
        )
    except Exception:
        pass
    await cb.answer("Rad etildi")


@router.message(F.text == "💰 Qarz/Avans qoldig'i")
async def on_balance(message: Message):
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
        if not p:
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
        await message.answer(q.balance_text(p))
    finally:
        db.close()


@router.message(F.text == "📦 Buyurtmalarim")
async def on_orders(message: Message):
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
        if not p:
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
        orders = q.recent_orders(db, p.id, limit=10)
        if not orders:
            await message.answer("Buyurtmalar topilmadi.")
            return
        lines = ["📦 <b>Oxirgi buyurtmalar:</b>\n"]
        for o in orders:
            d = o.date.strftime("%d.%m.%Y") if o.date else ""
            lines.append(
                f"№ {o.number} — {d}\n"
                f"  {q.fmt_money(o.total)} so'm · {q.order_status_label(o.status)}"
            )
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(F.text == "📅 Hisobot")
async def on_report_menu(message: Message):
    db = SessionLocal()
    try:
        if not _approved_partner(db, message.from_user.id):
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
    finally:
        db.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Bugun", callback_data="cbrep:today"),
         InlineKeyboardButton(text="Shu hafta", callback_data="cbrep:week")],
        [InlineKeyboardButton(text="Shu oy", callback_data="cbrep:month"),
         InlineKeyboardButton(text="30 kun", callback_data="cbrep:30")],
        [InlineKeyboardButton(text="🗓 Oraliq tanlash", callback_data="cbrep:custom")],
    ])
    await message.answer("📅 Davrni tanlang:", reply_markup=kb)


def _range_for(key):
    today = date.today()
    if key == "today":
        return today, today
    if key == "week":
        return today - timedelta(days=today.weekday()), today
    if key == "month":
        return today.replace(day=1), today
    return today - timedelta(days=30), today  # "30"


@router.callback_query(F.data.startswith("cbrep:") & ~F.data.endswith(":custom"))
async def on_report(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    if key == "custom":
        return
    d_from, d_to = _range_for(key)
    db = SessionLocal()
    try:
        p = _approved_partner(db, cb.from_user.id)
        if not p:
            await cb.answer("Avval ulaning", show_alert=True)
            return
        st = q.statement(db, p.id, d_from, d_to)
    finally:
        db.close()
    lines = [
        f"📅 <b>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</b>\n",
        f"Buyurtmalar: <b>{q.fmt_money(st['total_orders'])}</b> so'm ({len(st['orders'])} ta)",
        f"To'langan: <b>{q.fmt_money(st['total_paid'])}</b> so'm ({len(st['payments'])} ta)\n",
    ]
    for o in st["orders"][:30]:
        lines.append(f"  № {o.number} — {q.fmt_money(o.total)} so'm · {q.order_status_label(o.status)}")
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.message(F.text == "ℹ️ Yordam")
async def on_help(message: Message):
    await message.answer(
        "ℹ️ Bu bot orqali buyurtmalaringiz, to'lovlaringiz va qarz/avans "
        "qoldig'ingizni ko'rishingiz mumkin. Savollar uchun agentingizga murojaat qiling."
    )


# ── FSM: qo'lda sana oraliq tanlash ─────────────────────────────────────────
# Task 9B: MUHIM — FSM handlerlari catch-all on_other DAN OLDIN turishi kerak.

class ReportRange(StatesGroup):
    waiting_from = State()
    waiting_to = State()


@router.callback_query(F.data == "cbrep:custom")
async def on_custom_range_start(cb: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        if not _approved_partner(db, cb.from_user.id):
            await cb.answer("Avval ulaning", show_alert=True)
            return
    finally:
        db.close()
    await state.set_state(ReportRange.waiting_from)
    await cb.message.answer("🗓 Boshlanish sanasini kiriting (masalan 01.05.2026):")
    await cb.answer()


@router.message(ReportRange.waiting_from)
async def on_range_from(message: Message, state: FSMContext):
    d = q.parse_date_uz(message.text)
    if not d:
        await message.answer("Sana noto'g'ri. Masalan: 01.05.2026")
        return
    await state.update_data(d_from=d.isoformat())
    await state.set_state(ReportRange.waiting_to)
    await message.answer("Tugash sanasini kiriting (masalan 15.05.2026):")


@router.message(ReportRange.waiting_to)
async def on_range_to(message: Message, state: FSMContext):
    d_to = q.parse_date_uz(message.text)
    if not d_to:
        await message.answer("Sana noto'g'ri. Masalan: 15.05.2026")
        return
    data = await state.get_data()
    d_from = date.fromisoformat(data["d_from"])
    await state.clear()
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
        if not p:
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
        st = q.statement(db, p.id, d_from, d_to)
    finally:
        db.close()
    lines = [
        f"📅 <b>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</b>\n",
        f"Buyurtmalar: <b>{q.fmt_money(st['total_orders'])}</b> so'm ({len(st['orders'])} ta)",
        f"To'langan: <b>{q.fmt_money(st['total_paid'])}</b> so'm ({len(st['payments'])} ta)\n",
    ]
    for o in st["orders"][:30]:
        lines.append(f"  № {o.number} — {q.fmt_money(o.total)} so'm · {q.order_status_label(o.status)}")
    await message.answer("\n".join(lines), reply_markup=_menu_kb())


# ── Catch-all: FSM handlerlaridan KEYIN ──────────────────────────────────────
@router.message()
async def on_other(message: Message):
    db = SessionLocal()
    try:
        if _approved_partner(db, message.from_user.id):
            await message.answer("Quyidagi menyudan tanlang 👇", reply_markup=_menu_kb())
        else:
            await message.answer(
                "Boshlash uchun telefon raqamingizni ulashing 👇", reply_markup=_contact_kb()
            )
    finally:
        db.close()
