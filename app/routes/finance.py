"""
Moliya — kassa, to'lovlar, harajatlar, harajat turlari, kassadan kassaga o'tkazish.
"""
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func, text
from sqlalchemy.exc import OperationalError, IntegrityError

from app.core import templates
from app.models.database import (
    get_db, User, CashRegister, Payment, CashTransfer,
    Partner, Purchase, PurchaseExpense, ExpenseDoc, ExpenseDocItem, ExpenseType,
    Direction, Department,
)
from app.deps import require_auth, require_admin
from app.utils.db_schema import ensure_payments_status_column, ensure_cash_opening_balance_column

router = APIRouter(prefix="/finance", tags=["finance"])
cash_router = APIRouter(prefix="/cash", tags=["cash-transfers"])


def _cash_balance_formula(db: Session, cash_id: int) -> tuple:
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return (0.0, 0.0, 0.0)
    opening = float(getattr(cash, "opening_balance", None) or 0)
    confirmed = or_(Payment.status == "confirmed", Payment.status == None)
    income_sum = float(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.cash_register_id == cash_id, Payment.type == "income", confirmed)
        .scalar()
    ) or 0
    expense_sum = float(
        db.query(func.coalesce(func.sum(Payment.amount), 0))
        .filter(Payment.cash_register_id == cash_id, Payment.type == "expense", confirmed)
        .scalar()
    ) or 0
    return (opening + income_sum - expense_sum, income_sum, expense_sum)


def _sync_cash_balance(db: Session, cash_id: int) -> None:
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        return
    computed, _, _ = _cash_balance_formula(db, cash_id)
    cash.balance = computed


def _next_expense_doc_number(db: Session) -> str:
    today = datetime.now().strftime("%Y%m%d")
    q = db.query(ExpenseDoc).filter(ExpenseDoc.number.isnot(None)).filter(ExpenseDoc.number.like(f"HD-{today}-%"))
    last = q.order_by(ExpenseDoc.id.desc()).first()
    if not last or not last.number:
        return f"HD-{today}-0001"
    try:
        num = int(last.number.split("-")[-1])
        return f"HD-{today}-{num + 1:04d}"
    except (IndexError, ValueError):
        return f"HD-{today}-0001"


@router.get("", response_class=HTMLResponse)
async def finance(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Moliya - kassa. So'nggi to'lovlar sana bo'yicha filtrlanishi mumkin."""
    ensure_payments_status_column(db)
    cash_registers = db.query(CashRegister).all()
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    q = (
        db.query(Payment)
        .options(joinedload(Payment.cash_register), joinedload(Payment.partner))
        .order_by(Payment.date.desc())
    )
    if (date_from or "").strip():
        try:
            df = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(Payment.date >= df)
        except ValueError:
            pass
    if (date_to or "").strip():
        try:
            dt = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(Payment.date < datetime.combine(dt + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    payments = q.limit(200).all()
    filter_date_from = str(date_from or "").strip()[:10] if date_from else ""
    filter_date_to = str(date_to or "").strip()[:10] if date_to else ""
    today = datetime.now().date()
    try:
        _status_ok = or_(Payment.status == "confirmed", Payment.status == None)
        today_income = db.query(Payment).filter(
            Payment.type == "income",
            Payment.date >= today,
            _status_ok
        ).all()
        today_expense = db.query(Payment).filter(
            Payment.type == "expense",
            Payment.date >= today,
            _status_ok
        ).all()
    except OperationalError:
        today_income = db.query(Payment).filter(Payment.type == "income", Payment.date >= today).all()
        today_expense = db.query(Payment).filter(Payment.type == "expense", Payment.date >= today).all()
    stats = {
        "today_income": sum(p.amount for p in today_income),
        "today_expense": sum(p.amount for p in today_expense),
    }
    return templates.TemplateResponse("finance/index.html", {
        "request": request,
        "cash_registers": cash_registers,
        "partners": partners,
        "payments": payments,
        "stats": stats,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,
        "current_user": current_user,
        "page_title": "Moliya"
    })


@router.get("/harajatlar", response_class=HTMLResponse)
async def finance_harajatlar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Harajatlar jurnali — harajat hujjatlari va boshqa chiqimlar (1C uslubida)."""
    ensure_payments_status_column(db)
    cash_registers = db.query(CashRegister).all()
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    expense_docs = (
        db.query(ExpenseDoc)
        .options(
            joinedload(ExpenseDoc.cash_register),
            joinedload(ExpenseDoc.direction),
            joinedload(ExpenseDoc.department),
        )
        .order_by(ExpenseDoc.date.desc())
        .limit(100)
        .all()
    )
    purchases_with_expenses_q = (
        db.query(Purchase)
        .options(
            joinedload(Purchase.expense_cash_register),
            joinedload(Purchase.expense_direction),
            joinedload(Purchase.expense_department),
        )
        .filter(Purchase.status == "confirmed", Purchase.total_expenses > 0)
    )
    _df = str(date_from or "").strip()[:10] if date_from else ""
    _dt = str(date_to or "").strip()[:10] if date_to else ""
    if _df:
        try:
            df = datetime.strptime(_df, "%Y-%m-%d").date()
            purchases_with_expenses_q = purchases_with_expenses_q.filter(Purchase.date >= datetime.combine(df, datetime.min.time()))
        except ValueError:
            pass
    if _dt:
        try:
            dt = datetime.strptime(_dt, "%Y-%m-%d").date()
            purchases_with_expenses_q = purchases_with_expenses_q.filter(Purchase.date < datetime.combine(dt + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    purchases_with_expenses = purchases_with_expenses_q.order_by(Purchase.date.desc()).limit(100).all()
    harajat_hujjatlari = []
    for doc in expense_docs:
        harajat_hujjatlari.append({
            "is_purchase_expense_doc": False,
            "date": doc.date,
            "cash_register": doc.cash_register,
            "direction": doc.direction,
            "department": doc.department,
            "total_amount": doc.total_amount or 0,
            "status": doc.status or "draft",
            "url": f"/finance/harajat/hujjat/{doc.id}",
            "number": doc.number or "",
            "doc_id": doc.id,
        })
    for p in purchases_with_expenses:
        harajat_hujjatlari.append({
            "is_purchase_expense_doc": True,
            "date": p.date,
            "cash_register": p.expense_cash_register,
            "direction": getattr(p, "expense_direction", None),
            "department": getattr(p, "expense_department", None),
            "total_amount": p.total_expenses or 0,
            "status": "confirmed",
            "url": f"/purchases/edit/{p.id}",
            "number": p.number or "",
            "purchase_id": p.id,
        })
    harajat_hujjatlari.sort(key=lambda x: x["date"] or datetime.min, reverse=True)
    harajat_hujjatlari = harajat_hujjatlari[:150]
    q = (
        db.query(Payment)
        .options(joinedload(Payment.cash_register), joinedload(Payment.partner))
        .filter(Payment.type == "expense")
        .order_by(Payment.date.desc())
    )
    if (date_from or "").strip():
        try:
            df = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(Payment.date >= df)
        except ValueError:
            pass
    if (date_to or "").strip():
        try:
            dt = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(Payment.date < datetime.combine(dt + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    payments = q.limit(200).all()
    filter_date_from = str(date_from or "").strip()[:10] if date_from else ""
    filter_date_to = str(date_to or "").strip()[:10] if date_to else ""
    purchase_expenses_q = (
        db.query(PurchaseExpense)
        .options(
            joinedload(PurchaseExpense.purchase).joinedload(Purchase.partner),
            joinedload(PurchaseExpense.purchase).joinedload(Purchase.expense_cash_register),
        )
        .join(Purchase, PurchaseExpense.purchase_id == Purchase.id)
        .filter(Purchase.status == "confirmed")
    )
    if filter_date_from:
        try:
            df = datetime.strptime(filter_date_from[:10], "%Y-%m-%d").date()
            purchase_expenses_q = purchase_expenses_q.filter(Purchase.date >= datetime.combine(df, datetime.min.time()))
        except ValueError:
            pass
    if filter_date_to:
        try:
            dt = datetime.strptime(filter_date_to[:10], "%Y-%m-%d").date()
            purchase_expenses_q = purchase_expenses_q.filter(Purchase.date < datetime.combine(dt + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    purchase_expenses_list = purchase_expenses_q.order_by(Purchase.date.desc()).limit(200).all()
    all_outflows = []
    for p in payments:
        all_outflows.append({
            "is_purchase_expense": False,
            "date": p.date,
            "amount": float(p.amount or 0),
            "description": p.description or "-",
            "partner": p.partner,
            "cash_register": p.cash_register,
            "payment": p,
            "purchase_id": None,
        })
    for pe in purchase_expenses_list:
        pu = pe.purchase
        all_outflows.append({
            "is_purchase_expense": True,
            "date": pu.date if pu else datetime.now(),
            "amount": float(pe.amount or 0),
            "description": f"Kirim xarajati: {pu.number or ''} — {pe.name or 'xarajat'}",
            "partner": pu.partner if pu else None,
            "cash_register": pu.expense_cash_register if pu else None,
            "payment": None,
            "purchase_id": pu.id if pu else None,
        })
    all_outflows.sort(key=lambda x: x["date"] or datetime.min, reverse=True)
    all_outflows = all_outflows[:200]
    today = datetime.now().date()
    try:
        _status_ok = or_(Payment.status == "confirmed", Payment.status == None)
        today_expense = db.query(Payment).filter(
            Payment.type == "expense",
            Payment.date >= today,
            _status_ok
        ).all()
    except OperationalError:
        today_expense = db.query(Payment).filter(Payment.type == "expense", Payment.date >= today).all()
    stats = {
        "today_income": 0,
        "today_expense": sum(p.amount for p in today_expense),
    }
    return templates.TemplateResponse("finance/harajatlar.html", {
        "request": request,
        "cash_registers": cash_registers,
        "partners": partners,
        "expense_docs": expense_docs,
        "harajat_hujjatlari": harajat_hujjatlari,
        "payments": payments,
        "all_outflows": all_outflows,
        "stats": stats,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,
        "current_user": current_user,
        "page_title": "Harajatlar jurnali",
        "finance_harajatlar": True,
    })


@router.get("/kassa/{cash_register_id}", response_class=HTMLResponse)
async def finance_kassa_detail(
    cash_register_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: Optional[int] = None,
):
    """Kassaning kirim/chiqimlari."""
    cash = db.query(CashRegister).filter(CashRegister.id == cash_register_id).first()
    if not cash:
        raise HTTPException(status_code=404, detail="Kassa topilmadi")
    ensure_cash_opening_balance_column(db)
    computed_balance, total_income_all_time, total_expense_all_time = _cash_balance_formula(db, cash_register_id)
    total_income_all_time = float(total_income_all_time)
    total_expense_all_time = float(total_expense_all_time)
    stored_balance = float(cash.balance or 0)
    balance_mismatch = abs(computed_balance - stored_balance) > 0.01
    q = (
        db.query(Payment)
        .options(joinedload(Payment.partner))
        .filter(Payment.cash_register_id == cash_register_id)
        .order_by(Payment.date.desc())
    )
    if (date_from or "").strip():
        try:
            df = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(Payment.date >= df)
        except ValueError:
            pass
    if (date_to or "").strip():
        try:
            dt = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(Payment.date < datetime.combine(dt + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    per_page = 100
    page = max(1, int(page)) if page else 1
    total_count = q.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page) if total_count else 1
    page = min(page, total_pages)
    payments = q.offset((page - 1) * per_page).limit(per_page).all()
    filter_date_from = str(date_from or "").strip()[:10] if date_from else ""
    filter_date_to = str(date_to or "").strip()[:10] if date_to else ""
    total_income = sum(p.amount or 0 for p in payments if getattr(p, "type", None) == "income")
    total_expense = sum(p.amount or 0 for p in payments if getattr(p, "type", None) == "expense")
    parts = []
    if filter_date_from:
        parts.append(f"date_from={filter_date_from}")
    if filter_date_to:
        parts.append(f"date_to={filter_date_to}")
    pagination_query = "&".join(parts)
    return templates.TemplateResponse("finance/kassa_detail.html", {
        "request": request,
        "cash": cash,
        "payments": payments,
        "filter_date_from": filter_date_from,
        "filter_date_to": filter_date_to,
        "total_income": total_income,
        "total_expense": total_expense,
        "total_income_all_time": total_income_all_time,
        "total_expense_all_time": total_expense_all_time,
        "computed_balance": computed_balance,
        "stored_balance": stored_balance,
        "balance_mismatch": balance_mismatch,
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "pagination_query": pagination_query,
        "current_user": current_user,
        "page_title": (cash.name or "Kassa") + " — kirim/chiqimlar",
    })


@router.post("/payment")
async def finance_payment_post(
    request: Request,
    type: str = Form(...),
    amount: float = Form(...),
    cash_register_id: int = Form(...),
    partner_id: Optional[int] = Form(None),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    ensure_payments_status_column(db)
    if type not in ("income", "expense"):
        return RedirectResponse(url="/finance?error=type", status_code=303)
    cash = db.query(CashRegister).filter(CashRegister.id == cash_register_id).first()
    if not cash:
        return RedirectResponse(url="/finance?error=cash", status_code=303)
    amount = float(amount)
    if amount <= 0:
        return RedirectResponse(url="/finance?error=amount", status_code=303)
    pid = None
    if partner_id is not None and int(partner_id) > 0:
        p = db.query(Partner).filter(Partner.id == int(partner_id)).first()
        if p:
            pid = p.id
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    pay_count = db.query(Payment).filter(Payment.created_at >= today_start).count()
    pay_number = f"PAY-{datetime.now().strftime('%Y%m%d')}-{pay_count + 1:04d}"
    desc = (description or "").strip() or ("Kirim" if type == "income" else "Chiqim")
    db.add(Payment(
        number=pay_number,
        type=type,
        cash_register_id=cash_register_id,
        partner_id=pid,
        order_id=None,
        amount=amount,
        payment_type="cash",
        category="other",
        description=desc,
        user_id=current_user.id if current_user else None,
        status="confirmed",
    ))
    _sync_cash_balance(db, cash_register_id)
    db.commit()
    return RedirectResponse(url="/finance?success=1", status_code=303)


def _payment_apply_balance(db: Session, payment: Payment, sign: int):
    _sync_cash_balance(db, payment.cash_register_id)


@router.post("/payment/{payment_id}/confirm")
async def finance_payment_confirm(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    status = getattr(payment, "status", "confirmed")
    if status == "confirmed":
        return RedirectResponse(url="/finance?msg=already_confirmed", status_code=303)
    payment.status = "confirmed"
    _payment_apply_balance(db, payment, 1)
    db.commit()
    return RedirectResponse(url="/finance?success=confirmed", status_code=303)


@router.post("/payment/{payment_id}/cancel")
async def finance_payment_cancel(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    status = getattr(payment, "status", "confirmed")
    if status == "cancelled":
        return RedirectResponse(url="/finance?msg=already_cancelled", status_code=303)
    payment.status = "cancelled"
    _payment_apply_balance(db, payment, -1)
    db.commit()
    return RedirectResponse(url="/finance?success=cancelled", status_code=303)


@router.get("/payment/{payment_id}/edit", response_class=HTMLResponse)
async def finance_payment_edit_page(
    payment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    if getattr(payment, "status", "confirmed") == "confirmed":
        return RedirectResponse(
            url="/finance?error=" + quote("Tasdiqlangan to'lovni tahrirlash mumkin emas. Avval tasdiqni bekor qiling."),
            status_code=303,
        )
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    return templates.TemplateResponse("finance/payment_edit.html", {
        "request": request,
        "payment": payment,
        "partners": partners,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": "To'lovni tahrirlash",
    })


@router.post("/payment/{payment_id}/edit")
async def finance_payment_edit_post(
    payment_id: int,
    type: str = Form(...),
    amount: float = Form(...),
    cash_register_id: int = Form(...),
    partner_id: Optional[int] = Form(None),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    if getattr(payment, "status", "confirmed") == "confirmed":
        return RedirectResponse(
            url="/finance?error=" + quote("Tasdiqlangan to'lovni tahrirlash mumkin emas. Avval tasdiqni bekor qiling."),
            status_code=303,
        )
    if type not in ("income", "expense"):
        return RedirectResponse(url=f"/finance/payment/{payment_id}/edit?error=type", status_code=303)
    amount = float(amount)
    if amount <= 0:
        return RedirectResponse(url=f"/finance/payment/{payment_id}/edit?error=amount", status_code=303)
    cash_new = db.query(CashRegister).filter(CashRegister.id == cash_register_id).first()
    if not cash_new:
        return RedirectResponse(url=f"/finance/payment/{payment_id}/edit?error=cash", status_code=303)
    pid = None
    if partner_id is not None and int(partner_id) > 0:
        p = db.query(Partner).filter(Partner.id == int(partner_id)).first()
        if p:
            pid = p.id
    payment.type = type
    payment.amount = amount
    payment.cash_register_id = cash_register_id
    payment.partner_id = pid
    payment.description = (description or "").strip() or ("Kirim" if type == "income" else "Chiqim")
    db.commit()
    return RedirectResponse(url="/finance?success=edited", status_code=303)


@router.post("/payment/{payment_id}/delete")
async def finance_payment_delete(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    payment = db.query(Payment).filter(Payment.id == payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    if getattr(payment, "status", "confirmed") == "confirmed":
        return RedirectResponse(
            url="/finance?error=" + quote("Tasdiqlangan to'lovni o'chirish mumkin emas. Avval tasdiqni bekor qiling."),
            status_code=303,
        )
    db.delete(payment)
    db.commit()
    return RedirectResponse(url="/finance?success=deleted", status_code=303)


@router.get("/expense-types", response_class=HTMLResponse)
async def finance_expense_types_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    types_list = db.query(ExpenseType).filter(ExpenseType.is_active == True).order_by(ExpenseType.name).all()
    if not types_list and db.query(ExpenseType).count() == 0:
        for name, cat in [
            ("ish haqqi", "Ishlab chiqarish xarajatlari"),
            ("ishxona harajati", "Ishlab chiqarish xarajatlari"),
            ("karobka yasatishga", "Ishlab chiqarish xarajatlari"),
            ("oziq ovqatga", "Ma'muriy xarajatlar"),
            ("Yolkiro", "Ma'muriy xarajatlar"),
        ]:
            db.add(ExpenseType(name=name, category=cat, is_active=True))
        db.commit()
        types_list = db.query(ExpenseType).filter(ExpenseType.is_active == True).order_by(ExpenseType.name).all()
    return templates.TemplateResponse("finance/expense_types.html", {
        "request": request,
        "expense_types": types_list,
        "current_user": current_user,
        "page_title": "Harajat turlari",
    })


@router.post("/expense-types/add")
async def finance_expense_type_add(
    name: str = Form(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    name = (name or "").strip()
    if not name:
        return RedirectResponse(url="/finance/expense-types?error=name", status_code=303)
    db.add(ExpenseType(name=name, category=(category or "").strip() or None, is_active=True))
    db.commit()
    return RedirectResponse(url="/finance/expense-types", status_code=303)


@router.post("/expense-types/edit/{etype_id}")
async def finance_expense_type_edit(
    etype_id: int,
    name: str = Form(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    e = db.query(ExpenseType).filter(ExpenseType.id == etype_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Harajat turi topilmadi")
    e.name = (name or "").strip() or e.name
    e.category = (category or "").strip() or None
    db.commit()
    return RedirectResponse(url="/finance/expense-types", status_code=303)


@router.post("/expense-types/delete/{etype_id}")
async def finance_expense_type_delete(
    etype_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    e = db.query(ExpenseType).filter(ExpenseType.id == etype_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="Harajat turi topilmadi")
    e.is_active = False
    db.commit()
    return RedirectResponse(url="/finance/expense-types", status_code=303)


@router.get("/harajat/hujjat/new", response_class=HTMLResponse)
async def finance_harajat_hujjat_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    directions = db.query(Direction).filter(Direction.is_active == True).order_by(Direction.name).all() if hasattr(Direction, "is_active") else db.query(Direction).order_by(Direction.name).all()
    departments = db.query(Department).filter(Department.is_active == True).order_by(Department.name).all()
    expense_types = db.query(ExpenseType).filter(ExpenseType.is_active == True).order_by(ExpenseType.name).all()
    doc_date = datetime.now().date()
    return templates.TemplateResponse("finance/harajat_hujjat_form.html", {
        "request": request,
        "doc": None,
        "doc_date": doc_date,
        "cash_registers": cash_registers,
        "directions": directions,
        "departments": departments,
        "expense_types": expense_types,
        "current_user": current_user,
        "page_title": "Harajat hujjati — yaratish",
    })


@router.get("/harajat/hujjat/{doc_id}", response_class=HTMLResponse)
async def finance_harajat_hujjat_edit(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    doc = db.query(ExpenseDoc).options(
        joinedload(ExpenseDoc.items).joinedload(ExpenseDocItem.expense_type),
        joinedload(ExpenseDoc.cash_register),
        joinedload(ExpenseDoc.direction),
        joinedload(ExpenseDoc.department),
    ).filter(ExpenseDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Harajat hujjati topilmadi")
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    directions = db.query(Direction).filter(Direction.is_active == True).order_by(Direction.name).all() if hasattr(Direction, "is_active") else db.query(Direction).order_by(Direction.name).all()
    departments = db.query(Department).filter(Department.is_active == True).order_by(Department.name).all()
    expense_types = db.query(ExpenseType).filter(ExpenseType.is_active == True).order_by(ExpenseType.name).all()
    if doc.date:
        doc_date = doc.date.date() if hasattr(doc.date, "date") and callable(getattr(doc.date, "date")) else doc.date
    else:
        doc_date = datetime.now().date()
    return templates.TemplateResponse("finance/harajat_hujjat_form.html", {
        "request": request,
        "doc": doc,
        "doc_date": doc_date,
        "cash_registers": cash_registers,
        "directions": directions,
        "departments": departments,
        "expense_types": expense_types,
        "current_user": current_user,
        "page_title": f"Harajat hujjati #{doc.number or doc_id}",
    })


@router.post("/harajat/hujjat/save")
async def finance_harajat_hujjat_save(
    request: Request,
    doc_id: Optional[int] = Form(None),
    date: str = Form(...),
    cash_register_id: int = Form(...),
    direction_id: Optional[int] = Form(None),
    department_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    cash = db.query(CashRegister).filter(CashRegister.id == cash_register_id).first()
    if not cash:
        return RedirectResponse(url="/finance/harajatlar?error=cash", status_code=303)
    try:
        doc_date = datetime.strptime(str(date).strip()[:10], "%Y-%m-%d")
    except ValueError:
        doc_date = datetime.now()
    form = await request.form()
    ids = form.getlist("expense_type_id")
    amounts = form.getlist("amount")
    descriptions = form.getlist("description")
    if doc_id:
        doc = db.query(ExpenseDoc).filter(ExpenseDoc.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Hujjat topilmadi")
        if doc.status == "confirmed":
            return RedirectResponse(url="/finance/harajatlar?error=confirmed", status_code=303)
    else:
        doc = ExpenseDoc(
            number=_next_expense_doc_number(db),
            date=doc_date,
            cash_register_id=cash_register_id,
            direction_id=int(direction_id) if direction_id and int(direction_id) > 0 else None,
            department_id=int(department_id) if department_id and int(department_id) > 0 else None,
            status="draft",
            total_amount=0,
            user_id=current_user.id if current_user else None,
        )
        db.add(doc)
        db.flush()
    doc.date = doc_date
    doc.cash_register_id = cash_register_id
    doc.direction_id = int(direction_id) if direction_id and int(direction_id) > 0 else None
    doc.department_id = int(department_id) if department_id and int(department_id) > 0 else None
    doc.user_id = current_user.id if current_user else None
    for it in list(doc.items):
        db.delete(it)
    db.flush()
    total = 0.0
    for i in range(max(len(ids), len(amounts))):
        et_id = int(ids[i]) if i < len(ids) and str(ids[i]).strip().isdigit() else None
        amt = float(amounts[i]) if i < len(amounts) and str(amounts[i]).strip() else 0
        desc = (descriptions[i] if i < len(descriptions) else "").strip() or None
        if et_id and amt > 0:
            et = db.query(ExpenseType).filter(ExpenseType.id == et_id).first()
            if et:
                db.add(ExpenseDocItem(expense_doc_id=doc.id, expense_type_id=et_id, amount=amt, description=desc))
                total += amt
    doc.total_amount = total
    db.commit()
    return RedirectResponse(url=f"/finance/harajat/hujjat/{doc.id}", status_code=303)


@router.post("/harajat/hujjat/{doc_id}/tasdiqlash")
async def finance_harajat_hujjat_tasdiqlash(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    try:
        doc = db.query(ExpenseDoc).options(joinedload(ExpenseDoc.items)).filter(ExpenseDoc.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Harajat hujjati topilmadi")
        if doc.status == "confirmed":
            return RedirectResponse(url="/finance/harajatlar?error=already_confirmed", status_code=303)
        if not doc.items:
            return RedirectResponse(url="/finance/harajatlar?error=no_items", status_code=303)
        if not getattr(doc, "cash_register_id", None):
            return RedirectResponse(url="/finance/harajatlar?error=no_cash", status_code=303)
        total = sum(getattr(it, "amount", 0) or 0 for it in doc.items)
        if total <= 0:
            return RedirectResponse(url="/finance/harajatlar?error=no_amount", status_code=303)
        ensure_payments_status_column(db)
        pay_number = f"PAY-{datetime.now().strftime('%Y%m%d%H%M%S')}-D{doc_id}"
        payment_date = datetime.now()
        if getattr(doc, "date", None):
            d = doc.date
            if hasattr(d, "date") and callable(getattr(d, "date")):
                payment_date = datetime.combine(d.date(), datetime.min.time())
            else:
                payment_date = d
        uid = getattr(current_user, "id", None) if current_user else None
        if uid is None:
            first_user = db.query(User).order_by(User.id).first()
            uid = first_user.id if first_user else None
        if uid is None:
            return RedirectResponse(url="/finance/harajatlar?error=no_user", status_code=303)
        payment = Payment(
            number=pay_number,
            date=payment_date,
            type="expense",
            cash_register_id=doc.cash_register_id,
            partner_id=None,
            order_id=None,
            amount=total,
            payment_type="cash",
            category="expense_doc",
            description=f"Harajat hujjati #{doc.number or doc_id}",
            user_id=uid,
            status="confirmed",
        )
        db.add(payment)
        db.flush()
        db.execute(
            text("UPDATE expense_docs SET payment_id = :pid, status = 'confirmed', total_amount = :tot WHERE id = :id"),
            {"pid": payment.id, "tot": total, "id": doc_id}
        )
        _sync_cash_balance(db, doc.cash_register_id)
        db.commit()
        return RedirectResponse(url="/finance/harajatlar?success=confirmed", status_code=303)
    except HTTPException:
        raise
    except IntegrityError:
        db.rollback()
        return RedirectResponse(url="/finance/harajatlar?error=duplicate", status_code=303)
    except Exception:
        db.rollback()
        return RedirectResponse(url="/finance/harajatlar?error=save_error", status_code=303)


# ==========================================
# KASSADAN KASSAGA O'TKAZISH (/cash/transfers)
# ==========================================

@cash_router.get("/transfiers")
async def cash_transfiers_redirect():
    """Yozuv xatosi: transfiers -> transfers (ro'yxatga yo'naltirish)."""
    return RedirectResponse(url="/cash/transfers", status_code=301)


@cash_router.get("/transfers", response_class=HTMLResponse)
async def cash_transfers_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kassadan kassaga o'tkazish hujjatlari ro'yxati"""
    try:
        transfers = (
            db.query(CashTransfer)
            .options(
                joinedload(CashTransfer.from_cash),
                joinedload(CashTransfer.to_cash),
                joinedload(CashTransfer.user),
                joinedload(CashTransfer.approved_by),
            )
            .order_by(CashTransfer.created_at.desc())
            .limit(100)
            .all()
        )
    except Exception as e:
        err = str(e).lower()
        if "payment_type" in err or "no such column" in err or "operationalerror" in err:
            return HTMLResponse(
                "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Migratsiya kerak</title></head><body style='font-family:sans-serif;padding:2rem;'>"
                "<h2>Bazada yangi ustun yo'q</h2><p>Kassalar jadvaliga <code>payment_type</code> qo'shilishi kerak. "
                "Loyiha ildizida terminalda bajariladi:</p><pre>alembic upgrade head</pre>"
                "<p><a href='/cash/transfers'>Qayta urinish</a> &nbsp; <a href='/'>Bosh sahifa</a></p></body></html>",
                status_code=500,
            )
        raise
    return templates.TemplateResponse("cash/transfers_list.html", {
        "request": request,
        "transfers": transfers,
        "current_user": current_user,
        "page_title": "Kassadan kassaga o'tkazish",
    })


@cash_router.get("/transfers/new", response_class=HTMLResponse)
async def cash_transfer_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Yangi kassadan kassaga o'tkazish (qoralama)"""
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    return templates.TemplateResponse("cash/transfer_form.html", {
        "request": request,
        "transfer": None,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": "Kassadan kassaga o'tkazish (yaratish)",
    })


@cash_router.post("/transfers/create")
async def cash_transfer_create(
    request: Request,
    from_cash_id: int = Form(...),
    to_cash_id: int = Form(...),
    amount: float = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if from_cash_id == to_cash_id:
        return RedirectResponse(url="/cash/transfers/new?error=" + quote("Qayerdan va qayerga kassa bir xil bo'lmasin."), status_code=303)
    if amount <= 0:
        return RedirectResponse(url="/cash/transfers/new?error=" + quote("Summa 0 dan katta bo'lishi kerak."), status_code=303)
    from_cash = db.query(CashRegister).filter(CashRegister.id == from_cash_id).first()
    if not from_cash or (from_cash.balance or 0) < amount:
        return RedirectResponse(url="/cash/transfers/new?error=" + quote("Kassada yetarli mablag' yo'q."), status_code=303)
    last_t = db.query(CashTransfer).order_by(CashTransfer.id.desc()).first()
    num = f"KK-{datetime.now().strftime('%Y%m%d')}-{(last_t.id + 1) if last_t else 1:04d}"
    t = CashTransfer(
        number=num,
        from_cash_id=from_cash_id,
        to_cash_id=to_cash_id,
        amount=amount,
        status="draft",
        user_id=current_user.id if current_user else None,
        note=note or None,
    )
    db.add(t)
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{t.id}", status_code=303)


@cash_router.get("/transfers/{transfer_id}", response_class=HTMLResponse)
async def cash_transfer_view(
    request: Request,
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    transfer = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not transfer:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    return templates.TemplateResponse("cash/transfer_form.html", {
        "request": request,
        "transfer": transfer,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": f"Kassadan kassaga {transfer.number}",
    })


@cash_router.post("/transfers/{transfer_id}/send")
async def cash_transfer_send(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Jo'natuvchi yuboradi — hujjat tasdiqlash kutilmoqdaga o'tadi"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status != "draft":
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Faqat qoralamani yuborish mumkin."), status_code=303)
    from_cash = db.query(CashRegister).filter(CashRegister.id == t.from_cash_id).first()
    if not from_cash or (from_cash.balance or 0) < (t.amount or 0):
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Kassada yetarli mablag' yo'q."), status_code=303)
    t.status = "pending_approval"
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}?sent=1", status_code=303)


@cash_router.post("/transfers/{transfer_id}/confirm")
async def cash_transfer_confirm(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Qabul qiluvchi tasdiqlaydi — from_cash dan ayiriladi, to_cash ga qo'shiladi"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status != "pending_approval":
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Faqat tasdiqlash kutilayotgan hujjatni tasdiqlash mumkin."), status_code=303)
    from_cash = db.query(CashRegister).filter(CashRegister.id == t.from_cash_id).first()
    to_cash = db.query(CashRegister).filter(CashRegister.id == t.to_cash_id).first()
    if not from_cash or not to_cash:
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Kassa topilmadi."), status_code=303)
    amount = t.amount or 0
    if (from_cash.balance or 0) < amount:
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Jo'natuvchi kassada yetarli mablag' yo'q."), status_code=303)
    from_cash.balance = (from_cash.balance or 0) - amount
    to_cash.balance = (to_cash.balance or 0) + amount
    t.status = "confirmed"
    t.approved_by_user_id = current_user.id if current_user else None
    t.approved_at = datetime.now()
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}?confirmed=1", status_code=303)


@cash_router.post("/transfers/{transfer_id}/revert")
async def cash_transfer_revert(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tasdiqni bekor qilish (faqat admin): balanslarni qaytarish"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t or t.status != "confirmed":
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Faqat tasdiqlangan hujjatning tasdiqini bekor qilish mumkin."), status_code=303)
    amount = t.amount or 0
    from_cash = db.query(CashRegister).filter(CashRegister.id == t.from_cash_id).first()
    to_cash = db.query(CashRegister).filter(CashRegister.id == t.to_cash_id).first()
    if from_cash:
        from_cash.balance = (from_cash.balance or 0) + amount
    if to_cash:
        to_cash.balance = max(0, (to_cash.balance or 0) - amount)
    t.status = "pending_approval"
    t.approved_by_user_id = None
    t.approved_at = None
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}?reverted=1", status_code=303)


@cash_router.post("/transfers/{transfer_id}/delete")
async def cash_transfer_delete(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status != "draft":
        return RedirectResponse(url=f"/cash/transfers?error=" + quote("Faqat qoralamani o'chirish mumkin."), status_code=303)
    db.delete(t)
    db.commit()
    return RedirectResponse(url="/cash/transfers?deleted=1", status_code=303)
