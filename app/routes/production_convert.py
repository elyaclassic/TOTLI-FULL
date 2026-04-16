"""Tayyor mahsulotni yarim_tayyor ga aylantirish (ProductConversion).

Biznes kontekst: yarim_tayyor yetmasa, tayyor mahsulotni buzib yarim_tayyor
sifatida ishlatish. StockMovement (conversion_out + conversion_in) yaratiladi,
target Stock.cost_price source cost_price bilan weighted average orqali yangilanadi.

Birlik konversiyasi: manba `dona` (masalan "MALINALI 400gr" = 0.4 kg/dona) bo'lsa
belgilangan kg miqdoridan kerak bo'ladigan dona soni hisoblanadi (ceil). Target
yarim_tayyor ga actual_kg (dona_soni * kg_per_unit) qo'shiladi.
"""
import math
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
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


def _product_kg_per_unit(product) -> float:
    """Mahsulot nomidan 1 birlikning og'irligi kg da aniqlash.
    Masalan: "MALINALI 400gr" -> 0.4; "Xalva 1kg" -> 1.0; "Malinali" (kg birlik) -> 1.0."""
    if not product or not getattr(product, "name", None):
        return 1.0
    name = (product.name or "").lower()
    m_gr = re.search(r'(\d+)\s*gr', name)
    if m_gr:
        return int(m_gr.group(1)) / 1000.0
    m_g = re.search(r'(\d+)\s*g(?:\b|\))', name)
    if m_g:
        return int(m_g.group(1)) / 1000.0
    m_kg = re.search(r'([\d.]+)\s*kg', name)
    if m_kg:
        return float(m_kg.group(1))
    return 1.0


def _is_piece_unit(product) -> bool:
    """Mahsulot 'dona' birlikdami?"""
    unit = getattr(product, "unit", None)
    if not unit:
        return False
    txt = ((getattr(unit, "name", None) or "") + " " + (getattr(unit, "code", None) or "")).lower()
    return "dona" in txt


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


@router.get("/api/stock")
async def convert_api_stock(
    warehouse_id: int,
    product_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """UI live calculator uchun: manba mahsulot qoldig'i, birlik, kg_per_unit."""
    if not current_user:
        return JSONResponse(status_code=401, content={"error": "auth"})
    product = db.query(Product).options(joinedload(Product.unit)).filter(Product.id == product_id).first()
    if not product:
        return JSONResponse(status_code=404, content={"error": "product_not_found"})
    stock = (
        db.query(Stock)
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == product_id)
        .first()
    )
    qty = float(stock.quantity or 0) if stock else 0.0
    cost = float(getattr(stock, "cost_price", None) or 0) if stock else 0.0
    if cost <= 0:
        cost = float(product.purchase_price or 0)
    is_piece = _is_piece_unit(product)
    kg_per_unit = _product_kg_per_unit(product) if is_piece else 1.0
    return {
        "product_id": product.id,
        "product_name": product.name,
        "unit": (getattr(product.unit, "name", None) if product.unit else None) or "",
        "is_piece": is_piece,
        "kg_per_unit": kg_per_unit,
        "quantity": qty,  # mahsulot birligida (dona yoki kg)
        "quantity_kg": qty * kg_per_unit if is_piece else qty,
        "cost_price": cost,
    }


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

    source = db.query(Product).options(joinedload(Product.unit)).filter(Product.id == source_product_id).first()
    target = db.query(Product).filter(Product.id == target_product_id).first()
    warehouse = db.query(Warehouse).filter(Warehouse.id == warehouse_id).first()
    if not source or not target or not warehouse:
        return RedirectResponse(url="/production/convert?error=notfound", status_code=303)
    if source.type != "tayyor":
        return RedirectResponse(url="/production/convert?error=src_type&detail=" + quote("Manba mahsulot 'tayyor' turiga tegishli bo'lishi kerak"), status_code=303)
    if target.type != "yarim_tayyor":
        return RedirectResponse(url="/production/convert?error=tgt_type&detail=" + quote("Qabul qiluvchi mahsulot 'yarim_tayyor' turiga tegishli bo'lishi kerak"), status_code=303)

    # Birlik konversiyasi: manba dona bo'lsa kg ga o'gir
    is_piece = _is_piece_unit(source)
    kg_per_unit = _product_kg_per_unit(source) if is_piece else 1.0
    target_kg = float(quantity)  # UI'da user target kg miqdorini kiritadi
    if is_piece:
        # Kerak dona = ceil(target_kg / kg_per_unit); haqiqiy kg = dona * kg_per_unit
        source_units = math.ceil(target_kg / kg_per_unit) if kg_per_unit > 0 else 0
        actual_kg = source_units * kg_per_unit
    else:
        source_units = target_kg  # manba ham kg
        actual_kg = target_kg

    # Stock lock + yetishmovchilik tekshiruvi (race safety)
    source_stock = (
        db.query(Stock)
        .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == source_product_id)
        .with_for_update()
        .first()
    )
    have = float(source_stock.quantity or 0) if source_stock else 0.0
    if have + 1e-6 < source_units:
        unit_label = "dona" if is_piece else "kg"
        return RedirectResponse(
            url="/production/convert?error=stock&detail=" + quote(
                f"Ombor yetmaydi: {source.name} kerak {source_units} {unit_label}, bor {have} {unit_label}"
            ),
            status_code=303,
        )

    source_cost = float(getattr(source_stock, "cost_price", None) or 0)
    if source_cost <= 0:
        source_cost = float(source.purchase_price or 0)
    # source_cost = 1 dona narxi. Target kg ga ko'chirishda: kg narxi = dona_narxi / kg_per_unit
    target_cost_per_kg = (source_cost / kg_per_unit) if (is_piece and kg_per_unit > 0) else source_cost

    number = _next_conversion_number(db)
    conv = ProductConversion(
        number=number,
        date=datetime.now(),
        warehouse_id=warehouse_id,
        source_product_id=source_product_id,
        target_product_id=target_product_id,
        quantity=actual_kg,  # target ga qo'shiladigan kg (haqiqiy)
        source_cost_price=source_cost,
        note=(note.strip() or None),
        user_id=current_user.id if current_user else None,
        status="confirmed",
    )
    db.add(conv)
    db.flush()

    create_stock_movement(
        db=db,
        warehouse_id=warehouse_id,
        product_id=source_product_id,
        quantity_change=-source_units,  # manba birligida (dona yoki kg)
        operation_type="conversion_out",
        document_type="Conversion",
        document_id=conv.id,
        document_number=number,
        user_id=current_user.id if current_user else None,
        note=f"Konversiya (chiqim): {source.name} → {target.name} [{actual_kg} kg]",
        created_at=conv.date,
    )
    create_stock_movement(
        db=db,
        warehouse_id=warehouse_id,
        product_id=target_product_id,
        quantity_change=+actual_kg,
        operation_type="conversion_in",
        document_type="Conversion",
        document_id=conv.id,
        document_number=number,
        user_id=current_user.id if current_user else None,
        note=f"Konversiya (kirim): {source.name} ({source_units} dona) → {target.name}"
             if is_piece else f"Konversiya (kirim): {source.name} → {target.name}",
        created_at=conv.date,
    )

    # Target Stock cost_price — weighted average (kg bo'yicha)
    if target_cost_per_kg > 0 and hasattr(Stock, "cost_price"):
        target_stock = (
            db.query(Stock)
            .filter(Stock.warehouse_id == warehouse_id, Stock.product_id == target_product_id)
            .first()
        )
        if target_stock:
            qty_old = (target_stock.quantity or 0) - actual_kg
            cost_old = float(getattr(target_stock, "cost_price", None) or 0)
            if qty_old <= 0 or cost_old <= 0:
                target_stock.cost_price = target_cost_per_kg
            else:
                target_stock.cost_price = (qty_old * cost_old + actual_kg * target_cost_per_kg) / (target_stock.quantity or 1)

    db.commit()
    logger.info(
        "conversion_create: #%s wh=%s %s(%s)=-%s%s -> %s(%s)=+%skg cost=%.2f user=%s",
        number, warehouse_id, source.name, source_product_id,
        source_units, ("dona" if is_piece else "kg"),
        target.name, target_product_id, actual_kg, source_cost,
        current_user.id if current_user else None,
    )
    if is_piece:
        summary = f"✅ {number}: {source.name} {source_units} dona → {target.name} {actual_kg} kg"
    else:
        summary = f"✅ {number}: {source.name} {actual_kg} kg → {target.name} {actual_kg} kg"
    return RedirectResponse(
        url="/production/convert?msg=" + quote(summary),
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

    # Manba birligini aniqlash — agar dona bo'lsa, qaytariladigan dona = actual_kg / kg_per_unit
    source = db.query(Product).options(joinedload(Product.unit)).filter(Product.id == conv.source_product_id).first()
    actual_kg = float(conv.quantity or 0)
    if source and _is_piece_unit(source):
        kg_per_unit = _product_kg_per_unit(source)
        source_units_back = (actual_kg / kg_per_unit) if kg_per_unit > 0 else 0
    else:
        source_units_back = actual_kg

    create_stock_movement(
        db=db,
        warehouse_id=conv.warehouse_id,
        product_id=conv.source_product_id,
        quantity_change=+source_units_back,
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
