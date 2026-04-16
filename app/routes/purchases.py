"""
Tovar kirimi (purchases) — ro'yxat, yaratish, tahrir, tasdiq, revert, o'chirish.
"""
from datetime import datetime
from urllib.parse import quote

import openpyxl
from fastapi import APIRouter, Request, Depends, Form, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db,
    User,
    Product,
    Partner,
    Warehouse,
    Stock,
    Purchase,
    PurchaseItem,
    PurchaseExpense,
    CashRegister,
    Direction,
    Department,
)
from app.deps import require_auth, require_admin
from app.utils.notifications import check_low_stock_and_notify
from app.utils.audit import log_action
from app.utils.user_scope import get_warehouses_for_user
from app.utils.product_price import get_suggested_price
from app.constants import QUERY_LIMIT_DEFAULT, QUERY_LIMIT_HISTORY
from fastapi.responses import JSONResponse
from fastapi import Query

router = APIRouter(prefix="/purchases", tags=["purchases"])


@router.get("", response_class=HTMLResponse)
async def purchases_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    from urllib.parse import unquote
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    query = db.query(Purchase).order_by(Purchase.date.desc())
    # Filtrlar
    date_from = request.query_params.get("date_from", "").strip()
    date_to = request.query_params.get("date_to", "").strip()
    wh_id = request.query_params.get("warehouse_id", "").strip()
    if date_from:
        try:
            from datetime import datetime
            query = query.filter(Purchase.date >= datetime.strptime(date_from, "%Y-%m-%d"))
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime, timedelta
            query = query.filter(Purchase.date <= datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1))
        except ValueError:
            pass
    if wh_id and wh_id.isdigit():
        query = query.filter(Purchase.warehouse_id == int(wh_id))
    purchases = query.limit(QUERY_LIMIT_DEFAULT).all()
    warehouses = get_warehouses_for_user(db, current_user)
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    return templates.TemplateResponse("purchases/list.html", {
        "request": request,
        "purchases": purchases,
        "warehouses": warehouses,
        "current_user": current_user,
        "page_title": "Tovar kirimlari",
        "error": error,
        "error_detail": error_detail,
    })


@router.get("/new", response_class=HTMLResponse)
async def purchase_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    products = db.query(Product).filter(Product.is_active == True).all()
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    warehouses = get_warehouses_for_user(db, current_user)
    return templates.TemplateResponse("purchases/new.html", {
        "request": request,
        "products": products,
        "partners": partners,
        "warehouses": warehouses,
        "current_user": current_user,
        "page_title": "Yangi tovar kirimi",
    })


@router.post("/create")
async def purchase_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    form = await request.form()
    partner_id = form.get("partner_id")
    warehouse_id = form.get("warehouse_id")
    if not partner_id or not warehouse_id:
        raise HTTPException(status_code=400, detail="Ta'minotchi va omborni tanlang")
    try:
        partner_id = int(partner_id)
        warehouse_id = int(warehouse_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Noto'g'ri ma'lumot")
    product_ids = form.getlist("product_id")
    quantities = form.getlist("quantity")
    prices = form.getlist("price")
    expense_names = form.getlist("expense_name")
    expense_amounts = form.getlist("expense_amount")
    items_data = []
    for i, pid in enumerate(product_ids):
        if not pid or not str(pid).strip():
            continue
        try:
            qty = float(quantities[i]) if i < len(quantities) else 0
            pr = float(prices[i]) if i < len(prices) else 0
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue
        try:
            items_data.append((int(pid), qty, pr))
        except ValueError:
            continue
    if not items_data:
        raise HTTPException(status_code=400, detail="Kamida bitta mahsulot qo'shing (mahsulot, miqdor va narx).")
    # Sana: formadan yoki bugun
    purchase_date_raw = form.get("purchase_date", "").strip()
    if purchase_date_raw:
        try:
            today = datetime.strptime(purchase_date_raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            try:
                today = datetime.strptime(purchase_date_raw, "%Y-%m-%d")
            except ValueError:
                today = datetime.now()
    else:
        today = datetime.now()
    date_prefix = f"P-{today.strftime('%Y%m%d')}-"
    last_purchase = db.query(Purchase).filter(
        Purchase.number.like(f"{date_prefix}%")
    ).order_by(Purchase.number.desc()).first()
    if last_purchase:
        try:
            last_seq = int(last_purchase.number.split("-")[-1])
        except (ValueError, IndexError):
            last_seq = 0
    else:
        last_seq = 0
    number = f"{date_prefix}{str(last_seq + 1).zfill(4)}"
    total = sum(qty * pr for _, qty, pr in items_data)
    total_expenses = 0
    for j, name in enumerate(expense_names):
        if not (name and str(name).strip()):
            continue
        try:
            amt = float(expense_amounts[j]) if j < len(expense_amounts) else 0
        except (TypeError, ValueError):
            amt = 0
        if amt > 0:
            total_expenses += amt
    purchase = Purchase(
        number=number,
        partner_id=partner_id,
        warehouse_id=warehouse_id,
        date=today,
        total=total,
        total_expenses=total_expenses,
        status="draft",
    )
    db.add(purchase)
    db.flush()
    for pid, qty, pr in items_data:
        db.add(PurchaseItem(
            purchase_id=purchase.id,
            product_id=pid,
            quantity=qty,
            price=pr,
            total=qty * pr,
        ))
    for j, name in enumerate(expense_names):
        if not (name and str(name).strip()):
            continue
        try:
            amt = float(expense_amounts[j]) if j < len(expense_amounts) else 0
        except (TypeError, ValueError):
            amt = 0
        if amt > 0:
            db.add(PurchaseExpense(purchase_id=purchase.id, name=str(name).strip(), amount=amt))
    db.commit()
    return RedirectResponse(url=f"/purchases/edit/{purchase.id}", status_code=303)


@router.get("/edit/{purchase_id}", response_class=HTMLResponse)
async def purchase_edit(
    request: Request,
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    from urllib.parse import unquote
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Tovar kirimi topilmadi")
    if purchase.status == "confirmed" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Tasdiqlangan kirimni faqat administrator tahrirlashi mumkin")
    products = db.query(Product).filter(Product.is_active == True).all()
    revert_error = request.query_params.get("error") == "revert"
    revert_detail = unquote(request.query_params.get("detail", "") or "")
    cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).all()
    directions = db.query(Direction).filter(Direction.is_active == True).all()
    departments = db.query(Department).filter(Department.is_active == True).all()
    return templates.TemplateResponse("purchases/edit.html", {
        "request": request,
        "purchase": purchase,
        "products": products,
        "cash_registers": cash_registers,
        "directions": directions,
        "departments": departments,
        "current_user": current_user,
        "page_title": f"Tovar kirimi: {purchase.number}",
        "revert_error": revert_error,
        "revert_detail": revert_detail,
    })


@router.post("/{purchase_id}/add-item")
async def purchase_add_item(
    purchase_id: int,
    product_id: int = Form(...),
    quantity: float = Form(...),
    price: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Miqdor musbat bo'lishi kerak")
    if price < 0:
        raise HTTPException(status_code=400, detail="Narx manfiy bo'lishi mumkin emas")
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Tovar kirimi topilmadi")
    total = quantity * price
    db.add(PurchaseItem(purchase_id=purchase_id, product_id=product_id, quantity=quantity, price=price, total=total))
    purchase.total = (db.query(PurchaseItem).filter(PurchaseItem.purchase_id == purchase_id).with_entities(func.sum(PurchaseItem.total)).scalar() or 0) + total
    db.commit()
    return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)


@router.post("/{purchase_id}/delete-item/{item_id}")
async def purchase_delete_item(
    purchase_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase or purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    item = db.query(PurchaseItem).filter(PurchaseItem.id == item_id, PurchaseItem.purchase_id == purchase_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Qator topilmadi")
    purchase.total = (purchase.total or 0) - (item.total or 0)
    db.delete(item)
    db.commit()
    return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)


@router.post("/{purchase_id}/add-expense")
async def purchase_add_expense(
    purchase_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase or purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    form = await request.form()
    name = (form.get("name") or "").strip()
    try:
        amount = float(form.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0
    if not name or amount <= 0:
        return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)
    db.add(PurchaseExpense(purchase_id=purchase_id, name=name, amount=amount))
    purchase.total_expenses = (purchase.total_expenses or 0) + amount
    db.commit()
    return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)


@router.post("/{purchase_id}/set-expense-cash")
async def purchase_set_expense_cash(
    purchase_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kirim xarajatlari (yo'l kiro va b.) qaysi kassa/yo'nalish/bo'limdan — harajatlar jurnalida ko'rsatiladi."""
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Tovar kirimi topilmadi")
    form = await request.form()
    raw = (form.get("expense_cash_register_id") or "").strip()
    cash_id = int(raw) if raw.isdigit() else None
    if cash_id is not None:
        cr = db.query(CashRegister).filter(CashRegister.id == cash_id, CashRegister.is_active == True).first()
        if not cr:
            cash_id = None
    purchase.expense_cash_register_id = cash_id
    raw_dir = (form.get("expense_direction_id") or "").strip()
    direction_id = int(raw_dir) if raw_dir.isdigit() else None
    if direction_id is not None:
        dr = db.query(Direction).filter(Direction.id == direction_id, Direction.is_active == True).first()
        if not dr:
            direction_id = None
    purchase.expense_direction_id = direction_id
    raw_dept = (form.get("expense_department_id") or "").strip()
    department_id = int(raw_dept) if raw_dept.isdigit() else None
    if department_id is not None:
        dept = db.query(Department).filter(Department.id == department_id, Department.is_active == True).first()
        if not dept:
            department_id = None
    purchase.expense_department_id = department_id
    db.commit()
    return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)


@router.post("/{purchase_id}/delete-expense/{expense_id}")
async def purchase_delete_expense(
    purchase_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase or purchase.status != "draft":
        raise HTTPException(status_code=400, detail="Faqat qoralamani tahrirlash mumkin")
    expense = db.query(PurchaseExpense).filter(
        PurchaseExpense.id == expense_id,
        PurchaseExpense.purchase_id == purchase_id,
    ).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Xarajat topilmadi")
    purchase.total_expenses = (purchase.total_expenses or 0) - (expense.amount or 0)
    if purchase.total_expenses < 0:
        purchase.total_expenses = 0
    db.delete(expense)
    db.commit()
    return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)


@router.post("/{purchase_id}/confirm")
async def purchase_confirm(
    purchase_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Tovar kirimi topilmadi")

    # --- Atomik biznes operatsiyasi (stock + price + partner balance + log) ---
    from app.services.document_service import confirm_purchase_atomic, DocumentError
    try:
        confirm_purchase_atomic(
            db=db,
            purchase=purchase,
            current_user=current_user,
            client_host=request.client.host if request.client else "",
        )
    except DocumentError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    # --- Post-commit side-effects (commit'ga bog'liq emas) ---
    check_low_stock_and_notify(db)
    try:
        from app.bot.services.audit_watchdog import audit_purchase
        audit_purchase(purchase.id)
    except Exception:
        pass
    return RedirectResponse(url="/purchases", status_code=303)


@router.post("/{purchase_id}/revert")
async def purchase_revert(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Tovar kirimi topilmadi")

    # --- Atomik biznes operatsiyasi (revert stock + partner balance) ---
    from app.services.document_service import revert_purchase_atomic, DocumentError
    try:
        revert_purchase_atomic(
            db=db,
            purchase=purchase,
            current_user=current_user,
        )
    except DocumentError as e:
        return RedirectResponse(
            url=f"/purchases/edit/{purchase_id}?error=revert&detail=" + quote(e.detail),
            status_code=303,
        )

    return RedirectResponse(url=f"/purchases/edit/{purchase_id}", status_code=303)


@router.get("/api/product-price")
async def get_product_price_api(
    product_id: int = Query(...),
    warehouse_id: int = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """
    Mahsulot uchun taklif qilingan narxni olish (oxirgi narx yoki o'rtacha tannarx).
    """
    try:
        price = get_suggested_price(
            db=db,
            product_id=product_id,
            warehouse_id=warehouse_id,
            use_average=True  # O'rtacha tannarxni ishlatish
        )
        return JSONResponse({"price": price})
    except Exception:
        return JSONResponse({"price": 0, "error": "Narxni olishda xatolik"}, status_code=500)


@router.post("/{purchase_id}/delete")
async def purchase_delete(
    purchase_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Tovar kirimini o'chirish (faqat draft). Atomik: items, expenses, purchase birga."""
    purchase = db.query(Purchase).filter(Purchase.id == purchase_id).first()
    if not purchase:
        raise HTTPException(status_code=404, detail="Tovar kirimi topilmadi")

    from app.services.document_service import delete_purchase_fully, DocumentError
    try:
        delete_purchase_fully(db, purchase)
    except DocumentError as e:
        return RedirectResponse(
            url=f"/purchases?error=delete&detail=" + quote(e.detail),
            status_code=303,
        )
    return RedirectResponse(url="/purchases", status_code=303)
