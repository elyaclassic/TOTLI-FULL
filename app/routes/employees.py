"""
Xodimlar — core CRUD va import/export.

Tier C1 bo'limi bo'yicha ajratilgan modullar:
- employees_dismissals.py   — ishdan bo'shatish hujjatlari
- employees_employment.py   — ishga qabul qilish va mehnat shartnomasi
- employees_attendance.py   — davomat (kunlik tabellar)
- employees_advances.py     — avans hujjatlari
- employees_salary.py       — oylik hisoblash
"""
import io
from datetime import datetime
from typing import Optional, List
from urllib.parse import quote

import openpyxl

from fastapi import APIRouter, Request, Depends, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db, User, Employee, Department, Position, PieceworkTask,
)
from app.deps import require_auth

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_class=HTMLResponse)
async def employees_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    show_dismissed: bool = False,
    birthday_today: bool = False,
):
    """Xodimlar ro'yxati — odatiy holda faqat faol xodimlar."""
    q = db.query(Employee).order_by(Employee.full_name)
    if not show_dismissed:
        q = q.filter(Employee.is_active == True)
    if birthday_today:
        # SQLite: tug'ilgan kunni oy-kun bo'yicha filtrlash
        try:
            md = datetime.now().strftime("%m-%d")
            q = q.filter(func.strftime("%m-%d", Employee.birth_date) == md)
        except Exception:
            pass
    employees = q.all()
    piecework_tasks = db.query(PieceworkTask).filter(PieceworkTask.is_active == True).order_by(PieceworkTask.name).all()
    departments = db.query(Department).filter(Department.is_active == True).order_by(Department.name).all()
    positions = db.query(Position).filter(Position.is_active == True).order_by(Position.name).all()
    return templates.TemplateResponse("employees/list.html", {
        "request": request,
        "employees": employees,
        "piecework_tasks": piecework_tasks,
        "departments": departments,
        "positions": positions,
        "current_user": current_user,
        "page_title": "Xodimlar",
        "show_dismissed": show_dismissed,
        "birthday_today": birthday_today,
    })


@router.post("/add")
async def employee_add(
    request: Request,
    full_name: str = Form(...),
    code: str = Form(""),
    position: str = Form(""),
    department: str = Form(""),
    phone: str = Form(""),
    salary: float = Form(0),
    salary_type: str = Form(""),
    piecework_task_ids: List[int] = Form([]),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodim qo'shish. Kod bo'sh qolsa saqlashda avtomatik yaratiladi (EMP-<id>)."""
    if salary < 0:
        raise HTTPException(status_code=400, detail="Maosh manfiy bo'lishi mumkin emas")
    import uuid
    code_val = (code or "").strip()
    if not code_val:
        code_val = f"_auto_{uuid.uuid4().hex[:12]}"
    st = (salary_type or "").strip() or None
    if st and st not in ("oylik", "soatlik", "bo'lak", "bo'lak_oylik"):
        st = None
    task_ids = [int(x) for x in (piecework_task_ids or []) if str(x).strip().isdigit()]
    task_ids = list(dict.fromkeys(task_ids))
    employee = Employee(
        full_name=full_name,
        code=code_val,
        position=position,
        department=department,
        phone=phone,
        salary=salary,
        salary_type=st,
        piecework_task_id=task_ids[0] if task_ids else None,  # legacy
    )
    db.add(employee)
    db.flush()
    if not (code or "").strip():
        employee.code = f"EMP-{employee.id}"
    if st in ("bo'lak", "bo'lak_oylik") and task_ids:
        tasks = db.query(PieceworkTask).filter(PieceworkTask.id.in_(task_ids)).all()
        employee.piecework_tasks = tasks
    db.commit()
    return RedirectResponse(url="", status_code=303)


@router.get("/edit/{employee_id}", response_class=HTMLResponse)
async def employee_edit_page(
    request: Request,
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodim tahrirlash sahifasi"""
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=Xodim topilmadi", status_code=303)
    piecework_tasks = db.query(PieceworkTask).filter(PieceworkTask.is_active == True).order_by(PieceworkTask.name).all()
    return templates.TemplateResponse("employees/edit.html", {
        "request": request,
        "emp": emp,
        "piecework_tasks": piecework_tasks,
        "current_user": current_user,
        "page_title": "Xodimni tahrirlash"
    })


@router.post("/update/{employee_id}")
async def employee_update(
    employee_id: int,
    full_name: str = Form(...),
    code: str = Form(""),
    position: str = Form(""),
    department: str = Form(""),
    phone: str = Form(""),
    salary: float = Form(0),
    salary_type: str = Form(""),
    monthly_rest_days: int = Form(4),
    piecework_task_ids: List[int] = Form([]),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodim ma'lumotlarini yangilash. Kod bo'sh qolsa avtomatik EMP-<id> qo'yiladi."""
    if salary < 0:
        raise HTTPException(status_code=400, detail="Maosh manfiy bo'lishi mumkin emas")
    from urllib.parse import quote
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=Xodim topilmadi", status_code=303)
    code_val = (code or "").strip() or f"EMP-{employee_id}"
    duplicate = db.query(Employee).filter(Employee.code == code_val, Employee.id != employee_id).first()
    if duplicate:
        return RedirectResponse(url="/employees?error=" + quote("Bunday kod boshqa xodimda mavjud: " + code_val), status_code=303)
    emp.full_name = full_name
    emp.code = code_val
    emp.position = position
    emp.department = department
    emp.phone = phone
    emp.salary = salary
    st = (salary_type or "").strip() or None
    if st and st not in ("oylik", "soatlik", "bo'lak", "bo'lak_oylik"):
        st = None
    emp.salary_type = st
    if monthly_rest_days is not None and 0 <= monthly_rest_days <= 15:
        emp.monthly_rest_days = int(monthly_rest_days)
    task_ids = [int(x) for x in (piecework_task_ids or []) if str(x).strip().isdigit()]
    task_ids = list(dict.fromkeys(task_ids))
    emp.piecework_task_id = task_ids[0] if task_ids else None  # legacy
    if st in ("bo'lak", "bo'lak_oylik") and task_ids:
        tasks = db.query(PieceworkTask).filter(PieceworkTask.id.in_(task_ids)).all()
        emp.piecework_tasks = tasks
    else:
        emp.piecework_tasks = []
    db.commit()
    return RedirectResponse(url="/employees?updated=1", status_code=303)


@router.post("/delete/{employee_id}")
async def employee_delete(
    employee_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodimni o'chirish. Bog'liq hujjatlar bo'lsa (ishga qabul, avans, oylik, davomat va h.k.) DB xatolik beradi — foydalanuvchiga xabar."""
    from urllib.parse import quote
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=Xodim topilmadi", status_code=303)
    try:
        db.delete(emp)
        db.commit()
        return RedirectResponse(url="/employees?deleted=1", status_code=303)
    except IntegrityError:
        db.rollback()
        return RedirectResponse(
            url="/employees?error=" + quote(
                "Xodimni o'chirib bo'lmaydi: unga bog'liq yozuvlar mavjud (ishga qabul hujjati, avans, oylik, davomat va h.k.). "
                "Xodimni o'chirmasdan «Faol emas» deb belgilang yoki avval bog'liq hujjatlarni olib tashlang."
            ),
            status_code=303,
        )


# ==========================================
# EMPLOYEES EXCEL OPERATIONS + HIKVISION IMPORT
# ==========================================
@router.get("/export")
async def export_employees(db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    employees = db.query(Employee).all()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Employees"
    ws.append(["ID", "Kod", "F.I.SH", "Lavozim", "Bo'lim", "Telefon", "Oylik"])
    for e in employees:
        ws.append([e.id, e.code, e.full_name, e.position, e.department, e.phone, e.salary])
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=xodimlar.xlsx"})

@router.get("/template")
async def template_employees():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Template"
    ws.append(["Kod", "F.I.SH", "Lavozim", "Bo'lim", "Telefon", "Oylik"])
    ws.append(["X001", "Aliyev Vali", "Ishchi", "Ishlab chiqarish", "+998901234567", 3000000])
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=xodim_andoza.xlsx"})

@router.post("/import")
async def import_employees(file: UploadFile = File(...), db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents))
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    for row in rows:
        if not row[0]: continue
        code, full_name, position, department, phone, salary = row[0:6]
        employee = db.query(Employee).filter(Employee.code == code).first()
        if not employee:
            employee = Employee(
                code=code, 
                full_name=full_name, 
                position=position, 
                department=department, 
                phone=phone, 
                salary=salary
            )
            db.add(employee)
        else:
            employee.full_name = full_name
            employee.position = position
            employee.department = department
            employee.phone = phone
            employee.salary = salary
        db.commit()
    return RedirectResponse(url="", status_code=303)


@router.post("/import-from-hikvision-preview")
async def employees_import_from_hikvision_preview(
    request: Request,
    hikvision_host: str = Form(...),
    hikvision_port: str = Form("443"),
    hikvision_username: str = Form("admin"),
    hikvision_password: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hikvision ulanishi va yuklanadigan shaxslar ro'yxatini ko'rsatadi; tanlanganlarni keyin yuklash mumkin."""
    from urllib.parse import quote
    try:
        port = int((hikvision_port or "").strip() or "443")
    except (ValueError, TypeError):
        port = 443
    try:
        from app.utils.hikvision import HikvisionAPI
        api = HikvisionAPI(
            host=(hikvision_host or "").strip(),
            port=port,
            username=(hikvision_username or "admin").strip(),
            password=(hikvision_password or ""),
        )
        if not api.test_connection():
            return RedirectResponse(
                url="/employees?error=" + quote(api._last_error or "Qurilma bilan bog'lanib bo'lmadi."),
                status_code=303
            )
        persons = api.get_person_list()
    except Exception as e:
        return RedirectResponse(url="/employees?error=" + quote("Hikvision bilan bog'lashda xatolik"), status_code=303)
    return templates.TemplateResponse("employees/hikvision_import_preview.html", {
        "request": request,
        "persons": persons or [],
        "hikvision_host": (hikvision_host or "").strip(),
        "hikvision_port": str(port),
        "hikvision_username": (hikvision_username or "admin").strip(),
        "hikvision_password": hikvision_password or "",
        "current_user": current_user,
        "page_title": "Hikvision — xodimlarni tanlash"
    })


@router.get("/import-from-hikvision-preview", response_class=HTMLResponse)
async def employees_import_from_hikvision_preview_get(
    request: Request,
    current_user: User = Depends(require_auth),
):
    """Preview sahifasiga to'g'ridan-to'g'ri kirilsa xodimlar ro'yxatiga yo'naltiradi."""
    return RedirectResponse(url="", status_code=303)


@router.post("/import-from-hikvision")
async def employees_import_from_hikvision(
    hikvision_host: str = Form(...),
    hikvision_port: str = Form("443"),
    hikvision_username: str = Form("admin"),
    hikvision_password: str = Form(""),
    employee_no: Optional[List[str]] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hikvision qurilmasidan tanlangan (yoki barcha) xodimlarni Employee jadvaliga qo'shadi."""
    from urllib.parse import quote
    try:
        port = int((hikvision_port or "").strip() or "443")
    except (ValueError, TypeError):
        port = 443
    employee_nos = employee_no if isinstance(employee_no, list) and employee_no else None
    try:
        from app.utils.hikvision import import_employees_from_hikvision
        result = import_employees_from_hikvision(
            (hikvision_host or "").strip(),
            port,
            (hikvision_username or "admin").strip(),
            (hikvision_password or ""),
            db,
            employee_nos=employee_nos,
        )
        err_list = result.get("errors") or []
        imported = result.get("imported", 0)
        updated = result.get("updated", 0)
        if err_list:
            msg = f"Qo'shildi: {imported}, yangilandi: {updated}. Xato: {len(err_list)} ta."
            return RedirectResponse(url="/employees?warning=" + quote(msg), status_code=303)
        msg = f"Qo'shildi: {imported}, yangilandi: {updated}."
        return RedirectResponse(url="/employees?imported=1&msg=" + quote(msg), status_code=303)
    except Exception:
        return RedirectResponse(url="/employees?error=" + quote("Hikvision import xatoligi"), status_code=303)


