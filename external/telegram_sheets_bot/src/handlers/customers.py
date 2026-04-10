"""Mijozlar oqimi: ro'yxat, tanlash, yangi mijoz, summa kiritish."""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.access import AllowedUserFilter, RoleFilter, deny_role_callback, deny_role_message, get_user_role
from src.keyboards import (
    after_save_kb,
    currency_kb,
    customer_actions_kb,
    customer_delete_confirm_kb,
    customer_list_kb,
    main_menu_kb,
)
from src.services.excel_ledger import (
    add_customer,
    append_operation_row,
    customer_operation_count,
    delete_customer,
    get_customer,
    list_customers,
)
from src.states import CustomerEntryState, NewCustomerState

router = Router()
router.message.filter(AllowedUserFilter())
router.callback_query.filter(AllowedUserFilter())
logger = logging.getLogger(__name__)


def _fmt_money(value: float) -> str:
    return f"{float(value):,.0f}".replace(",", " ")


def _parse_number(text: str) -> float | None:
    raw = (text or "").strip().replace(" ", "").replace(",", "").replace(".", "")
    if not raw:
        return None
    sign = 1
    if raw.startswith("-"):
        sign = -1
        raw = raw[1:]
    if not raw.isdigit():
        return None
    return sign * float(raw)


async def _show_customers_menu(target: Message | CallbackQuery) -> None:
    customers = await asyncio.to_thread(list_customers)
    if isinstance(target, Message):
        if not customers:
            await target.answer("Mijozlar hali yo'q. `Yangi mijoz` orqali qo'shing.", parse_mode="HTML")
            return
        await target.answer("Mijozni tanlang:", reply_markup=customer_list_kb(customers, page=1))
        return

    if not customers:
        await target.answer("Mijozlar hali yo'q.", show_alert=True)
        if target.message:
            role = get_user_role(target.from_user.id if target.from_user else None)
            await target.message.edit_text("Asosiy menyu:", reply_markup=main_menu_kb(role))
        return
    if target.message:
        await target.message.edit_text("Mijozni tanlang:", reply_markup=customer_list_kb(customers, page=1))
    await target.answer()


@router.message(Command("customers"))
@router.message(F.text == "Mijozlar")
async def customers_menu(message: Message) -> None:
    await _show_customers_menu(message)


@router.callback_query(F.data == "menu:customers")
async def cb_customers_menu(callback: CallbackQuery) -> None:
    await _show_customers_menu(callback)


@router.message(F.text == "Orqaga")
async def text_back_to_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    role = get_user_role(message.from_user.id if message.from_user else None)
    await message.answer("Asosiy menyu:", reply_markup=main_menu_kb(role))


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = "Asosiy menyu:"
    if callback.message:
        role = get_user_role(callback.from_user.id if callback.from_user else None)
        await callback.message.edit_text(text, reply_markup=main_menu_kb(role))
    await callback.answer()


@router.callback_query(F.data.startswith("customer:list:"))
@router.callback_query(F.data.startswith("customer:page:"))
async def cb_customer_list(callback: CallbackQuery) -> None:
    customers = await asyncio.to_thread(list_customers)
    if not customers:
        await callback.answer("Mijozlar topilmadi", show_alert=True)
        return
    page = int(callback.data.split(":")[-1])
    if callback.message:
        await callback.message.edit_text("Mijozni tanlang:", reply_markup=customer_list_kb(customers, page=page))
    await callback.answer()


@router.callback_query(F.data.startswith("customer:pick:"))
async def cb_customer_pick(callback: CallbackQuery, state: FSMContext) -> None:
    customer_id = int(callback.data.split(":")[-1])
    customer = await asyncio.to_thread(get_customer, customer_id)
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    await state.update_data(selected_customer_id=customer_id, selected_customer_name=customer["name"])
    text = (
        f"<b>{customer['name']}</b>\n"
        f"Telefon: {customer.get('phone') or '-'}\n"
        f"Qarz qoldiq (UZS): {_fmt_money(customer.get('qoldiq_uzs') or 0)}\n"
        f"Qarz qoldiq (USD): {_fmt_money(customer.get('qoldiq_usd') or 0)}"
    )
    if callback.message:
        await callback.message.edit_text(
            text,
            reply_markup=customer_actions_kb(customer_id, can_report=True),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("customer:op:"))
async def cb_customer_operation(callback: CallbackQuery, state: FSMContext) -> None:
    _prefix, _op, customer_id, operation_type = callback.data.split(":")
    customer = await asyncio.to_thread(get_customer, int(customer_id))
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    await state.set_state(CustomerEntryState.waiting_currency)
    await state.update_data(
        selected_customer_id=int(customer_id),
        selected_customer_name=customer["name"],
        selected_operation=operation_type,
    )
    if callback.message:
        action_label = "mijoz to'lovi" if operation_type == "kirim" else "biz bergan summa"
        await callback.message.edit_text(
            f"<b>{customer['name']}</b> uchun <b>{action_label}</b> valyutasini tanlang:",
            reply_markup=currency_kb(int(customer_id), operation_type),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("customer:currency:"))
async def cb_customer_currency(callback: CallbackQuery, state: FSMContext) -> None:
    _prefix, _kind, customer_id, operation_type, currency = callback.data.split(":")
    customer = await asyncio.to_thread(get_customer, int(customer_id))
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    await state.set_state(CustomerEntryState.waiting_amount)
    await state.update_data(
        selected_customer_id=int(customer_id),
        selected_customer_name=customer["name"],
        selected_operation=operation_type,
        selected_currency=currency,
    )
    if callback.message:
        await callback.message.edit_text(
            f"<b>{customer['name']}</b> uchun <b>{currency}</b> summasini yozing.\n\n"
            "Masalan: <code>500000</code> yoki <code>100</code>",
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("customer:delete:"))
async def cb_customer_delete_prompt(callback: CallbackQuery) -> None:
    customer_id = int(callback.data.split(":")[-1])
    customer = await asyncio.to_thread(get_customer, customer_id)
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    op_count = await asyncio.to_thread(customer_operation_count, customer_id)
    if callback.message:
        await callback.message.edit_text(
            f"<b>{customer['name']}</b> o'chirilsinmi?\n\n"
            f"Bog'liq operatsiyalar soni: <b>{op_count}</b>\n\n"
            "Bu mijozga bog'liq operatsiyalar ham o'chadi.",
            parse_mode="HTML",
            reply_markup=customer_delete_confirm_kb(customer_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("customer:deleteconfirm:"))
async def cb_customer_delete_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    customer_id = int(callback.data.split(":")[-1])
    customer = await asyncio.to_thread(get_customer, customer_id)
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    deleted = await asyncio.to_thread(delete_customer, customer_id)
    await state.clear()
    if not deleted:
        await callback.answer("O'chirib bo'lmadi", show_alert=True)
        return
    if callback.message:
        role = get_user_role(callback.from_user.id if callback.from_user else None)
        await callback.message.edit_text(
            f"<b>{customer['name']}</b> o'chirildi.",
            parse_mode="HTML",
            reply_markup=main_menu_kb(role),
        )
    await callback.answer("Mijoz o'chirildi")


@router.message(CustomerEntryState.waiting_amount)
async def on_amount_entered(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    customer_id = data.get("selected_customer_id")
    customer_name = data.get("selected_customer_name")
    operation_type = data.get("selected_operation")
    currency = data.get("selected_currency")
    if not customer_id or not customer_name or operation_type not in {"kirim", "chiqim"} or currency not in {"UZS", "USD"}:
        await state.clear()
        await message.answer("Avval mijoz va amalni tanlang.", reply_markup=main_menu_kb())
        return

    amount = _parse_number(message.text or "")
    if amount is None or amount <= 0:
        await message.answer("Faqat summa yuboring. Masalan: <code>500000</code>", parse_mode="HTML")
        return

    await state.set_state(CustomerEntryState.waiting_rate)
    await state.update_data(selected_amount=amount)
    await message.answer(
        f"Kursni yozing.\n\n"
        f"Valyuta: <b>{currency}</b>\n"
        f"Summa: <b>{_fmt_money(amount)}</b>\n\n"
        "Masalan: <code>12700</code>",
        parse_mode="HTML",
    )


@router.message(CustomerEntryState.waiting_rate)
async def on_rate_entered(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    customer_id = data.get("selected_customer_id")
    customer_name = data.get("selected_customer_name")
    operation_type = data.get("selected_operation")
    currency = data.get("selected_currency")
    amount = data.get("selected_amount")
    if (
        not customer_id
        or not customer_name
        or operation_type not in {"kirim", "chiqim"}
        or currency not in {"UZS", "USD"}
        or amount is None
    ):
        await state.clear()
        await message.answer("Avval mijoz va amalni tanlang.", reply_markup=main_menu_kb())
        return

    rate = _parse_number(message.text or "")
    if rate is None or rate <= 0:
        await message.answer("Kursni son bilan yuboring. Masalan: <code>12700</code>", parse_mode="HTML")
        return

    text = f"{operation_type} {currency} {amount:,.0f} {customer_name}".replace(",", " ")
    try:
        await asyncio.to_thread(
            append_operation_row,
            text,
            message.from_user.id if message.from_user else 0,
            message.from_user.username if message.from_user else None,
            "matn",
            customer_id,
            customer_name,
            operation_type,
            amount,
            f"Telegram orqali {operation_type}",
            currency,
            rate,
        )
    except Exception as e:
        logger.exception("append_operation_row")
        await message.answer(f"❌ Excelga yozishda xato: {str(e)[:300]}")
        return

    await state.clear()
    await message.answer(
        f"✅ <b>{customer_name}</b> uchun amaliyot saqlandi.\n"
        f"Valyuta: <b>{currency}</b>\n"
        f"Summa: <b>{_fmt_money(amount)}</b>\n"
        f"Kurs: <b>{_fmt_money(rate)}</b>",
        parse_mode="HTML",
        reply_markup=after_save_kb(customer_id, can_report=True),
    )


@router.message(Command("add_customer"), RoleFilter("admin", "rahbar", "xodim"))
@router.message(RoleFilter("admin", "rahbar", "xodim"), F.text == "Yangi mijoz")
async def add_customer_start(message: Message, state: FSMContext) -> None:
    await state.set_state(NewCustomerState.waiting_name)
    await message.answer("Yangi mijoz nomini yozing:")


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data == "menu:add_customer")
async def cb_add_customer_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(NewCustomerState.waiting_name)
    if callback.message:
        await callback.message.edit_text("Yangi mijoz nomini yozing:")
    await callback.answer()


@router.message(F.text == "Yangi mijoz")
async def add_customer_denied(message: Message) -> None:
    await deny_role_message(message)


@router.callback_query(F.data == "menu:add_customer")
async def add_customer_denied_callback(callback: CallbackQuery) -> None:
    await deny_role_callback(callback)


@router.message(NewCustomerState.waiting_name)
async def add_customer_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await message.answer("Mijoz nomini yozing.")
        return
    await state.update_data(new_customer_name=name)
    await state.set_state(NewCustomerState.waiting_phone)
    await message.answer("Telefon raqamini yozing yoki `-` yuboring.", parse_mode="HTML")


@router.message(NewCustomerState.waiting_phone)
async def add_customer_phone(message: Message, state: FSMContext) -> None:
    phone = (message.text or "").strip()
    if phone == "-":
        phone = ""
    await state.update_data(new_customer_phone=phone)
    await state.set_state(NewCustomerState.waiting_opening_balance_uzs)
    await message.answer("Boshlang'ich so'm qarzni yozing yoki `0` yuboring.", parse_mode="HTML")


@router.message(NewCustomerState.waiting_opening_balance_uzs)
async def add_customer_balance_uzs(message: Message, state: FSMContext) -> None:
    opening_uzs = _parse_number(message.text or "")
    if opening_uzs is None:
        await message.answer("Boshlang'ich so'm qarz uchun son yuboring. Masalan: <code>0</code>", parse_mode="HTML")
        return
    await state.update_data(new_customer_opening_uzs=opening_uzs)
    await state.set_state(NewCustomerState.waiting_opening_balance_usd)
    await message.answer("Boshlang'ich dollar qarzni yozing yoki `0` yuboring.", parse_mode="HTML")


@router.message(NewCustomerState.waiting_opening_balance_usd)
async def add_customer_balance_usd(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data.get("new_customer_name", "").strip()
    phone = data.get("new_customer_phone", "").strip()
    opening_uzs = float(data.get("new_customer_opening_uzs", 0) or 0)
    opening_usd = _parse_number(message.text or "")
    if opening_usd is None:
        await message.answer("Boshlang'ich dollar qarz uchun son yuboring. Masalan: <code>0</code>", parse_mode="HTML")
        return

    customer = await asyncio.to_thread(add_customer, name, phone, opening_uzs, opening_usd)
    await state.clear()
    await message.answer(
        f"✅ Yangi mijoz qo'shildi:\n<b>{customer['name']}</b>",
        parse_mode="HTML",
        reply_markup=customer_actions_kb(int(customer["id"]), can_report=True),
    )


@router.callback_query(F.data.startswith("customer:"))
async def customer_callback_fallback(_callback: CallbackQuery) -> None:
    # Aniq callback handlerlar yuqorida ishlaydi; bu yer faqat mos kelmagan customer callbacklar uchun.
    return
