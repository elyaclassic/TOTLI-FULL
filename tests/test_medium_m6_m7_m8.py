"""MEDIUM M7 + M8 fix testlari (M6 = bir qatorli with_for_update lock, review).

M7: payment edit kassa valyutasi o'zgarsa bloklanadi (summa noto'g'ri talqin qilinmasin).
M8: cross-currency transfer edit'da to_amount/exchange_rate yangi amount bo'yicha qayta
    hisoblanadi (eskirib qolmasin).
"""
import asyncio
from datetime import datetime, date


# ============ M8 ============

def _mk_rate(db, frm, to, rate, eff=date(2026, 1, 1)):
    from app.models.database import ExchangeRate
    db.add(ExchangeRate(from_currency=frm, to_currency=to, rate=rate, effective_date=eff))
    db.flush()


def test_m8_cross_currency_recompute(db):
    from app.models.database import CashRegister
    from app.routes.finance import _transfer_conversion
    usd = CashRegister(name="USD kassa", payment_type="naqd", currency="USD", is_active=True)
    uzs = CashRegister(name="UZS kassa", payment_type="naqd", currency="UZS", is_active=True)
    db.add_all([usd, uzs]); db.flush()
    _mk_rate(db, "USD", "UZS", 12000)

    rate, to_amount = _transfer_conversion(db, usd.id, uzs.id, 100)
    assert rate == 12000.0
    assert to_amount == 1200000.0, f"$100 -> 1.2M so'm kutilgan, keldi {to_amount}"


def test_m8_same_currency_clears_fields(db):
    from app.models.database import CashRegister
    from app.routes.finance import _transfer_conversion
    a = CashRegister(name="A", payment_type="naqd", currency="UZS", is_active=True)
    b = CashRegister(name="B", payment_type="plastik", currency="UZS", is_active=True)
    db.add_all([a, b]); db.flush()
    rate, to_amount = _transfer_conversion(db, a.id, b.id, 500000)
    assert rate is None and to_amount is None, "Bir xil valyuta -> rate/to_amount None"


def test_m8_no_rate_raises(db):
    from app.models.database import CashRegister
    from app.routes.finance import _transfer_conversion
    eur = CashRegister(name="EUR", payment_type="naqd", currency="EUR", is_active=True)
    uzs = CashRegister(name="UZS", payment_type="naqd", currency="UZS", is_active=True)
    db.add_all([eur, uzs]); db.flush()
    # EUR kursi yo'q
    try:
        _transfer_conversion(db, eur.id, uzs.id, 100)
        assert False, "Kurs yo'qligida ValueError kutilgan"
    except ValueError as ex:
        assert "EUR" in str(ex)


# ============ M7 ============

class _User:
    username = "tester"
    role = "admin"


def test_m7_payment_edit_blocks_currency_change(db):
    from app.models.database import Payment, CashRegister
    from app.routes.finance import finance_payment_edit_post
    uzs = CashRegister(name="UZS", payment_type="naqd", currency="UZS", is_active=True)
    usd = CashRegister(name="USD", payment_type="naqd", currency="USD", is_active=True)
    db.add_all([uzs, usd]); db.flush()
    pay = Payment(number="PAY-T-M7", date=datetime(2026, 6, 1), type="expense",
                  amount=100000, cash_register_id=uzs.id, status="pending")
    db.add(pay); db.commit()

    # USD kassaga o'zgartirishga urinish -> bloklanishi kerak
    res = asyncio.run(finance_payment_edit_post(
        payment_id=pay.id, type="expense", amount=100000,
        cash_register_id=usd.id, partner_id=None, description="x",
        db=db, current_user=_User(),
    ))
    db.refresh(pay)
    assert getattr(res, "status_code", None) == 303
    assert "error" in str(getattr(res, "headers", {}).get("location", "")), "Xato redirect kutilgan"
    assert pay.cash_register_id == uzs.id, "Valyuta o'zgarishi qo'llanmasligi kerak"


def test_m7_payment_edit_same_currency_ok(db):
    from app.models.database import Payment, CashRegister
    from app.routes.finance import finance_payment_edit_post
    uzs1 = CashRegister(name="UZS naqd", payment_type="naqd", currency="UZS", is_active=True)
    uzs2 = CashRegister(name="UZS plastik", payment_type="plastik", currency="UZS", is_active=True)
    db.add_all([uzs1, uzs2]); db.flush()
    pay = Payment(number="PAY-T-M7b", date=datetime(2026, 6, 1), type="expense",
                  amount=100000, cash_register_id=uzs1.id, status="pending")
    db.add(pay); db.commit()

    res = asyncio.run(finance_payment_edit_post(
        payment_id=pay.id, type="expense", amount=120000,
        cash_register_id=uzs2.id, partner_id=None, description="x",
        db=db, current_user=_User(),
    ))
    db.refresh(pay)
    assert pay.cash_register_id == uzs2.id and pay.amount == 120000, "Bir xil valyuta tahriri ishlashi kerak"
