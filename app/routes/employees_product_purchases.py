"""
Xodim mahsulot xaridi (oylikdan kvota o'tib ushlanadi).

Logika:
- Xodim ombor mahsulotidan oladi (sotuv narxi bo'yicha)
- StockMovement yaratiladi (stockdan chiqim)
- EmployeeAdvance yaratiladi (is_product=True, amount=jami)
- Oylik hisoblanganda: free_used = MIN(quota, monthly_purchases), deductible qoldig'i ushlanadi
"""
from datetime import datetime, date
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db,
    User,
    Employee,
    EmployeeAdvance,
    Product,
    Stock,
    Warehouse,
    StockMovement,
)
from app.deps import require_auth, require_admin
from app.services.stock_service import create_stock_movement
from app.utils.db_schema import ensure_employee_quota_column, ensure_advance_is_product_column

router = APIRouter(prefix="/employees", tags=["employees-product-purchases"])


def _month_range(d: date) -> tuple:
    """Berilgan sana oyining boshi va oxirini qaytaradi."""
    from calendar import monthrange
    start = date(d.year, d.month, 1)
    end = date(d.year, d.month, monthrange(d.year, d.month)[1])
    return start, end


def _employee_month_summary(db: Session, employee_id: int, ref_date: date) -> dict:
    """Xodimning oy davomidagi mahsulot xaridi xulosasi: olgan, kvota ichida, oshig'i."""
    start, end = _month_range(ref_date)
    total = float(
        db.query(func.coalesce(func.sum(EmployeeAdvance.amount), 0))
        .filter(
            EmployeeAdvance.employee_id == employee_id,
            EmployeeAdvance.is_product == True,
            EmployeeAdvance.advance_date >= start,
            EmployeeAdvance.advance_date <= end,
            EmployeeAdvance.confirmed_at.isnot(None),
        )
        .scalar() or 0
    )
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    quota = float(getattr(emp, "monthly_free_quota", None) or 0) if emp else 0
    free_used = min(quota, total)
    deductible = max(0, total - free_used)
    free_remaining = max(0, quota - free_used)
    return {
        "month_total": total,
        "quota": quota,
        "free_used": free_used,
        "free_remaining": free_remaining,
        "deductible": deductible,
    }


@router.get("/mahsulot", response_class=HTMLResponse)
async def employee_product_purchases_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    employee_id: Optional[int] = None,
):
    """Xodim mahsulot xaridi — ro'yxat va yangi kiritish formasi."""
    ensure_employee_quota_column(db)
    ensure_advance_is_product_column(db)
    today = date.today()

    # Ro'yxat: oxirgi oydagi mahsulot avanslari (yoki filtrlangan)
    q = db.query(EmployeeAdvance).options(joinedload(EmployeeAdvance.employee)).filter(
        EmployeeAdvance.is_product == True,
    )
    df_str = (date_from or "").strip()[:10]
    dt_str = (date_to or "").strip()[:10]
    if df_str:
        try:
            df = datetime.strptime(df_str, "%Y-%m-%d").date()
            q = q.filter(EmployeeAdvance.advance_date >= df)
        except ValueError:
            pass
    if dt_str:
        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d").date()
            q = q.filter(EmployeeAdvance.advance_date <= dt)
        except ValueError:
            pass
    if employee_id:
        q = q.filter(EmployeeAdvance.employee_id == employee_id)
    advances = q.order_by(EmployeeAdvance.advance_date.desc(), EmployeeAdvance.id.desc()).limit(500).all()

    # Oy bo'yicha xulosalar (har xodim uchun joriy oydagi kvota holati)
    employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.full_name).all()
    summaries = {}
    for e in employees:
        summaries[e.id] = _employee_month_summary(db, e.id, today)

    # Omborlar
    warehouses = db.query(Warehouse).filter(Warehouse.is_active == True).order_by(Warehouse.name).all()

    return templates.TemplateResponse("employees/product_purchases.html", {
        "request": request,
        "advances": advances,
        "employees": employees,
        "summaries": summaries,
        "warehouses": warehouses,
        "default_date": today.strftime("%Y-%m-%d"),
        "filter_date_from": df_str,
        "filter_date_to": dt_str,
        "filter_employee_id": employee_id,
        "current_user": current_user,
        "page_title": "Hodim mahsulot xaridi",
    })


@router.get("/mahsulot/products-by-warehouse")
async def products_by_warehouse(
    warehouse_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Berilgan ombor uchun mavjud mahsulotlarni qaytaradi (qoldiq > 0). AJAX uchun."""
    rows = (
        db.query(Product, Stock)
        .join(Stock, Stock.product_id == Product.id)
        .filter(Stock.warehouse_id == warehouse_id, Stock.quantity > 0)
        .order_by(Product.name)
        .all()
    )
    items = []
    for p, s in rows:
        unit_name = p.unit.name if p.unit else "dona"
        items.append({
            "id": p.id,
            "name": p.name,
            "code": p.code or "",
            "sale_price": float(p.sale_price or 0),
            "available": float(s.quantity or 0),
            "unit": unit_name,
        })
    return {"items": items}


@router.post("/mahsulot/add")
async def employee_product_purchase_add(
    request: Request,
    employee_id: int = Form(...),
    warehouse_id: int = Form(...),
    advance_date: str = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Yangi xodim mahsulot xaridi.
    Forma: product_id[], quantity[], price[] (ko'p qator)."""
    ensure_employee_quota_column(db)
    ensure_advance_is_product_column(db)

    form = await request.form()
    product_ids = form.getlist("product_id")
    quantities = form.getlist("quantity")
    prices = form.getlist("price")

    try:
        adv_date = datetime.strptime(advance_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url="/employees/mahsulot?error=" + quote("Noto'g'ri sana"), status_code=303)

    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees/mahsulot?error=" + quote("Xodim topilmadi"), status_code=303)

    wh = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not wh:
        return RedirectResponse(url="/employees/mahsulot?error=" + quote("Ombor topilmadi"), status_code=303)

    # Qatorlarni yig'ish
    items = []
    total = 0.0
    item_notes = []
    for i in range(max(len(product_ids), len(quantities))):
        try:
            pid = int(product_ids[i]) if i < len(product_ids) and str(product_ids[i]).strip() else 0
            qty = float(quantities[i]) if i < len(quantities) and str(quantities[i]).strip() else 0
            price = float(prices[i]) if i < len(prices) and str(prices[i]).strip() else 0
        except (ValueError, TypeError):
            continue
        if pid <= 0 or qty <= 0 or price <= 0:
            continue
        product = db.query(Product).filter(Product.id == pid).first()
        if not product:
            continue
        # Qoldiq tekshirish
        stock = db.query(Stock).filter(Stock.warehouse_id == warehouse_id, Stock.product_id == pid).first()
        available = float(stock.quantity if stock else 0)
        if available + 1e-6 < qty:
            return RedirectResponse(
                url="/employees/mahsulot?error=" + quote(
                    f"Qoldiq yetmaydi: {product.name} (omborda {available:.2f}, kerak {qty:.2f})"
                ),
                status_code=303,
            )
        line_total = qty * price
        items.append({"product": product, "qty": qty, "price": price, "total": line_total})
        total += line_total
        item_notes.append(f"{product.name} {qty:g}×{price:,.0f}")

    if not items:
        return RedirectResponse(url="/employees/mahsulot?error=" + quote("Hech qanday mahsulot kiritilmagan"), status_code=303)

    # 1) EmployeeAdvance yaratish (is_product=True)
    final_note = (note + " | " if note else "") + ", ".join(item_notes)
    advance = EmployeeAdvance(
        employee_id=employee_id,
        cash_register_id=None,
        amount=total,
        advance_date=adv_date,
        note=final_note[:500],
        is_product=True,
        confirmed_at=datetime.now(),
    )
    db.add(advance)
    db.flush()

    # 2) StockMovementlar yaratish (har mahsulot uchun)
    for it in items:
        create_stock_movement(
            db=db,
            warehouse_id=warehouse_id,
            product_id=it["product"].id,
            quantity_change=-it["qty"],
            operation_type="employee_purchase",
            document_type="EmployeeAdvance",
            document_id=advance.id,
            document_number=f"HD-MAHS-{advance.id}",
            user_id=current_user.id if current_user else None,
            note=f"Xodim mahsulot xaridi: {emp.full_name}",
            created_at=datetime.combine(adv_date, datetime.now().time()),
        )

    db.commit()

    return RedirectResponse(
        url="/employees/mahsulot?success=" + quote(f"{emp.full_name}: {total:,.0f} so'm yozildi"),
        status_code=303,
    )


@router.post("/mahsulot/{adv_id}/delete")
async def employee_product_purchase_delete(
    adv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Xaridni o'chirish — stock movementlar ham revert qilinadi (faqat admin)."""
    advance = db.query(EmployeeAdvance).filter(
        EmployeeAdvance.id == adv_id,
        EmployeeAdvance.is_product == True,
    ).first()
    if not advance:
        raise HTTPException(status_code=404, detail="Topilmadi")

    # Tegishli stock movementlarni topib reverse
    movements = db.query(StockMovement).filter(
        StockMovement.document_type == "EmployeeAdvance",
        StockMovement.document_id == adv_id,
    ).all()

    for sm in movements:
        # Reverse movement yaratish
        create_stock_movement(
            db=db,
            warehouse_id=sm.warehouse_id,
            product_id=sm.product_id,
            quantity_change=-sm.quantity_change,  # teskari
            operation_type="employee_purchase_revert",
            document_type="EmployeeAdvance",
            document_id=adv_id,
            document_number=sm.document_number,
            user_id=current_user.id if current_user else None,
            note=f"Xarid bekor qilindi: {advance.note or ''}",
            created_at=datetime.now(),
        )

    db.delete(advance)
    db.commit()
    return RedirectResponse(url="/employees/mahsulot?success=" + quote("O'chirildi"), status_code=303)
