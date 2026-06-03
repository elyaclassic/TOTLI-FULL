"""C1 test: avans tasdiqlanganda kassa chiqim Payment ta'minlanadi (yaratish/un-cancel/idempotent)."""
from datetime import date, datetime
from app.models.database import CashRegister, Employee, EmployeeAdvance, Payment
from app.routes.employees_advances import _ensure_advance_payment, _cancel_linked_advance_payment
from app.services.finance_service import cash_balance_formula


class _U:
    id = 1


def _setup(db):
    c = CashRegister(name="Test kassa C1", opening_balance=1_000_000, balance=1_000_000, currency="UZS")
    db.add(c); db.flush()
    e = Employee(full_name="Test Xodim C1")
    db.add(e); db.flush()
    adv = EmployeeAdvance(employee_id=e.id, amount=100_000, advance_date=date(2026, 6, 3),
                          cash_register_id=c.id, confirmed_at=datetime.now())
    db.add(adv); db.flush()
    return c, e, adv


def test_ensure_creates_payment_and_debits_cash(db):
    c, e, adv = _setup(db)
    _ensure_advance_payment(db, adv, _U())
    db.flush()
    pays = db.query(Payment).filter(Payment.cash_register_id == c.id, Payment.type == "expense").all()
    assert len(pays) == 1
    assert float(pays[0].amount) == 100_000
    assert pays[0].status == "confirmed"
    # opening 1,000,000 - 100,000 expense = 900,000
    assert cash_balance_formula(db, c.id)[0] == 900_000


def test_ensure_idempotent(db):
    c, e, adv = _setup(db)
    _ensure_advance_payment(db, adv, _U())
    _ensure_advance_payment(db, adv, _U())  # 2-marta — dublikat bo'lmasin
    db.flush()
    pays = db.query(Payment).filter(Payment.cash_register_id == c.id, Payment.type == "expense",
                                    Payment.status == "confirmed").all()
    assert len(pays) == 1
    assert cash_balance_formula(db, c.id)[0] == 900_000


def test_unconfirm_then_reconfirm_debits_once(db):
    """add -> unconfirm (cancel) -> reconfirm (ensure) = kassa BIR marta kamayadi (C1 bug)."""
    c, e, adv = _setup(db)
    _ensure_advance_payment(db, adv, _U())          # add: Payment yaratildi
    db.flush()
    assert cash_balance_formula(db, c.id)[0] == 900_000
    _cancel_linked_advance_payment(db, adv)         # unconfirm: bekor
    db.flush()
    assert cash_balance_formula(db, c.id)[0] == 1_000_000   # kassa qaytdi
    _ensure_advance_payment(db, adv, _U())          # reconfirm: un-cancel (yangi emas)
    db.flush()
    confirmed = db.query(Payment).filter(Payment.cash_register_id == c.id, Payment.type == "expense",
                                         Payment.status == "confirmed").all()
    assert len(confirmed) == 1                      # dublikat yo'q
    assert cash_balance_formula(db, c.id)[0] == 900_000    # bir marta kamaydi
