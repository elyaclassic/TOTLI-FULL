"""Kadr o'zgarishi buyrug'i: effective salary + payroll."""
from datetime import date, datetime
from app.models.database import Employee, EmploymentDoc, EmployeeChangeDoc

_CONFIRMED_AT = datetime(2026, 1, 1, 0, 0, 0)


def _emp(db, salary=1_000_000, position="Ishchi"):
    e = Employee(full_name="Test Xodim", salary=salary, position=position, salary_type="oylik", is_active=True)
    db.add(e); db.flush()
    return e


def _hire(db, emp, salary, d):
    doc = EmploymentDoc(number=f"IQ-{emp.id}", employee_id=emp.id, doc_date=d, hire_date=d,
                        salary=salary, salary_type="oylik", confirmed_at=_CONFIRMED_AT)
    db.add(doc); db.flush()
    return doc


def _change(db, emp, new_salary, eff, status="confirmed"):
    doc = EmployeeChangeDoc(number=f"KO-{emp.id}-{eff}", employee_id=emp.id, doc_date=eff,
                            effective_date=eff, change_salary=True, old_salary=emp.salary,
                            new_salary=new_salary, status=status,
                            confirmed_at=(_CONFIRMED_AT if status == "confirmed" else None))
    db.add(doc); db.flush()
    return doc


def test_effective_hire_only(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    sal, _ = get_effective_salary(db, e.id, date(2026, 3, 1))
    assert sal == 1_000_000


def test_effective_after_change(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    _change(db, e, 1_500_000, date(2026, 3, 1))
    assert get_effective_salary(db, e.id, date(2026, 2, 1))[0] == 1_000_000
    assert get_effective_salary(db, e.id, date(2026, 3, 1))[0] == 1_500_000


def test_effective_ignores_future_and_unconfirmed(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    _change(db, e, 2_000_000, date(2026, 6, 1))
    _change(db, e, 9_000_000, date(2026, 2, 1), status="draft")
    sal, _ = get_effective_salary(db, e.id, date(2026, 3, 1))
    assert sal == 1_000_000


def test_effective_latest_of_two_changes(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    _change(db, e, 1_500_000, date(2026, 2, 1))
    _change(db, e, 1_800_000, date(2026, 4, 1))
    assert get_effective_salary(db, e.id, date(2026, 5, 1))[0] == 1_800_000
    assert get_effective_salary(db, e.id, date(2026, 3, 1))[0] == 1_500_000
