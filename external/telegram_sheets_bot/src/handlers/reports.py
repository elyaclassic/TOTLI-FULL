"""Hisobotlar: tur, davr va chiqish bo'yicha."""
import asyncio
from pathlib import Path

from aiogram import F, Router
from aiogram.types import FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.access import AllowedUserFilter, RoleFilter, deny_role_callback, deny_role_message
from src.keyboards import report_output_kb, report_period_kb, report_type_kb, reports_kb
from src.services.excel_ledger import (
    customer_report_by_period,
    export_report_excel,
    get_customer,
    summary_report_by_period,
)
from src.states import ReportState

router = Router()
router.message.filter(AllowedUserFilter())
router.callback_query.filter(AllowedUserFilter())


def _fmt_money(value: float) -> str:
    number = float(value)
    if number.is_integer():
        return f"{number:,.0f}".replace(",", " ")
    return f"{number:,.2f}".rstrip("0").rstrip(".").replace(",", " ")


@router.message(RoleFilter("admin", "rahbar", "xodim"), F.text == "Hisobot")
async def reports_menu(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ReportState.choosing_type)
    await message.answer("Hisobot turini tanlang:", reply_markup=report_type_kb(data.get("selected_customer_id")))


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data == "menu:reports")
async def cb_reports_menu(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ReportState.choosing_type)
    if callback.message:
        await callback.message.edit_text(
            "Hisobot turini tanlang:",
            reply_markup=report_type_kb(data.get("selected_customer_id")),
        )
    await callback.answer()


@router.message(F.text == "Hisobot")
async def reports_menu_denied(message: Message) -> None:
    await deny_role_message(message)


@router.callback_query(F.data == "menu:reports")
async def reports_menu_denied_callback(callback: CallbackQuery) -> None:
    await deny_role_callback(callback)


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data == "report:menu")
async def cb_report_menu(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.set_state(ReportState.choosing_type)
    if callback.message:
        await callback.message.edit_text(
            "Hisobot turini tanlang:",
            reply_markup=report_type_kb(data.get("selected_customer_id")),
        )
    await callback.answer()


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data.startswith("reporttype:"))
async def cb_report_type(callback: CallbackQuery, state: FSMContext) -> None:
    report_type = callback.data.split(":")[-1]
    if report_type == "customer":
        data = await state.get_data()
        if not data.get("selected_customer_id"):
            await callback.answer("Avval mijoz tanlang", show_alert=True)
            return
    await state.update_data(report_type=report_type)
    await state.set_state(ReportState.choosing_period)
    if callback.message:
        await callback.message.edit_text("Davrni tanlang:", reply_markup=report_period_kb())
    await callback.answer()


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data == "report:period")
async def cb_report_period_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ReportState.choosing_period)
    if callback.message:
        await callback.message.edit_text("Davrni tanlang:", reply_markup=report_period_kb())
    await callback.answer()


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data.startswith("reportperiod:"))
async def cb_report_period(callback: CallbackQuery, state: FSMContext) -> None:
    period = callback.data.split(":")[-1]
    await state.update_data(report_period=period)
    await state.set_state(ReportState.choosing_output)
    if callback.message:
        await callback.message.edit_text(
            "Hisobotni qayerda ko'rasiz?",
            reply_markup=report_output_kb(),
        )
    await callback.answer()


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data.startswith("report:customer:"))
async def cb_report_customer_open(callback: CallbackQuery, state: FSMContext) -> None:
    customer_id = int(callback.data.split(":")[-1])
    customer = await asyncio.to_thread(get_customer, customer_id)
    if not customer:
        await callback.answer("Mijoz topilmadi", show_alert=True)
        return
    await state.update_data(
        selected_customer_id=customer_id,
        selected_customer_name=customer["name"],
        report_type="customer",
    )
    await state.set_state(ReportState.choosing_period)
    if callback.message:
        await callback.message.edit_text(
            f"<b>{customer['name']}</b> uchun hisobot davrini tanlang:",
            parse_mode="HTML",
            reply_markup=report_period_kb(),
        )
    await callback.answer()


@router.callback_query(RoleFilter("admin", "rahbar", "xodim"), F.data.startswith("reportoutput:"))
async def cb_report_output(callback: CallbackQuery, state: FSMContext) -> None:
    output = callback.data.split(":")[-1]
    data = await state.get_data()
    report_type = data.get("report_type")
    period = data.get("report_period", "all")
    customer_id = data.get("selected_customer_id")
    if report_type not in {"summary", "customer"}:
        await callback.answer("Avval hisobot turini tanlang", show_alert=True)
        return

    if output == "bot":
        if report_type == "summary":
            report = await asyncio.to_thread(summary_report_by_period, period)
            lines = [
                "<b>Umumiy hisobot</b>\n\n"
                f"Davr: <b>{period}</b>\n"
                f"Mijozlar to'lagan (UZS): <b>{_fmt_money(report['jami_kirim_uzs'])}</b>\n"
                f"Mijozlar to'lagan (USD): <b>{_fmt_money(report['jami_kirim_usd'])}</b>\n"
                f"Biz bergan (UZS): <b>{_fmt_money(report['jami_chiqim_uzs'])}</b>\n"
                f"Biz bergan (USD): <b>{_fmt_money(report['jami_chiqim_usd'])}</b>\n"
                f"Jami qarz qoldiq (UZS): <b>{_fmt_money(report['farq_uzs'])}</b>\n"
                f"Jami qarz qoldiq (USD): <b>{_fmt_money(report['farq_usd'])}</b>\n"
                f"Operatsiyalar soni: <b>{report['operatsiyalar_soni']}</b>",
                "",
                "<b>Mijozlar:</b>",
            ]
            if not report["customers"]:
                lines.append("Ma'lumot yo'q.")
            else:
                for item in report["customers"]:
                    lines.append(
                        f"{item['customer_name']} | "
                        f"to'lagan: UZS {_fmt_money(item['kirim_uzs'])}, USD {_fmt_money(item['kirim_usd'])} | "
                        f"berilgan: UZS {_fmt_money(item['chiqim_uzs'])}, USD {_fmt_money(item['chiqim_usd'])} | "
                        f"qoldiq: UZS {_fmt_money(item['qoldiq_uzs'])}, USD {_fmt_money(item['qoldiq_usd'])}"
                    )
            text = "\n".join(lines)
            if len(text) > 3500:
                text = text[:3400].rstrip() + "\n\n... ro'yxat qisqartirildi."
        else:
            report = await asyncio.to_thread(customer_report_by_period, int(customer_id or 0), period)
            if not report:
                await callback.answer("Mijoz topilmadi", show_alert=True)
                return
            customer = report["customer"]
            lines = [
                f"<b>{customer['name']}</b>",
                f"Davr: <b>{period}</b>",
                f"Boshlang'ich qarz (UZS): <b>{_fmt_money(customer.get('opening_uzs', 0))}</b>",
                f"Boshlang'ich qarz (USD): <b>{_fmt_money(customer.get('opening_usd', 0))}</b>",
                f"Mijoz to'lagan (UZS): <b>{_fmt_money(report['kirim_uzs'])}</b>",
                f"Mijoz to'lagan (USD): <b>{_fmt_money(report['kirim_usd'])}</b>",
                f"Biz bergan (UZS): <b>{_fmt_money(report['chiqim_uzs'])}</b>",
                f"Biz bergan (USD): <b>{_fmt_money(report['chiqim_usd'])}</b>",
                f"Qarz qoldiq (UZS): <b>{_fmt_money(report['farq_uzs'])}</b>",
                f"Qarz qoldiq (USD): <b>{_fmt_money(report['farq_usd'])}</b>",
                "",
                "<b>Operatsiyalar:</b>",
            ]
            if not report["history"]:
                lines.append("Ma'lumot yo'q.")
            else:
                for item in report["history"]:
                    lines.append(
                        f"{item['date']} {item['time']} | {item['type']} | "
                        f"{item['currency']} {_fmt_money(item['amount'])} | kurs {_fmt_money(item['rate'])}"
                    )
            text = "\n".join(lines)

        if callback.message:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=reports_kb(customer_id))
    else:
        path = await asyncio.to_thread(export_report_excel, report_type, period, customer_id)
        if callback.message:
            await callback.message.answer_document(FSInputFile(Path(path)), caption="Excel hisobot tayyor.")
            await callback.message.answer("Yana hisobot kerak bo'lsa tanlang:", reply_markup=reports_kb(customer_id))
    await callback.answer()


@router.callback_query(F.data.startswith("report:"))
async def reports_callback_denied(callback: CallbackQuery) -> None:
    await deny_role_callback(callback)
