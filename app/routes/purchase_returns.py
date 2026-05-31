from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from datetime import datetime
from urllib.parse import quote

from app.core import templates
from app.models.database import (
    get_db, User, Partner, Warehouse, Product, Stock,
    PurchaseReturn, PurchaseReturnItem,
)
from app.deps import require_auth
from app.services.purchase_return_service import confirm_return, cancel_return, DocumentError

router = APIRouter(prefix="/purchase-returns", tags=["purchase-returns"])

SUPPLIER_TYPES = ["supplier", "both"]  # adjust per Step 1 findings


def _is_manager(user) -> bool:
    return bool(user and getattr(user, "role", None) in ("admin", "manager"))


@router.get("", response_class=HTMLResponse)
async def pr_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _is_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    docs = db.query(PurchaseReturn).order_by(PurchaseReturn.id.desc()).limit(200).all()
    return templates.TemplateResponse("purchase_returns/list.html",
                                      {"request": request, "docs": docs, "current_user": current_user})


@router.get("/new", response_class=HTMLResponse)
async def pr_new(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _is_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    suppliers = db.query(Partner).filter(
        Partner.is_active == True, Partner.type.in_(SUPPLIER_TYPES)
    ).order_by(Partner.name).all()
    warehouses = db.query(Warehouse).order_by(Warehouse.name).all()
    products = db.query(Product).order_by(Product.name).all()
    return templates.TemplateResponse("purchase_returns/new.html",
        {"request": request, "suppliers": suppliers, "warehouses": warehouses,
         "products": products, "current_user": current_user})


@router.get("/price", response_class=JSONResponse)
async def pr_price(product_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    p = db.query(Product).filter(Product.id == product_id).first()
    return {"price": float((p.purchase_price if p else 0) or 0)}


@router.post("")
async def pr_create(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _is_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    form = await request.form()
    try:
        partner_id = int(form.get("partner_id"))
        warehouse_id = int(form.get("warehouse_id"))
    except (TypeError, ValueError):
        return RedirectResponse(url="/purchase-returns/new?error=" + quote("Yetkazib beruvchi va ombor tanlang"), status_code=303)
    reason = (form.get("reason") or "brak").strip()
    notes = (form.get("notes") or "").strip()
    date_raw = (form.get("date") or "").strip()
    try:
        doc_date = datetime.strptime(date_raw, "%Y-%m-%d") if date_raw else datetime.now()
    except ValueError:
        doc_date = datetime.now()
    product_ids = form.getlist("product_id")
    quantities = form.getlist("quantity")
    prices = form.getlist("price")
    items = []
    for i, pid in enumerate(product_ids):
        if not pid:
            continue
        try:
            qty = float(quantities[i]); prc = float(prices[i])
        except (ValueError, IndexError):
            continue
        if qty > 0:
            items.append((int(pid), qty, prc))
    if not items:
        return RedirectResponse(url="/purchase-returns/new?error=" + quote("Kamida bitta mahsulot qo'shing"), status_code=303)
    prefix = f"PR-{doc_date.strftime('%Y%m%d')}-"
    last = db.query(PurchaseReturn).filter(PurchaseReturn.number.like(f"{prefix}%")).order_by(PurchaseReturn.number.desc()).first()
    seq = 0
    if last:
        try:
            seq = int(last.number.split("-")[-1])
        except (ValueError, IndexError):
            seq = 0
    number = f"{prefix}{str(seq + 1).zfill(4)}"
    total = sum(q * p for _, q, p in items)
    doc = PurchaseReturn(number=number, partner_id=partner_id, warehouse_id=warehouse_id,
                         date=doc_date, status="draft", reason=reason, total=total, notes=notes,
                         user_id=current_user.id if current_user else None)
    db.add(doc); db.flush()
    for pid, q, p in items:
        db.add(PurchaseReturnItem(return_id=doc.id, product_id=pid, quantity=q, price=p, total=q * p))
    db.commit()
    return RedirectResponse(url=f"/purchase-returns/{doc.id}", status_code=303)


@router.get("/{doc_id}", response_class=HTMLResponse)
async def pr_detail(doc_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _is_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    doc = db.query(PurchaseReturn).filter(PurchaseReturn.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/purchase-returns", status_code=303)
    return templates.TemplateResponse("purchase_returns/detail.html",
        {"request": request, "doc": doc, "current_user": current_user})


@router.post("/{doc_id}/confirm")
async def pr_confirm(doc_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _is_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    doc = db.query(PurchaseReturn).filter(PurchaseReturn.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/purchase-returns", status_code=303)
    try:
        confirm_return(db, doc, current_user=current_user, client_host=request.client.host if request.client else None)
    except DocumentError as e:
        return RedirectResponse(url=f"/purchase-returns/{doc_id}?error={quote(str(e))}", status_code=303)
    return RedirectResponse(url=f"/purchase-returns/{doc_id}", status_code=303)


@router.post("/{doc_id}/cancel")
async def pr_cancel(doc_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _is_manager(current_user):
        return RedirectResponse(url="/", status_code=303)
    doc = db.query(PurchaseReturn).filter(PurchaseReturn.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/purchase-returns", status_code=303)
    try:
        cancel_return(db, doc, current_user=current_user)
    except DocumentError as e:
        return RedirectResponse(url=f"/purchase-returns/{doc_id}?error={quote(str(e))}", status_code=303)
    return RedirectResponse(url=f"/purchase-returns/{doc_id}", status_code=303)
