"""Telegram tugmalari."""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu_kb(role: str | None = None) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Mijozlar", callback_data="menu:customers")]
    ]
    if role in {"admin", "rahbar", "xodim"}:
        keyboard[0].append(InlineKeyboardButton(text="Hisobot", callback_data="menu:reports"))
    if role in {"admin", "rahbar", "xodim"}:
        keyboard.append([InlineKeyboardButton(text="Yangi mijoz", callback_data="menu:add_customer")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def customer_list_kb(customers: list[dict], page: int = 1, page_size: int = 10) -> InlineKeyboardMarkup:
    total = max(1, (len(customers) + page_size - 1) // page_size)
    page = max(1, min(page, total))
    start = (page - 1) * page_size
    items = customers[start : start + page_size]

    rows: list[list[InlineKeyboardButton]] = []
    for customer in items:
        label = f"{customer['id']}. {customer['name']}"
        rows.append(
            [InlineKeyboardButton(text=label[:60], callback_data=f"customer:pick:{customer['id']}")]
        )

    nav: list[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(text="Oldingi", callback_data=f"customer:page:{page - 1}"))
    if page < total:
        nav.append(InlineKeyboardButton(text="Keyingi", callback_data=f"customer:page:{page + 1}"))
    if nav:
        rows.append(nav)

    rows.append(
        [
            InlineKeyboardButton(text="Orqaga", callback_data="menu:main"),
            InlineKeyboardButton(text="Menyu", callback_data="menu:main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def customer_actions_kb(customer_id: int, can_report: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Mijoz to'ladi", callback_data=f"customer:op:{customer_id}:kirim"),
            InlineKeyboardButton(text="Biz berdik", callback_data=f"customer:op:{customer_id}:chiqim"),
        ],
    ]
    if can_report:
        rows.append([InlineKeyboardButton(text="Hisobot", callback_data=f"report:customer:{customer_id}")])
    rows.append([InlineKeyboardButton(text="Orqaga", callback_data="customer:list:1")])
    rows.append([InlineKeyboardButton(text="Menyu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_save_kb(customer_id: int, can_report: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Yana to'lov oldim", callback_data=f"customer:op:{customer_id}:kirim"),
            InlineKeyboardButton(text="Yana pul berdim", callback_data=f"customer:op:{customer_id}:chiqim"),
        ],
    ]
    if can_report:
        rows.append([InlineKeyboardButton(text="Hisobot", callback_data=f"report:customer:{customer_id}")])
    rows.append(
        [
            InlineKeyboardButton(text="Orqaga", callback_data=f"customer:pick:{customer_id}"),
            InlineKeyboardButton(text="Menyu", callback_data="menu:main"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reports_kb(selected_customer_id: int | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if selected_customer_id:
        rows.append(
            [InlineKeyboardButton(text="Tanlangan mijoz", callback_data=f"report:customer:{selected_customer_id}")]
        )
    rows.append([InlineKeyboardButton(text="Umumiy hisobot", callback_data="report:summary")])
    rows.append([InlineKeyboardButton(text="Orqaga", callback_data="menu:main")])
    rows.append([InlineKeyboardButton(text="Menyu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_type_kb(selected_customer_id: int | None = None) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="Umumiy hisobot", callback_data="reporttype:summary")],
        [InlineKeyboardButton(text="Mijoz bo'yicha hisobot", callback_data="reporttype:customer")],
    ]
    if selected_customer_id:
        rows.append(
            [InlineKeyboardButton(text="Tanlangan mijozni ochish", callback_data=f"report:customer:{selected_customer_id}")]
        )
    rows.append([InlineKeyboardButton(text="Orqaga", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def report_period_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Bugun", callback_data="reportperiod:today")],
            [InlineKeyboardButton(text="Shu oy", callback_data="reportperiod:this_month")],
            [InlineKeyboardButton(text="Hammasi", callback_data="reportperiod:all")],
            [InlineKeyboardButton(text="Orqaga", callback_data="report:menu")],
        ]
    )


def report_output_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Botda ko'raman", callback_data="reportoutput:bot")],
            [InlineKeyboardButton(text="Excelda olaman", callback_data="reportoutput:excel")],
            [InlineKeyboardButton(text="Orqaga", callback_data="report:period")],
        ]
    )
