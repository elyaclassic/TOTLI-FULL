"""Kadr o'zgarishi buyruqlari (EmployeeChangeDoc) — list, new, create, confirm, cancel."""
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, Employee, EmployeeChangeDoc, EmploymentDoc, User
from app.deps import require_auth
from app.services.employee_salary_service import get_effective_salary

router = APIRouter(prefix="/employees", tags=["employee-changes"])

_ALLOWED = ("admin", "manager", "menejer", "rahbar", "raxbar")


def _can(user):
    return user and (getattr(user, "role", None) or "").strip().lower() in _ALLOWED


@router.get("/changes", response_class=HTMLResponse)
async def changes_list(request: Request, employee_id: int = None,
                       db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    q = db.query(EmployeeChangeDoc).order_by(EmployeeChangeDoc.doc_date.desc(), EmployeeChangeDoc.id.desc())
    if employee_id:
        q = q.filter(EmployeeChangeDoc.employee_id == employee_id)
    docs = q.limit(500).all()
    emp_map = {e.id: e for e in db.query(Employee).all()}
    return templates.TemplateResponse("employees/changes_list.html", {
        "request": request, "docs": docs, "emp_map": emp_map,
        "selected_employee_id": employee_id, "current_user": current_user,
        "page_title": "Kadr o'zgarishlari",
    })


@router.get("/change/new", response_class=HTMLResponse)
async def change_new_page(request: Request, employee_id: int,
                          db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _can(current_user):
        return RedirectResponse(url="/employees?error=" + quote("Ruxsat yo'q"), status_code=303)
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=" + quote("Xodim topilmadi"), status_code=303)
    cur_salary, cur_type = get_effective_salary(db, emp.id, datetime.now().date())
    return templates.TemplateResponse("employees/change_form.html", {
        "request": request, "emp": emp, "cur_salary": cur_salary, "cur_type": cur_type,
        "today": datetime.now().date().isoformat(), "current_user": current_user,
        "page_title": "Yangi kadr o'zgarishi",
    })


@router.post("/change/create")
async def change_create(
    request: Request,
    employee_id: int = Form(...),
    doc_date: str = Form(...),
    effective_date: str = Form(...),
    change_salary: int = Form(0),
    new_salary: float = Form(0),
    change_salary_type: int = Form(0),
    new_salary_type: str = Form(""),
    change_position: int = Form(0),
    new_position: str = Form(""),
    change_department: int = Form(0),
    new_department: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if not _can(current_user):
        return RedirectResponse(url="/employees?error=" + quote("Ruxsat yo'q"), status_code=303)
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=" + quote("Xodim topilmadi"), status_code=303)
    try:
        doc_d = datetime.strptime(doc_date, "%Y-%m-%d").date()
        eff_d = datetime.strptime(effective_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=f"/employees/change/new?employee_id={employee_id}&error=" + quote("Noto'g'ri sana"), status_code=303)
    if not (change_salary or change_salary_type or change_position or change_department):
        return RedirectResponse(url=f"/employees/change/new?employee_id={employee_id}&error=" + quote("Kamida bitta o'zgarish belgilang"), status_code=303)

    cur_salary, cur_type = get_effective_salary(db, emp.id, datetime.now().date())
    count = db.query(EmployeeChangeDoc).filter(
        EmployeeChangeDoc.number.like(f"KO-{doc_d.strftime('%Y%m%d')}-%")
    ).count()
    number = f"KO-{doc_d.strftime('%Y%m%d')}-{count + 1:04d}"

    doc = EmployeeChangeDoc(
        number=number, employee_id=emp.id, doc_date=doc_d, effective_date=eff_d,
        change_salary=bool(change_salary), old_salary=cur_salary if change_salary else None,
        new_salary=float(new_salary) if change_salary else None,
        change_salary_type=bool(change_salary_type), old_salary_type=cur_type if change_salary_type else None,
        new_salary_type=(new_salary_type or None) if change_salary_type else None,
        change_position=bool(change_position), old_position=emp.position if change_position else None,
        new_position=(new_position or None) if change_position else None,
        change_department=bool(change_department), old_department=emp.department if change_department else None,
        new_department=(new_department or None) if change_department else None,
        reason=(reason or None), user_id=current_user.id if current_user else None,
        status="draft",
    )
    db.add(doc)
    db.commit()
    return RedirectResponse(url=f"/employees/changes?employee_id={employee_id}&created=1", status_code=303)


def _refresh_employee_current(db, emp):
    """Employee.salary/position/department keshini bugungi effective holatga keltiradi."""
    today = datetime.now().date()
    sal, st = get_effective_salary(db, emp.id, today)
    emp.salary = sal
    if st:
        emp.salary_type = st
    last = (
        db.query(EmployeeChangeDoc)
        .filter(EmployeeChangeDoc.employee_id == emp.id,
                EmployeeChangeDoc.status == "confirmed",
                EmployeeChangeDoc.effective_date <= today)
        .order_by(EmployeeChangeDoc.effective_date.desc(), EmployeeChangeDoc.id.desc())
        .all()
    )
    pos_set = dep_set = False
    for ch in last:
        if not pos_set and ch.change_position and ch.new_position:
            emp.position = ch.new_position; pos_set = True
        if not dep_set and ch.change_department and ch.new_department:
            emp.department = ch.new_department; dep_set = True
        if pos_set and dep_set:
            break
    # Hech qaysi tasdiqlangan change position/dept bermasa — hire hujjatiga qaytadi
    # (bekor qilingandan keyin kesh stale qolmasin; tarix bilan kelishadi).
    if not pos_set or not dep_set:
        hire = (
            db.query(EmploymentDoc)
            .filter(EmploymentDoc.employee_id == emp.id, EmploymentDoc.confirmed_at.isnot(None))
            .order_by(EmploymentDoc.doc_date.desc(), EmploymentDoc.id.desc())
            .first()
        )
        if hire:
            if not pos_set and hire.position:
                emp.position = hire.position
            if not dep_set and hire.department:
                emp.department = hire.department


@router.post("/change/{doc_id}/confirm")
async def change_confirm(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _can(current_user):
        return RedirectResponse(url="/employees/changes?error=" + quote("Ruxsat yo'q"), status_code=303)
    doc = db.query(EmployeeChangeDoc).filter(EmployeeChangeDoc.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/employees/changes?error=" + quote("Hujjat topilmadi"), status_code=303)
    if doc.status == "confirmed":
        return RedirectResponse(url=f"/employees/changes?employee_id={doc.employee_id}", status_code=303)
    doc.status = "confirmed"
    doc.confirmed_at = datetime.now()
    db.flush()
    emp = db.query(Employee).filter(Employee.id == doc.employee_id).first()
    if emp:
        _refresh_employee_current(db, emp)
    db.commit()
    return RedirectResponse(url=f"/employees/changes?employee_id={doc.employee_id}&confirmed=1", status_code=303)


@router.post("/change/{doc_id}/cancel")
async def change_cancel(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _can(current_user):
        return RedirectResponse(url="/employees/changes?error=" + quote("Ruxsat yo'q"), status_code=303)
    doc = db.query(EmployeeChangeDoc).filter(EmployeeChangeDoc.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/employees/changes?error=" + quote("Hujjat topilmadi"), status_code=303)
    doc.status = "cancelled"
    doc.confirmed_at = None
    db.flush()
    emp = db.query(Employee).filter(Employee.id == doc.employee_id).first()
    if emp:
        _refresh_employee_current(db, emp)
    db.commit()
    return RedirectResponse(url=f"/employees/changes?employee_id={doc.employee_id}&cancelled=1", status_code=303)
