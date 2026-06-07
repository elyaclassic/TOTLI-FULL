"""Xodim effective ish haqi — hire (EmploymentDoc) + kadr o'zgarishlari (EmployeeChangeDoc)."""
from datetime import date

from app.models.database import Employee, EmploymentDoc, EmployeeChangeDoc


def get_effective_salary(db, employee_id, as_of_date):
    """as_of_date sanasiga kuchda bo'lgan (salary, salary_type) ni qaytaradi.

    Ustuvorlik: effective_date <= as_of_date bo'lgan eng so'nggi tasdiqlangan
    EmployeeChangeDoc -> bo'lmasa eng so'nggi tasdiqlangan EmploymentDoc (hire)
    -> bo'lmasa Employee.salary (fallback). salary_type ham shu tartibda.
    """
    salary = None
    salary_type = None

    ch_q = (
        db.query(EmployeeChangeDoc)
        .filter(
            EmployeeChangeDoc.employee_id == employee_id,
            EmployeeChangeDoc.status == "confirmed",
            EmployeeChangeDoc.effective_date <= as_of_date,
        )
        .order_by(EmployeeChangeDoc.effective_date.desc(), EmployeeChangeDoc.id.desc())
        .all()
    )
    for ch in ch_q:
        if salary is None and ch.change_salary and ch.new_salary is not None:
            salary = float(ch.new_salary)
        if salary_type is None and ch.change_salary_type and ch.new_salary_type:
            salary_type = ch.new_salary_type
        if salary is not None and salary_type is not None:
            break

    if salary is None or salary_type is None:
        hire = (
            db.query(EmploymentDoc)
            .filter(EmploymentDoc.employee_id == employee_id, EmploymentDoc.confirmed_at.isnot(None))
            .order_by(EmploymentDoc.doc_date.desc(), EmploymentDoc.id.desc())
            .first()
        )
        if hire:
            if salary is None and hire.salary:
                salary = float(hire.salary)
            if salary_type is None and hire.salary_type:
                salary_type = hire.salary_type

    if salary is None or salary_type is None:
        emp = db.query(Employee).filter(Employee.id == employee_id).first()
        if emp:
            if salary is None:
                salary = float(emp.salary or 0)
            if salary_type is None:
                salary_type = emp.salary_type

    return float(salary or 0), salary_type
