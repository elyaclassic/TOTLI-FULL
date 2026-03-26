"""Asosiy menyu va davr tanlash klaviaturalari"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton


def main_menu_reply_kb() -> ReplyKeyboardMarkup:
    """Pastdagi doimiy menyu (ReplyKeyboard)"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="💰 Savdo"),
                KeyboardButton(text="💵 Pul oqimi"),
            ],
            [
                KeyboardButton(text="📌 Qarzdorlar"),
                KeyboardButton(text="📉 Harajatlar"),
            ],
            [
                KeyboardButton(text="🏆 Top mahsulotlar"),
                KeyboardButton(text="🚗 Agentlar"),
            ],
            [
                KeyboardButton(text="💳 Ish haqi"),
                KeyboardButton(text="📊 KPI"),
            ],
            [
                KeyboardButton(text="🏭 Ishlab chiqarish"),
                KeyboardButton(text="📋 Davomat"),
            ],
            [
                KeyboardButton(text="🔄 Obmen/Vozvrat"),
            ],
        ],
        resize_keyboard=True,
    )


# Matn -> report_type mapping
MENU_TEXT_MAP = {
    "💰 Savdo": "sales",
    "💵 Pul oqimi": "cashflow",
    "📌 Qarzdorlar": "debtors",
    "📉 Harajatlar": "expenses",
    "🏆 Top mahsulotlar": "top_products",
    "🚗 Agentlar": "agents",
    "💳 Ish haqi": "salaries",
    "📊 KPI": "kpi",
    "🏭 Ishlab chiqarish": "production",
    "📋 Davomat": "attendance",
    "🔄 Obmen/Vozvrat": "returns",
}


def main_menu_kb() -> InlineKeyboardMarkup:
    """Inline menyu (eski usul — saqlab qolish)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Savdo", callback_data="report:sales"),
            InlineKeyboardButton(text="💵 Pul oqimi", callback_data="report:cashflow"),
        ],
        [
            InlineKeyboardButton(text="📌 Qarzdorlar", callback_data="report:debtors"),
            InlineKeyboardButton(text="📉 Harajatlar", callback_data="report:expenses"),
        ],
        [
            InlineKeyboardButton(text="🏆 Top mahsulotlar", callback_data="report:top_products"),
            InlineKeyboardButton(text="🚗 Agentlar", callback_data="report:agents"),
        ],
        [
            InlineKeyboardButton(text="💳 Ish haqi", callback_data="report:salaries"),
            InlineKeyboardButton(text="📊 KPI", callback_data="report:kpi"),
        ],
        [
            InlineKeyboardButton(text="📋 Davomat", callback_data="report:attendance"),
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
