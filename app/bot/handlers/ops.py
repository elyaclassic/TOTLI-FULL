"""Bot ichidan operatsiya kirityish: harajat, pul kirim, kassa o'tkazma, tovar kirim.

Ishlash oqimi:
1. /ops yoki "💼 Amaliyot" tugmasi → PIN so'raladi (agar sessiya faol bo'lmasa)
2. PIN to'g'ri → asosiy ops menyu
3. Har operatsiya o'z FSM bilan bosqichma-bosqich
4. Tasdiqlash oynasi → Saqla / Bekor
5. Saqlansa: DB ga yoziladi + audit_* chaqiriladi
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from app.bot.handlers.ops_auth import is_ops_allowed, pin_ok, pin_grant, pin_revoke, check_pin
from app.models.database import (
    SessionLocal, CashRegister, ExpenseDoc, ExpenseDocItem, ExpenseType,
    Payment, CashTransfer, Partner,
)
from sqlalchemy import func

router = Router()


# ============ FSM STATES ============
class PinStates(StatesGroup):
    waiting_pin = State()


class ExpenseStates(StatesGroup):
    cash = State()
    type = State()
    amount = State()
    note = State()
    confirm = State()


class IncomeStates(StatesGroup):
    cash = State()
    payment_type = State()
    amount = State()
    partner = State()
    note = State()
    confirm = State()


class TransferStates(StatesGroup):
    from_cash = State()
    to_cash = State()
    amount = State()
    note = State()
    confirm = State()


# ============ KEYBOARDS ============
def _ops_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Harajat", callback_data="ops:expense"),
         InlineKeyboardButton(text="💰 Pul kirim", callback_data="ops:income")],
        [InlineKeyboardButton(text="↔️ Kassa o'tkazma", callback_data="ops:transfer"),
         InlineKeyboardButton(text="📥 Tovar kirim", callback_data="ops:purchase")],
        [InlineKeyboardButton(text="🔒 Chiqish (logout)", callback_data="ops:logout")],
    ])


def _yes_no_kb(yes_data: str, no_data: str = "ops:cancel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Saqla", callback_data=yes_data),
         InlineKeyboardButton(text="❌ Bekor", callback_data=no_data)],
    ])


def _cash_registers_kb(prefix: str) -> InlineKeyboardMarkup:
    """Aktiv kassalar ro'yxati inline tugma sifatida."""
    db = SessionLocal()
    try:
        regs = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.id).all()
        rows = []
        for cr in regs:
            rows.append([InlineKeyboardButton(text=cr.name, callback_data=f"{prefix}:{cr.id}")])
        rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data="ops:cancel")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    finally:
        db.close()


def _expense_types_kb() -> InlineKeyboardMarkup:
    """Aktiv harajat turlari ro'yxati."""
    db = SessionLocal()
    try:
        types_q = db.query(ExpenseType).filter(ExpenseType.is_active == True).order_by(ExpenseType.name).limit(30).all()
        rows = []
        for et in types_q:
            rows.append([InlineKeyboardButton(text=et.name, callback_data=f"ops:exptype:{et.id}")])
        rows.append([InlineKeyboardButton(text="➕ Tur yo'q — har qanday", callback_data="ops:exptype:0")])
        rows.append([InlineKeyboardButton(text="❌ Bekor", callback_data="ops:cancel")])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    finally:
        db.close()


def _payment_types_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💵 Naqd", callback_data="ops:ptype:naqd"),
         InlineKeyboardButton(text="💳 Plastik", callback_data="ops:ptype:plastik")],
        [InlineKeyboardButton(text="🏦 Perechisleniye", callback_data="ops:ptype:perechisleniye")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="ops:cancel")],
    ])


def _income_category_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="— Mijozsiz —", callback_data="ops:partner:0")],
        [InlineKeyboardButton(text="❌ Bekor", callback_data="ops:cancel")],
    ])


def _fmt(v) -> str:
    try:
        return f"{float(v or 0):,.0f}".replace(",", " ")
    except Exception:
        return str(v)


# ============ ENTRY POINT — /ops ============
@router.message(Command("ops"))
async def cmd_ops(message: Message, state: FSMContext):
    if not is_ops_allowed(message.from_user.id):
        await message.answer("⛔ Sizga ruxsat berilmagan.")
        return
    await state.clear()
    if not pin_ok(message.from_user.id):
        await state.set_state(PinStates.waiting_pin)
        await message.answer("🔒 PIN kodni yuboring:")
        return
    await message.answer("💼 <b>Amaliyot menyu</b>\nQaysi operatsiya?", reply_markup=_ops_menu_kb())


@router.message(PinStates.waiting_pin)
async def on_pin(message: Message, state: FSMContext):
    if not is_ops_allowed(message.from_user.id):
        await state.clear()
        return
    if check_pin(message.text or ""):
        exp = pin_grant(message.from_user.id)
        await state.clear()
        # Xavfsizlik: PIN xabarini o'chirib yuborish
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(
            f"✅ PIN qabul qilindi. Sessiya: {exp.strftime('%d.%m %H:%M')} gacha.",
            reply_markup=_ops_menu_kb(),
        )
    else:
        await message.answer("❌ PIN noto'g'ri. Qayta yuboring (yoki /cancel):")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.")


@router.callback_query(F.data == "ops:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("Bekor qilindi.")
    except Exception:
        await callback.message.answer("Bekor qilindi.")
    await callback.answer()


@router.callback_query(F.data == "ops:logout")
async def cb_logout(callback: CallbackQuery, state: FSMContext):
    pin_revoke(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("🔒 PIN sessiyasi yopildi. /ops — qayta kirish.")
    await callback.answer()


# ============ OPERATION ENTRY ============
def _require_ops(callback: CallbackQuery) -> bool:
    if not is_ops_allowed(callback.from_user.id):
        return False
    if not pin_ok(callback.from_user.id):
        return False
    return True


# --- HARAJAT (Expense) ---
@router.callback_query(F.data == "ops:expense")
async def cb_expense_start(callback: CallbackQuery, state: FSMContext):
    if not _require_ops(callback):
        await callback.answer("PIN kerak", show_alert=True)
        return
    await state.clear()
    await state.set_state(ExpenseStates.cash)
    await callback.message.edit_text("💸 <b>Harajat</b>\n\nQaysi kassadan?", reply_markup=_cash_registers_kb("ops:exp_cash"))
    await callback.answer()


@router.callback_query(F.data.startswith("ops:exp_cash:"), ExpenseStates.cash)
async def cb_expense_cash(callback: CallbackQuery, state: FSMContext):
    cash_id = int(callback.data.split(":")[-1])
    await state.update_data(cash_id=cash_id)
    await state.set_state(ExpenseStates.type)
    await callback.message.edit_text("💸 Harajat turi?", reply_markup=_expense_types_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("ops:exptype:"), ExpenseStates.type)
async def cb_expense_type(callback: CallbackQuery, state: FSMContext):
    type_id = int(callback.data.split(":")[-1])
    await state.update_data(type_id=type_id if type_id > 0 else None)
    await state.set_state(ExpenseStates.amount)
    await callback.message.edit_text("💸 Summa (so'm)? Raqam yozing:")
    await callback.answer()


@router.message(ExpenseStates.amount)
async def on_expense_amount(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(" ", "").replace(",", "."))
        if amt <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("⚠ Noto'g'ri summa. Raqam yuboring (masalan: 50000):")
        return
    await state.update_data(amount=amt)
    await state.set_state(ExpenseStates.note)
    await message.answer("📝 Izoh yozing (yoki /skip):")


@router.message(ExpenseStates.note, Command("skip"))
async def on_expense_skip_note(message: Message, state: FSMContext):
    await state.update_data(note="")
    await _expense_confirm(message, state)


@router.message(ExpenseStates.note)
async def on_expense_note(message: Message, state: FSMContext):
    await state.update_data(note=(message.text or "")[:500])
    await _expense_confirm(message, state)


async def _expense_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    db = SessionLocal()
    try:
        cr = db.query(CashRegister).filter(CashRegister.id == data["cash_id"]).first()
        et = db.query(ExpenseType).filter(ExpenseType.id == data["type_id"]).first() if data.get("type_id") else None
    finally:
        db.close()
    text = (
        "💸 <b>Harajat — tasdiqlash</b>\n\n"
        f"Kassa: <b>{cr.name if cr else '—'}</b>\n"
        f"Tur: <b>{et.name if et else '—'}</b>\n"
        f"Summa: <b>{_fmt(data['amount'])}</b> so'm\n"
        f"Izoh: {data.get('note') or '—'}"
    )
    await state.set_state(ExpenseStates.confirm)
    await message.answer(text, reply_markup=_yes_no_kb("ops:exp_save"))


@router.callback_query(F.data == "ops:exp_save", ExpenseStates.confirm)
async def cb_expense_save(callback: CallbackQuery, state: FSMContext):
    if not _require_ops(callback):
        return
    data = await state.get_data()
    # DB yaratish
    result = await asyncio.to_thread(_save_expense, data)
    await state.clear()
    await callback.message.edit_text(result)
    await callback.answer("Saqlandi")


def _save_expense(data: dict) -> str:
    """Expense doc + payment yaratish (sinxron DB)."""
    db = SessionLocal()
    try:
        today = datetime.now()
        prefix = f"EXP-{today.strftime('%Y%m%d')}"
        last = db.query(ExpenseDoc).filter(ExpenseDoc.number.like(f"{prefix}%")).order_by(ExpenseDoc.id.desc()).first()
        try:
            seq = int(last.number.split("-")[-1]) + 1 if last and last.number else 1
        except Exception:
            seq = 1
        number = f"{prefix}-{seq:03d}"

        doc = ExpenseDoc(
            number=number,
            date=today,
            cash_register_id=data["cash_id"],
            total_amount=float(data["amount"]),
            note=data.get("note") or "",
            status="confirmed",
        )
        db.add(doc)
        db.flush()
        if data.get("type_id"):
            item = ExpenseDocItem(
                expense_doc_id=doc.id,
                expense_type_id=data["type_id"],
                amount=float(data["amount"]),
                note=data.get("note") or "",
            )
            db.add(item)
        # Payment (expense kategoriyasi)
        last_p = db.query(Payment).order_by(Payment.id.desc()).first()
        p_num = f"PAY-{today.strftime('%Y%m%d')}-{((last_p.id + 1) if last_p else 1):04d}"
        payment = Payment(
            number=p_num,
            date=today,
            type="expense",
            cash_register_id=data["cash_id"],
            amount=float(data["amount"]),
            category="expense",
            description=f"Bot orqali harajat: {number}",
            status="confirmed",
        )
        db.add(payment)
        db.commit()
        # Audit
        try:
            from app.bot.services.audit_watchdog import audit_expense, audit_payment
            audit_expense(doc.id)
            audit_payment(payment.id)
        except Exception:
            pass
        # Kassa balans sync
        try:
            from app.services.finance_service import sync_cash_balance
            sync_cash_balance(db, data["cash_id"])
            db.commit()
        except Exception:
            db.rollback()
        return f"✅ Harajat saqlandi: <b>{number}</b>\nSumma: {_fmt(data['amount'])} so'm"
    except Exception as e:
        db.rollback()
        return f"❌ Xato: {e}"
    finally:
        db.close()


# --- PUL KIRIM (Income Payment) ---
@router.callback_query(F.data == "ops:income")
async def cb_income_start(callback: CallbackQuery, state: FSMContext):
    if not _require_ops(callback):
        await callback.answer("PIN kerak", show_alert=True)
        return
    await state.clear()
    await state.set_state(IncomeStates.cash)
    await callback.message.edit_text("💰 <b>Pul kirim</b>\n\nQaysi kassaga?", reply_markup=_cash_registers_kb("ops:inc_cash"))
    await callback.answer()


@router.callback_query(F.data.startswith("ops:inc_cash:"), IncomeStates.cash)
async def cb_income_cash(callback: CallbackQuery, state: FSMContext):
    cash_id = int(callback.data.split(":")[-1])
    await state.update_data(cash_id=cash_id)
    await state.set_state(IncomeStates.payment_type)
    await callback.message.edit_text("💰 To'lov turi?", reply_markup=_payment_types_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("ops:ptype:"), IncomeStates.payment_type)
async def cb_income_ptype(callback: CallbackQuery, state: FSMContext):
    ptype = callback.data.split(":")[-1]
    await state.update_data(payment_type=ptype)
    await state.set_state(IncomeStates.amount)
    await callback.message.edit_text(f"💰 To'lov: {ptype}\nSumma (so'm)? Raqam yozing:")
    await callback.answer()


@router.message(IncomeStates.amount)
async def on_income_amount(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(" ", "").replace(",", "."))
        if amt <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("⚠ Noto'g'ri summa. Raqam yuboring:")
        return
    await state.update_data(amount=amt)
    await state.set_state(IncomeStates.note)
    await message.answer("📝 Izoh yozing (yoki /skip):")


@router.message(IncomeStates.note, Command("skip"))
async def on_income_skip_note(message: Message, state: FSMContext):
    await state.update_data(note="")
    await _income_confirm(message, state)


@router.message(IncomeStates.note)
async def on_income_note(message: Message, state: FSMContext):
    await state.update_data(note=(message.text or "")[:500])
    await _income_confirm(message, state)


async def _income_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    db = SessionLocal()
    try:
        cr = db.query(CashRegister).filter(CashRegister.id == data["cash_id"]).first()
    finally:
        db.close()
    text = (
        "💰 <b>Pul kirim — tasdiqlash</b>\n\n"
        f"Kassa: <b>{cr.name if cr else '—'}</b>\n"
        f"Turi: <b>{data['payment_type']}</b>\n"
        f"Summa: <b>{_fmt(data['amount'])}</b> so'm\n"
        f"Izoh: {data.get('note') or '—'}"
    )
    await state.set_state(IncomeStates.confirm)
    await message.answer(text, reply_markup=_yes_no_kb("ops:inc_save"))


@router.callback_query(F.data == "ops:inc_save", IncomeStates.confirm)
async def cb_income_save(callback: CallbackQuery, state: FSMContext):
    if not _require_ops(callback):
        return
    data = await state.get_data()
    result = await asyncio.to_thread(_save_income, data)
    await state.clear()
    await callback.message.edit_text(result)
    await callback.answer("Saqlandi")


def _save_income(data: dict) -> str:
    db = SessionLocal()
    try:
        today = datetime.now()
        last_p = db.query(Payment).order_by(Payment.id.desc()).first()
        p_num = f"PAY-{today.strftime('%Y%m%d')}-{((last_p.id + 1) if last_p else 1):04d}"
        payment = Payment(
            number=p_num,
            date=today,
            type="income",
            cash_register_id=data["cash_id"],
            amount=float(data["amount"]),
            payment_type=data["payment_type"],
            category="other",
            description=f"Bot orqali kirim: {data.get('note') or ''}".strip(),
            status="confirmed",
        )
        db.add(payment)
        db.commit()
        try:
            from app.bot.services.audit_watchdog import audit_payment
            audit_payment(payment.id)
        except Exception:
            pass
        try:
            from app.services.finance_service import sync_cash_balance
            sync_cash_balance(db, data["cash_id"])
            db.commit()
        except Exception:
            db.rollback()
        return f"✅ Pul kirim saqlandi: <b>{p_num}</b>\nSumma: {_fmt(data['amount'])} so'm"
    except Exception as e:
        db.rollback()
        return f"❌ Xato: {e}"
    finally:
        db.close()


# --- KASSA O'TKAZMA ---
@router.callback_query(F.data == "ops:transfer")
async def cb_transfer_start(callback: CallbackQuery, state: FSMContext):
    if not _require_ops(callback):
        await callback.answer("PIN kerak", show_alert=True)
        return
    await state.clear()
    await state.set_state(TransferStates.from_cash)
    await callback.message.edit_text(
        "↔️ <b>Kassa o'tkazma</b>\n\nQaysi kassadan chiqariladi?",
        reply_markup=_cash_registers_kb("ops:tr_from"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ops:tr_from:"), TransferStates.from_cash)
async def cb_transfer_from(callback: CallbackQuery, state: FSMContext):
    from_id = int(callback.data.split(":")[-1])
    await state.update_data(from_cash_id=from_id)
    await state.set_state(TransferStates.to_cash)
    await callback.message.edit_text("↔️ Qaysi kassaga keladi?", reply_markup=_cash_registers_kb("ops:tr_to"))
    await callback.answer()


@router.callback_query(F.data.startswith("ops:tr_to:"), TransferStates.to_cash)
async def cb_transfer_to(callback: CallbackQuery, state: FSMContext):
    to_id = int(callback.data.split(":")[-1])
    data = await state.get_data()
    if data.get("from_cash_id") == to_id:
        await callback.answer("Bir xil kassa bo'lmasin!", show_alert=True)
        return
    await state.update_data(to_cash_id=to_id)
    await state.set_state(TransferStates.amount)
    await callback.message.edit_text("↔️ Summa (so'm)? Raqam yozing:")
    await callback.answer()


@router.message(TransferStates.amount)
async def on_transfer_amount(message: Message, state: FSMContext):
    try:
        amt = float((message.text or "").replace(" ", "").replace(",", "."))
        if amt <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.answer("⚠ Noto'g'ri summa. Raqam yuboring:")
        return
    await state.update_data(amount=amt)
    await state.set_state(TransferStates.note)
    await message.answer("📝 Izoh yozing (yoki /skip):")


@router.message(TransferStates.note, Command("skip"))
async def on_transfer_skip_note(message: Message, state: FSMContext):
    await state.update_data(note="")
    await _transfer_confirm(message, state)


@router.message(TransferStates.note)
async def on_transfer_note(message: Message, state: FSMContext):
    await state.update_data(note=(message.text or "")[:500])
    await _transfer_confirm(message, state)


async def _transfer_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    db = SessionLocal()
    try:
        from_cr = db.query(CashRegister).filter(CashRegister.id == data["from_cash_id"]).first()
        to_cr = db.query(CashRegister).filter(CashRegister.id == data["to_cash_id"]).first()
    finally:
        db.close()
    text = (
        "↔️ <b>Kassa o'tkazma — tasdiqlash</b>\n\n"
        f"<b>{from_cr.name if from_cr else '—'}</b> → <b>{to_cr.name if to_cr else '—'}</b>\n"
        f"Summa: <b>{_fmt(data['amount'])}</b> so'm\n"
        f"Izoh: {data.get('note') or '—'}"
    )
    await state.set_state(TransferStates.confirm)
    await message.answer(text, reply_markup=_yes_no_kb("ops:tr_save"))


@router.callback_query(F.data == "ops:tr_save", TransferStates.confirm)
async def cb_transfer_save(callback: CallbackQuery, state: FSMContext):
    if not _require_ops(callback):
        return
    data = await state.get_data()
    result = await asyncio.to_thread(_save_transfer, data)
    await state.clear()
    await callback.message.edit_text(result)
    await callback.answer("Saqlandi")


def _save_transfer(data: dict) -> str:
    db = SessionLocal()
    try:
        today = datetime.now()
        last = db.query(CashTransfer).order_by(CashTransfer.id.desc()).first()
        tr_num = f"CT-{today.strftime('%Y%m%d')}-{((last.id + 1) if last else 1):03d}"
        tr = CashTransfer(
            number=tr_num,
            date=today,
            from_cash_id=data["from_cash_id"],
            to_cash_id=data["to_cash_id"],
            amount=float(data["amount"]),
            note=data.get("note") or "",
            status="completed",  # bot orqali — darhol tasdiq
            approved_at=today,
        )
        db.add(tr)
        db.commit()
        try:
            from app.bot.services.audit_watchdog import audit_cash_transfer
            audit_cash_transfer(tr.id)
        except Exception:
            pass
        try:
            from app.services.finance_service import sync_cash_balance
            sync_cash_balance(db, data["from_cash_id"])
            sync_cash_balance(db, data["to_cash_id"])
            db.commit()
        except Exception:
            db.rollback()
        return f"✅ O'tkazma saqlandi: <b>{tr_num}</b>\nSumma: {_fmt(data['amount'])} so'm"
    except Exception as e:
        db.rollback()
        return f"❌ Xato: {e}"
    finally:
        db.close()


# --- TOVAR KIRIM — web formaga havola (oddiy pozitsiyadan ko'proq bo'lgani uchun) ---
@router.callback_query(F.data == "ops:purchase")
async def cb_purchase_link(callback: CallbackQuery):
    if not _require_ops(callback):
        await callback.answer("PIN kerak", show_alert=True)
        return
    await callback.message.edit_text(
        "📥 <b>Tovar kirim</b>\n\n"
        "Ko'p pozitsiya bo'ladi, bot ichida kiritish noqulay.\n"
        "Iltimos, web ilova orqali yarating:\n\n"
        "<a href=\"http://10.243.165.156:8080/purchases/add\">➕ Yangi xarid (web)</a>\n\n"
        "Yaratilgandan keyin audit botga avtomatik xabar yuboradi.",
        disable_web_page_preview=True,
    )
    await callback.answer()
