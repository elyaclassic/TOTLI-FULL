"""Hisobotlar: umumiy va tanlangan mijoz bo'yicha."""
import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.access import AllowedUserFilter, RoleFilter, deny_role_callback, deny_role_message
from src.keyboards import main_menu_kb, reports_kb
from src.services.excel_ledger import customer_history, get_customer, summary_report

router = Router()
router.message.filter(AllowedUserFilter())
router.callback_query.filter(AllowedUserFilter())


def _fmt_money(value: float) -> str:
    return f"{float(value):,.0f}".replace(",", " ")


@router.message(RoleFilter("admin", "rahbar"), F.text == "Hisobot")
async def reports_menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer("Hisobot turini tanlang:", reply_markup=reports_kb(data.get("selected_customer_id")))


@router.message(F.text == "Hisobot")
async def reports_menu_denied(message: Message) -> None:
    await deny_role_message(message)


@router.callback_query(RoleFilter("admin", "rahbar"), F.data == "report:summary")
async def cb_report_summary(callback: CallbackQuery) -> None:
    report = await asyncio.to_thread(summary_report)
    text = (
        "<b>Umumiy hisobot</b>\n\n"
        f"Mijozlar to'lagan: <b>{_fmt_money(report['jami_kirim'])}</b>\n"
        f"Biz bergan: <b>{_fmt_money(report['jami_chiqim'])}</b>\n"
        f"Jami qarz qoldiq: <b>{_fmt_money(report['farq'])}</b>\n"
        f"Operatsiyalar soni: <b>{report['operatsiyalar_soni']}</b>"
    )
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=reports_kb())
    await callback.answer()


@router.callback_query(RoleFilter("admin", "rahbar"), F.data.startswith("report:customer:"))
async def cb_report_customer(callback: CallbackQuery, state: FSMContext) -> None:
    customer_id = int(callback.data.split(":")[-1])
    customer = await asyncio.to_thread(get_customer, customer_id)
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    await state.update_data(selected_customer_id=customer_id, selected_customer_name=customer["name"])
    history = await asyncio.to_thread(customer_history, customer_id, 10)

    lines = [
        f"<b>{customer['name']}</b>",
        f"Mijoz to'lagan: <b>{_fmt_money(customer.get('kirim') or 0)}</b>",
        f"Biz bergan: <b>{_fmt_money(customer.get('chiqim') or 0)}</b>",
        f"Qarz qoldiq: <b>{_fmt_money(customer.get('qoldiq') or 0)}</b>",
        "",
        "<b>Oxirgi operatsiyalar:</b>",
    ]
    if not history:
        lines.append("Ma'lumot yo'q.")
    else:
        for item in history[-10:]:
            lines.append(
                f"{item['date']} {item['time']} | {item['type']} | {_fmt_money(item['amount'])}"
            )

    if callback.message:
        await callback.message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=reports_kb(customer_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("report:"))
async def reports_callback_denied(callback: CallbackQuery) -> None:
    await deny_role_callback(callback)
