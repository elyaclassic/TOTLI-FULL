"""
Xodimlar — davomat (kunlik tabellar) (Tier C1 3-bosqich).

Manba: employees.py:1080-1731 (~652 qator) dan ajratib olindi.
MUHIM: Ko'chirish paytida eski bug tuzatildi — redirect URL'lar endi
to'liq prefix bilan (`/employees/attendance/...` o'rniga `/attendance/...`).
"""
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import (
    get_db,
    User,
    Employee,
    Attendance,
    AttendanceDoc,
)
from app.deps import require_auth, require_admin

router = APIRouter(prefix="/employees", tags=["employees-attendance"])


def _parse_time(s: str):
    """'09:00' yoki '09:00:00' dan time object qaytaradi, bo'sh bo'lsa None."""
    if not s or not str(s).strip():
        return None
    s = str(s).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(s, fmt).time()
            return t
        except ValueError:
            continue
    return None


@router.get("/attendance", response_class=HTMLResponse)
async def attendance_docs_list(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kunlik tabel hujjatlari ro'yxati — saralash: number, date, count, confirmed_at"""
    today = date.today()
    start_date = start_date or (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = end_date or today.strftime("%Y-%m-%d")
    sort = (sort or "date").strip().lower()
    order = (order or "asc").strip().lower()
    if order not in ("asc", "desc"):
        order = "asc"
    query = (
        db.query(AttendanceDoc)
        .filter(AttendanceDoc.date >= start_date, AttendanceDoc.date <= end_date)
    )
    if sort == "number":
        query = query.order_by(AttendanceDoc.number.desc() if order == "desc" else AttendanceDoc.number.asc())
    elif sort == "date":
        query = query.order_by(AttendanceDoc.date.desc() if order == "desc" else AttendanceDoc.date.asc())
    elif sort == "confirmed_at":
        query = query.order_by(
            AttendanceDoc.confirmed_at.desc() if order == "desc" else AttendanceDoc.confirmed_at.asc()
        )
    else:
        query = query.order_by(AttendanceDoc.date.desc())
    docs = query.all()
    count_by_doc = {}
    for doc in docs:
        count_by_doc[doc.id] = db.query(Attendance).filter(Attendance.date == doc.date).count()
    if sort == "count":
        reverse = order == "desc"
        docs = sorted(docs, key=lambda d: count_by_doc.get(d.id, 0), reverse=reverse)
    return templates.TemplateResponse("employees/attendance_docs_list.html", {
        "request": request,
        "docs": docs,
        "count_by_doc": count_by_doc,
        "start_date": start_date,
        "end_date": end_date,
        "sort": sort,
        "order": order,
        "current_user": current_user,
        "page_title": "Kunlik tabellar",
    })


@router.get("/attendance/form", response_class=HTMLResponse)
async def attendance_form(
    request: Request,
    date_param: Optional[str] = Query(None, alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tabel formasi — sana tanlash, shu kundagi yozuvlar, Hikvision yuklash."""
    today = date.today()
    form_date_str = (date_param or "").strip() or today.strftime("%Y-%m-%d")
    try:
        form_date = datetime.strptime(form_date_str, "%Y-%m-%d").date()
    except ValueError:
        form_date = today
        form_date_str = form_date.strftime("%Y-%m-%d")
    attendances = (
        db.query(Attendance)
        .filter(Attendance.date == form_date)
        .order_by(Attendance.employee_id)
        .all()
    )
    attendance_by_employee = {a.employee_id: a for a in attendances}
    employees_active = (
        db.query(Employee)
        .filter(Employee.is_active == True)
        .order_by(Employee.full_name)
        .all()
    )
    employee_ids_in_rows = {e.id for e in employees_active}
    attendance_rows = [{"employee": e, "attendance": attendance_by_employee.get(e.id)} for e in employees_active]
    for att in attendances:
        if att.employee_id not in employee_ids_in_rows:
            emp = db.query(Employee).filter(Employee.id == att.employee_id).first()
            if emp:
                attendance_rows.append({"employee": emp, "attendance": att})
                employee_ids_in_rows.add(emp.id)
    doc = db.query(AttendanceDoc).filter(AttendanceDoc.date == form_date).first()
    return templates.TemplateResponse("employees/attendance_form.html", {
        "request": request,
        "form_date": form_date,
        "form_date_str": form_date_str,
        "attendances": attendances,
        "attendance_rows": attendance_rows,
        "doc": doc,
        "current_user": current_user,
        "page_title": "Tabel formasi",
    })


@router.post("/attendance/sync-hikvision")
async def attendance_sync_hikvision(
    request: Request,
    start_date: str = Form(...),
    end_date: str = Form(...),
    hikvision_host: str = Form(...),
    hikvision_port: str = Form("443"),
    hikvision_username: str = Form("admin"),
    hikvision_password: str = Form(""),
    redirect_url: str = Form("/employees/attendance/form"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hikvision'dan davomat yuklash"""
    sep = "&" if "?" in (redirect_url or "") else "?"
    base_redirect = (redirect_url or "/employees/attendance/form").strip()
    try:
        start_d = datetime.strptime((start_date or "").strip(), "%Y-%m-%d").date()
        end_d = datetime.strptime((end_date or "").strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return RedirectResponse(url=base_redirect + sep + "error=" + quote("Noto'g'ri sana"), status_code=303)
    try:
        port = int(hikvision_port.strip() or "443")
    except (ValueError, TypeError):
        port = 443
    try:
        from app.utils.hikvision import sync_hikvision_attendance
        result = sync_hikvision_attendance(
            (hikvision_host or "").strip(),
            port,
            (hikvision_username or "admin").strip(),
            (hikvision_password or ""),
            start_d,
            end_d,
            db,
        )
        err_list = result.get("errors") or []
        events_count = result.get("events_count", 0)
        imported = result.get("imported", 0)
        msg = f"Hodisa: {events_count} ta, yuklangan: {imported} ta. Xato: {len(err_list)} ta."
        return RedirectResponse(url=base_redirect + sep + "synced=1&msg=" + quote(msg), status_code=303)
    except Exception:
        return RedirectResponse(url=base_redirect + sep + "error=" + quote("Hikvision yuklash xatoligi"), status_code=303)


@router.post("/attendance/form/bulk-time")
async def attendance_form_bulk_time(
    request: Request,
    date_param: str = Form(..., alias="date"),
    check_in_time: str = Form("09:00"),
    check_out_time: str = Form("18:00"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Barcha faol xodimlarga tanlangan kun uchun Keldi/Ketdi/Soat yuklash."""
    try:
        doc_date = datetime.strptime(date_param.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return RedirectResponse(url="/employees/attendance/form?error=" + quote("Noto'g'ri sana"), status_code=303)
    t_in = _parse_time((check_in_time or "09:00").strip())
    t_out = _parse_time((check_out_time or "18:00").strip())
    if not t_in:
        t_in = datetime.strptime("09:00", "%H:%M").time()
    if not t_out:
        t_out = datetime.strptime("18:00", "%H:%M").time()
    check_in_dt = datetime.combine(doc_date, t_in)
    check_out_dt = datetime.combine(doc_date, t_out)
    delta = check_out_dt - check_in_dt
    if delta.total_seconds() < 0:
        delta += timedelta(days=1)
    raw_hours = delta.total_seconds() / 3600
    if raw_hours >= 6:
        raw_hours -= 1.0
    hours_worked = round(raw_hours, 2)
    form = await request.form()
    employee_ids_param = form.getlist("employee_ids")
    if employee_ids_param:
        try:
            emp_ids = [int(x) for x in employee_ids_param if str(x).strip().isdigit()]
        except (ValueError, TypeError):
            emp_ids = []
        employees = db.query(Employee).filter(Employee.id.in_(emp_ids), Employee.is_active == True).all() if emp_ids else []
    else:
        employees = db.query(Employee).filter(Employee.is_active == True).all()
    saved = 0
    for emp in employees:
        att = db.query(Attendance).filter(Attendance.employee_id == emp.id, Attendance.date == doc_date).first()
        if not att:
            att = Attendance(employee_id=emp.id, date=doc_date)
            db.add(att)
        att.check_in = check_in_dt
        att.check_out = check_out_dt
        att.hours_worked = hours_worked
        att.status = "present"
        saved += 1
    db.commit()
    msg = f"{saved} ta xodimga vaqt yuklandi (Keldi {check_in_time or '09:00'}, Ketdi {check_out_time or '18:00'})."
    return RedirectResponse(
        url=f"/employees/attendance/form?date={doc_date.strftime('%Y-%m-%d')}&saved={saved}&msg=" + quote(msg),
        status_code=303,
    )


@router.post("/attendance/form/save")
async def attendance_form_save(
    request: Request,
    date_param: str = Form(..., alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tabelni qo'lda to'ldirish."""
    try:
        doc_date = datetime.strptime(date_param.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return RedirectResponse(url="/employees/attendance/form?error=" + quote("Noto'g'ri sana"), status_code=303)
    form = await request.form()
    employee_ids = form.getlist("employee_id")
    saved = 0
    for i, emp_id_str in enumerate(employee_ids):
        try:
            emp_id = int(emp_id_str)
        except (ValueError, TypeError):
            continue
        emp = db.query(Employee).filter(Employee.id == emp_id).first()
        if not emp:
            continue
        check_in_str = (form.get(f"check_in_{emp_id}") or "").strip()
        check_out_str = (form.get(f"check_out_{emp_id}") or "").strip()
        hours_str = (form.get(f"hours_{emp_id}") or "").strip().replace(",", ".")
        status_val = (form.get(f"status_{emp_id}") or "").strip() or "present"
        note_val = (form.get(f"note_{emp_id}") or "").strip() or None
        if status_val not in ("present", "absent", "leave", "kasallik", "tatil", "mehnat_safari"):
            status_val = "present"
        if not check_in_str and not check_out_str:
            status_val = "absent"
        try:
            hours_worked = float(hours_str) if hours_str else None
            if hours_worked is not None and hours_worked < 0:
                hours_worked = 0
        except ValueError:
            hours_worked = None
        check_in_time = _parse_time(check_in_str)
        check_out_time = _parse_time(check_out_str)
        check_in_dt = datetime.combine(doc_date, check_in_time) if check_in_time else None
        check_out_dt = datetime.combine(doc_date, check_out_time) if check_out_time else None
        if hours_worked is None and check_in_dt and check_out_dt:
            delta = check_out_dt - check_in_dt
            if delta.total_seconds() < 0:
                delta += timedelta(days=1)
            if delta.total_seconds() > 16 * 3600:
                hours_worked = 0
            else:
                raw_hours = delta.total_seconds() / 3600
                if raw_hours >= 6:
                    raw_hours -= 1.0
                hours_worked = round(raw_hours, 2)
        att = db.query(Attendance).filter(Attendance.employee_id == emp_id, Attendance.date == doc_date).first()
        if not att:
            att = Attendance(employee_id=emp_id, date=doc_date)
            db.add(att)
        att.check_in = check_in_dt
        att.check_out = check_out_dt
        att.hours_worked = hours_worked if hours_worked is not None else (att.hours_worked if att.hours_worked is not None else 0)
        att.status = status_val
        att.note = note_val
        saved += 1
    db.commit()
    return RedirectResponse(
        url=f"/employees/attendance/form?date={doc_date.strftime('%Y-%m-%d')}&saved={saved}&msg=" + quote("Tabel qo'lda saqlandi."),
        status_code=303,
    )


@router.post("/attendance/form/confirm")
async def attendance_form_confirm(
    request: Request,
    date_param: str = Form(..., alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Kunni tasdiqlash — AttendanceDoc yaratiladi"""
    try:
        doc_date = datetime.strptime(date_param, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url="/employees/attendance/form?error=Noto'g'ri sana", status_code=303)
    existing = db.query(AttendanceDoc).filter(AttendanceDoc.date == doc_date).first()
    if existing:
        if existing.confirmed_at:
            return RedirectResponse(url="/employees/attendance?already=1", status_code=303)
        existing.confirmed_at = datetime.now()
        existing.user_id = current_user.id
        db.commit()
        return RedirectResponse(url="/employees/attendance?confirmed=1", status_code=303)
    count = db.query(AttendanceDoc).filter(AttendanceDoc.date >= doc_date.replace(day=1)).count()
    number = f"TBL-{doc_date.strftime('%Y%m%d')}-{count + 1:04d}"
    doc = AttendanceDoc(number=number, date=doc_date, user_id=current_user.id, confirmed_at=datetime.now())
    db.add(doc)
    db.flush()
    db.query(Attendance).filter(Attendance.date == doc_date).update({"doc_id": doc.id})
    db.commit()
    return RedirectResponse(url="/employees/attendance?confirmed=1", status_code=303)


@router.get("/attendance/doc/{doc_id}", response_class=HTMLResponse)
async def attendance_doc_view(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kunlik tabel hujjati ko'rinishi"""
    doc = db.query(AttendanceDoc).filter(AttendanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    rows = db.query(Attendance).filter(Attendance.date == doc.date).order_by(Attendance.employee_id).all()
    return templates.TemplateResponse("employees/attendance_doc.html", {
        "request": request,
        "doc": doc,
        "rows": rows,
        "current_user": current_user,
        "page_title": f"Tabel {doc.number}",
    })


@router.get("/attendance/records", response_class=HTMLResponse)
async def attendance_records(
    request: Request,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Barcha davomat yozuvlari (sana oralig'i) — qo'lda qo'shish/tahrirlash"""
    today = date.today()
    start_date = start_date or (today - timedelta(days=7)).strftime("%Y-%m-%d")
    end_date = end_date or today.strftime("%Y-%m-%d")
    records = (
        db.query(Attendance)
        .filter(Attendance.date >= start_date, Attendance.date <= end_date)
        .order_by(Attendance.date.desc(), Attendance.employee_id)
        .all()
    )
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    return templates.TemplateResponse("employees/attendance_records.html", {
        "request": request,
        "records": records,
        "employees": employees,
        "start_date": start_date,
        "end_date": end_date,
        "current_user": current_user,
        "page_title": "Davomat yozuvlari",
    })


@router.post("/attendance/doc/{doc_id}/delete")
async def attendance_doc_delete(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tabel hujjatini o'chirish (davomat yozuvlari saqlanadi)."""
    doc = db.query(AttendanceDoc).filter(AttendanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    db.delete(doc)
    db.commit()
    return RedirectResponse(url="/employees/attendance?deleted=1", status_code=303)


@router.post("/attendance/doc/{doc_id}/cancel-confirm")
async def attendance_doc_cancel_confirm(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tasdiqlashni bekor qilish"""
    doc = db.query(AttendanceDoc).filter(AttendanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    doc.confirmed_at = None
    db.commit()
    return RedirectResponse(url="/employees/attendance?unconfirmed=1", status_code=303)


@router.post("/attendance/records/add")
async def attendance_record_add(
    request: Request,
    employee_id: int = Form(...),
    att_date: str = Form(...),
    check_in: Optional[str] = Form(None),
    check_out: Optional[str] = Form(None),
    hours_worked: float = Form(0),
    note: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Davomat yozuvi qo'shish (qo'lda)"""
    try:
        att_d = datetime.strptime(att_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&error=Noto'g'ri sana", status_code=303)
    check_in_dt = None
    if check_in:
        try:
            check_in_dt = datetime.strptime(f"{att_date} {check_in}", "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    check_out_dt = None
    if check_out:
        try:
            check_out_dt = datetime.strptime(f"{att_date} {check_out}", "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    att = Attendance(
        employee_id=employee_id,
        date=att_d,
        check_in=check_in_dt,
        check_out=check_out_dt,
        hours_worked=hours_worked or 0,
        status="present",
        note=note or None,
    )
    db.add(att)
    db.commit()
    return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&added=1", status_code=303)


@router.get("/attendance/records/edit/{record_id}", response_class=HTMLResponse)
async def attendance_record_edit_page(
    request: Request,
    record_id: int,
    start_date: str = Query(""),
    end_date: str = Query(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Davomat yozuvini tahrirlash sahifasi"""
    att = db.query(Attendance).filter(Attendance.id == record_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    return templates.TemplateResponse("employees/attendance_record_edit.html", {
        "request": request,
        "record": att,
        "start_date": start_date or att.date.strftime("%Y-%m-%d"),
        "end_date": end_date or att.date.strftime("%Y-%m-%d"),
        "current_user": current_user,
        "page_title": "Davomat yozuvini tahrirlash",
    })


@router.post("/attendance/records/edit/{record_id}")
async def attendance_record_edit_save(
    record_id: int,
    check_in: Optional[str] = Form(None),
    check_out: Optional[str] = Form(None),
    hours_worked: float = Form(None),
    status: str = Form("present"),
    note: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Davomat yozuvini saqlash"""
    att = db.query(Attendance).filter(Attendance.id == record_id).first()
    if not att:
        raise HTTPException(status_code=404, detail="Yozuv topilmadi")
    att_date_str = att.date.strftime("%Y-%m-%d")
    check_in_dt = None
    if check_in and str(check_in).strip():
        try:
            check_in_dt = datetime.strptime(f"{att_date_str} {check_in.strip()}", "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    check_out_dt = None
    if check_out and str(check_out).strip():
        try:
            check_out_dt = datetime.strptime(f"{att_date_str} {check_out.strip()}", "%Y-%m-%d %H:%M")
        except ValueError:
            pass
    att.check_in = check_in_dt
    att.check_out = check_out_dt
    if hours_worked is not None:
        att.hours_worked = max(0, float(hours_worked))
    elif check_in_dt and check_out_dt:
        delta = check_out_dt - check_in_dt
        if delta.total_seconds() < 0:
            delta += timedelta(days=1)
        if delta.total_seconds() > 16 * 3600:
            att.hours_worked = 0
        else:
            raw_hours = delta.total_seconds() / 3600
            if raw_hours >= 6:
                raw_hours -= 1.0
            att.hours_worked = round(raw_hours, 2)
    if status in ("present", "absent", "leave", "kasallik", "tatil", "mehnat_safari"):
        att.status = status
    att.note = (note or "").strip() or None
    db.commit()
    return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&updated=1", status_code=303)


@router.post("/attendance/records/bulk-time")
async def attendance_records_bulk_time(
    request: Request,
    start_date: str = Form(""),
    end_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan yozuvlarga Keldi 9:00, Ketdi 18:00, Soat 9 qo'llash"""
    form = await request.form()
    record_ids_raw = form.getlist("record_ids")
    try:
        record_ids = [int(x) for x in record_ids_raw if str(x).strip().isdigit()]
    except (ValueError, TypeError):
        record_ids = []
    if not record_ids:
        return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&error=" + quote("Hech qanday yozuv tanlanmagan"), status_code=303)
    check_in_dt = datetime.strptime("09:00", "%H:%M").time()
    check_out_dt = datetime.strptime("18:00", "%H:%M").time()
    hours_worked = 9.0
    updated = 0
    for rid in record_ids:
        att = db.query(Attendance).filter(Attendance.id == rid).first()
        if not att:
            continue
        att.check_in = datetime.combine(att.date, check_in_dt)
        att.check_out = datetime.combine(att.date, check_out_dt)
        att.hours_worked = hours_worked
        att.status = "present"
        updated += 1
    db.commit()
    return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&updated={updated}&msg=" + quote("Vaqt yuklandi (9:00–18:00)."), status_code=303)


@router.post("/attendance/records/bulk-time-all")
async def attendance_records_bulk_time_all(
    start_date: str = Form(...),
    end_date: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan sana oralig'idagi har bir kun uchun barcha faol xodimlarga 9:00-18:00 yuklash."""
    try:
        d_start = datetime.strptime(start_date.strip()[:10], "%Y-%m-%d").date()
        d_end = datetime.strptime(end_date.strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return RedirectResponse(url=f"/employees/attendance/records?error=" + quote("Noto'g'ri sana"), status_code=303)
    if d_end < d_start:
        d_end = d_start
    check_in_t = datetime.strptime("09:00", "%H:%M").time()
    check_out_t = datetime.strptime("18:00", "%H:%M").time()
    hours_worked = 9.0
    employees = db.query(Employee).filter(Employee.is_active == True).all()
    saved = 0
    d = d_start
    while d <= d_end:
        check_in_dt = datetime.combine(d, check_in_t)
        check_out_dt = datetime.combine(d, check_out_t)
        for emp in employees:
            att = db.query(Attendance).filter(Attendance.employee_id == emp.id, Attendance.date == d).first()
            if not att:
                att = Attendance(employee_id=emp.id, date=d)
                db.add(att)
            att.check_in = check_in_dt
            att.check_out = check_out_dt
            att.hours_worked = hours_worked
            att.status = "present"
            saved += 1
        d += timedelta(days=1)
    db.commit()
    msg = quote(f"Barcha xodimlar uchun vaqt yuklandi: {saved} ta yozuv (9:00–18:00).")
    return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&updated={saved}&msg={msg}", status_code=303)


@router.post("/attendance/records/delete/{record_id}")
async def attendance_record_delete(
    record_id: int,
    start_date: str = Form(""),
    end_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Davomat yozuvini o'chirish"""
    att = db.query(Attendance).filter(Attendance.id == record_id).first()
    if att:
        db.delete(att)
        db.commit()
    return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}", status_code=303)


@router.post("/attendance/records/bulk-delete")
async def attendance_records_bulk_delete(
    request: Request,
    start_date: str = Form(""),
    end_date: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan davomat yozuvlarini o'chirish."""
    form = await request.form()
    record_ids_raw = form.getlist("record_ids")
    try:
        record_ids = [int(x) for x in record_ids_raw if str(x).strip().isdigit()]
    except (ValueError, TypeError):
        record_ids = []
    if not record_ids:
        return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&error=" + quote("Hech qanday yozuv tanlanmagan."), status_code=303)
    deleted = 0
    for rid in record_ids:
        att = db.query(Attendance).filter(Attendance.id == rid).first()
        if att:
            db.delete(att)
            deleted += 1
    db.commit()
    msg = quote(f"Tanlangan {deleted} ta yozuv o'chirildi.")
    return RedirectResponse(url=f"/employees/attendance/records?start_date={start_date}&end_date={end_date}&deleted={deleted}&msg={msg}", status_code=303)
