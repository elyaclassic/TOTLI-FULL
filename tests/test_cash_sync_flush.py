"""Kassa balans sync — autoflush=False tuzog'i.

SessionLocal `autoflush=False` (database.py). Avans 'add' yo'li (employees_advances.py)
expense Payment'ni db.add() qiladi, lekin flush qilmasdan _sync_cash_balance chaqiradi.
cash_balance_formula ORM db.query(SUM) ishlatadi — flushlanmagan Payment hisobga
olinmaydi => stored balans avans qadar yuqori qoladi (drift, "Qayta hisoblash" kerak).

FIX: sync_cash_balance boshida db.flush() — har qanday chaqiruvchi uchun kutilgan
Payment/Transfer'larni DB'ga yuborib, formula ularni ko'rsin.
"""
from datetime import datetime
from app.models.database import CashRegister, Payment
from app.services.finance_service import sync_cash_balance


def test_sync_sees_unflushed_expense_payment(db):
    cash = CashRegister(name="T-sync", opening_balance=100000, balance=100000,
                        is_active=True, payment_type="naqd")
    db.add(cash)
    db.flush()
    # Avans 'add' yo'lini taqlid: confirmed expense Payment qo'shiladi, FLUSH QILINMAYDI
    db.add(Payment(number="PAY-SYNCT-1", date=datetime.now(), type="expense",
                   amount=30000, status="confirmed", cash_register_id=cash.id,
                   payment_type="cash", category="other"))
    sync_cash_balance(db, cash.id)
    # opening 100k - expense 30k = 70k. Bug'da (flushsiz) expense ko'rinmaydi => 100k qoladi.
    assert cash.balance == 70000, f"kutilgan 70000 (opening-expense), got {cash.balance}"


def test_sync_sees_unflushed_income_payment(db):
    cash = CashRegister(name="T-sync2", opening_balance=0, balance=0,
                        is_active=True, payment_type="naqd")
    db.add(cash)
    db.flush()
    db.add(Payment(number="PAY-SYNCT-2", date=datetime.now(), type="income",
                   amount=45000, status="confirmed", cash_register_id=cash.id,
                   payment_type="cash", category="other"))
    sync_cash_balance(db, cash.id)
    assert cash.balance == 45000, f"kutilgan 45000 (income), got {cash.balance}"
