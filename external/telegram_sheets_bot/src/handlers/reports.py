"""Hisobotlar: umumiy va tanlangan mijoz bo'yicha."""
import asyncio

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.keyboards import reports_kb
from src.services.excel_ledger import customer_history, get_customer, summary_report

router = Router()


def _fmt_money(value: float) -> str:
    return f"{float(value):,.0f}".replace(",", " ")


@router.message(F.text == "Hisobot")
async def reports_menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await message.answer("Hisobot turini tanlang:", reply_markup=reports_kb(data.get("selected_customer_id")))


@router.callback_query(F.data == "report:summary")
async def cb_report_summary(callback: CallbackQuery) -> None:
    report = await asyncio.to_thread(summary_report)
    text = (
        "<b>Umumiy hisobot</b>\n\n"
        f"Jami kirim: <b>{_fmt_money(report['jami_kirim'])}</b>\n"
        f"Jami chiqim: <b>{_fmt_money(report['jami_chiqim'])}</b>\n"
        f"Farq: <b>{_fmt_money(report['farq'])}</b>\n"
        f"Operatsiyalar soni: <b>{report['operatsiyalar_soni']}</b>"
    )
    if callback.message:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=reports_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("report:customer:"))
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
        f"Jami kirim: <b>{_fmt_money(customer.get('kirim') or 0)}</b>",
        f"Jami chiqim: <b>{_fmt_money(customer.get('chiqim') or 0)}</b>",
        f"Qoldiq: <b>{_fmt_money(customer.get('qoldiq') or 0)}</b>",
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
