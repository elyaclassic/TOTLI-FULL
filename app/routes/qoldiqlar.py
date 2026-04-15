"""
Qoldiqlar — kassa, tovar, kontragent qoldiqlari va hujjatlar (1C uslubida).
"""
import io
import traceback
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import openpyxl
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core import templates
from app.utils.user_scope import get_warehouses_for_user
from app.models.database import (
    get_db,
    User,
    Product,
    Partner,
    Warehouse,
    Stock,
    StockMovement,
    CashRegister,
    StockAdjustmentDoc,
    StockAdjustmentDocItem,
    CashBalanceDoc,
    CashBalanceDocItem,
    PartnerBalanceDoc,
    PartnerBalanceDocItem,
    EmployeeBalanceDoc,
    EmployeeBalanceDocItem,
    Order,
    Purchase,
    Payment,
    Employee,
    Salary,
)
from app.deps import require_auth, require_admin
from app.services.stock_service import create_stock_movement, delete_stock_movements_for_document

router = APIRouter(prefix="/qoldiqlar", tags=["qoldiqlar"])


def _tarix_doc_type_label(doc_type: str) -> str:
    """Hujjat turi uchun o'qiladigan nom (tarix sahifasi)."""
    labels = {
        "Purchase": "Kirim",
        "Production": "Ishlab chiqarish",
        "WarehouseTransfer": "Ombordan omborga",
        "StockAdjustmentDoc": "Qoldiq tuzatish",
        "Sale": "Sotuv",
        "SaleReturn": "Qaytish",
    }
    return labels.get(doc_type or "", doc_type or "—")


@router.get("", response_class=HTMLResponse)
async def qoldiqlar_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Qoldiqlar sahifasi: kassa, tovar (forma spiska 1C), kontragent qoldiqlarini kiritish"""
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    warehouses = get_warehouses_for_user(db, current_user)
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
    stocks = db.query(Stock).join(Warehouse).join(Product).order_by(Stock.updated_at.desc()).limit(300).all()
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    tovar_docs = (
        db.query(StockAdjustmentDoc)
        .order_by(StockAdjustmentDoc.id.desc())
        .limit(500)
        .all()
    )
    cash_docs = (
        db.query(CashBalanceDoc)
        .order_by(CashBalanceDoc.created_at.desc())
        .limit(200)
        .all()
    )
    kontragent_docs = (
        db.query(PartnerBalanceDoc)
        .order_by(PartnerBalanceDoc.created_at.desc())
        .limit(200)
        .all()
    )
    # Xodimlar qoldiqlari — har xodimning oxirgi Salary.total qiymati (bitta query)
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    emp_ids = [e.id for e in employees]
    emp_balances = {}
    if emp_ids:
        latest_sal_ids = (
            db.query(func.max(Salary.id))
            .filter(Salary.employee_id.in_(emp_ids))
            .group_by(Salary.employee_id)
            .subquery()
        )
        latest_salaries = db.query(Salary).filter(Salary.id.in_(latest_sal_ids)).all()
        emp_balances = {
            s.employee_id: {"year": s.year, "month": s.month, "total": float(s.total or 0), "status": s.status}
            for s in latest_salaries
        }
    xodim_docs = (
        db.query(EmployeeBalanceDoc)
        .order_by(EmployeeBalanceDoc.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse("qoldiqlar/index.html", {
        "request": request,
        "cash_registers": cash_registers,
        "warehouses": warehouses,
        "products": products,
        "stocks": stocks,
        "partners": partners,
        "tovar_docs": tovar_docs,
        "cash_docs": cash_docs,
        "kontragent_docs": kontragent_docs,
        "employees": employees,
        "emp_balances": emp_balances,
        "xodim_docs": xodim_docs,
        "current_user": current_user,
        "page_title": "Qoldiqlar",
        "show_tannarx": (getattr(current_user, "role", None) if current_user else None) == "admin",
    })


@router.get("/tarix", response_class=HTMLResponse)
async def qoldiqlar_tarix(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    warehouse_id: Optional[str] = None,
    product_id: Optional[str] = None,
):
    """Mahsulot harakati tarixi — tanlanmasa barcha harakatlar; filtr ixtiyoriy (ombor/mahsulot)."""
    try:
        warehouses = db.query(Warehouse).filter(Warehouse.is_active == True).all()
        products = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
        try:
            selected_warehouse_id = int(warehouse_id) if (warehouse_id and str(warehouse_id).strip()) else None
        except (ValueError, TypeError):
            selected_warehouse_id = None
        try:
            selected_product_id = int(product_id) if (product_id and str(product_id).strip()) else None
        except (ValueError, TypeError):
            selected_product_id = None

        q = db.query(StockMovement)
        if selected_warehouse_id:
            q = q.filter(StockMovement.warehouse_id == selected_warehouse_id)
        if selected_product_id:
            q = q.filter(StockMovement.product_id == selected_product_id)
        q = q.order_by(StockMovement.created_at.desc()).limit(500)
        movements = q.all()

        movement_rows = []
        warehouse_ids = [m.warehouse_id for m in movements if m.warehouse_id is not None]
        product_ids = [m.product_id for m in movements if m.product_id is not None]
        wh_by_id = {}
        if warehouse_ids:
            for w in db.query(Warehouse).filter(Warehouse.id.in_(set(warehouse_ids))).all():
                wh_by_id[w.id] = w
        prod_by_id = {}
        if product_ids:
            for p in db.query(Product).filter(Product.id.in_(set(product_ids))).all():
                prod_by_id[p.id] = p
        for m in movements:
            wh = wh_by_id.get(m.warehouse_id) if m.warehouse_id is not None else None
            pr = prod_by_id.get(m.product_id) if m.product_id is not None else None
            movement_rows.append({
                "date": m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "—",
                "warehouse_name": (getattr(wh, "name", None) if wh else None) or (f"#{m.warehouse_id}" if m.warehouse_id is not None else "—"),
                "product_name": (getattr(pr, "name", None) if pr else None) or (f"#{m.product_id}" if m.product_id is not None else "—"),
                "product_code": (getattr(pr, "code", None) or "") if pr else "",
                "doc_type_label": _tarix_doc_type_label(m.document_type or ""),
                "doc_number": m.document_number or (f"{m.document_type or ''}-{m.document_id}" if m.document_id else "—"),
                "quantity_change": float(m.quantity_change or 0),
                "warehouse_id": m.warehouse_id,
                "product_id": m.product_id,
            })

        return templates.TemplateResponse("qoldiqlar/tarix.html", {
            "request": request,
            "current_user": current_user,
            "warehouses": warehouses,
            "products": products,
            "selected_product_id": selected_product_id,
            "selected_warehouse_id": selected_warehouse_id,
            "movements": movement_rows,
            "page_title": "Qoldiqlar — Mahsulot harakati tarixi",
        })
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("qoldiqlar_tarix: %s", e)
        try:
            _wh = db.query(Warehouse).filter(Warehouse.is_active == True).all()
            _pr = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
        except Exception:
            _wh = []
            _pr = []
        return templates.TemplateResponse("qoldiqlar/tarix.html", {
            "request": request,
            "current_user": current_user,
            "warehouses": _wh,
            "products": _pr,
            "selected_product_id": None,
            "selected_warehouse_id": None,
            "movements": [],
            "page_title": "Qoldiqlar — Mahsulot harakati tarixi",
            "error_message": "Ma'lumotlarni yuklashda xatolik yuz berdi",
        }, status_code=500)


@router.post("/kassa/{cash_id:int}")
async def qoldiqlar_kassa_save(
    cash_id: int,
    balance: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Kassa opening_balance ni to'g'ridan-to'g'ri o'rnatish (faqat admin, faqat boshlang'ich qoldiq uchun)"""
    cash = db.query(CashRegister).filter(CashRegister.id == cash_id).first()
    if not cash:
        raise HTTPException(status_code=404, detail="Kassa topilmadi")
    from app.services.finance_service import sync_cash_balance
    cash.opening_balance = balance
    db.flush()
    sync_cash_balance(db, cash_id)
    db.commit()
    return RedirectResponse(url="/qoldiqlar#kassa", status_code=303)


# --- Kassa qoldiq HUJJATLARI (1C uslubida) ---
@router.get("/kassa/hujjat/new", response_class=HTMLResponse)
async def qoldiqlar_kassa_hujjat_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Yangi kassa qoldiq hujjati"""
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    return templates.TemplateResponse("qoldiqlar/kassa_hujjat_form.html", {
        "request": request,
        "doc": None,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": "Kassa qoldiqlari — yangi hujjat",
    })


@router.post("/kassa/hujjat")
async def qoldiqlar_kassa_hujjat_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kassa qoldiq hujjatini yaratish (qoralama)"""
    form = await request.form()
    cash_ids = form.getlist("cash_register_id")
    balances = form.getlist("balance")

    items_data = []
    for i, cid in enumerate(cash_ids):
        if not cid:
            continue
        try:
            bid = int(cid)
            bal = float(balances[i]) if i < len(balances) and balances[i] != "" else None
        except (TypeError, ValueError):
            continue
        if bal is not None:
            items_data.append((bid, bal))

    if not items_data:
        return RedirectResponse(url="/qoldiqlar/kassa/hujjat/new", status_code=303)

    today = datetime.now()
    count = db.query(CashBalanceDoc).filter(
        CashBalanceDoc.date >= today.replace(hour=0, minute=0, second=0)
    ).count()
    number = f"KLD-{today.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

    doc = CashBalanceDoc(
        number=number,
        date=today,
        user_id=current_user.id if current_user else None,
        status="draft",
    )
    db.add(doc)
    db.flush()
    for cid, bal in items_data:
        db.add(CashBalanceDocItem(doc_id=doc.id, cash_register_id=cid, balance=bal))
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/kassa/hujjat/{doc.id}", status_code=303)


@router.get("/kassa/hujjat/{doc_id}", response_class=HTMLResponse)
async def qoldiqlar_kassa_hujjat_view(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kassa qoldiq hujjatini ko'rish"""
    doc = db.query(CashBalanceDoc).filter(CashBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    return templates.TemplateResponse("qoldiqlar/kassa_hujjat_form.html", {
        "request": request,
        "doc": doc,
        "cash_registers": cash_registers,
        "current_user": current_user,
        "page_title": f"Kassa qoldiqlari {doc.number}",
    })


@router.post("/kassa/hujjat/{doc_id}/tasdiqlash")
async def qoldiqlar_kassa_hujjat_tasdiqlash(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kassa hujjatini tasdiqlash — kassa balanslarini yangilash"""
    doc = db.query(CashBalanceDoc).filter(CashBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Hujjat allaqachon tasdiqlangan")
    if not doc.items:
        raise HTTPException(status_code=400, detail="Kamida bitta kassa qatori bo'lishi kerak")
    from app.services.finance_service import cash_balance_formula as _cash_balance_formula
    for item in doc.items:
        cash = db.query(CashRegister).filter(CashRegister.id == item.cash_register_id).first()
        if cash:
            item.previous_balance = cash.balance
            # Hozirgi hisoblangan balans
            current_balance, income_sum, expense_sum = _cash_balance_formula(db, cash.id)
            # Qo'shish: eski balansga kiritilgan qiymatni qo'shamiz
            delta = float(item.balance or 0)
            target = current_balance + delta
            # opening_balance ni shunday moslaymizki: opening + income - expense = target
            cash.opening_balance = target - income_sum + expense_sum
            cash.balance = target
    doc.status = "confirmed"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/kassa/hujjat/{doc_id}", status_code=303)


@router.post("/kassa/hujjat/{doc_id}/revert")
async def qoldiqlar_kassa_hujjat_revert(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Kassa hujjati tasdiqini bekor qilish (faqat admin)"""
    doc = db.query(CashBalanceDoc).filter(CashBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "confirmed":
        raise HTTPException(status_code=400, detail="Faqat tasdiqlangan hujjatning tasdiqini bekor qilish mumkin")
    from app.services.finance_service import cash_balance_formula as _cash_balance_formula
    for item in doc.items:
        cash = db.query(CashRegister).filter(CashRegister.id == item.cash_register_id).first()
        if cash and item.previous_balance is not None:
            # Oldingi balansga qaytish uchun opening_balance ni moslash
            current_balance, income_sum, expense_sum = _cash_balance_formula(db, cash.id)
            target = float(item.previous_balance)
            cash.opening_balance = target - income_sum + expense_sum
            cash.balance = target
    doc.status = "draft"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/kassa/hujjat/{doc_id}", status_code=303)


@router.post("/kassa/hujjat/{doc_id}/delete")
async def qoldiqlar_kassa_hujjat_delete(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Kassa hujjatini o'chirish (faqat qoralama, faqat admin)"""
    doc = db.query(CashBalanceDoc).filter(CashBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralama holatidagi hujjatni o'chirish mumkin. Avval tasdiqni bekor qiling.")
    db.delete(doc)
    db.commit()
    return RedirectResponse(url="/qoldiqlar#kassa", status_code=303)


# --- Kontragent qoldiq HUJJATLARI (1C uslubida) ---
@router.get("/kontragent/hujjat/new", response_class=HTMLResponse)
async def qoldiqlar_kontragent_hujjat_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Yangi kontragent balans hujjati"""
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    today_str = datetime.now().strftime("%Y-%m-%d")
    return templates.TemplateResponse("qoldiqlar/kontragent_hujjat_form.html", {
        "request": request,
        "doc": None,
        "partners": partners,
        "current_user": current_user,
        "today_str": today_str,
        "page_title": "Kontragent qoldiqlari — yangi hujjat",
    })


@router.post("/kontragent/hujjat")
async def qoldiqlar_kontragent_hujjat_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kontragent balans hujjatini yaratish (qoralama)"""
    form = await request.form()
    partner_ids = form.getlist("partner_id")
    balances = form.getlist("balance")

    # Formadan sanani olish
    doc_date_str = form.get("doc_date", "")
    if doc_date_str:
        try:
            doc_date = datetime.strptime(doc_date_str, "%Y-%m-%d")
        except ValueError:
            doc_date = datetime.now()
    else:
        doc_date = datetime.now()

    items_data = []
    for i, pid in enumerate(partner_ids):
        if not pid:
            continue
        try:
            pid_int = int(pid)
            bal_str = (balances[i] if i < len(balances) else "").strip()
            if not bal_str:
                continue
            bal = float(bal_str)
        except (TypeError, ValueError):
            continue
        items_data.append((pid_int, bal))

    if not items_data:
        return RedirectResponse(url="/qoldiqlar/kontragent/hujjat/new", status_code=303)

    count = db.query(PartnerBalanceDoc).filter(
        PartnerBalanceDoc.date >= doc_date.replace(hour=0, minute=0, second=0),
        PartnerBalanceDoc.date < doc_date.replace(hour=23, minute=59, second=59)
    ).count()
    number = f"KNT-{doc_date.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

    doc = PartnerBalanceDoc(
        number=number,
        date=doc_date,
        user_id=current_user.id if current_user else None,
        status="draft",
    )
    db.add(doc)
    db.flush()
    for pid, bal in items_data:
        db.add(PartnerBalanceDocItem(doc_id=doc.id, partner_id=pid, balance=bal))
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/kontragent/hujjat/{doc.id}", status_code=303)


@router.get("/kontragent/hujjat/{doc_id}", response_class=HTMLResponse)
async def qoldiqlar_kontragent_hujjat_view(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kontragent balans hujjatini ko'rish"""
    doc = db.query(PartnerBalanceDoc).filter(PartnerBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    return templates.TemplateResponse("qoldiqlar/kontragent_hujjat_form.html", {
        "request": request,
        "doc": doc,
        "partners": partners,
        "current_user": current_user,
        "page_title": f"Kontragent qoldiqlari {doc.number}",
    })


@router.post("/kontragent/hujjat/{doc_id}/tasdiqlash")
async def qoldiqlar_kontragent_hujjat_tasdiqlash(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kontragent hujjatini tasdiqlash — kontragent balanslarini yangilash"""
    doc = db.query(PartnerBalanceDoc).filter(PartnerBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Hujjat allaqachon tasdiqlangan")
    if not doc.items:
        raise HTTPException(status_code=400, detail="Kamida bitta kontragent qatori bo'lishi kerak")
    for item in doc.items:
        partner = db.query(Partner).filter(Partner.id == item.partner_id).first()
        if partner:
            item.previous_balance = partner.balance
            partner.balance = (partner.balance or 0) + item.balance  # Mavjud balansga QO'SHISH
    doc.status = "confirmed"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/kontragent/hujjat/{doc_id}", status_code=303)


@router.post("/kontragent/hujjat/{doc_id}/revert")
async def qoldiqlar_kontragent_hujjat_revert(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Kontragent hujjati tasdiqini bekor qilish (faqat admin)"""
    doc = db.query(PartnerBalanceDoc).filter(PartnerBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "confirmed":
        raise HTTPException(status_code=400, detail="Faqat tasdiqlangan hujjatning tasdiqini bekor qilish mumkin")
    for item in doc.items:
        partner = db.query(Partner).filter(Partner.id == item.partner_id).first()
        if partner and item.previous_balance is not None:
            partner.balance = item.previous_balance
    doc.status = "draft"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/kontragent/hujjat/{doc_id}", status_code=303)


@router.post("/kontragent/hujjat/{doc_id}/delete")
async def qoldiqlar_kontragent_hujjat_delete(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Kontragent hujjatini o'chirish (faqat qoralama, faqat admin)"""
    doc = db.query(PartnerBalanceDoc).filter(PartnerBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralama holatidagi hujjatni o'chirish mumkin. Avval tasdiqni bekor qiling.")
    db.delete(doc)
    db.commit()
    return RedirectResponse(url="/qoldiqlar#kontragent", status_code=303)


@router.post("/tovar")
async def qoldiqlar_tovar_save(
    warehouse_id: int = Form(...),
    product_id: int = Form(...),
    quantity: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tovar qoldig'ini kiritish yoki qo'shish (omborda mavjud bo'lsa qo'shiladi). StockMovement audit trail bilan."""
    if quantity < 0:
        return RedirectResponse(url="/qoldiqlar#tovar", status_code=303)
    from app.services.stock_service import create_stock_movement
    create_stock_movement(
        db=db,
        warehouse_id=warehouse_id,
        product_id=product_id,
        quantity_change=quantity,
        operation_type="manual_add",
        document_type="ManualAdjustment",
        document_id=0,
        document_number="MANUAL",
        user_id=current_user.id if current_user else None,
        note="Qo'lda qoldiq kiritish",
    )
    db.commit()
    return RedirectResponse(url="/qoldiqlar#tovar", status_code=303)


# ==========================================
# XODIM QOLDIQLARI HUJJAT TIZIMI
# ==========================================

@router.get("/xodim/hujjat/new", response_class=HTMLResponse)
async def qoldiqlar_xodim_hujjat_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Yangi xodim balans hujjati"""
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    today_str = datetime.now().strftime("%Y-%m-%d")
    return templates.TemplateResponse("qoldiqlar/xodim_hujjat_form.html", {
        "request": request,
        "doc": None,
        "employees": employees,
        "current_user": current_user,
        "today_str": today_str,
        "page_title": "Xodim qoldiqlari — yangi hujjat",
    })


@router.post("/xodim/hujjat")
async def qoldiqlar_xodim_hujjat_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodim balans hujjatini yaratish (qoralama)"""
    form = await request.form()
    employee_ids = form.getlist("employee_id")
    balances = form.getlist("balance")
    doc_date_str = form.get("doc_date", "")
    if doc_date_str:
        try:
            doc_date = datetime.strptime(doc_date_str, "%Y-%m-%d")
        except ValueError:
            doc_date = datetime.now()
    else:
        doc_date = datetime.now()

    items_data = []
    for i, eid in enumerate(employee_ids):
        if not eid:
            continue
        try:
            eid_int = int(eid)
            bal_str = (balances[i] if i < len(balances) else "").strip()
            if not bal_str:
                continue
            bal = float(bal_str)
        except (TypeError, ValueError):
            continue
        items_data.append((eid_int, bal))

    if not items_data:
        return RedirectResponse(url="/qoldiqlar/xodim/hujjat/new", status_code=303)

    count = db.query(EmployeeBalanceDoc).filter(
        EmployeeBalanceDoc.date >= doc_date.replace(hour=0, minute=0, second=0),
        EmployeeBalanceDoc.date < doc_date.replace(hour=23, minute=59, second=59)
    ).count()
    number = f"XOD-{doc_date.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

    doc = EmployeeBalanceDoc(
        number=number,
        date=doc_date,
        user_id=current_user.id if current_user else None,
        status="draft",
    )
    db.add(doc)
    db.flush()
    for eid, bal in items_data:
        db.add(EmployeeBalanceDocItem(doc_id=doc.id, employee_id=eid, balance=bal))
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/xodim/hujjat/{doc.id}", status_code=303)


@router.get("/xodim/hujjat/{doc_id}", response_class=HTMLResponse)
async def qoldiqlar_xodim_hujjat_view(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodim balans hujjatini ko'rish"""
    doc = db.query(EmployeeBalanceDoc).filter(EmployeeBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    return templates.TemplateResponse("qoldiqlar/xodim_hujjat_form.html", {
        "request": request,
        "doc": doc,
        "employees": employees,
        "current_user": current_user,
        "page_title": f"Xodim qoldiqlari {doc.number}",
    })


@router.post("/xodim/hujjat/{doc_id}/tasdiqlash")
async def qoldiqlar_xodim_hujjat_tasdiqlash(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Xodim hujjatini tasdiqlash — Salary jadvaliga yozish"""
    doc = db.query(EmployeeBalanceDoc).filter(EmployeeBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Hujjat allaqachon tasdiqlangan")
    if not doc.items:
        raise HTTPException(status_code=400, detail="Kamida bitta xodim qatori bo'lishi kerak")
    now = datetime.now()
    year, month = doc.date.year if doc.date else now.year, doc.date.month if doc.date else now.month
    for item in doc.items:
        emp = db.query(Employee).filter(Employee.id == item.employee_id).first()
        if not emp:
            continue
        s = db.query(Salary).filter(Salary.employee_id == item.employee_id, Salary.year == year, Salary.month == month).first()
        old_total = float(s.total or 0) if s else 0
        item.previous_balance = old_total
        if not s:
            s = Salary(employee_id=item.employee_id, year=year, month=month)
            db.add(s)
        # Hujjatda: musbat = xodim qarzi, manfiy = bizning qarzimiz
        # Salary da: musbat = biz to'lashimiz kerak, manfiy = xodim qarzda
        # Shuning uchun ishorani teskari qilamiz
        new_total = old_total - item.balance
        s.base_salary = max(0, abs(new_total))
        s.total = new_total
        if s.paid is None:
            s.paid = 0
        s.status = "paid" if new_total <= 0 else "pending"
        s.is_balance_entry = True
    doc.status = "confirmed"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/xodim/hujjat/{doc_id}", status_code=303)


@router.post("/xodim/hujjat/{doc_id}/revert")
async def qoldiqlar_xodim_hujjat_revert(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Xodim hujjati tasdiqini bekor qilish (faqat admin)"""
    doc = db.query(EmployeeBalanceDoc).filter(EmployeeBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "confirmed":
        raise HTTPException(status_code=400, detail="Faqat tasdiqlangan hujjatning tasdiqini bekor qilish mumkin")
    now = datetime.now()
    year, month = doc.date.year if doc.date else now.year, doc.date.month if doc.date else now.month
    for item in doc.items:
        if item.previous_balance is not None:
            s = db.query(Salary).filter(Salary.employee_id == item.employee_id, Salary.year == year, Salary.month == month).first()
            if s:
                s.total = item.previous_balance
                s.base_salary = max(0, item.previous_balance)
                s.status = "paid" if item.previous_balance <= 0 else "pending"
    doc.status = "draft"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/xodim/hujjat/{doc_id}", status_code=303)


@router.post("/xodim/hujjat/{doc_id}/delete")
async def qoldiqlar_xodim_hujjat_delete(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Xodim hujjatini o'chirish (faqat qoralama, faqat admin)"""
    doc = db.query(EmployeeBalanceDoc).filter(EmployeeBalanceDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralama holatidagi hujjatni o'chirish mumkin")
    db.delete(doc)
    db.commit()
    return RedirectResponse(url="/qoldiqlar?tab=xodim", status_code=303)


@router.post("/xodim/hujjat/{doc_id}/add-row")
async def qoldiqlar_xodim_hujjat_add_row(
    doc_id: int,
    employee_id: int = Form(...),
    balance: float = Form(...),
    balance_type: int = Form(1),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Draft hujjatga qator qo'shish"""
    doc = db.query(EmployeeBalanceDoc).filter(EmployeeBalanceDoc.id == doc_id).first()
    if not doc or doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    bal = abs(balance) * (1 if balance_type == 1 else -1)
    # Dublikat tekshiruv
    existing = db.query(EmployeeBalanceDocItem).filter(
        EmployeeBalanceDocItem.doc_id == doc_id,
        EmployeeBalanceDocItem.employee_id == employee_id,
    ).first()
    if existing:
        existing.balance = bal
    else:
        db.add(EmployeeBalanceDocItem(doc_id=doc_id, employee_id=employee_id, balance=bal))
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/xodim/hujjat/{doc_id}", status_code=303)


@router.post("/xodim/hujjat/{doc_id}/delete-row/{item_id}")
async def qoldiqlar_xodim_hujjat_delete_row(
    doc_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Draft hujjatdan qatorni o'chirish"""
    doc = db.query(EmployeeBalanceDoc).filter(EmployeeBalanceDoc.id == doc_id).first()
    if not doc or doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    item = db.query(EmployeeBalanceDocItem).filter(
        EmployeeBalanceDocItem.id == item_id,
        EmployeeBalanceDocItem.doc_id == doc_id,
    ).first()
    if item:
        db.delete(item)
        db.commit()
    return RedirectResponse(url=f"/qoldiqlar/xodim/hujjat/{doc_id}", status_code=303)


@router.post("/kontragent/recalculate")
async def qoldiqlar_kontragent_recalculate(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Barcha kontragent balanslarini qayta hisoblash (admin).
    Hisoblash: sotuvlar qarz + qoldiq hujjatlari - xaridlar - kirim to'lovlar + chiqim to'lovlar - qaytarishlar
    """
    from sqlalchemy import or_
    partners = db.query(Partner).filter(Partner.is_active == True).all()
    updated = 0
    for partner in partners:
        bal = 0.0
        # 1. Sotuvlar — qarz (confirmed/completed)
        sale_debt = db.query(func.coalesce(func.sum(Order.debt), 0)).filter(
            Order.partner_id == partner.id,
            Order.type == "sale",
            Order.status.in_(["confirmed", "completed"]),
        ).scalar()
        bal += float(sale_debt or 0)

        # 2. Qaytarishlar — kredit (confirmed/completed)
        return_total = db.query(func.coalesce(func.sum(Order.total), 0)).filter(
            Order.partner_id == partner.id,
            Order.type == "return_sale",
            Order.status.in_(["confirmed", "completed"]),
        ).scalar()
        bal -= float(return_total or 0)

        # 3. Xaridlar — kredit (confirmed)
        purchase_total = db.query(func.coalesce(func.sum(Purchase.total + func.coalesce(Purchase.total_expenses, 0)), 0)).filter(
            Purchase.partner_id == partner.id,
            Purchase.status == "confirmed",
        ).scalar()
        bal -= float(purchase_total or 0)

        # 4. To'lovlar (confirmed)
        # POS naqd sotuvlarda order.debt=0 lekin Payment yaratiladi (kassa uchun).
        # Bu paymentlarni hisobga olmaslik kerak — aks holda balans manfiy bo'ladi.
        pos_paid_order_ids = db.query(Order.id).filter(
            Order.partner_id == partner.id,
            Order.type == "sale",
            Order.debt == 0,
            Order.paid > 0,
            Order.status.in_(["confirmed", "completed"]),
        ).subquery()

        income_total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.partner_id == partner.id,
            Payment.type == "income",
            or_(Payment.status == "confirmed", Payment.status.is_(None)),
            or_(Payment.order_id == None, ~Payment.order_id.in_(pos_paid_order_ids)),
        ).scalar()
        bal -= float(income_total or 0)

        expense_total = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
            Payment.partner_id == partner.id,
            Payment.type == "expense",
            or_(Payment.status == "confirmed", Payment.status.is_(None)),
        ).scalar()
        bal += float(expense_total or 0)

        # 5. Qoldiq hujjatlari (confirmed) — qo'shish
        balance_doc_total = (
            db.query(func.coalesce(func.sum(PartnerBalanceDocItem.balance), 0))
            .join(PartnerBalanceDoc, PartnerBalanceDocItem.doc_id == PartnerBalanceDoc.id)
            .filter(
                PartnerBalanceDocItem.partner_id == partner.id,
                PartnerBalanceDoc.status == "confirmed",
            )
            .scalar()
        )
        bal += float(balance_doc_total or 0)

        old_bal = partner.balance or 0
        if abs(old_bal - bal) > 0.01:
            partner.balance = bal
            updated += 1

    db.commit()
    return RedirectResponse(
        url=f"/qoldiqlar?msg={updated} ta kontragent balansi qayta hisoblandi",
        status_code=303,
    )


@router.post("/kontragent/{partner_id}")
async def qoldiqlar_kontragent_save(
    partner_id: int,
    balance: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kontragent balansini yangilash"""
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        raise HTTPException(status_code=404, detail="Kontragent topilmadi")
    balance_str = (balance or "").strip()
    if not balance_str:
        return RedirectResponse(url="/qoldiqlar#kontragent", status_code=303)
    try:
        partner.balance = float(balance_str)
    except (TypeError, ValueError):
        return RedirectResponse(url="/qoldiqlar#kontragent", status_code=303)
    db.commit()
    return RedirectResponse(url="/qoldiqlar#kontragent", status_code=303)


@router.get("/export")
async def qoldiqlar_export(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tovar qoldiqlari hisoboti — Excel hujjat sifatida yuklab olish"""
    stocks = (
        db.query(Stock)
        .join(Warehouse, Stock.warehouse_id == Warehouse.id)
        .join(Product, Stock.product_id == Product.id)
        .order_by(Warehouse.name, Product.name)
        .all()
    )
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Tovar qoldiqlari"
    ws.append(["Ombor", "Mahsulot", "Kod", "Miqdor"])
    for s in stocks:
        ws.append([
            s.warehouse.name if s.warehouse else "-",
            s.product.name if s.product else "-",
            (s.product.code or "") if s.product else "",
            float(s.quantity) if s.quantity is not None else 0,
        ])
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=tovar_qoldiqlari.xlsx"},
    )


# --- Tovar qoldiq HUJJATLARI (1C uslubida: ro'yxat + hujjat + qatorlar) ---
@router.get("/tovar/hujjat", response_class=HTMLResponse)
async def qoldiqlar_tovar_hujjat_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tovar qoldiqlari hujjatlari ro'yxati"""
    docs = (
        db.query(StockAdjustmentDoc)
        .order_by(StockAdjustmentDoc.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse("qoldiqlar/hujjat_list.html", {
        "request": request,
        "docs": docs,
        "current_user": current_user,
        "page_title": "Tovar qoldiqlari hujjatlari",
        "show_tannarx": (getattr(current_user, "role", None) if current_user else None) == "admin",
    })


@router.get("/tovar/hujjat/new", response_class=HTMLResponse)
async def qoldiqlar_tovar_hujjat_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Yangi tovar qoldiq hujjati (qoralama)"""
    warehouses = get_warehouses_for_user(db, current_user)
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
    return templates.TemplateResponse("qoldiqlar/hujjat_form.html", {
        "request": request,
        "doc": None,
        "warehouses": warehouses,
        "products": products,
        "current_user": current_user,
        "page_title": "Tovar qoldiqlari — yangi hujjat",
        "show_tannarx": (getattr(current_user, "role", None) if current_user else None) == "admin",
        "now": datetime.now(),
    })


@router.post("/tovar/hujjat")
async def qoldiqlar_tovar_hujjat_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tovar qoldiq hujjatini yaratish (qoralama)"""
    form = await request.form()
    product_ids = form.getlist("product_id")
    warehouse_ids = form.getlist("warehouse_id")
    quantities = form.getlist("quantity")
    cost_prices = form.getlist("cost_price")
    sale_prices = form.getlist("sale_price")

    items_data = []
    for i, pid in enumerate(product_ids):
        if not pid or not str(pid).strip():
            continue
        try:
            wid = int(warehouse_ids[i]) if i < len(warehouse_ids) and warehouse_ids[i] else None
            qty = float(quantities[i]) if i < len(quantities) and str(quantities[i]).strip() else 0
            _cp = cost_prices[i] if i < len(cost_prices) else ""
            _sp = sale_prices[i] if i < len(sale_prices) else ""
            cp = float(_cp) if str(_cp).strip() else 0
            sp = float(_sp) if str(_sp).strip() else 0
        except (TypeError, ValueError):
            continue
        if wid and qty > 0:
            try:
                items_data.append((int(pid), wid, qty, cp, sp))
            except ValueError:
                continue

    # Sana: formdan kelgan yoki hozirgi vaqt
    doc_date_str = form.get("doc_date", "")
    if doc_date_str and str(doc_date_str).strip():
        try:
            doc_date = datetime.fromisoformat(str(doc_date_str))
        except (ValueError, TypeError):
            doc_date = datetime.now()
    else:
        doc_date = datetime.now()

    count = db.query(StockAdjustmentDoc).filter(
        StockAdjustmentDoc.date >= doc_date.replace(hour=0, minute=0, second=0)
    ).count()
    number = f"QLD-{doc_date.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

    total_tannarx = sum(qty * cp for _, _, qty, cp, _ in items_data)
    total_sotuv = sum(qty * sp for _, _, qty, _, sp in items_data)

    doc = StockAdjustmentDoc(
        number=number,
        date=doc_date,
        user_id=current_user.id if current_user else None,
        status="draft",
        total_tannarx=total_tannarx,
        total_sotuv=total_sotuv,
    )
    db.add(doc)
    db.flush()

    for pid, wid, qty, cp, sp in items_data:
        db.add(StockAdjustmentDocItem(
            doc_id=doc.id,
            product_id=pid,
            warehouse_id=wid,
            quantity=qty,
            cost_price=cp,
            sale_price=sp,
        ))
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc.id}", status_code=303)


@router.post("/tovar/import-excel")
async def qoldiqlar_tovar_import_excel(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Exceldan tovar qoldiqlarini yuklash — hujjat (QLD-...) yaratiladi, jadvalda ko'rinadi."""
    form = await request.form()
    file = form.get("file") or form.get("excel_file")
    if not file or not getattr(file, "filename", None):
        return RedirectResponse(url="/qoldiqlar?error=import&detail=" + quote("Excel fayl tanlang") + "#tovar", status_code=303)
    try:
        contents = await file.read()
        if not contents:
            return RedirectResponse(url="/qoldiqlar?error=import&detail=" + quote("Fayl bo'sh") + "#tovar", status_code=303)
        wb = openpyxl.load_workbook(io.BytesIO(contents), read_only=False, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        items_data = []
        for row in rows:
            if not row or (row[0] is None and (len(row) < 2 or row[1] is None)):
                continue
            wh_key = str(row[0] or "").strip() if len(row) > 0 else ""
            raw_prod = row[1] if len(row) > 1 else None
            if raw_prod is not None and isinstance(raw_prod, (int, float)) and float(raw_prod) == int(float(raw_prod)):
                prod_key = str(int(float(raw_prod)))
            else:
                prod_key = str(raw_prod or "").strip()
            try:
                qty = float(row[2]) if len(row) > 2 and row[2] is not None else 0
            except (TypeError, ValueError):
                qty = 0
            cp = 0.0
            sp = 0.0
            if len(row) > 3 and row[3] is not None and row[3] != "":
                try:
                    cp = float(row[3])
                except (TypeError, ValueError):
                    pass
            if len(row) > 4 and row[4] is not None and row[4] != "":
                try:
                    sp = float(row[4])
                except (TypeError, ValueError):
                    pass
            if not wh_key or not prod_key or qty <= 0:
                continue
            warehouse = db.query(Warehouse).filter(
                (func.lower(Warehouse.name) == wh_key.lower()) | (Warehouse.code == wh_key)
            ).first()
            product = db.query(Product).filter(
                (Product.code == prod_key) | (Product.barcode == prod_key)
            ).first()
            if not product and prod_key:
                product = db.query(Product).filter(
                    Product.name.isnot(None),
                    func.lower(Product.name) == prod_key.lower()
                ).first()
            if not warehouse or not product:
                continue
            items_data.append((product.id, warehouse.id, qty, cp, sp))
        if not items_data:
            return RedirectResponse(
                url="/qoldiqlar?error=import&detail=" + quote("Hech qanday to'g'ri qator topilmadi. Ombor va mahsulot nomi/kodi to'g'ri ekanligini tekshiring.") + "#tovar",
                status_code=303,
            )
        today = datetime.now()
        count = db.query(StockAdjustmentDoc).filter(
            StockAdjustmentDoc.date >= today.replace(hour=0, minute=0, second=0)
        ).count()
        number = f"QLD-{today.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"
        total_tannarx = sum(qty * cp for _, _, qty, cp, _ in items_data)
        total_sotuv = sum(qty * sp for _, _, qty, _, sp in items_data)
        doc = StockAdjustmentDoc(
            number=number,
            date=today,
            user_id=current_user.id if current_user else None,
            status="draft",
            total_tannarx=total_tannarx,
            total_sotuv=total_sotuv,
        )
        db.add(doc)
        db.flush()
        for pid, wid, qty, cp, sp in items_data:
            db.add(StockAdjustmentDocItem(
                doc_id=doc.id,
                product_id=pid,
                warehouse_id=wid,
                quantity=qty,
                cost_price=cp,
                sale_price=sp,
            ))
        db.commit()
        return RedirectResponse(
            url="/qoldiqlar?success=import&doc_number=" + quote(doc.number) + "#tovar",
            status_code=303,
        )
    except Exception as e:
        pass  # logged above
        return RedirectResponse(
            url="/qoldiqlar?error=import&detail=" + quote("Import xatoligi. Fayl formatini tekshiring.") + "#tovar",
            status_code=303,
        )


@router.get("/tovar/hujjat/{doc_id}", response_class=HTMLResponse)
async def qoldiqlar_tovar_hujjat_view(
    request: Request,
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tovar qoldiq hujjatini ko'rish/tahrirlash"""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    warehouses = get_warehouses_for_user(db, current_user)
    products = db.query(Product).filter(Product.is_active == True).order_by(Product.name).all()
    return templates.TemplateResponse("qoldiqlar/hujjat_form.html", {
        "request": request,
        "doc": doc,
        "warehouses": warehouses,
        "products": products,
        "current_user": current_user,
        "page_title": f"Tovar qoldiqlari {doc.number}",
        "show_tannarx": (getattr(current_user, "role", None) if current_user else None) == "admin",
    })


@router.post("/tovar/hujjat/{doc_id}/add-row")
async def qoldiqlar_tovar_hujjat_add_row(
    doc_id: int,
    product_id: int = Form(...),
    warehouse_id: int = Form(...),
    quantity: float = Form(...),
    cost_price: float = Form(0),
    sale_price: float = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hujjatga qator qo'shish (faqat qoralama)"""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc or doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    if quantity <= 0:
        return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)
    # Dublikat tekshiruv: bir xil ombor+mahsulot bo'lsa — miqdorni yangilash
    existing_item = db.query(StockAdjustmentDocItem).filter(
        StockAdjustmentDocItem.doc_id == doc_id,
        StockAdjustmentDocItem.product_id == product_id,
        StockAdjustmentDocItem.warehouse_id == warehouse_id,
    ).first()
    if existing_item:
        # Eski summalarni chiqarish
        doc.total_tannarx = (doc.total_tannarx or 0) - (existing_item.quantity * (existing_item.cost_price or 0))
        doc.total_sotuv = (doc.total_sotuv or 0) - (existing_item.quantity * (existing_item.sale_price or 0))
        existing_item.quantity = quantity
        existing_item.cost_price = cost_price or 0
        existing_item.sale_price = sale_price or 0
        doc.total_tannarx = (doc.total_tannarx or 0) + quantity * (cost_price or 0)
        doc.total_sotuv = (doc.total_sotuv or 0) + quantity * (sale_price or 0)
        db.commit()
        return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)
    doc.total_tannarx = (doc.total_tannarx or 0) + quantity * (cost_price or 0)
    doc.total_sotuv = (doc.total_sotuv or 0) + quantity * (sale_price or 0)
    db.add(StockAdjustmentDocItem(
        doc_id=doc_id,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity=quantity,
        cost_price=cost_price or 0,
        sale_price=sale_price or 0,
    ))
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)


@router.post("/tovar/hujjat/{doc_id}/delete-row/{item_id}")
async def qoldiqlar_tovar_hujjat_delete_row(
    doc_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hujjatdan qatorni o'chirish (faqat qoralama)"""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc or doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    item = db.query(StockAdjustmentDocItem).filter(
        StockAdjustmentDocItem.id == item_id,
        StockAdjustmentDocItem.doc_id == doc_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Qator topilmadi")
    doc.total_tannarx = (doc.total_tannarx or 0) - (item.quantity * (item.cost_price or 0))
    doc.total_sotuv = (doc.total_sotuv or 0) - (item.quantity * (item.sale_price or 0))
    if doc.total_tannarx < 0:
        doc.total_tannarx = 0
    if doc.total_sotuv < 0:
        doc.total_sotuv = 0
    db.delete(item)
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)


@router.post("/tovar/hujjat/{doc_id}/edit-row/{item_id}")
async def qoldiqlar_tovar_hujjat_edit_row(
    doc_id: int,
    item_id: int,
    quantity: float = Form(...),
    warehouse_id: int = Form(...),
    cost_price: float = Form(0),
    sale_price: float = Form(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hujjat qatorini tahrirlash (faqat qoralama): soni, ombor, tannarx, sotuv narx"""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc or doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    item = db.query(StockAdjustmentDocItem).filter(
        StockAdjustmentDocItem.id == item_id,
        StockAdjustmentDocItem.doc_id == doc_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Qator topilmadi")
    if quantity <= 0:
        return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)
    # Eski summalarni hisobdan chiqarish
    doc.total_tannarx = (doc.total_tannarx or 0) - (item.quantity * (item.cost_price or 0))
    doc.total_sotuv = (doc.total_sotuv or 0) - (item.quantity * (item.sale_price or 0))
    item.quantity = quantity
    item.warehouse_id = warehouse_id
    item.cost_price = cost_price or 0
    item.sale_price = sale_price or 0
    doc.total_tannarx = (doc.total_tannarx or 0) + item.quantity * item.cost_price
    doc.total_sotuv = (doc.total_sotuv or 0) + item.quantity * item.sale_price
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)


@router.post("/tovar/hujjat/{doc_id}/tasdiqlash")
async def qoldiqlar_tovar_hujjat_tasdiqlash(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Hujjatni tasdiqlash — ombor qoldiqlariga qo'shiladi (create_stock_movement orqali)"""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Hujjat allaqachon tasdiqlangan")
    if not doc.items:
        raise HTTPException(status_code=400, detail="Kamida bitta qator bo'lishi kerak")

    doc_warehouse_ids = list({item.warehouse_id for item in doc.items})
    doc_pairs = {(item.warehouse_id, item.product_id) for item in doc.items}

    is_qld = (doc.number or "").startswith("QLD")  # QLD = qo'shish, INV = almashtirish

    for item in doc.items:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == item.warehouse_id,
            Stock.product_id == item.product_id,
        ).first()
        old_quantity = float(stock.quantity or 0) if stock else 0
        new_quantity = float(item.quantity or 0)

        if is_qld:
            # QLD: mavjud qoldiqqa qo'shish
            quantity_change = new_quantity
            item.previous_quantity = old_quantity
        else:
            # INV: aniq raqamga almashtirish
            quantity_change = new_quantity - old_quantity
            item.previous_quantity = old_quantity

        if abs(quantity_change) > 1e-9:
            create_stock_movement(
                db=db,
                warehouse_id=item.warehouse_id,
                product_id=item.product_id,
                quantity_change=quantity_change,
                operation_type="adjustment",
                document_type="StockAdjustmentDoc",
                document_id=doc.id,
                document_number=doc.number,
                user_id=current_user.id if current_user else None,
                note=f"{'Qoldiq kiritish' if is_qld else 'Inventarizatsiya'}: {doc.number}",
                created_at=doc.date,
            )
        if (item.cost_price or 0) > 0:
            prod = db.query(Product).filter(Product.id == item.product_id).first()
            if prod:
                prod.purchase_price = item.cost_price

    # Faqat hujjatdagi tovarlar yangilanadi — boshqa tovarlarning qoldig'iga tegmaydi

    doc.status = "confirmed"
    db.commit()
    try:
        from app.bot.services.audit_watchdog import audit_stock_adjustment
        audit_stock_adjustment(doc.id)
    except Exception:
        pass
    return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}", status_code=303)


@router.post("/tovar/hujjat/{doc_id}/apply-to-warehouse")
async def qoldiqlar_tovar_hujjat_apply_to_warehouse(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tasdiqlangan hujjat bo'yicha omborni qayta moslash: hujjatda yo'q mahsulotlar uchun qoldiq 0 (savdoda ko'rinmasin)."""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status not in ("confirmed",):
        raise HTTPException(status_code=400, detail="Faqat tasdiqlangan hujjat uchun")
    # Ikki marta bosish himoyasi: allaqachon apply qilinganmi?
    if doc.status == "applied":
        return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}?applied=1", status_code=303)
    doc_warehouse_ids = list({item.warehouse_id for item in doc.items})
    doc_pairs = {(item.warehouse_id, item.product_id) for item in doc.items}
    for wh_id in doc_warehouse_ids:
        for stock in db.query(Stock).filter(Stock.warehouse_id == wh_id).all():
            if (stock.warehouse_id, stock.product_id) in doc_pairs:
                continue
            old_q = float(stock.quantity or 0)
            if old_q > 0:
                create_stock_movement(
                    db=db,
                    warehouse_id=stock.warehouse_id,
                    product_id=stock.product_id,
                    quantity_change=-old_q,
                    operation_type="adjustment",
                    document_type="StockAdjustmentDoc",
                    document_id=doc.id,
                    document_number=doc.number,
                    user_id=current_user.id if current_user else None,
                    note=f"Omborni hujjatga moslash: {doc.number}",
                    created_at=doc.date,
                )
    doc.status = "applied"
    db.commit()
    return RedirectResponse(url=f"/qoldiqlar/tovar/hujjat/{doc_id}?applied=1", status_code=303)


@router.post("/tovar/hujjat/{doc_id}/revert")
async def qoldiqlar_tovar_hujjat_revert(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tovar qoldiq hujjati tasdiqini bekor qilish (faqat admin) — ombor qoldig'i harakatdagi o'zgarishlar orqali qayta tiklanadi."""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status not in ("confirmed", "applied"):
        raise HTTPException(status_code=400, detail="Faqat tasdiqlangan hujjatning tasdiqini bekor qilish mumkin")
    movements = db.query(StockMovement).filter(
        StockMovement.document_type == "StockAdjustmentDoc",
        StockMovement.document_id == doc_id,
    ).all()
    for m in movements:
        if not m.warehouse_id or not m.product_id:
            continue
        create_stock_movement(
            db=db,
            warehouse_id=m.warehouse_id,
            product_id=m.product_id,
            quantity_change=-float(m.quantity_change or 0),
            operation_type="adjustment_revert",
            document_type="StockAdjustmentDoc",
            document_id=doc_id,
            document_number=doc.number,
            note=f"Hujjat tasdiqini bekor qilish: {doc.number}",
        )
    doc.status = "draft"
    db.commit()
    return RedirectResponse(url="/qoldiqlar/tovar/hujjat?reverted=1", status_code=303)


@router.post("/tovar/hujjat/{doc_id}/delete")
async def qoldiqlar_tovar_hujjat_delete(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tovar qoldiq hujjatini o'chirish (faqat qoralama, faqat admin)"""
    doc = db.query(StockAdjustmentDoc).filter(StockAdjustmentDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Hujjat topilmadi")
    if doc.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralama holatidagi hujjatni o'chirish mumkin. Avval tasdiqni bekor qiling.")
    db.delete(doc)
    db.commit()
    return RedirectResponse(url="/qoldiqlar#tovar", status_code=303)
