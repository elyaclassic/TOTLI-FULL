"""
Moliya — kassa, to'lovlar, harajatlar, harajat turlari, kassadan kassaga o'tkazish.
"""
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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
from app.utils.audit import log_action

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
    # Sana filtrlari
    filter_date_from = str(date_from or "").strip()[:10] if date_from else ""
    filter_date_to = str(date_to or "").strip()[:10] if date_to else ""
    has_date_filter = bool(filter_date_from or filter_date_to)
    df_parsed = None
    dt_parsed = None
    if filter_date_from:
        try:
            df_parsed = datetime.strptime(filter_date_from, "%Y-%m-%d").date()
            q = q.filter(Payment.date >= df_parsed)
        except ValueError:
            pass
    if filter_date_to:
        try:
            dt_parsed = datetime.strptime(filter_date_to, "%Y-%m-%d").date()
            q = q.filter(Payment.date < datetime.combine(dt_parsed + timedelta(days=1), datetime.min.time()))
        except ValueError:
            pass
    payments = q.limit(200).all()
    today = datetime.now().date()
    _status_ok = or_(Payment.status == "confirmed", Payment.status == None)

    # Stat kartochkalar — sana filtri bo'lsa shu oraliq, bo'lmasa bugungi
    if has_date_filter:
        stat_q_income = db.query(Payment).filter(Payment.type == "income", _status_ok)
        stat_q_expense = db.query(Payment).filter(Payment.type == "expense", _status_ok)
        if df_parsed:
            stat_q_income = stat_q_income.filter(Payment.date >= df_parsed)
            stat_q_expense = stat_q_expense.filter(Payment.date >= df_parsed)
        if dt_parsed:
            stat_q_income = stat_q_income.filter(Payment.date < datetime.combine(dt_parsed + timedelta(days=1), datetime.min.time()))
            stat_q_expense = stat_q_expense.filter(Payment.date < datetime.combine(dt_parsed + timedelta(days=1), datetime.min.time()))
        stat_income = sum(float(p.amount or 0) for p in stat_q_income.all())
        stat_expense = sum(float(p.amount or 0) for p in stat_q_expense.all())
        stats_label = f"{filter_date_from} — {filter_date_to}" if filter_date_from and filter_date_to else (filter_date_from or filter_date_to)
    else:
        try:
            stat_income = sum(float(p.amount or 0) for p in db.query(Payment).filter(Payment.type == "income", Payment.date >= today, _status_ok).all())
            stat_expense = sum(float(p.amount or 0) for p in db.query(Payment).filter(Payment.type == "expense", Payment.date >= today, _status_ok).all())
        except OperationalError:
            stat_income = sum(float(p.amount or 0) for p in db.query(Payment).filter(Payment.type == "income", Payment.date >= today).all())
            stat_expense = sum(float(p.amount or 0) for p in db.query(Payment).filter(Payment.type == "expense", Payment.date >= today).all())
        stats_label = "Bugungi"
    stats = {
        "income": stat_income,
        "expense": stat_expense,
        "label": stats_label,
    }

    # Kassalar — sana filtri bo'lsa shu oraliq bo'yicha kirim/chiqim
    cash_data = []
    for cash in cash_registers:
        if has_date_filter:
            cq_base = db.query(Payment).filter(Payment.cash_register_id == cash.id, _status_ok)
            if df_parsed:
                cq_base = cq_base.filter(Payment.date >= df_parsed)
            if dt_parsed:
                cq_base = cq_base.filter(Payment.date < datetime.combine(dt_parsed + timedelta(days=1), datetime.min.time()))
            c_income = sum(float(p.amount or 0) for p in cq_base.filter(Payment.type == "income").all())
            c_expense = sum(float(p.amount or 0) for p in cq_base.filter(Payment.type == "expense").all())
            cash_data.append({
                "cash": cash,
                "balance": c_income - c_expense,
                "income": c_income,
                "expense": c_expense,
                "is_filtered": True,
            })
        else:
            cash_data.append({
                "cash": cash,
                "balance": float(cash.balance or 0),
                "income": 0,
                "expense": 0,
                "is_filtered": False,
            })

    return templates.TemplateResponse("finance/index.html", {
        "request": request,
        "cash_registers": cash_registers,
        "cash_data": cash_data,
        "partners": partners,
        "payments": payments,
        "stats": stats,
        "has_date_filter": has_date_filter,
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
    today_str = datetime.now().strftime('%Y%m%d')
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    last_pay = db.query(Payment).filter(
        Payment.number.like(f"PAY-{today_str}-%"),
        Payment.created_at >= today_start,
    ).order_by(Payment.id.desc()).first()
    if last_pay and last_pay.number:
        try:
            seq = int(last_pay.number.split("-")[-1]) + 1
        except (ValueError, IndexError):
            seq = db.query(Payment).filter(Payment.created_at >= today_start).count() + 1
    else:
        seq = 1
    pay_number = f"PAY-{today_str}-{seq:04d}"
    desc = (description or "").strip() or ("Kirim" if type == "income" else "Chiqim")
    payment = Payment(
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
    )
    db.add(payment)
    db.flush()
    _payment_apply_balance(db, payment, 1)
    log_action(db, user=current_user, action="create", entity_type="payment",
               entity_id=payment.id, entity_number=payment.number,
               details=f"Tur: {type}, Summa: {amount:,.0f}, Partner: {pid or 'yo`q'}",
               ip_address=request.client.host if request.client else "")
    db.commit()
    return RedirectResponse(url="/finance?success=1", status_code=303)


def _payment_apply_balance(db: Session, payment: Payment, sign: int):
    """Kassa va kontragent balanslarini yangilash.
    sign=1: tasdiqlash, sign=-1: bekor qilish.
    income (kirim) = kontragent bizga to'ladi → balance += amount (qarz kamayadi)
    expense (chiqim) = biz kontragentga to'laymiz → balance += amount (qarz kamayadi)
    """
    _sync_cash_balance(db, payment.cash_register_id)
    # Kontragent balansini yangilash
    if payment.partner_id:
        partner = db.query(Partner).filter(Partner.id == payment.partner_id).first()
        if partner:
            amount = float(payment.amount or 0)
            if payment.type == "income":
                # Kontragent bizga to'ladi — uning qarzi kamayadi (balance -= amount)
                partner.balance = (partner.balance or 0) - (amount * sign)
            elif payment.type == "expense":
                # Biz kontragentga to'laymiz — bizning qarzimiz kamayadi (balance += amount)
                partner.balance = (partner.balance or 0) + (amount * sign)


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


def _user_owns_cash_register(user, cash_register_id):
    """Foydalanuvchi shu kassaga tegishlimi?"""
    if not user or not cash_register_id:
        return False
    if getattr(user, "cash_register_id", None) == cash_register_id:
        return True
    for cr in (getattr(user, "cash_registers_list", None) or []):
        if cr.id == cash_register_id:
            return True
    return False


@cash_router.get("/transfers", response_class=HTMLResponse)
async def cash_transfers_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Inkasatsiya hujjatlari ro'yxati"""
    role = (getattr(current_user, "role", None) or "").strip().lower()
    q = (
        db.query(CashTransfer)
        .options(
            joinedload(CashTransfer.from_cash),
            joinedload(CashTransfer.to_cash),
            joinedload(CashTransfer.user),
            joinedload(CashTransfer.approved_by),
        )
        .order_by(CashTransfer.created_at.desc())
    )
    # Sotuvchi faqat o'z kassasiga tegishli hujjatlarni ko'radi
    if role not in ("admin", "manager", "menejer", "rahbar", "raxbar"):
        user_cash_ids = []
        if getattr(current_user, "cash_register_id", None):
            user_cash_ids.append(current_user.cash_register_id)
        for cr in (getattr(current_user, "cash_registers_list", None) or []):
            user_cash_ids.append(cr.id)
        if user_cash_ids:
            q = q.filter(CashTransfer.from_cash_id.in_(user_cash_ids))
        else:
            q = q.filter(CashTransfer.id == -1)  # hech narsa ko'rsatma
    transfers = q.limit(100).all()
    return templates.TemplateResponse("cash/transfers_list.html", {
        "request": request,
        "transfers": transfers,
        "current_user": current_user,
        "page_title": "Inkasatsiya — kassadan kassaga o'tkazish",
    })


@cash_router.get("/transfers/new", response_class=HTMLResponse)
async def cash_transfer_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Yangi inkasatsiya hujjati yaratish (faqat admin)"""
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
    return templates.TemplateResponse("cash/transfer_form.html", {
        "request": request,
        "transfer": None,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": "Inkasatsiya yaratish",
    })


@cash_router.post("/transfers/create")
async def cash_transfer_create(
    request: Request,
    from_cash_id: int = Form(...),
    to_cash_id: int = Form(...),
    amount: float = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin inkasatsiya hujjat yaratadi — status: pending"""
    if from_cash_id == to_cash_id:
        return RedirectResponse(url="/cash/transfers/new?error=" + quote("Qayerdan va qayerga kassa bir xil bolmasin."), status_code=303)
    if amount <= 0:
        return RedirectResponse(url="/cash/transfers/new?error=" + quote("Summa 0 dan katta bolishi kerak."), status_code=303)
    last_t = db.query(CashTransfer).order_by(CashTransfer.id.desc()).first()
    num = f"KK-{datetime.now().strftime('%Y%m%d')}-{(last_t.id + 1) if last_t else 1:04d}"
    t = CashTransfer(
        number=num,
        from_cash_id=from_cash_id,
        to_cash_id=to_cash_id,
        amount=amount,
        status="pending",
        user_id=current_user.id if current_user else None,
        note=note or None,
    )
    db.add(t)
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{t.id}", status_code=303)


@cash_router.get("/transfers/my-pending")
async def cash_transfers_my_pending(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuvchining kassasiga tegishli kutilayotgan inkasatsiya hujjatlari (JSON)"""
    role = (getattr(current_user, "role", None) or "").strip().lower()
    # Admin/manager barcha pending hujjatlarni ko'radi
    if role in ("admin", "manager", "menejer", "rahbar", "raxbar"):
        transfers = (
            db.query(CashTransfer)
            .options(joinedload(CashTransfer.from_cash), joinedload(CashTransfer.to_cash))
            .filter(CashTransfer.status == "pending")
            .order_by(CashTransfer.created_at.desc())
            .all()
        )
    else:
        user_cash_ids = []
        if getattr(current_user, "cash_register_id", None):
            user_cash_ids.append(current_user.cash_register_id)
        for cr in (getattr(current_user, "cash_registers_list", None) or []):
            user_cash_ids.append(cr.id)
        if not user_cash_ids:
            return JSONResponse([])
        transfers = (
            db.query(CashTransfer)
            .options(joinedload(CashTransfer.from_cash), joinedload(CashTransfer.to_cash))
            .filter(CashTransfer.from_cash_id.in_(user_cash_ids), CashTransfer.status == "pending")
            .order_by(CashTransfer.created_at.desc())
            .all()
        )
    result = []
    for t in transfers:
        result.append({
            "id": t.id,
            "number": t.number,
            "amount": t.amount or 0,
            "from_cash": t.from_cash.name if t.from_cash else "?",
            "to_cash": t.to_cash.name if t.to_cash else "?",
            "note": t.note or "",
            "date": t.created_at.strftime("%d.%m.%Y %H:%M") if t.created_at else "",
        })
    return JSONResponse(result)


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
        "page_title": f"Inkasatsiya {transfer.number}",
    })


@cash_router.post("/transfers/{transfer_id}/sotuvchi-confirm")
async def cash_transfer_sotuvchi_confirm(
    transfer_id: int,
    request: Request = None,
    inkasator_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuvchi tasdiqlaydi — pulni inkasatorga berdi. Status: pending -> in_transit"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status != "pending":
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Faqat kutilayotgan hujjatni tasdiqlash mumkin."), status_code=303)
    # Sotuvchi faqat o'z kassasidan tasdiqlashi mumkin
    if not _user_owns_cash_register(current_user, t.from_cash_id):
        role = (getattr(current_user, "role", None) or "").strip().lower()
        if role not in ("admin", "manager", "menejer"):
            return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Bu kassa sizga tegishli emas."), status_code=303)
    from_cash = db.query(CashRegister).filter(CashRegister.id == t.from_cash_id).first()
    if not from_cash:
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Kassa topilmadi."), status_code=303)
    amount = t.amount or 0
    if (from_cash.balance or 0) < amount:
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Kassada yetarli mablag yoq."), status_code=303)
    # Inkasator ma'lumotini saqlash (note ga qo'shish)
    if inkasator_id:
        inkasator = db.query(Partner).filter(Partner.id == inkasator_id).first()
        if inkasator:
            ink_note = f"Inkasator: {inkasator.name}"
            t.note = (t.note + " | " + ink_note) if t.note else ink_note
    # Mablag' kassadan ayriladi
    from_cash.balance = (from_cash.balance or 0) - amount
    t.status = "in_transit"
    t.sent_by_user_id = current_user.id
    t.sent_at = datetime.now()
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}?sent=1", status_code=303)


@cash_router.get("/transfers/{transfer_id}/receipt", response_class=HTMLResponse)
async def cash_transfer_receipt(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Inkasatsiya cheki — chop etish uchun"""
    t = db.query(CashTransfer).options(
        joinedload(CashTransfer.from_cash),
        joinedload(CashTransfer.to_cash),
        joinedload(CashTransfer.user),
        joinedload(CashTransfer.sent_by),
    ).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    html = f"""<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<title>Inkasatsiya cheki {t.number}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', Arial, sans-serif; width: 350px; margin: 0 auto; padding: 20px 15px; color: #1a1d21; }}
.header {{ text-align: center; padding-bottom: 15px; border-bottom: 2px dashed #ccc; margin-bottom: 15px; }}
.header h1 {{ font-size: 18px; font-weight: 800; color: #0d6b4b; margin-bottom: 4px; }}
.header .subtitle {{ font-size: 12px; color: #888; }}
.row {{ display: flex; justify-content: space-between; padding: 6px 0; font-size: 13px; border-bottom: 1px solid #f0f0f0; }}
.row .label {{ color: #666; }}
.row .value {{ font-weight: 600; text-align: right; }}
.amount-row {{ padding: 12px 0; margin: 10px 0; border-top: 2px solid #0d6b4b; border-bottom: 2px solid #0d6b4b; }}
.amount-row .label {{ font-size: 14px; font-weight: 700; }}
.amount-row .value {{ font-size: 20px; font-weight: 800; color: #0d6b4b; }}
.footer {{ text-align: center; margin-top: 20px; padding-top: 15px; border-top: 2px dashed #ccc; }}
.footer .sign {{ margin-top: 30px; display: flex; justify-content: space-between; }}
.footer .sign div {{ text-align: center; flex: 1; }}
.footer .sign .line {{ border-bottom: 1px solid #333; height: 25px; margin-bottom: 4px; }}
.footer .sign .name {{ font-size: 10px; color: #888; }}
.status {{ display: inline-block; background: #fff3cd; color: #856404; padding: 3px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; }}
@media print {{ .no-print {{ display: none !important; }} body {{ padding: 10px; }} }}
</style>
</head>
<body>
<div class="no-print" style="margin-bottom:15px;">
    <button onclick="window.print();" style="padding:8px 20px;background:#0d6b4b;color:#fff;border:none;border-radius:8px;font-weight:600;cursor:pointer;">Chop etish</button>
</div>
<div class="header">
    <h1>INKASATSIYA CHEKI</h1>
    <div class="subtitle">Kassadan kassaga pul o'tkazish</div>
</div>
<div class="row"><span class="label">Hujjat №</span><span class="value">{t.number}</span></div>
<div class="row"><span class="label">Sana</span><span class="value">{t.created_at.strftime('%d.%m.%Y %H:%M') if t.created_at else '-'}</span></div>
<div class="row"><span class="label">Qayerdan</span><span class="value">{t.from_cash.name if t.from_cash else '-'}</span></div>
<div class="row"><span class="label">Qayerga</span><span class="value">{t.to_cash.name if t.to_cash else '-'}</span></div>
<div class="row"><span class="label">Status</span><span class="value"><span class="status">{'Yolda' if t.status == 'in_transit' else t.status}</span></span></div>
<div class="row"><span class="label">Jo'natuvchi</span><span class="value">{t.sent_by.full_name or t.sent_by.username if t.sent_by else '-'}</span></div>
<div class="row"><span class="label">Jo'natish vaqti</span><span class="value">{t.sent_at.strftime('%d.%m.%Y %H:%M') if t.sent_at else '-'}</span></div>
{('<div class="row"><span class="label">Izoh</span><span class="value">' + (t.note or '') + '</span></div>') if t.note else ''}
<div class="row amount-row"><span class="label">SUMMA</span><span class="value">{t.amount:,.0f} som</span></div>
<div class="footer">
    <div class="sign">
        <div><div class="line"></div><div class="name">Berdi (sotuvchi)</div></div>
        <div><div class="line"></div><div class="name">Oldi (inkasator)</div></div>
    </div>
</div>
<script>window.onload=function(){{ try {{ window.print(); }} catch(e){{}} }};</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@cash_router.post("/transfers/{transfer_id}/admin-confirm")
async def cash_transfer_admin_confirm(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin qabul qiladi — inkasator pulni yetkazdi. Status: in_transit -> completed"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status != "in_transit":
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Faqat yoldagi hujjatni qabul qilish mumkin."), status_code=303)
    to_cash = db.query(CashRegister).filter(CashRegister.id == t.to_cash_id).first()
    if not to_cash:
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Qabul kassasi topilmadi."), status_code=303)
    # Mablag' qabul kassasiga qo'shiladi
    to_cash.balance = (to_cash.balance or 0) + (t.amount or 0)
    t.status = "completed"
    t.approved_by_user_id = current_user.id
    t.approved_at = datetime.now()
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}?confirmed=1", status_code=303)


# Eski endpoint nomini saqlaymiz (backward compat)
@cash_router.post("/transfers/{transfer_id}/confirm")
async def cash_transfer_confirm_legacy(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Legacy confirm — statusga qarab sotuvchi yoki admin confirm ga yo'naltiradi"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status == "pending":
        return await cash_transfer_sotuvchi_confirm(transfer_id, db=db, current_user=current_user)
    elif t.status == "in_transit":
        return await cash_transfer_admin_confirm(transfer_id, db=db, current_user=current_user)
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}", status_code=303)


@cash_router.post("/transfers/{transfer_id}/revert")
async def cash_transfer_revert(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tasdiqni bekor qilish (faqat admin)"""
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        return RedirectResponse(url="/cash/transfers?error=" + quote("Hujjat topilmadi."), status_code=303)
    amount = t.amount or 0
    if t.status == "completed":
        # completed -> in_transit: qabul kassasidan qaytarish
        to_cash = db.query(CashRegister).filter(CashRegister.id == t.to_cash_id).first()
        if to_cash:
            to_cash.balance = max(0, (to_cash.balance or 0) - amount)
        t.status = "in_transit"
        t.approved_by_user_id = None
        t.approved_at = None
    elif t.status == "in_transit":
        # in_transit -> pending: jo'natuvchi kassaga qaytarish
        from_cash = db.query(CashRegister).filter(CashRegister.id == t.from_cash_id).first()
        if from_cash:
            from_cash.balance = (from_cash.balance or 0) + amount
        t.status = "pending"
        t.sent_by_user_id = None
        t.sent_at = None
    else:
        return RedirectResponse(url=f"/cash/transfers/{transfer_id}?error=" + quote("Bu statusda bekor qilib bolmaydi."), status_code=303)
    db.commit()
    return RedirectResponse(url=f"/cash/transfers/{transfer_id}?reverted=1", status_code=303)


@cash_router.post("/transfers/{transfer_id}/delete")
async def cash_transfer_delete(
    transfer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    t = db.query(CashTransfer).filter(CashTransfer.id == transfer_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if t.status not in ("pending", "draft"):
        return RedirectResponse(url="/cash/transfers?error=" + quote("Faqat kutilayotgan hujjatni o'chirish mumkin."), status_code=303)
    db.delete(t)
    db.commit()
    return RedirectResponse(url="/cash/transfers?deleted=1", status_code=303)
