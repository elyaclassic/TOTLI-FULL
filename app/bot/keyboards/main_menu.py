"""Asosiy menyu va davr tanlash klaviaturalari"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Davomat", callback_data="report:attendance"),
            InlineKeyboardButton(text="💰 Savdo", callback_data="report:sales"),
        ],
        [
            InlineKeyboardButton(text="💵 Pul oqimi", callback_data="report:cashflow"),
            InlineKeyboardButton(text="📉 Harajatlar", callback_data="report:expenses"),
        ],
        [
            InlineKeyboardButton(text="📌 Qarzdorlar", callback_data="report:debtors"),
            InlineKeyboardButton(text="💳 Ish haqi", callback_data="report:salaries"),
        ],
        [
            InlineKeyboardButton(text="📊 KPI", callback_data="report:kpi"),
            InlineKeyboardButton(text="🏆 Top mahsulotlar", callback_data="report:top_products"),
        ],
        [
            InlineKeyboardButton(text="🚗 Agentlar", callback_data="report:agents"),
            InlineKeyboardButton(text="🔄 Obmen/Vozvrat", callback_data="report:returns"),
        ],
    ])


def period_kb(report_type: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Bugun", callback_data=f"period:{report_type}:today"),
            InlineKeyboardButton(text="📅 Kecha", callback_data=f"period:{report_type}:yesterday"),
        ],
        [
            InlineKeyboardButton(text="📅 Shu hafta", callback_data=f"period:{report_type}:this_week"),
            InlineKeyboardButton(text="📅 Shu oy", callback_data=f"period:{report_type}:this_month"),
        ],
        [
            InlineKeyboardButton(text="📅 O'tgan oy", callback_data=f"period:{report_type}:last_month"),
            InlineKeyboardButton(text="📅 Davr tanlash", callback_data=f"custom:{report_type}"),
        ],
        [
            InlineKeyboardButton(text="🔙 Menyu", callback_data="menu"),
        ],
    ])


def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Menyu", callback_data="menu")],
    ])
