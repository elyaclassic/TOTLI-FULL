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


def test_confirm_refreshes_employee_cache(db):
    from app.routes.employees_changes import _refresh_employee_current
    from datetime import date as _d, datetime as _dt
    e = _emp(db, salary=1_000_000, position="Ishchi")
    _hire(db, e, 1_000_000, _d(2026, 1, 1))
    ch = EmployeeChangeDoc(number="KO-x", employee_id=e.id, doc_date=_d(2026, 1, 1),
                           effective_date=_d(2026, 1, 1), change_salary=True, old_salary=1_000_000,
                           new_salary=1_700_000, change_position=True, old_position="Ishchi",
                           new_position="Brigadir", status="confirmed", confirmed_at=_dt(2026, 1, 1))
    db.add(ch); db.flush()
    _refresh_employee_current(db, e)
    assert e.salary == 1_700_000
    assert e.position == "Brigadir"


def test_payroll_uses_effective_by_month(db):
    from app.services.employee_salary_service import get_effective_salary
    from datetime import date as _d
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, _d(2026, 1, 1))
    _change(db, e, 1_500_000, _d(2026, 4, 1))
    assert get_effective_salary(db, e.id, _d(2026, 3, 1))[0] == 1_000_000
    assert get_effective_salary(db, e.id, _d(2026, 4, 1))[0] == 1_500_000
    _change(db, e, 2_000_000, _d(2026, 5, 15))
    assert get_effective_salary(db, e.id, _d(2026, 5, 1))[0] == 1_500_000
    assert get_effective_salary(db, e.id, _d(2026, 6, 1))[0] == 2_000_000


def test_cancel_reverts_position_to_hire(db):
    """Bekor qilingan lavozim o'zgarishi keshni hire holatiga qaytarsin (stale qolmasin)."""
    from app.routes.employees_changes import _refresh_employee_current
    from datetime import date as _d, datetime as _dt
    e = _emp(db, salary=1_000_000, position="Brigadir")  # kesh hozir stale "Brigadir"
    hire = EmploymentDoc(number="IQ-rev", employee_id=e.id, doc_date=_d(2026, 1, 1), hire_date=_d(2026, 1, 1),
                         salary=1_000_000, salary_type="oylik", position="Ishchi", confirmed_at=_dt(2026, 1, 1))
    db.add(hire)
    ch = EmployeeChangeDoc(number="KO-rev", employee_id=e.id, doc_date=_d(2026, 2, 1), effective_date=_d(2026, 2, 1),
                           change_position=True, old_position="Ishchi", new_position="Brigadir",
                           status="cancelled", confirmed_at=None)
    db.add(ch); db.flush()
    _refresh_employee_current(db, e)
    assert e.position == "Ishchi"  # hire'ga qaytdi (bekor qilingan change hisobga olinmadi)
