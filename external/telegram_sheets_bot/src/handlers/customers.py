"""Mijozlar oqimi: ro'yxat, tanlash, yangi mijoz, summa kiritish."""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.access import AllowedUserFilter, RoleFilter, deny_role_message, get_user_role, has_role
from src.keyboards import after_save_kb, customer_actions_kb, customer_list_kb, main_menu_kb
from src.services.excel_ledger import add_customer, append_operation_row, get_customer, list_customers
from src.states import CustomerEntryState, NewCustomerState

router = Router()
router.message.filter(AllowedUserFilter())
router.callback_query.filter(AllowedUserFilter())
logger = logging.getLogger(__name__)


def _fmt_money(value: float) -> str:
    return f"{float(value):,.0f}".replace(",", " ")


@router.message(Command("customers"))
@router.message(F.text == "Mijozlar")
async def customers_menu(message: Message) -> None:
    customers = await asyncio.to_thread(list_customers)
    if not customers:
        await message.answer("Mijozlar hali yo'q. `Yangi mijoz` orqali qo'shing.", parse_mode="HTML")
        return
    await message.answer("Mijozni tanlang:", reply_markup=customer_list_kb(customers, page=1))


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
        await callback.message.answer(text, reply_markup=main_menu_kb(role))
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
        f"Qarz qoldiq: {_fmt_money(customer.get('qoldiq') or 0)}"
    )
    if callback.message:
        can_report = has_role(callback.from_user.id if callback.from_user else None, "admin", "rahbar")
        await callback.message.edit_text(
            text,
            reply_markup=customer_actions_kb(customer_id, can_report=can_report),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("customer:op:"))
async def cb_customer_operation(callback: CallbackQuery, state: FSMContext) -> None:
    _prefix, _kind, _op, customer_id, operation_type = callback.data.split(":")
    customer = await asyncio.to_thread(get_customer, int(customer_id))
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    await state.set_state(CustomerEntryState.waiting_amount)
    await state.update_data(
        selected_customer_id=int(customer_id),
        selected_customer_name=customer["name"],
        selected_operation=operation_type,
    )
    if callback.message:
        action_label = "mijoz to'lovi" if operation_type == "kirim" else "biz bergan summa"
        await callback.message.answer(
            f"<b>{customer['name']}</b> uchun <b>{action_label}</b> summasini yozing.\n\n"
            "Masalan: <code>500000</code>",
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(CustomerEntryState.waiting_amount)
async def on_amount_entered(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    customer_id = data.get("selected_customer_id")
    customer_name = data.get("selected_customer_name")
    operation_type = data.get("selected_operation")
    if not customer_id or not customer_name or operation_type not in {"kirim", "chiqim"}:
        await state.clear()
        await message.answer("Avval mijoz va amalni tanlang.", reply_markup=main_menu_kb())
        return

    raw = (message.text or "").strip().replace(" ", "").replace(",", "").replace(".", "")
    if not raw.isdigit():
        await message.answer("Faqat summa yuboring. Masalan: <code>500000</code>", parse_mode="HTML")
        return

    amount = float(raw)
    text = f"{operation_type} {amount:,.0f} {customer_name}".replace(",", " ")
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
        )
    except Exception as e:
        logger.exception("append_operation_row")
        await message.answer(f"❌ Excelga yozishda xato: {str(e)[:300]}")
        return

    await state.clear()
    await message.answer(
        f"✅ <b>{customer_name}</b> uchun amaliyot saqlandi.\n"
        f"Summa: <b>{_fmt_money(amount)}</b>",
        parse_mode="HTML",
        reply_markup=after_save_kb(
            customer_id,
            can_report=has_role(message.from_user.id if message.from_user else None, "admin", "rahbar"),
        ),
    )


@router.message(Command("add_customer"), RoleFilter("admin"))
@router.message(RoleFilter("admin"), F.text == "Yangi mijoz")
async def add_customer_start(message: Message, state: FSMContext) -> None:
    await state.set_state(NewCustomerState.waiting_name)
    await message.answer("Yangi mijoz nomini yozing:")


@router.message(F.text == "Yangi mijoz")
async def add_customer_denied(message: Message) -> None:
    await deny_role_message(message)


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
    await state.set_state(NewCustomerState.waiting_opening_balance)
    await message.answer("Boshlang'ich qoldiqni yozing yoki `0` yuboring.", parse_mode="HTML")


@router.message(NewCustomerState.waiting_opening_balance)
async def add_customer_balance(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data.get("new_customer_name", "").strip()
    phone = data.get("new_customer_phone", "").strip()
    raw = (message.text or "").strip().replace(" ", "").replace(",", "").replace(".", "")
    if raw.startswith("-"):
        sign = -1
        raw = raw[1:]
    else:
        sign = 1
    if not raw.isdigit():
        await message.answer("Boshlang'ich qoldiq uchun son yuboring. Masalan: <code>0</code>", parse_mode="HTML")
        return

    opening = sign * float(raw)
    customer = await asyncio.to_thread(add_customer, name, phone, opening)
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
