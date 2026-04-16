"""Tayyor mahsulotni yarim_tayyor ga aylantirish (ProductConversion).

Biznes kontekst: yarim_tayyor yetmasa, tayyor mahsulotni buzib yarim_tayyor
sifatida ishlatish. StockMovement (conversion_out + conversion_in) yaratiladi,
target Stock.cost_price source cost_price bilan weighted average orqali yangilanadi.
"""
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.logging_config import get_logger
from app.models.database import (
    get_db, User, Warehouse, Product, Stock, ProductConversion,
)
from app.deps import require_auth, require_admin_or_manager
from app.utils.user_scope import get_warehouses_for_user
from app.services.stock_service import create_stock_movement, delete_stock_movements_for_document

logger = get_logger("production_convert")
router = APIRouter(prefix="/production/convert", tags=["production-convert"])


def _next_conversion_number(db: Session) -> str:
    today = datetime.now()
    prefix = f"CONV-{today.strftime('%Y%m%d')}"
    last = (
        db.query(ProductConversion)
        .filter(ProductConversion.number.like(f"{prefix}%"))
        .order_by(ProductConversion.id.desc())
        .first()
    )
    try:
        seq = int(last.number.split("-")[-1]) + 1 if last and last.number else 1
    except Exception:
        seq = 1
    return f"{prefix}-{seq:03d}"


@router.get("", response_class=HTMLResponse)
async def convert_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Konversiyalar ro'yxati + yangi yaratish formasi."""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    warehouses = get_warehouses_for_user(db, current_user)
    tayyor_products = db.query(Product).filter(
        Product.is_active == True,
        Product.type == "tayyor",
    ).order_by(Product.name).all()
    yarim_products = db.query(Product).filter(
        Product.is_active == True,
        Product.type == "yarim_tayyor",
    ).order_by(Product.name).all()
    conversions = (
        db.query(ProductConversion)
        .options(
            joinedload(ProductConversion.source_product),
            joinedload(ProductConversion.target_product),
            joinedload(ProductConversion.warehouse),
            joinedload(ProductConversion.user),
        )
        .order_by(ProductConversion.id.desc())
        .limit(100)
        .all()
    )
    msg = request.query_params.get("msg") or ""
    error = request.query_params.get("error") or ""
    detail = request.query_params.get("detail") or ""
    return templates.TemplateResponse("production/convert.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Tayyor → Yarim-tayyor konversiya",
        "warehouses": warehouses,
        "tayyor_products": tayyor_products,
        "yarim_products": yarim_products,
        "conversions": conversions,
        "msg": msg,
        "error": error,
        "detail": detail,
    })


@router.post("")
async def convert_create(
    warehouse_id: int = Form(...),
    source_product_id: int = Form(...),
    target_product_id: int = Form(...),
    quantity: float = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Konversiya yaratish va darhol tasdiqlash (atomik)."""
    if quantity is None or quantity <= 0:
        return RedirectResponse(url="/production/convert?error=qty&detail=" + quote("Miqdor 0 dan katta bo'lishi kerak"), status_code=303)
    if source_product_id == target_product_id:
        return RedirectResponse(url="/production/convert?error=same&detail=" + quote("Manba va qabul qiluvchi mahsulot bir xil bo'lmasin"), status_code=303)

    source = db.query(Product).filter(Product.id == source_product_id).first()
    target = db.query(Product).filter(Product.id == target_product_id).first()
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not source or not target or not warehouse:
        return RedirectResponse(url="/production/convert?error=notfound", status_code=303)
    if source.type != "tayyor":
        return RedirectResponse(url="/production/convert?error=src_type&detail=" + quote("Manba mahsulot 'tayyor' turiga tegishli bo'lishi kerak"), status_code=303)
    if target.type != "yarim_tayyor":
        return RedirectResponse(url="/production/convert?error=tgt_type&detail=" + quote("Qabul qiluvchi mahsulot 'yarim_tayyor' turiga tegishli bo'lishi kerak"), status_code=303)

    # Stock lock + yetishmovchilik tekshiruvi (race safety)
    source_stock = (
        db.query(Stock)
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == source_product_id)
        .with_for_update()
        .first()
    )
    have = float(source_stock.quantity or 0) if source_stock else 0.0
    if have + 1e-6 < float(quantity):
        return RedirectResponse(
            url="/production/convert?error=stock&detail=" + quote(f"Ombor yetmaydi: {source.name} kerak {quantity}, bor {have}"),
            status_code=303,
        )

    source_cost = float(getattr(source_stock, "cost_price", None) or 0)
    if source_cost <= 0:
        source_cost = float(source.purchase_price or 0)

    number = _next_conversion_number(db)
    conv = ProductConversion(
        number=number,
        date=datetime.now(),
        warehouse_id=warehouse_id,
        source_product_id=source_product_id,
        target_product_id=target_product_id,
        quantity=float(quantity),
        source_cost_price=source_cost,
        note=note.strip() or None,
        user_id=current_user.id if current_user else None,
        status="confirmed",
    )
    db.add(conv)
    db.flush()

    create_stock_movement(
        db=db,
        warehouse_id=warehouse_id,
        product_id=source_product_id,
        quantity_change=-float(quantity),
        operation_type="conversion_out",
        document_type="Conversion",
        document_id=conv.id,
        document_number=number,
        user_id=current_user.id if current_user else None,
        note=f"Konversiya (chiqim): {source.name} → {target.name}",
        created_at=conv.date,
    )
    create_stock_movement(
        db=db,
        warehouse_id=warehouse_id,
        product_id=target_product_id,
        quantity_change=+float(quantity),
        operation_type="conversion_in",
        document_type="Conversion",
        document_id=conv.id,
        document_number=number,
        user_id=current_user.id if current_user else None,
        note=f"Konversiya (kirim): {source.name} → {target.name}",
        created_at=conv.date,
    )

    # Target Stock cost_price — weighted average
    if source_cost > 0 and hasattr(Stock, "cost_price"):
        target_stock = (
            db.query(Stock)
            .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == target_product_id)
            .first()
        )
        if target_stock:
            qty_old = (target_stock.quantity or 0) - float(quantity)
            cost_old = float(getattr(target_stock, "cost_price", None) or 0)
            if qty_old <= 0 or cost_old <= 0:
                target_stock.cost_price = source_cost
            else:
                target_stock.cost_price = (qty_old * cost_old + float(quantity) * source_cost) / (target_stock.quantity or 1)

    db.commit()
    logger.info(
        "conversion_create: #%s wh=%s %s(%s) -> %s(%s) qty=%s cost=%.2f user=%s",
        number, warehouse_id, source.name, source_product_id,
        target.name, target_product_id, quantity, source_cost,
        current_user.id if current_user else None,
    )
    return RedirectResponse(
        url="/production/convert?msg=" + quote(f"✅ {number} tasdiqlandi: {source.name} {quantity} kg → {target.name}"),
        status_code=303,
    )


@router.post("/{conv_id}/revert")
async def convert_revert(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin_or_manager),
):
    """Konversiyani bekor qilish — teskari StockMovement lar yaratish + status cancelled."""
    conv = db.query(ProductConversion).filter(ProductConversion.id == conv_id).with_for_update().first()
    if not conv:
        raise HTTPException(status_code=404, detail="Konversiya topilmadi")
    if conv.status != "confirmed":
        return RedirectResponse(url="/production/convert?error=already_cancelled", status_code=303)

    create_stock_movement(
        db=db,
        warehouse_id=conv.warehouse_id,
        product_id=conv.source_product_id,
        quantity_change=+float(conv.quantity or 0),
        operation_type="conversion_revert",
        document_type="Conversion",
        document_id=conv.id,
        document_number=f"{conv.number}-REVERT",
        user_id=current_user.id if current_user else None,
        note=f"Konversiya bekor: manba qaytarildi",
        created_at=datetime.now(),
    )
    create_stock_movement(
        db=db,
        warehouse_id=conv.warehouse_id,
        product_id=conv.target_product_id,
        quantity_change=-float(conv.quantity or 0),
        operation_type="conversion_revert",
        document_type="Conversion",
        document_id=conv.id,
        document_number=f"{conv.number}-REVERT",
        user_id=current_user.id if current_user else None,
        note=f"Konversiya bekor: target kamaytirildi",
        created_at=datetime.now(),
    )
    conv.status = "cancelled"
    db.commit()
    logger.info("conversion_revert: #%s user=%s", conv.number, current_user.id if current_user else None)
    return RedirectResponse(
        url="/production/convert?msg=" + quote(f"♻️ {conv.number} bekor qilindi"),
        status_code=303,
    )
