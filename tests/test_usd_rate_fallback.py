"""H4: USD to'lov kursi yo'q bo'lsa xom summani SO'M deb olMAYDI (fallback yoki 0)."""
from datetime import date, datetime
from app.models.database import CashRegister, Payment, ExchangeRate
from app.services.partner_balance_service import _payment_amount_uzs


def _usd_kassa(db, name):
    c = CashRegister(name=name, currency="USD", balance=0, opening_balance=0)
    db.add(c); db.flush()
    return c


def test_usd_payment_uses_date_rate(db):
    c = _usd_kassa(db, "USD kassa H4a")
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", effective_date=date(2026, 6, 1), rate=12000))
    db.flush()
    p = Payment(cash_register_id=c.id, type="expense", amount=100, status="confirmed", date=datetime(2026, 6, 3))
    db.add(p); db.flush()
    assert _payment_amount_uzs(db, p) == 1_200_000  # 100 * 12000


def test_usd_payment_missing_date_rate_falls_back(db):
    c = _usd_kassa(db, "USD kassa H4b")
    # faqat to'lov sanasidan KEYINGI kurs bor (06-10), sana (06-03) kursi yo'q
    db.add(ExchangeRate(from_currency="USD", to_currency="UZS", effective_date=date(2026, 6, 10), rate=12500))
    db.flush()
    p = Payment(cash_register_id=c.id, type="expense", amount=100, status="confirmed", date=datetime(2026, 6, 3))
    db.add(p); db.flush()
    # fallback eng yaqin kurs (12500), xom 100 EMAS
    assert _payment_amount_uzs(db, p) == 1_250_000


def test_usd_payment_no_rate_returns_zero_not_raw(db):
    c = _usd_kassa(db, "USD kassa H4c")
    p = Payment(cash_register_id=c.id, type="expense", amount=100, status="confirmed", date=datetime(2026, 6, 3))
    db.add(p); db.flush()
    # hech qanday USD kurs yo'q → 0 (xom 100 EMAS)
    assert _payment_amount_uzs(db, p) == 0.0
