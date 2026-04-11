"""
Xodimlar — avans hujjatlari (Tier C1 2-bosqich).

Manba: employees.py:1735-2225 (~493 qator) dan ajratib olindi.
Endpoint path'lar o'zgarishsiz — URL'lar eskidek ishlashda davom etadi.
"""
from datetime import datetime, date, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload

from app.core import templates
from app.models.database import (
    get_db,
    User,
    Employee,
    EmployeeAdvance,
    CashRegister,
    Payment,
)
from app.deps import require_auth

router = APIRouter(prefix="/employees", tags=["employees-advances"])


def _advances_list_redirect_params(form_or_params, key_from="date_from", key_to="date_to"):
    """Filtr parametrlarini redirect URL ga qo'shish."""
    parts = []
    if hasattr(form_or_params, "get"):
        df, dt = form_or_params.get(key_from) or "", form_or_params.get(key_to) or ""
    else:
        df = form_or_params.get(key_from, "") or ""
        dt = form_or_params.get(key_to, "") or ""
    if (df or "").strip():
        parts.append("date_from=" + quote(str(df).strip()[:10]))
    if (dt or "").strip():
        parts.append("date_to=" + quote(str(dt).strip()[:10]))
    return "&".join(parts)


@router.get("/advances", response_class=HTMLResponse)
async def employee_advances_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Xodim avanslari ro'yxati — sana bo'yicha filtrlash."""
    q = db.query(EmployeeAdvance).options(
        joinedload(EmployeeAdvance.cash_register),
        joinedload(EmployeeAdvance.employee),
    ).order_by(EmployeeAdvance.advance_date.desc())
    if (date_from or "").strip():
        try:
            df = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(EmployeeAdvance.advance_date >= df)
        except ValueError:
            pass
    if (date_to or "").strip():
        try:
            dt = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(EmployeeAdvance.advance_date <= dt)
        except ValueError:
            pass
    advances = q.all()
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    default_date = date.today().strftime("%Y-%m-%d")
    filter_date_from = str(date_from or "").strip()[:10] if date_from else ""
    filter_date_to = str(date_to or "").strip()[:10] if date_to else ""
    return templates.TemplateResponse("employees/advances_list.html", {
        "request": request,
        "advances": advances,
        "employees": employees,
        "cash_registers": cash_registers,
        "default_date": default_date,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,
        "current_user": current_user,
        "page_title": "Avans berish",
    })


@router.get("/advance-docs", response_class=HTMLResponse)
async def employee_advance_docs_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Avans hujjatlari — sana+kassa bo'yicha guruhlangan avanslar ro'yxati."""
    q = db.query(EmployeeAdvance).options(
        joinedload(EmployeeAdvance.cash_register),
    ).filter(EmployeeAdvance.confirmed_at.isnot(None))
    if (date_from or "").strip():
        try:
            df = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(EmployeeAdvance.advance_date >= df)
        except ValueError:
            pass
    if (date_to or "").strip():
        try:
            dt = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(EmployeeAdvance.advance_date <= dt)
        except ValueError:
            pass
    advances = q.order_by(EmployeeAdvance.advance_date.desc(), EmployeeAdvance.id).all()
    from collections import OrderedDict
    groups = OrderedDict()
    for a in advances:
        key = (a.advance_date, a.cash_register_id)
        if key not in groups:
            groups[key] = {
                "date": a.advance_date,
                "cash_register": a.cash_register,
                "first_id": a.id,
                "count": 0,
                "total": 0.0,
            }
        groups[key]["count"] += 1
        groups[key]["total"] += float(a.amount or 0)
    docs = list(groups.values())
    filter_date_from = str(date_from or "").strip()[:10] if date_from else ""
    filter_date_to = str(date_to or "").strip()[:10] if date_to else ""
    return templates.TemplateResponse("employees/advance_docs_list.html", {
        "request": request,
        "docs": docs,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,
        "current_user": current_user,
        "page_title": "Avans hujjatlari",
    })


@router.post("/advances/add")
async def employee_advance_add(
    request: Request,
    employee_id: int = Form(...),
    amount: float = Form(...),
    advance_date: str = Form(...),
    cash_register_id: Optional[int] = Form(None),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avans qo'shish; tanlangan kassadan chiqim yoziladi."""
    try:
        adv_date = datetime.strptime(advance_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url="/employees/advances?error=Noto'g'ri sana", status_code=303)
    if amount <= 0:
        return RedirectResponse(url="/employees/advances?error=Summa 0 dan katta bo'lishi kerak", status_code=303)
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees/advances?error=Xodim topilmadi", status_code=303)
    cash = None
    if cash_register_id:
        cash = db.query(CashRegister).filter(CashRegister.id == cash_register_id, CashRegister.is_active == True).first()
    if not cash:
        return RedirectResponse(url="/employees/advances?error=Kassani tanlang", status_code=303)
    # Duplikat tekshirish — 5 daqiqa ichida shu xodimga shu summada avans bo'lsa rad etish
    five_min_ago = datetime.now() - timedelta(minutes=5)
    dup = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.employee_id == employee_id,
        EmployeeAdvance.amount == amount,
        EmployeeAdvance.advance_date == adv_date,
        EmployeeAdvance.confirmed_at >= five_min_ago,
    ).first()
    if dup:
        return RedirectResponse(url="/employees/advances?error=" + quote("Bu avans allaqachon yozilgan (duplikat)"), status_code=303)
    today = datetime.now()
    adv = EmployeeAdvance(
        employee_id=employee_id,
        amount=amount,
        advance_date=adv_date,
        cash_register_id=cash.id,
        note=note or None,
        confirmed_at=today,
    )
    db.add(adv)
    db.flush()
    prefix = f"PAY-{today.strftime('%Y%m%d')}-"
    last_pay = db.query(Payment).filter(Payment.number.like(prefix + "%")).order_by(Payment.number.desc()).first()
    if last_pay and last_pay.number:
        try:
            last_seq = int(last_pay.number.split("-")[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0
    pay_number = f"{prefix}{last_seq + 1:04d}"
    emp_name = (emp.full_name or f"Xodim {employee_id}")[:100]
    db.add(Payment(
        number=pay_number,
        type="expense",
        cash_register_id=cash.id,
        partner_id=None,
        order_id=None,
        amount=amount,
        payment_type="cash",
        category="other",
        description=f"Avans: {emp_name}",
        user_id=current_user.id if current_user else None,
        status="confirmed",
    ))
    from app.routes.finance import _sync_cash_balance
    _sync_cash_balance(db, cash.id)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        import traceback
        traceback.print_exc()
        print(f"[Avans xato] {e}")
        return RedirectResponse(url="/employees/advances?error=" + quote(f"Avansni saqlashda xatolik: {str(e)[:200]}"), status_code=303)
    return RedirectResponse(url="/employees/advances?added=1", status_code=303)


@router.get("/advances/view/{advance_id}", response_class=HTMLResponse)
async def employee_advance_view_page(
    advance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avans hujjatini ko'rish — shu kun+kassadagi barcha avanslarni guruh sifatida ko'rsatish."""
    adv = db.query(EmployeeAdvance).options(
        joinedload(EmployeeAdvance.employee),
        joinedload(EmployeeAdvance.cash_register),
    ).filter(EmployeeAdvance.id == advance_id).first()
    if not adv:
        return RedirectResponse(url="/employees/advances?error=Avans topilmadi", status_code=303)
    batch = db.query(EmployeeAdvance).options(
        joinedload(EmployeeAdvance.employee),
    ).filter(
        EmployeeAdvance.advance_date == adv.advance_date,
        EmployeeAdvance.cash_register_id == adv.cash_register_id,
        EmployeeAdvance.confirmed_at.isnot(None),
    ).order_by(EmployeeAdvance.id).all()
    batch_total = sum(float(a.amount or 0) for a in batch)
    return templates.TemplateResponse("employees/advance_view.html", {
        "request": request,
        "advance": adv,
        "batch": batch,
        "batch_total": batch_total,
        "current_user": current_user,
        "page_title": f"Avans hujjati — {adv.advance_date.strftime('%d.%m.%Y')}",
    })


@router.get("/advances/edit/{advance_id}", response_class=HTMLResponse)
async def employee_advance_edit_page(
    advance_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avansni tahrirlash sahifasi — faqat tasdiqlanmagan avanslar."""
    adv = db.query(EmployeeAdvance).options(
        joinedload(EmployeeAdvance.employee),
        joinedload(EmployeeAdvance.cash_register),
    ).filter(EmployeeAdvance.id == advance_id).first()
    if not adv:
        return RedirectResponse(url="/employees/advances?error=Avans topilmadi", status_code=303)
    if adv.confirmed_at:
        return RedirectResponse(
            url="/employees/advances?error=" + quote("Tasdiqlangan avansni tahrirlash mumkin emas. Avval tasdiqni bekor qiling."),
            status_code=303,
        )
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    if adv.employee and not any(e.id == adv.employee_id for e in employees):
        employees = [adv.employee] + list(employees)
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    next_ids = (request.query_params.get("next_ids") or "").strip()
    next_count = len([x for x in next_ids.split(",") if x.strip()]) if next_ids else 0
    return templates.TemplateResponse("employees/advance_edit.html", {
        "request": request,
        "advance": adv,
        "employees": employees,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": "Avansni tahrirlash",
        "next_ids": next_ids,
        "next_count": next_count,
    })


@router.post("/advances/edit/{advance_id}")
async def employee_advance_edit_save(
    advance_id: int,
    request: Request,
    employee_id: int = Form(...),
    amount: float = Form(...),
    advance_date: str = Form(...),
    cash_register_id: Optional[int] = Form(None),
    note: str = Form(""),
    next_ids: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avansni saqlash (tahrirlash) — faqat tasdiqlanmagan avanslar."""
    adv = db.query(EmployeeAdvance).filter(EmployeeAdvance.id == advance_id).first()
    if not adv:
        return RedirectResponse(url="/employees/advances?error=Avans topilmadi", status_code=303)
    if adv.confirmed_at:
        return RedirectResponse(
            url="/employees/advances?error=" + quote("Tasdiqlangan avansni tahrirlash mumkin emas."),
            status_code=303,
        )
    try:
        adv_date = datetime.strptime(advance_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=f"/advances/edit/{advance_id}?error=Noto'g'ri sana", status_code=303)
    if amount <= 0:
        return RedirectResponse(url=f"/advances/edit/{advance_id}?error=Summa 0 dan katta bo'lishi kerak", status_code=303)
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url=f"/advances/edit/{advance_id}?error=Xodim topilmadi", status_code=303)
    if cash_register_id:
        cash = db.query(CashRegister).filter(CashRegister.id == cash_register_id, CashRegister.is_active == True).first()
        adv.cash_register_id = cash.id if cash else adv.cash_register_id
    else:
        adv.cash_register_id = None
    adv.employee_id = employee_id
    adv.amount = amount
    adv.advance_date = adv_date
    adv.note = note or None
    adv.confirmed_at = datetime.now()
    db.commit()
    next_param = (next_ids or "").strip()
    if next_param:
        rest = [x.strip() for x in next_param.split(",") if x.strip()]
        if rest:
            try:
                next_id = int(rest[0])
                remaining = ",".join(rest[1:])
                url = f"/advances/edit/{next_id}"
                if remaining:
                    url += "?next_ids=" + remaining
                return RedirectResponse(url=url, status_code=303)
            except (ValueError, TypeError):
                pass
    return RedirectResponse(url="/employees/advances?edited=1", status_code=303)


@router.post("/advances/confirm/{advance_id}")
async def employee_advance_confirm(
    advance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avansni tasdiqlash"""
    adv = db.query(EmployeeAdvance).filter(EmployeeAdvance.id == advance_id).first()
    if not adv:
        return RedirectResponse(url="/employees/advances?error=Avans topilmadi", status_code=303)
    adv.confirmed_at = datetime.now()
    db.commit()
    return RedirectResponse(url="/employees/advances?confirmed=1", status_code=303)


@router.post("/advances/unconfirm/{advance_id}")
async def employee_advance_unconfirm(
    advance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avans tasdiqini bekor qilish"""
    adv = db.query(EmployeeAdvance).filter(EmployeeAdvance.id == advance_id).first()
    if not adv:
        return RedirectResponse(url="/employees/advances?error=Avans topilmadi", status_code=303)
    adv.confirmed_at = None
    db.commit()
    return RedirectResponse(url="/employees/advances?unconfirmed=1", status_code=303)


@router.post("/advances/delete/{advance_id}")
async def employee_advance_delete(
    advance_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Avansni ro'yxatdan o'chirish — faqat tasdiqlanmagan."""
    adv = db.query(EmployeeAdvance).filter(EmployeeAdvance.id == advance_id).first()
    if not adv:
        return RedirectResponse(url="/employees/advances?error=Avans topilmadi", status_code=303)
    if adv.confirmed_at:
        return RedirectResponse(
            url="/employees/advances?error=" + quote("Tasdiqlangan avansni o'chirish mumkin emas. Avval tasdiqni bekor qiling."),
            status_code=303,
        )
    db.delete(adv)
    db.commit()
    return RedirectResponse(url="/employees/advances?deleted=1", status_code=303)


@router.post("/advances/bulk-edit", response_class=RedirectResponse)
async def employee_advances_bulk_edit(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan tasdiqlanmagan avanslarni ketma-ket tahrirlash — birinchisiga yo'naltiradi."""
    form = await request.form()
    raw = form.getlist("advance_ids")
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not ids:
        return RedirectResponse(url="/employees/advances?error=" + quote("Hech qaysi avans tanlanmagan."), status_code=303)
    unconfirmed = (
        db.query(EmployeeAdvance.id)
        .filter(EmployeeAdvance.id.in_(ids), EmployeeAdvance.confirmed_at.is_(None))
        .order_by(EmployeeAdvance.id)
        .all()
    )
    unconfirmed_ids = [r[0] for r in unconfirmed]
    if not unconfirmed_ids:
        return RedirectResponse(url="/employees/advances?error=" + quote("Tanlangan avanslar tasdiqlangan. Faqat tasdiqlanmagan avanslarni tahrirlash mumkin."), status_code=303)
    first_id = unconfirmed_ids[0]
    next_ids = unconfirmed_ids[1:]
    next_param = ",".join(str(i) for i in next_ids) if next_ids else ""
    url = f"/advances/edit/{first_id}"
    if next_param:
        url += "?next_ids=" + next_param
    return RedirectResponse(url=url, status_code=303)


@router.post("/advances/bulk-unconfirm", response_class=RedirectResponse)
async def employee_advances_bulk_unconfirm(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan tasdiqlangan avanslarning tasdiqini bekor qilish"""
    form = await request.form()
    raw = form.getlist("advance_ids")
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not ids:
        return RedirectResponse(url="/employees/advances?error=" + quote("Hech qaysi avans tanlanmagan."), status_code=303)
    updated = db.query(EmployeeAdvance).filter(EmployeeAdvance.id.in_(ids), EmployeeAdvance.confirmed_at.isnot(None)).update({EmployeeAdvance.confirmed_at: None}, synchronize_session=False)
    db.commit()
    base = "/advances?bulk_unconfirmed=" + str(updated)
    extra = _advances_list_redirect_params(form)
    return RedirectResponse(url=base + ("&" + extra if extra else ""), status_code=303)


@router.post("/advances/bulk-confirm", response_class=RedirectResponse)
async def employee_advances_bulk_confirm(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan tasdiqlanmagan avanslarni tasdiqlash"""
    form = await request.form()
    raw = form.getlist("advance_ids")
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not ids:
        return RedirectResponse(url="/employees/advances?error=" + quote("Hech qaysi avans tanlanmagan."), status_code=303)
    now = datetime.now()
    updated = db.query(EmployeeAdvance).filter(EmployeeAdvance.id.in_(ids), EmployeeAdvance.confirmed_at.is_(None)).update({EmployeeAdvance.confirmed_at: now}, synchronize_session=False)
    db.commit()
    base = "/advances?bulk_confirmed=" + str(updated)
    extra = _advances_list_redirect_params(form)
    return RedirectResponse(url=base + ("&" + extra if extra else ""), status_code=303)


@router.post("/advances/bulk-delete", response_class=RedirectResponse)
async def employee_advances_bulk_delete(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tanlangan tasdiqlanmagan avanslarni o'chirish."""
    form = await request.form()
    raw = form.getlist("advance_ids")
    ids = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            pass
    if not ids:
        base = "/advances?error=" + quote("Hech qaysi avans tanlanmagan.")
        extra = _advances_list_redirect_params(form)
        return RedirectResponse(url=base + ("&" + extra if extra else ""), status_code=303)
    deleted = db.query(EmployeeAdvance).filter(EmployeeAdvance.id.in_(ids), EmployeeAdvance.confirmed_at.is_(None)).delete(synchronize_session=False)
    db.commit()
    if ids and deleted == 0:
        base = "/advances?error=" + quote("Tanlangan avanslar tasdiqlangan. O'chirish uchun avval tasdiqni bekor qiling.")
    else:
        base = "/advances?bulk_deleted=" + str(deleted)
    extra = _advances_list_redirect_params(form)
    return RedirectResponse(url=base + ("&" + extra if extra else ""), status_code=303)
