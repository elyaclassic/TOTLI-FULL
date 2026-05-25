"""Valyuta kursi xizmati — kurs olish va konvertatsiya helper'lari."""
from datetime import date as _date
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.database import ExchangeRate


def get_rate(db: Session, from_currency: str, to_currency: str, on_date: _date = None) -> float:
    """Berilgan sanadagi (yoki undan oldingi eng yangi) kursni topadi.

    on_date None bo'lsa — bugungi kurs.
    Bir xil valyuta bo'lsa — 1.0 qaytaradi.
    Kurs topilmasa — 0.0 qaytaradi (chaqiruvchi tekshirsin).
    """
    if from_currency == to_currency:
        return 1.0
    target_date = on_date or _date.today()
    row = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.from_currency == from_currency,
            ExchangeRate.to_currency == to_currency,
            ExchangeRate.effective_date <= target_date,
        )
        .order_by(desc(ExchangeRate.effective_date), desc(ExchangeRate.id))
        .first()
    )
    if row:
        return float(row.rate or 0)

    reverse = (
        db.query(ExchangeRate)
        .filter(
            ExchangeRate.from_currency == to_currency,
            ExchangeRate.to_currency == from_currency,
            ExchangeRate.effective_date <= target_date,
        )
        .order_by(desc(ExchangeRate.effective_date), desc(ExchangeRate.id))
        .first()
    )
    if reverse and reverse.rate:
        return 1.0 / float(reverse.rate)
    return 0.0


def convert(db: Session, amount: float, from_currency: str, to_currency: str, on_date: _date = None) -> float:
    """Berilgan summani belgilangan kursda boshqa valyutaga aylantiradi."""
    rate = get_rate(db, from_currency, to_currency, on_date)
    return float(amount or 0) * rate
