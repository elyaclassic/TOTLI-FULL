"""
Xodimlar — oylik hisoblash (Tier C1 4-bosqich).

Manba: employees.py:1086-1629 (~545 qator) dan ajratib olindi.
Endpoint path'lar o'zgarishsiz.

Kichik fix: employee_salary_save'da `no_cash_warn` oldin ishlatilar edi
(existing_expense path'ida) — endi funksiya boshida None deb initsializatsiya qilinadi.
"""
import calendar
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_

from app.core import templates
from app.models.database import (
    get_db,
    User,
    Employee,
    EmploymentDoc,
    DismissalDoc,
    Salary,
    EmployeeAdvance,
    Attendance,
    ProductionGroup,
    production_group_members,
    PieceworkTask,
    employee_piecework_tasks,
    Production,
    CashRegister,
    ExpenseDoc,
    ExpenseDocItem,
    ExpenseType,
)
from app.deps import require_auth
from app.utils.production_order import is_qiyom_recipe, recipe_kg_per_unit

router = APIRouter(prefix="/employees", tags=["employees-salary"])


@router.get("/salary", response_class=HTMLResponse)
async def employee_salary_page(
    request: Request,
    year: Optional[int] = None,
    month: Optional[int] = None,
    rest_days: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Oylik hisoblash — oy tanlash, xodimlar ro'yxati (base, bonus, deduction, avans, total)."""
    today = date.today()
    year = year or today.year
    month = month or today.month
    if not (1 <= month <= 12):
        month = today.month
    if year < 2020 or year > 2030:
        year = today.year
    hired_employee_ids = db.query(EmploymentDoc.employee_id).distinct().all()
    hired_ids = [r[0] for r in hired_employee_ids if r[0]]
    dismissed_before = db.query(DismissalDoc.employee_id).filter(
        DismissalDoc.doc_date < date(year, month, 1),
    ).distinct().all()
    dismissed_ids = {r[0] for r in dismissed_before if r[0]}
    active_hired_ids = [eid for eid in hired_ids if eid not in dismissed_ids]
    if not active_hired_ids:
        employees = []
    else:
        employees = (
            db.query(Employee)
            .filter(Employee.is_active == True, Employee.id.in_(active_hired_ids))
            .order_by(Employee.full_name)
            .all()
        )
    salaries = {s.employee_id: s for s in db.query(Salary).filter(Salary.year == year, Salary.month == month).all()}
    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    prev_debt_by_emp = {}
    prev_credit_by_emp = {}
    for s in db.query(Salary).filter(Salary.year == prev_year, Salary.month == prev_month).all():
        prev_total = float(s.total or 0)
        if prev_total < 0:
            prev_debt_by_emp[s.employee_id] = -prev_total
        elif prev_total > 0 and getattr(s, "is_balance_entry", False):
            prev_credit_by_emp[s.employee_id] = prev_total
    emp_ids = [e.id for e in employees]
    latest_doc_salary = {}
    if emp_ids:
        subq_conf = (
            db.query(EmploymentDoc.employee_id, func.max(EmploymentDoc.doc_date).label("max_date"))
            .filter(EmploymentDoc.employee_id.in_(emp_ids), EmploymentDoc.confirmed_at.isnot(None))
            .group_by(EmploymentDoc.employee_id)
        ).subquery()
        docs_confirmed = (
            db.query(EmploymentDoc.employee_id, EmploymentDoc.salary)
            .join(subq_conf, (EmploymentDoc.employee_id == subq_conf.c.employee_id) & (EmploymentDoc.doc_date == subq_conf.c.max_date))
            .filter(EmploymentDoc.employee_id.in_(emp_ids), EmploymentDoc.confirmed_at.isnot(None))
            .all()
        )
        for row in docs_confirmed:
            if (row.salary or 0) > 0:
                latest_doc_salary[row.employee_id] = float(row.salary)
        missing = [eid for eid in emp_ids if eid not in latest_doc_salary]
        if missing:
            subq = (
                db.query(EmploymentDoc.employee_id, func.max(EmploymentDoc.doc_date).label("max_date"))
                .filter(EmploymentDoc.employee_id.in_(missing))
                .group_by(EmploymentDoc.employee_id)
            ).subquery()
            docs_latest = (
                db.query(EmploymentDoc.employee_id, EmploymentDoc.salary)
                .join(subq, (EmploymentDoc.employee_id == subq.c.employee_id) & (EmploymentDoc.doc_date == subq.c.max_date))
                .filter(EmploymentDoc.employee_id.in_(missing))
                .all()
            )
            for row in docs_latest:
                if (row.salary or 0) > 0:
                    latest_doc_salary[row.employee_id] = float(row.salary)
    advance_sums = {}
    from calendar import monthrange
    _, last_day = monthrange(year, month)
    start_d = date(year, month, 1)
    end_d = date(year, month, last_day)
    for a in db.query(EmployeeAdvance).filter(
        EmployeeAdvance.advance_date >= start_d,
        EmployeeAdvance.advance_date <= end_d,
        EmployeeAdvance.confirmed_at.isnot(None),
    ).all():
        advance_sums[a.employee_id] = advance_sums.get(a.employee_id, 0) + (a.amount or 0)
    worked_days_by_emp = {}
    if emp_ids:
        try:
            worked_rows = (
                db.query(Attendance.employee_id, func.count(func.distinct(Attendance.date)).label("days"))
                .filter(
                    Attendance.employee_id.in_(emp_ids),
                    Attendance.date >= start_d,
                    Attendance.date <= end_d,
                    or_(
                        Attendance.status == "present",
                        Attendance.check_in.isnot(None),
                    ),
                )
                .group_by(Attendance.employee_id)
                .all()
            )
            for r in worked_rows:
                worked_days_by_emp[r.employee_id] = int(r.days or 0)
        except Exception:
            pass
    holiday_days = rest_days if rest_days is not None else 0
    if holiday_days < 0 or holiday_days >= last_day:
        holiday_days = 0
    days_in_month = last_day
    working_days_by_emp_total = {}
    for emp in employees:
        emp_rest = int(getattr(emp, "monthly_rest_days", None) or 4)
        if emp_rest < 0:
            emp_rest = 0
        if emp_rest >= last_day:
            emp_rest = last_day - 1
        working_days_by_emp_total[emp.id] = max(1, last_day - emp_rest - holiday_days)
    working_days_in_month = last_day - 4 - holiday_days
    for emp in employees:
        if emp.id not in worked_days_by_emp:
            if not getattr(emp, "hikvision_id", None):
                worked_days_by_emp[emp.id] = working_days_by_emp_total.get(emp.id, working_days_in_month)
    piecework_calculated = {}
    emp_by_id = {e.id: e for e in employees}
    group_member_ids = set()
    production_groups = (
        db.query(ProductionGroup)
        .options(joinedload(ProductionGroup.members), joinedload(ProductionGroup.piecework_task))
        .filter(ProductionGroup.is_active == True, ProductionGroup.operator_id.in_(emp_ids) if emp_ids else False)
        .all()
    )
    for gr in production_groups:
        member_ids = [m.id for m in gr.members if m.id in emp_ids] if hasattr(gr, "members") and gr.members else []
        if not member_ids or gr.operator_id not in emp_ids:
            continue
        group_member_ids.update(member_ids)
        member_rates = {}
        rate_rows = db.execute(
            production_group_members.select().where(production_group_members.c.group_id == gr.id)
        ).fetchall()
        default_rate = float(gr.piecework_task.price_per_unit or 0) if gr.piecework_task else 0
        for rr in rate_rows:
            member_rates[rr.employee_id] = float(rr.price_per_unit or 0) or default_rate
        prod_list = (
            db.query(Production)
            .options(joinedload(Production.recipe))
            .filter(
                Production.operator_id == gr.operator_id,
                Production.status == "completed",
                func.date(Production.date) >= start_d,
                func.date(Production.date) <= end_d,
            )
            .all()
        )
        day_kg = {}
        for p in prod_list:
            if not getattr(gr, "include_qiyom", True) and is_qiyom_recipe(p.recipe):
                continue
            kg = (float(p.quantity or 0) * recipe_kg_per_unit(p.recipe)) if p.recipe else 0
            if kg <= 0:
                continue
            d = p.date.date() if hasattr(p.date, "date") else p.date
            day_kg[d] = day_kg.get(d, 0) + kg
        attendances = (
            db.query(Attendance.employee_id, Attendance.date, Attendance.status, Attendance.check_in)
            .filter(Attendance.employee_id.in_(member_ids), Attendance.date >= start_d, Attendance.date <= end_d)
            .all()
        )
        present_by_date = {}
        for row in attendances:
            d = row.date
            if d not in present_by_date:
                present_by_date[d] = set()
            if (row.status or "").strip() == "present" or (getattr(row, "check_in", None) is not None):
                present_by_date[d].add(row.employee_id)
        member_kg = {mid: 0.0 for mid in member_ids}
        for d, kg in day_kg.items():
            present = present_by_date.get(d, set()) & set(member_ids)
            for mid in present:
                member_kg[mid] = member_kg.get(mid, 0) + kg
        for mid in member_ids:
            rate = member_rates.get(mid, default_rate)
            piecework_calculated[mid] = piecework_calculated.get(mid, 0) + member_kg.get(mid, 0) * rate
    piece_rate_sum = {}
    if emp_ids:
        rows_rates = (
            db.query(employee_piecework_tasks.c.employee_id, func.min(PieceworkTask.price_per_unit).label("rate"))
            .join(PieceworkTask, PieceworkTask.id == employee_piecework_tasks.c.task_id)
            .filter(employee_piecework_tasks.c.employee_id.in_(emp_ids))
            .filter(PieceworkTask.price_per_unit > 0)
            .group_by(employee_piecework_tasks.c.employee_id)
            .all()
        )
        for eid, rate in rows_rates:
            piece_rate_sum[int(eid)] = float(rate or 0)
    boalak_emp_ids = [e.id for e in employees if getattr(e, "salary_type", None) in ("bo'lak", "bo'lak_oylik")]
    if boalak_emp_ids:
        docs_with_tasks = (
            db.query(EmploymentDoc.employee_id, EmploymentDoc.piecework_task_ids)
            .filter(EmploymentDoc.employee_id.in_(boalak_emp_ids), EmploymentDoc.confirmed_at.isnot(None))
            .order_by(EmploymentDoc.doc_date.desc())
            .all()
        )
        for row in docs_with_tasks:
            eid = row.employee_id
            if piece_rate_sum.get(eid, 0) > 0:
                continue
            raw = (row.piecework_task_ids or "").strip()
            ids = [int(x) for x in raw.split(",") if x.strip().isdigit()] if raw else []
            if not ids:
                continue
            first_task = db.query(PieceworkTask).filter(PieceworkTask.id == ids[0], PieceworkTask.price_per_unit > 0).first()
            if first_task:
                piece_rate_sum[eid] = float(first_task.price_per_unit)
    boalak_employees = [e for e in employees if getattr(e, "salary_type", None) in ("bo'lak", "bo'lak_oylik") and piece_rate_sum.get(e.id, 0) > 0]
    emp_by_id = {e.id: e for e in employees}
    user_to_employee_id = {}
    for e in employees:
        if e.user_id:
            user_to_employee_id[e.user_id] = e.id
    if boalak_employees:
        productions_for_salary = (
            db.query(Production)
            .options(joinedload(Production.recipe))
            .filter(
                Production.status == "completed",
                func.date(Production.date) >= start_d,
                func.date(Production.date) <= end_d,
            )
            .all()
        )
        total_kg_by_emp_id = {}
        for p in productions_for_salary:
            if is_qiyom_recipe(p.recipe):
                continue
            kg = (float(p.quantity or 0) * recipe_kg_per_unit(p.recipe)) if p.recipe else 0
            if kg <= 0:
                continue
            emp_id = None
            if p.operator_id and p.operator_id in emp_by_id:
                emp_id = p.operator_id
            elif p.user_id and p.user_id in user_to_employee_id:
                emp_id = user_to_employee_id[p.user_id]
            if emp_id and emp_id not in group_member_ids:
                total_kg_by_emp_id[emp_id] = total_kg_by_emp_id.get(emp_id, 0) + kg
        for emp in boalak_employees:
            if emp.id in group_member_ids:
                continue
            total_kg = total_kg_by_emp_id.get(emp.id, 0)
            rate = piece_rate_sum.get(emp.id, 0)
            if total_kg > 0 and rate > 0:
                piecework_calculated[emp.id] = total_kg * rate
    rows = []
    for emp in employees:
        s = salaries.get(emp.id)
        piecework_amount = float(piecework_calculated.get(emp.id, 0) or 0)
        base_source = ""
        if emp.id in group_member_ids and emp.id in piecework_calculated:
            mehnat_haqi = float(latest_doc_salary.get(emp.id, 0) or 0) or float(emp.salary or 0)
            piece_total = piecework_amount
            base = max(mehnat_haqi, piece_total)
            base_source = "bo'lak" if piece_total >= mehnat_haqi and piece_total > 0 else "oylik"
        elif getattr(emp, "salary_type", None) == "bo'lak":
            base = piecework_amount
            base_source = "bo'lak" if piecework_amount > 0 else ""
        elif getattr(emp, "salary_type", None) == "bo'lak_oylik":
            mehnat_haqi = float(latest_doc_salary.get(emp.id, 0) or 0) or float(emp.salary or 0)
            piece_total = piecework_amount
            base = max(mehnat_haqi, piece_total)
            base_source = "bo'lak" if piece_total >= mehnat_haqi and piece_total > 0 else "oylik"
        else:
            base = (s.base_salary if s else 0) or (emp.salary or 0) or latest_doc_salary.get(emp.id, 0)
            if not base and emp.id in piecework_calculated:
                base = piecework_calculated[emp.id]
            base = float(base or 0)
            if getattr(emp, "salary_type", None) in ("oylik", "soatlik") or not getattr(emp, "salary_type", None):
                base_source = "oylik" if base > 0 else ""
        base = float(base or 0)
        calculated_base = None
        emp_working_days = working_days_by_emp_total.get(emp.id, working_days_in_month)
        if emp_working_days and emp_working_days > 0:
            contract_monthly = float(latest_doc_salary.get(emp.id, 0) or 0) or float(emp.salary or 0)
            worked_days = worked_days_by_emp.get(emp.id, 0) or 0
            if getattr(emp, "salary_type", None) == "oylik":
                calculated_base = round((contract_monthly / emp_working_days) * worked_days, 2)
            elif base_source == "oylik" and contract_monthly > 0:
                calculated_base = round((contract_monthly / emp_working_days) * worked_days, 2)
        amount_for_total = calculated_base if calculated_base is not None else base
        bonus = float(s.bonus if s and s.bonus is not None else 0) or 0
        deduction = float(s.deduction if s and s.deduction is not None else 0) or 0
        adv_ded = float(advance_sums.get(emp.id, 0) or 0)
        if adv_ded == 0 and s and getattr(s, "advance_deduction", None) is not None:
            adv_ded = float(s.advance_deduction)
        prev_debt = float(prev_debt_by_emp.get(emp.id, 0) or 0)
        prev_credit = float(prev_credit_by_emp.get(emp.id, 0) or 0)
        total = amount_for_total + bonus - deduction - adv_ded - prev_debt + prev_credit
        total = round(total, 2)
        paid = float(s.paid if s and s.paid is not None else 0) or 0
        if s and s.status == "paid":
            status = "paid"
        elif total > 0 and paid >= total:
            status = "paid"
        else:
            status = "pending"
        rows.append({
            "employee": emp,
            "salary_row": s,
            "base_salary": base,
            "calculated_base": calculated_base,
            "piecework_amount": piecework_amount,
            "base_source": base_source,
            "bonus": bonus,
            "deduction": deduction,
            "advance_deduction": adv_ded,
            "prev_debt": prev_debt,
            "prev_credit": prev_credit,
            "total": total,
            "paid": paid,
            "status": status,
            "worked_days": worked_days_by_emp.get(emp.id, 0) or 0,
            "days_in_month": working_days_by_emp_total.get(emp.id, working_days_in_month),
        })
    cash_doc_id = request.query_params.get("cash_doc")
    try:
        cash_doc_id = int(cash_doc_id) if cash_doc_id else None
    except (TypeError, ValueError):
        cash_doc_id = None
    cash_register_id = request.query_params.get("cash_id")
    try:
        cash_register_id = int(cash_register_id) if cash_register_id else None
    except (TypeError, ValueError):
        cash_register_id = None
    expense_doc_id = request.query_params.get("expense_doc_id")
    try:
        expense_doc_id = int(expense_doc_id) if expense_doc_id else None
    except (TypeError, ValueError):
        expense_doc_id = None
    no_cash_warn = request.query_params.get("no_cash") == "1"
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    try:
        last_day = calendar.monthrange(year, month)[1]
        harajatlar_date_from = f"{year}-{month:02d}-01"
        harajatlar_date_to = f"{year}-{month:02d}-{last_day}"
    except (ValueError, TypeError):
        harajatlar_date_from = harajatlar_date_to = ""
    return templates.TemplateResponse("employees/salary_list.html", {
        "request": request,
        "year": year,
        "month": month,
        "rows": rows,
        "current_user": current_user,
        "page_title": "Oylik hisoblash",
        "cash_doc_id": cash_doc_id,
        "cash_register_id": cash_register_id,
        "expense_doc_id": expense_doc_id,
        "no_cash_warn": no_cash_warn,
        "cash_registers": cash_registers,
        "harajatlar_date_from": harajatlar_date_from,
        "harajatlar_date_to": harajatlar_date_to,
        "rest_days": holiday_days,
        "working_days": working_days_in_month,
    })


@router.post("/salary/save")
async def employee_salary_save(
    request: Request,
    year: int = Form(...),
    month: int = Form(...),
    cash_register_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Oylik yozuvlarini saqlash; tanlangan kassadan chiqim hujjati (Payment) va qoldiq hujjati yaratiladi."""
    # FIX: no_cash_warn oldin initsializatsiya — existing_expense path'da UnboundLocalError oldini olish
    no_cash_warn = False
    expense_doc_id = None

    if not (1 <= month <= 12) or year < 2020 or year > 2030:
        return RedirectResponse(url="/employees/salary?error=Noto'g'ri oy yoki yil", status_code=303)
    form = await request.form()
    hired_ids = [r[0] for r in db.query(EmploymentDoc.employee_id).distinct().all() if r[0]]
    if not hired_ids:
        employees = []
    else:
        employees = db.query(Employee).filter(Employee.is_active == True, Employee.id.in_(hired_ids)).all()
    prev_month = 12 if month == 1 else month - 1
    prev_year = year - 1 if month == 1 else year
    prev_debt_by_emp = {}
    prev_credit_by_emp = {}
    for ps in db.query(Salary).filter(Salary.year == prev_year, Salary.month == prev_month).all():
        pt = float(ps.total or 0)
        if pt < 0:
            prev_debt_by_emp[ps.employee_id] = -pt
        elif pt > 0 and getattr(ps, "is_balance_entry", False):
            prev_credit_by_emp[ps.employee_id] = pt
    total_payroll = 0.0
    for emp in employees:
        base = float(form.get(f"base_{emp.id}", 0) or 0)
        bonus = float(form.get(f"bonus_{emp.id}", 0) or 0)
        deduction = float(form.get(f"deduction_{emp.id}", 0) or 0)
        advance_deduction = float(form.get(f"advance_{emp.id}", 0) or 0)
        prev_debt = float(prev_debt_by_emp.get(emp.id, 0) or 0)
        prev_credit = float(prev_credit_by_emp.get(emp.id, 0) or 0)
        total = base + bonus - deduction - advance_deduction - prev_debt + prev_credit
        total_payroll += max(0, float(total))
        s = db.query(Salary).filter(Salary.employee_id == emp.id, Salary.year == year, Salary.month == month).first()
        if not s:
            s = Salary(employee_id=emp.id, year=year, month=month)
            db.add(s)
        s.base_salary = base
        s.bonus = bonus
        s.deduction = deduction
        s.advance_deduction = advance_deduction
        s.total = total
        if s.paid is None:
            s.paid = 0
        s.status = "paid" if (s.paid or 0) >= total else "pending"
    db.commit()
    # Agar shu oy uchun allaqachon draft hujjat bor bo'lsa — yangilash
    existing_expense = db.query(ExpenseDocItem).join(ExpenseDoc).filter(
        ExpenseDocItem.description == f"Oylik to'lovi {year}-{month:02d}",
        ExpenseDoc.status == "draft",
    ).first()
    if existing_expense:
        ex_doc = db.query(ExpenseDoc).filter(ExpenseDoc.id == existing_expense.expense_doc_id).first()
        if ex_doc:
            ex_doc.total_amount = total_payroll
            existing_expense.amount = total_payroll
            db.commit()
        params = f"year={year}&month={month}&saved=1&expense_doc_id={ex_doc.id if ex_doc else ''}"
        if no_cash_warn:
            params += "&no_cash=1"
        return RedirectResponse(url=f"/employees/salary?{params}", status_code=303)

    if total_payroll > 0:
        cash = None
        if cash_register_id:
            cash = db.query(CashRegister).filter(CashRegister.id == int(cash_register_id), CashRegister.is_active == True).first()
        if not cash:
            cash = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.id).first()
        if not cash:
            no_cash_warn = True
        else:
            et = db.query(ExpenseType).filter(ExpenseType.is_active == True, ExpenseType.name.ilike("%ish haqqi%")).first()
            if not et:
                et = db.query(ExpenseType).filter(ExpenseType.is_active == True).order_by(ExpenseType.id).first()
            if not et:
                et = ExpenseType(name="ish haqqi", category="Ishlab chiqarish xarajatlari", is_active=True)
                db.add(et)
                db.flush()
            try:
                last_day = calendar.monthrange(year, month)[1]
                doc_date = datetime(year, month, last_day)
            except (ValueError, TypeError):
                doc_date = datetime.now()
            from app.routes.finance import _next_expense_doc_number
            doc_number = _next_expense_doc_number(db)
            doc = ExpenseDoc(
                number=doc_number,
                date=doc_date,
                cash_register_id=cash.id,
                direction_id=None,
                department_id=None,
                status="draft",
                total_amount=total_payroll,
                payment_id=None,
                user_id=current_user.id if current_user else None,
            )
            db.add(doc)
            db.flush()
            db.add(ExpenseDocItem(
                expense_doc_id=doc.id,
                expense_type_id=et.id,
                amount=total_payroll,
                description=f"Oylik to'lovi {year}-{month:02d}",
            ))
            expense_doc_id = doc.id
            db.commit()
    params = f"year={year}&month={month}&saved=1"
    if expense_doc_id:
        params += f"&expense_doc_id={expense_doc_id}"
    if no_cash_warn:
        params += "&no_cash=1"
    return RedirectResponse(url=f"/employees/salary?{params}", status_code=303)


@router.post("/salary/mark-paid/{employee_id}")
async def employee_salary_mark_paid(
    request: Request,
    employee_id: int,
    year: int = Form(...),
    month: int = Form(...),
    paid_amount: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Oylik to'langanligini belgilash"""
    s = db.query(Salary).filter(
        Salary.employee_id == employee_id,
        Salary.year == year,
        Salary.month == month,
    ).first()
    if not s:
        s = Salary(employee_id=employee_id, year=year, month=month, base_salary=0, total=0, paid=0)
        db.add(s)
    s.paid = paid_amount
    s.status = "paid" if paid_amount >= (s.total or 0) else "pending"
    db.commit()
    return RedirectResponse(url=f"/employees/salary?year={year}&month={month}", status_code=303)
