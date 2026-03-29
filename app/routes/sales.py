"""
Savdo (sales) — sotuvlar ro'yxati, yangi sotuv, tahrir, tasdiq, revert, o'chirish, POS, qaytarish.
"""
import base64
import io
import json
from datetime import datetime, timedelta
from urllib.parse import quote, unquote
from typing import Optional

import barcode
from barcode.writer import ImageWriter
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db,
    User,
    Product,
    Partner,
    Warehouse,
    Stock,
    Order,
    OrderItem,
    Payment,
    ProductPrice,
    PriceType,
    Category,
    PosDraft,
    CashRegister,
    ExpenseType,
    StockMovement,
)
from app.deps import require_auth, require_admin


def _check_order_access(order: Order, current_user: User):
    """Admin/manager — hamma buyurtma, boshqalar — faqat o'ziniki."""
    if current_user.role in ("admin", "manager"):
        return
    if order.user_id and order.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Bu buyurtmaga ruxsat yo'q")
from app.utils.notifications import check_low_stock_and_notify
from app.utils.user_scope import get_warehouses_for_user
from app.utils.audit import log_action
from app.utils.production_order import (
    create_production_from_order,
    get_semi_finished_warehouse,
    get_product_stock_in_warehouse,
    notify_qiyom_operators,
    notify_cutting_packing_operators,
)
from app.utils.db_schema import ensure_orders_payment_due_date_column, ensure_order_item_warehouse_id_column
from app.services.stock_service import create_stock_movement
from app.services.pos_helpers import (
    get_pos_price_type as _get_pos_price_type,
    get_pos_warehouses_for_user as _get_pos_warehouses_for_user,
    get_pos_warehouse_for_user as _get_pos_warehouse_for_user,
    get_pos_partner as _get_pos_partner,
    get_pos_cash_register as _get_pos_cash_register,
)

router = APIRouter(prefix="/sales", tags=["sales"])


@router.get("", response_class=HTMLResponse)
async def sales_list(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    status: Optional[str] = None,
    sort_by: Optional[str] = None,
    sort_dir: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    from urllib.parse import unquote
    q = db.query(Order).filter(Order.type == "sale")
    if date_from and date_from.strip():
        q = q.filter(Order.date >= date_from.strip()[:10] + " 00:00:00")
    if date_to and date_to.strip():
        q = q.filter(Order.date <= date_to.strip()[:10] + " 23:59:59")
    wh_id = None
    if warehouse_id and str(warehouse_id).strip().isdigit():
        try:
            wh_id = int(warehouse_id)
        except (ValueError, TypeError):
            pass
    if wh_id is not None and wh_id > 0:
        q = q.filter(Order.warehouse_id == wh_id)
    status_filter = (status or "").strip()
    if status_filter:
        q = q.filter(Order.status == status_filter)
    sort_col = (sort_by or "date").strip().lower()
    sort_order = (sort_dir or "desc").strip().lower()
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"
    if sort_col == "number":
        q = q.order_by(Order.number.asc() if sort_order == "asc" else Order.number.desc())
    elif sort_col == "date":
        q = q.order_by(Order.date.asc() if sort_order == "asc" else Order.date.desc())
    elif sort_col == "partner":
        q = q.outerjoin(Partner, Order.partner_id == Partner.id).order_by(
            Partner.name.asc() if sort_order == "asc" else Partner.name.desc()
        )
    elif sort_col == "warehouse":
        q = q.outerjoin(Warehouse, Order.warehouse_id == Warehouse.id).order_by(
            Warehouse.name.asc() if sort_order == "asc" else Warehouse.name.desc()
        )
    elif sort_col == "total":
        q = q.order_by(Order.total.asc() if sort_order == "asc" else Order.total.desc())
    elif sort_col == "status":
        q = q.order_by(Order.status.asc() if sort_order == "asc" else Order.status.desc())
    else:
        q = q.order_by(Order.date.desc())
    orders = q.limit(500).all()
    confirmed_orders = [o for o in orders if o.status in ('completed', 'confirmed')]
    total_sum = sum(float(o.total or 0) for o in confirmed_orders)
    # To'lov turlari bo'yicha statistika (faqat tasdiqlangan)
    # Kassadagi haqiqiy to'lovlardan hisoblash
    naqd_sum = 0
    plastik_sum = 0
    terminal_sum = 0
    click_sum = 0
    aralash_sum = 0
    for o in confirmed_orders:
        pt = (o.payment_type or '').strip().lower()
        t = float(o.total or 0)
        if pt == 'naqd':
            naqd_sum += t
        elif pt == 'plastik':
            plastik_sum += t
        elif pt == 'terminal':
            terminal_sum += t
        elif pt == 'click':
            click_sum += t
        elif pt in ('split', 'mixed', 'qarz', ''):
            aralash_sum += t
    qarz_sum = sum(float(o.debt or 0) for o in confirmed_orders if float(o.debt or 0) > 0)
    warehouses = get_warehouses_for_user(db, current_user)
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    info = request.query_params.get("info")
    info_detail = unquote(request.query_params.get("detail", "") or "") if info else ""
    sort_by_val = sort_col if sort_col in ("number", "date", "partner", "warehouse", "total", "status") else "date"
    from urllib.parse import urlencode
    filter_params = urlencode({
        k: v for k, v in [
            ("date_from", (date_from or "").strip()[:10] or None),
            ("date_to", (date_to or "").strip()[:10] or None),
            ("warehouse_id", wh_id if wh_id else None),
            ("status", status_filter or None),
        ] if v is not None
    })
    return templates.TemplateResponse("sales/list.html", {
        "request": request,
        "orders": orders,
        "total_sum": total_sum,
        "naqd_sum": naqd_sum,
        "plastik_sum": plastik_sum,
        "terminal_sum": terminal_sum,
        "click_sum": click_sum,
        "qarz_sum": qarz_sum,
        "aralash_sum": aralash_sum,
        "warehouses": warehouses,
        "date_from": (date_from or "").strip()[:10] or None,
        "date_to": (date_to or "").strip()[:10] or None,
        "selected_warehouse_id": wh_id,
        "selected_status": status_filter,
        "sort_by": sort_by_val,
        "sort_dir": sort_order,
        "filter_params": filter_params,
        "page_title": "Sotuvlar",
        "current_user": current_user,
        "error": error,
        "error_detail": error_detail,
    })


@router.get("/new", response_class=HTMLResponse)
async def sales_new(
    request: Request,
    price_type_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    ensure_order_item_warehouse_id_column(db)
    products = db.query(Product).options(
        joinedload(Product.unit),
    ).filter(
        Product.type.in_(["tayyor", "yarim_tayyor", "hom_ashyo", "material"]),
        Product.is_active == True,
    ).options(joinedload(Product.unit)).order_by(Product.name).all()
    partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    warehouses = get_warehouses_for_user(db, current_user)
    price_types = db.query(PriceType).filter(PriceType.is_active == True).order_by(PriceType.name).all()
    current_pt_id = price_type_id or (price_types[0].id if price_types else None)
    product_prices_by_type = {}
    if current_pt_id:
        pps = db.query(ProductPrice).filter(ProductPrice.price_type_id == current_pt_id).all()
        product_prices_by_type = {pp.product_id: pp.sale_price for pp in pps}
    warehouse_products = {}
    warehouse_stock_quantities = {}
    role = (current_user.role or "").strip()
    show_all_warehouses = role in ("admin", "manager")
    for wh in warehouses:
        rows = (
            db.query(Stock.product_id)
            .filter(Stock.warehouse_id == wh.id)
            .group_by(Stock.product_id)
            .having(func.sum(Stock.quantity) > 0)
            .all()
        )
        warehouse_products[str(wh.id)] = [r[0] for r in rows]
        qty_rows = (
            db.query(Stock.product_id, func.coalesce(func.sum(Stock.quantity), 0).label("total"))
            .filter(Stock.warehouse_id == wh.id)
            .group_by(Stock.product_id)
            .all()
        )
        warehouse_stock_quantities[str(wh.id)] = {str(r[0]): float(r[1] or 0) for r in qty_rows}
    product_warehouse_quantities = {}
    if show_all_warehouses and warehouses:
        all_pids = set()
        all_qty = {}
        for wh in warehouses:
            for pid in warehouse_products.get(str(wh.id), []):
                all_pids.add(pid)
            qty = warehouse_stock_quantities.get(str(wh.id), {})
            for pid, q in qty.items():
                all_qty[pid] = all_qty.get(pid, 0) + q
                if pid not in product_warehouse_quantities:
                    product_warehouse_quantities[pid] = {}
                product_warehouse_quantities[pid][str(wh.id)] = float(q)
        warehouse_products["all"] = list(all_pids)
        warehouse_stock_quantities["all"] = {str(k): v for k, v in all_qty.items()}
    return templates.TemplateResponse("sales/new.html", {
        "request": request,
        "products": products,
        "partners": partners,
        "warehouses": warehouses,
        "show_all_warehouses": show_all_warehouses,
        "price_types": price_types,
        "current_price_type_id": current_pt_id,
        "product_prices_by_type": product_prices_by_type,
        "warehouse_products": warehouse_products,
        "warehouse_stock_quantities": warehouse_stock_quantities,
        "product_warehouse_quantities": product_warehouse_quantities,
        "current_user": current_user,
        "page_title": "Yangi sotuv",
    })


@router.post("/create")
async def sales_create(
    request: Request,
    partner_id: int = Form(...),
    warehouse_id: int = Form(...),
    price_type_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    form = await request.form()
    product_ids = [int(x) for x in form.getlist("product_id") if str(x).strip().isdigit()]
    quantities_raw = form.getlist("quantity")
    prices_raw = form.getlist("price")
    warehouse_ids_raw = form.getlist("warehouse_id")
    quantities = []
    for q in quantities_raw:
        try:
            val = float(q)
            if 0 < val < 1_000_000:
                quantities.append(val)
        except (ValueError, TypeError):
            pass
    prices = []
    for p in prices_raw:
        try:
            val = float(p)
            if 0 <= val < 1_000_000_000:
                prices.append(val)
        except (ValueError, TypeError):
            pass
    warehouse_ids = []
    for w in warehouse_ids_raw:
        try:
            if str(w).strip().isdigit():
                warehouse_ids.append(int(w))
            else:
                warehouse_ids.append(None)
        except (ValueError, TypeError):
            warehouse_ids.append(None)
    last_order = db.query(Order).filter(Order.type == "sale").order_by(Order.id.desc()).first()
    new_number = f"S-{datetime.now().strftime('%Y%m%d')}-{(last_order.id + 1) if last_order else 1:04d}"
    order = Order(
        number=new_number,
        type="sale",
        partner_id=partner_id,
        warehouse_id=warehouse_id,
        price_type_id=price_type_id if price_type_id else None,
        status="draft",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    for i in range(min(len(product_ids), len(quantities))):
        pid, qty = product_ids[i], float(quantities[i])
        if pid and qty > 0:
            item_wh_id = warehouse_ids[i] if i < len(warehouse_ids) and warehouse_ids[i] else warehouse_id
            price = prices[i] if i < len(prices) and prices[i] >= 0 else None
            if price is None or price < 0:
                pp = db.query(ProductPrice).filter(
                    ProductPrice.product_id == pid,
                    ProductPrice.price_type_id == order.price_type_id,
                ).first()
                price = pp.sale_price or 0 if pp else 0
                if not price:
                    prod = db.query(Product).filter(Product.id == pid).first()
                    price = (prod.sale_price or prod.purchase_price or 0) if prod else 0
            total_row = qty * price
            db.add(OrderItem(order_id=order.id, product_id=pid, warehouse_id=item_wh_id, quantity=qty, price=price, total=total_row))
            order.subtotal = (order.subtotal or 0) + total_row
            order.total = (order.total or 0) + total_row
    db.commit()
    return RedirectResponse(url=f"/sales/edit/{order.id}", status_code=303)


@router.get("/edit/{order_id}", response_class=HTMLResponse)
async def sales_edit(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    from urllib.parse import unquote
    order = db.query(Order).options(
        joinedload(Order.items).joinedload(OrderItem.product),
    ).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    _check_order_access(order, current_user)
    products = db.query(Product).filter(
        Product.type.in_(["tayyor", "yarim_tayyor"]),
        Product.is_active == True,
    ).order_by(Product.name).all()
    product_prices_by_type = {}
    if order.price_type_id:
        pps = db.query(ProductPrice).filter(ProductPrice.price_type_id == order.price_type_id).all()
        product_prices_by_type = {pp.product_id: pp.sale_price for pp in pps}
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    info = request.query_params.get("info")
    info_detail = unquote(request.query_params.get("detail", "") or "") if info else ""
    foyda_zarar = 0
    for item in order.items:
        cost = 0
        if item.product:
            # Tannarxni stock.cost_price dan olish (ombordagi haqiqiy tannarx)
            item_wh = getattr(item, "warehouse_id", None) or order.warehouse_id
            st = db.query(Stock).filter(
                Stock.warehouse_id == item_wh,
                Stock.product_id == item.product_id,
            ).first()
            if st and st.cost_price and st.cost_price > 0:
                cost = st.cost_price
            # cost_price topilmasa, cost=0 qoladi (noto'g'ri purchase_price ishlatilmaydi)
        foyda_zarar += (item.quantity or 0) * ((item.price or 0) - cost)
    role = (getattr(current_user, "role", None) or "").strip().lower() if current_user else ""
    # Foyda/Zarar faqat admin yoki rahbar/raxbar ko'radi
    show_foyda_zarar = bool(role in ("admin", "rahbar", "raxbar"))
    return templates.TemplateResponse("sales/edit.html", {
        "request": request,
        "order": order,
        "products": products,
        "product_prices_by_type": product_prices_by_type,
        "current_user": current_user,
        "page_title": f"Sotuv: {order.number}",
        "error": error,
        "error_detail": error_detail,
        "info": info,
        "info_detail": info_detail,
        "foyda_zarar": foyda_zarar,
        "show_foyda_zarar": show_foyda_zarar,
    })


@router.post("/{order_id}/add-item")
async def sales_add_item(
    order_id: int,
    product_id: int = Form(...),
    quantity: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    _check_order_access(order, current_user)
    if order.status != "draft":
        return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)
    price = 0
    pp = db.query(ProductPrice).filter(
        ProductPrice.product_id == product_id,
        ProductPrice.price_type_id == order.price_type_id,
    ).first()
    if pp:
        price = pp.sale_price or 0
    if not price:
        prod = db.query(Product).filter(Product.id == product_id).first()
        price = (prod.sale_price or prod.purchase_price or 0) if prod else 0
    total_row = quantity * price
    db.add(OrderItem(order_id=order_id, product_id=product_id, quantity=quantity, price=price, total=total_row))
    order.subtotal = (order.subtotal or 0) + total_row
    order.total = (order.total or 0) + total_row
    db.commit()
    return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)


@router.post("/{order_id}/add-items")
async def sales_add_items(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    _check_order_access(order, current_user)
    if order.status != "draft":
        return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)
    form = await request.form()
    product_ids = [int(x) for x in form.getlist("product_id") if str(x).strip().isdigit()]
    quantities_raw = form.getlist("quantity")
    prices_raw = form.getlist("price")
    quantities = []
    for q in quantities_raw:
        try:
            val = float(q)
            if 0 < val < 1_000_000:
                quantities.append(val)
        except (ValueError, TypeError):
            pass
    prices = []
    for p in prices_raw:
        try:
            val = float(p)
            if 0 <= val < 1_000_000_000:
                prices.append(val)
        except (ValueError, TypeError):
            pass
    for i in range(min(len(product_ids), len(quantities))):
        pid, qty = product_ids[i], quantities[i]
        if not pid or qty <= 0:
            continue
        price = prices[i] if i < len(prices) and prices[i] >= 0 else None
        if price is None or price < 0:
            pp = db.query(ProductPrice).filter(
                ProductPrice.product_id == pid,
                ProductPrice.price_type_id == order.price_type_id,
            ).first()
            price = pp.sale_price or 0 if pp else 0
            if not price:
                prod = db.query(Product).filter(Product.id == pid).first()
                price = (prod.sale_price or prod.purchase_price or 0) if prod else 0
        total_row = qty * price
        db.add(OrderItem(order_id=order_id, product_id=pid, warehouse_id=order.warehouse_id, quantity=qty, price=price, total=total_row))
        order.subtotal = (order.subtotal or 0) + total_row
        order.total = (order.total or 0) + total_row
    db.commit()
    return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)


@router.post("/{order_id}/confirm")
async def sales_confirm(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    _check_order_access(order, current_user)
    if order.status != "draft":
        return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)

    # Qoldiq tekshiruvi va yetarli bo'lmagan mahsulotlarni yig'ish
    # Agar tanlangan omborda qoldiq 0 yoki <1 bo'lsa, avval yarim tayyor omborni tekshiramiz
    insufficient_items = []
    semi_warehouse = get_semi_finished_warehouse(db)
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == item.product_id,
        ).first()
        available = stock.quantity if stock else 0.0
        if available < item.quantity:
            # Yarim tayyor omborda shu mahsulot bormi?
            semi_available = 0.0
            if semi_warehouse:
                semi_available = get_product_stock_in_warehouse(db, semi_warehouse.id, item.product_id)
            if semi_available >= 1 and semi_available >= item.quantity:
                # Yarim tayyor omborda yetarli — kesuvchi + qadoqlovchiga bildirish
                notify_cutting_packing_operators(
                    db=db,
                    order_number=order.number,
                    order_id=order.id,
                    product_name=(item.product.name if item.product else "Mahsulot"),
                )
                continue
            # Yarim tayyor omborda ham yetarli emas — qiyom operatoriga bildirish
            notify_qiyom_operators(
                db=db,
                order_number=order.number,
                order_id=order.id,
                product_name=(item.product.name if item.product else "Mahsulot"),
            )
            insufficient_items.append({
                "product": item.product,
                "required": item.quantity,
                "available": available
            })
    
    # Agar yetarli bo'lmagan mahsulotlar bo'lsa, ishlab chiqarishga yo'naltirish
    if insufficient_items:
        try:
            # Yetmayotgan mahsulotlar ro'yxati (foydalanuvchiga ko'rsatish uchun)
            parts = []
            for it in insufficient_items:
                p = it.get("product")
                name = (getattr(p, "name", None) or "Mahsulot")
                req = float(it.get("required") or 0)
                avail = float(it.get("available") or 0)
                lack = max(req - avail, 0.0)
                parts.append(f"{name}: kerak {req:g}, mavjud {avail:g}, yetmaydi {lack:g}")
            detail_list = "; ".join(parts[:12]) + ("; ..." if len(parts) > 12 else "")

            productions, missing = create_production_from_order(
                db=db,
                order=order,
                insufficient_items=insufficient_items,
                current_user=current_user
            )
            if not productions:
                db.rollback()
                msg = "Ishlab chiqarish buyurtmasi yaratilmadi."
                if missing:
                    msg += " Retsept topilmadi: " + ", ".join(missing[:10]) + ("…" if len(missing) > 10 else "")
                return RedirectResponse(
                    url=f"/sales/edit/{order_id}?error=production&detail=" + quote(msg),
                    status_code=303,
                )

            # Production yaratilsa — buyurtma ishlab chiqarishni kutmoqda
            order.status = "waiting_production"
            db.commit()
            
            # Xabar bilan qaytish
            production_numbers = ", ".join([p.number for p in productions])
            return RedirectResponse(
                url=f"/sales/edit/{order_id}?info=production&detail=" + quote(
                    f"Yetmayotganlar: {detail_list}. "
                    f"Ishlab chiqarish buyurtmalari yaratildi: {production_numbers}. "
                    f"Mahsulotlar tayyor bo'lgach, buyurtma tasdiqlanadi."
                ),
                status_code=303,
            )
        except Exception as e:
            db.rollback()
            return RedirectResponse(
                url=f"/sales/edit/{order_id}?error=production&detail=" + quote("Ishlab chiqarish yaratishda xatolik yuz berdi"),
                status_code=303,
            )
    
    # Barcha mahsulotlar yetarli bo'lsa, oddiy sotuv sifatida tasdiqlash
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == item.product_id,
        ).first()
        if stock:
            stock.quantity -= item.quantity
    order.status = "completed"
    # Qarzdorlikni hisoblash
    order.debt = max(0.0, (order.total or 0) - (order.paid or 0))
    # Partner balansini yangilash
    if order.partner_id and order.debt > 0:
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        if partner:
            partner.balance = (partner.balance or 0) + order.debt
    db.commit()
    check_low_stock_and_notify(db)
    # Telegram bildirish
    try:
        from app.bot.services.notifier import notify_new_sale, notify_big_sale
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first() if order.partner_id else None
        p_name = partner.name if partner else "Naqd"
        notify_new_sale(order.number, p_name, order.total or 0, order.paid or 0)
        if (order.total or 0) >= 10_000_000:
            notify_big_sale(order.number, p_name, order.total)
    except Exception:
        pass
    return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)


@router.post("/{order_id}/delete-item/{item_id}")
async def sales_delete_item(
    order_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order or order.status != "draft":
        return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)
    _check_order_access(order, current_user)
    item = db.query(OrderItem).filter(OrderItem.id == item_id, OrderItem.order_id == order_id).first()
    if item:
        order.total = (order.total or 0) - (item.total or 0)
        order.subtotal = (order.subtotal or 0) - (item.total or 0)
        db.delete(item)
        db.commit()
    return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)


@router.post("/{order_id}/revert")
async def sales_revert(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    status = (getattr(order, "status", None) or "").strip().lower()
    if status == "waiting_production":
        # Ombor hisobdan chiqarilmagan — faqat draft ga qaytarish
        order.status = "draft"
        db.commit()
        return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)
    if status != "completed":
        return RedirectResponse(
            url=f"/sales/edit/{order_id}?error=revert&detail=" + quote("Faqat bajarilgan sotuvning tasdiqini bekor qilish mumkin."),
            status_code=303,
        )
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == item.product_id,
        ).first()
        if stock:
            stock.quantity = (stock.quantity or 0) + item.quantity
    order.status = "draft"
    db.commit()
    return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)


@router.get("/{order_id}/nakladnoy", response_class=HTMLResponse)
async def sales_nakladnoy(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuv nakladnoy — tasdiqlangan sotuv uchun chop etish."""
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product).joinedload(Product.unit),
            joinedload(Order.partner),
            joinedload(Order.warehouse),
            joinedload(Order.user),
            joinedload(Order.price_type),
        )
        .filter(Order.id == order_id, Order.type == "sale")
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    return templates.TemplateResponse("sales/nakladnoy.html", {
        "request": request,
        "order": order,
        "current_user": current_user,
    })


@router.post("/delete/{order_id}")
async def sales_delete(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sotuvni o'chirish (admin). Qoralama — bekor qilingan qiladi; bekor qilingan — bazadan o'chiradi."""
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")
    if order.status not in ("draft", "cancelled", "waiting_production"):
        return RedirectResponse(
            url="/sales?error=delete&detail=" + quote("Faqat qoralama yoki bekor qilingan sotuvni o'chirish mumkin. Avval tasdiqni bekor qiling."),
            status_code=303,
        )
    if order.status == "draft":
        order.status = "cancelled"
        db.commit()
    else:
        db.query(OrderItem).filter(OrderItem.order_id == order_id).delete()
        db.query(Payment).filter(Payment.order_id == order_id).update({Payment.order_id: None})
        db.query(Order).filter(Order.id == order_id).delete()
        db.commit()
    return RedirectResponse(url="/sales", status_code=303)


# ---------- POS (sotuv oynasi) ----------
@router.get("/pos", response_class=HTMLResponse)
async def sales_pos(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuv oynasi: faqat sotuvchi (yoki admin/menejer). Tovarlar foydalanuvchi bo'limi/omboridan."""
    ensure_orders_payment_due_date_column(db)
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return RedirectResponse(url="/?error=pos_access", status_code=303)
    pos_user_warehouses = _get_pos_warehouses_for_user(db, current_user)
    sales_warehouse = _get_pos_warehouse_for_user(db, current_user)
    warehouse_id_param = request.query_params.get("warehouse_id")
    if warehouse_id_param and pos_user_warehouses:
        try:
            wid = int(warehouse_id_param)
            chosen = next((w for w in pos_user_warehouses if w.id == wid), None)
            if chosen:
                sales_warehouse = chosen
        except (TypeError, ValueError):
            pass
    from datetime import date as date_type
    today_date = date_type.today()
    pos_today_orders = db.query(Order).filter(
        Order.type == "sale",
        Order.status == "completed",
        func.date(Order.created_at) == today_date,
    ).order_by(Order.created_at.desc()).limit(10).all()
    if not sales_warehouse and role == "sotuvchi":
        err = "no_warehouse"
        detail_msg = "Sizga ombor yoki bo'lim biriktirilmagan. Administrator bilan bog'laning."
        return templates.TemplateResponse("sales/pos.html", {
            "request": request,
            "page_title": "Sotuv oynasi",
            "current_user": current_user,
            "warehouse": None,
            "pos_user_warehouses": pos_user_warehouses,
            "pos_today_orders": pos_today_orders,
            "products": [],
            "product_prices": {},
            "stock_by_product": {},
            "pos_categories": [],
            "pos_all_categories": [],
            "pos_partners": [],
            "default_partner_id": None,
            "success": request.query_params.get("success"),
            "error": err,
            "error_detail": detail_msg,
            "number": request.query_params.get("number", ""),
        })
    # Faqat tanlangan ombordagi mahsulotlar (admin/menejer/sotuvchi — hammasi uchun bir xil)
    if not sales_warehouse:
        stock_rows = []
    else:
        stock_rows = db.query(Stock.product_id, Stock.quantity).filter(
            Stock.warehouse_id == sales_warehouse.id,
            Stock.quantity > 0,
        ).all()
    stock_by_product = {}
    for r in stock_rows:
        pid, qty = r[0], float(r[1] or 0)
        stock_by_product[pid] = stock_by_product.get(pid, 0) + qty
    product_ids_in_warehouse = list(stock_by_product.keys())
    if product_ids_in_warehouse:
        products = db.query(Product).options(joinedload(Product.unit)).filter(
            Product.id.in_(product_ids_in_warehouse),
            Product.is_active == True,
        ).order_by(Product.name).all()
    else:
        products = []
    price_type = _get_pos_price_type(db)
    product_prices = {}
    if price_type and product_ids_in_warehouse:
        pps = db.query(ProductPrice).filter(
            ProductPrice.price_type_id == price_type.id,
            ProductPrice.product_id.in_(product_ids_in_warehouse),
        ).all()
        product_prices = {pp.product_id: float(pp.sale_price or 0) for pp in pps}
    for p in products:
        if p.id not in product_prices or product_prices[p.id] == 0:
            product_prices[p.id] = float(p.sale_price or p.purchase_price or 0)
    pos_categories = []
    if products:
        cat_ids = list({p.category_id for p in products if p.category_id})
        if cat_ids:
            for c in db.query(Category).filter(Category.id.in_(cat_ids)).order_by(Category.name).all():
                pos_categories.append({"id": c.id, "name": c.name or c.code or ""})
    # Dropdown uchun barcha kategoriyalar (omborda qoldiq bo'lmasa ham)
    pos_all_categories = [
        {"id": c.id, "name": c.name or c.code or ""} for c in
        db.query(Category).order_by(Category.name).all()
    ]
    success = request.query_params.get("success")
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    number = request.query_params.get("number", "")
    user_with_partners = db.query(User).options(joinedload(User.partners_list)).filter(User.id == current_user.id).first()
    if user_with_partners and getattr(user_with_partners, "partners_list", None):
        assigned = [p for p in user_with_partners.partners_list if getattr(p, "is_active", True)]
        if assigned:
            pos_partners = sorted(assigned, key=lambda p: (p.name or ""))
        else:
            pos_partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    else:
        pos_partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    default_partner = _get_pos_partner(db)
    default_partner_id = default_partner.id if default_partner else None
    if pos_partners and default_partner_id is not None:
        if not any(p.id == default_partner_id for p in pos_partners):
            default_partner_id = pos_partners[0].id if pos_partners else None
    # Harajat turlari (POS expense modal uchun)
    pos_expense_types = db.query(ExpenseType).order_by(ExpenseType.name).all()
    return templates.TemplateResponse("sales/pos.html", {
        "request": request,
        "page_title": "Sotuv oynasi",
        "current_user": current_user,
        "warehouse": sales_warehouse,
        "pos_user_warehouses": pos_user_warehouses,
        "pos_today_orders": pos_today_orders,
        "products": products,
        "product_prices": product_prices,
        "stock_by_product": stock_by_product,
        "price_type": price_type,
        "pos_categories": pos_categories,
        "pos_all_categories": pos_all_categories,
        "pos_partners": pos_partners,
        "default_partner_id": default_partner_id,
        "pos_expense_types": pos_expense_types,
        "success": success,
        "error": error,
        "error_detail": error_detail,
        "number": number,
    })


@router.get("/pos/daily-orders")
async def sales_pos_daily_orders(
    request: Request,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    order_type: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Kunlik / sanadan-sanagacha sotuvlar yoki qaytarishlar ro'yxati (JSON)."""
    from datetime import date as date_type, datetime as dt
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return []
    today = date_type.today()
    try:
        d_from = dt.strptime(date_from, "%Y-%m-%d").date() if date_from else today
    except (ValueError, TypeError):
        d_from = today
    try:
        d_to = dt.strptime(date_to, "%Y-%m-%d").date() if date_to else today
    except (ValueError, TypeError):
        d_to = today
    if d_from > d_to:
        d_from, d_to = d_to, d_from
    o_type = (order_type or "sale").strip().lower()
    if o_type != "return_sale":
        o_type = "sale"
    orders = db.query(Order).filter(
        Order.type == o_type,
        Order.status == "completed",
        func.date(Order.created_at) >= d_from,
        func.date(Order.created_at) <= d_to,
    ).order_by(Order.created_at.desc()).limit(200).all()
    out = []
    for o in orders:
        out.append({
            "id": o.id,
            "number": o.number or "",
            "type": o.type or "sale",
            "created_at": o.created_at.strftime("%H:%M") if o.created_at else "-",
            "date": o.created_at.strftime("%d.%m.%Y") if o.created_at else "-",
            "partner_name": o.partner.name if o.partner else "-",
            "warehouse_name": o.warehouse.name if o.warehouse else "-",
            "total": float(o.total or 0),
        })
    return out


@router.post("/pos/draft/save")
async def sales_pos_draft_save(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Chekni saqlash — savatdagi tovarlarni vaqtinchalik saqlab qo'yish."""
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return JSONResponse({"ok": False, "error": "Ruxsat yo'q"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON xato"}, status_code=400)
    items = body.get("items")
    if not items or not isinstance(items, list):
        return JSONResponse({"ok": False, "error": "Savat bo'sh. Kamida bitta mahsulot qo'shing."}, status_code=400)
    warehouse = _get_pos_warehouse_for_user(db, current_user)
    name = (body.get("name") or "").strip() or None
    items_json = json.dumps(items, ensure_ascii=False)
    draft = PosDraft(
        user_id=current_user.id,
        warehouse_id=warehouse.id if warehouse else None,
        name=name,
        items_json=items_json,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return JSONResponse({"ok": True, "id": draft.id, "message": "Chek saqlandi."})


@router.get("/pos/drafts")
async def sales_pos_drafts_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Saqlangan cheklar ro'yxati."""
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return JSONResponse([], status_code=200)
    drafts = (
        db.query(PosDraft)
        .filter(PosDraft.user_id == current_user.id)
        .order_by(PosDraft.created_at.desc())
        .limit(50)
        .all()
    )
    out = []
    for d in drafts:
        try:
            items = json.loads(d.items_json or "[]")
        except Exception:
            items = []
        total = sum((float(x.get("price") or 0) * float(x.get("quantity") or 0)) for x in items)
        out.append({
            "id": d.id,
            "name": d.name or f"Chek #{d.id}",
            "created_at": d.created_at.strftime("%d.%m.%Y %H:%M") if d.created_at else "-",
            "total": round(total, 2),
            "item_count": len(items),
        })
    return out


@router.get("/pos/draft/{draft_id}")
async def sales_pos_draft_get(
    draft_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Bitta saqlangan chekni olish (savatga yuklash uchun)."""
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return JSONResponse({"ok": False, "error": "Ruxsat yo'q"}, status_code=403)
    draft = db.query(PosDraft).filter(PosDraft.id == draft_id, PosDraft.user_id == current_user.id).first()
    if not draft:
        return JSONResponse({"ok": False, "error": "Chek topilmadi"}, status_code=404)
    try:
        items = json.loads(draft.items_json or "[]")
    except Exception:
        items = []
    return JSONResponse({"ok": True, "items": items})


@router.post("/pos/complete")
async def sales_pos_complete(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """POS savatni sotuv qilish. Naqd mijoz → pul kassaga; boshqa kontragent → qarz."""
    ensure_orders_payment_due_date_column(db)
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return RedirectResponse(url="/?error=pos_access", status_code=303)
    form = await request.form()
    payment_type = (form.get("payment_type") or "").strip().lower()
    if payment_type not in ("naqd", "plastik", "click", "terminal", "split"):
        return RedirectResponse(url="/sales/pos?error=payment", status_code=303)
    warehouse = _get_pos_warehouse_for_user(db, current_user)
    wh_id_form = form.get("warehouse_id")
    if wh_id_form:
        try:
            wh_id = int(wh_id_form)
            allowed = _get_pos_warehouses_for_user(db, current_user)
            chosen = next((w for w in allowed if w.id == wh_id), None)
            if chosen:
                warehouse = chosen
        except (TypeError, ValueError):
            pass
    default_partner = _get_pos_partner(db)
    if not warehouse or not default_partner:
        return RedirectResponse(url="/sales/pos?error=config", status_code=303)
    partner_id_form = form.get("partner_id")
    partner = default_partner
    if partner_id_form and str(partner_id_form).strip().isdigit():
        try:
            pid = int(partner_id_form)
            p = db.query(Partner).filter(Partner.id == pid, Partner.is_active == True).first()
            if p:
                partner = p
        except (ValueError, TypeError):
            pass
    product_ids = [int(x) for x in form.getlist("product_id") if str(x).strip().isdigit()]
    quantities = []
    for q in form.getlist("quantity"):
        try:
            quantities.append(float(q))
        except (ValueError, TypeError):
            pass
    prices = []
    for p in form.getlist("price"):
        try:
            prices.append(float(p))
        except (ValueError, TypeError):
            pass
    if not product_ids or len(quantities) < len(product_ids):
        return RedirectResponse(url="/sales/pos?error=empty", status_code=303)
    price_type = _get_pos_price_type(db)
    last_order = db.query(Order).filter(Order.type == "sale").order_by(Order.id.desc()).first()
    new_number = f"S-{datetime.now().strftime('%Y%m%d')}-{(last_order.id + 1) if last_order else 1:04d}"
    order = Order(
        number=new_number,
        type="sale",
        partner_id=partner.id,
        warehouse_id=warehouse.id,
        price_type_id=price_type.id if price_type else None,
        user_id=current_user.id if current_user else None,
        status="draft",
        payment_type=payment_type,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    total_order = 0.0
    items_for_stock = []
    for i in range(min(len(product_ids), len(quantities))):
        pid, qty = product_ids[i], float(quantities[i])
        if not pid or qty <= 0:
            continue
        price = prices[i] if i < len(prices) and prices[i] >= 0 else None
        if price is None or price < 0:
            pp = db.query(ProductPrice).filter(ProductPrice.product_id == pid, ProductPrice.price_type_id == order.price_type_id).first()
            if pp:
                price = pp.sale_price or 0
            else:
                prod = db.query(Product).filter(Product.id == pid).first()
                price = (prod.sale_price or prod.purchase_price or 0) if prod else 0
        total_row = qty * price
        db.add(OrderItem(order_id=order.id, product_id=pid, quantity=qty, price=price, total=total_row))
        total_order += total_row
        items_for_stock.append((pid, qty))
    order.subtotal = total_order
    discount_percent = 0.0
    discount_amount = 0.0
    try:
        discount_percent = float(form.get("discount_percent") or 0)
    except (ValueError, TypeError):
        pass
    try:
        discount_amount = float(form.get("discount_amount") or 0)
    except (ValueError, TypeError):
        pass
    if discount_percent < 0 or discount_percent > 100:
        discount_percent = 0.0
    if discount_amount < 0 or discount_amount > total_order:
        discount_amount = 0.0
    discount_sum = (total_order * discount_percent / 100.0) + discount_amount
    if discount_sum > total_order:
        discount_sum = total_order
    order.discount_percent = discount_percent
    order.discount_amount = discount_amount
    order.total = total_order - discount_sum
    is_cash_client = (partner.id == default_partner.id)
    if is_cash_client:
        order.paid = order.total
        order.debt = 0
    else:
        order.paid = 0
        order.debt = order.total
        due_str = (form.get("payment_due_date") or "").strip()
        if due_str:
            try:
                order.payment_due_date = datetime.strptime(due_str, "%Y-%m-%d").date()
            except (ValueError, TypeError):
                order.payment_due_date = (datetime.now() + timedelta(days=7)).date()
        else:
            order.payment_due_date = (datetime.now() + timedelta(days=7)).date()
    # with_for_update() — bir vaqtda 2 so'rov bir xil zaxirani olishini oldini olish
    for pid, qty in items_for_stock:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == order.warehouse_id,
            Stock.product_id == pid
        ).with_for_update().first()
        if not stock or (stock.quantity or 0) < qty:
            prod = db.query(Product).filter(Product.id == pid).first()
            name = prod.name if prod else f"#{pid}"
            mavjud = float(stock.quantity or 0) if stock else 0
            order.status = "cancelled"
            db.commit()
            detail = f"Yetarli yo'q: {name} (savatda: {qty}, omborda: {mavjud:.0f})"
            url = "/sales/pos?error=stock&detail=" + quote(detail)
            if warehouse and warehouse.id:
                url += "&warehouse_id=" + str(warehouse.id)
            return RedirectResponse(url=url, status_code=303)
    for pid, qty in items_for_stock:
        create_stock_movement(
            db=db,
            warehouse_id=order.warehouse_id,
            product_id=pid,
            quantity_change=-qty,
            operation_type="sale",
            document_type="Sale",
            document_id=order.id,
            document_number=order.number,
            user_id=current_user.id if current_user else None,
            note=f"Sotuv (POS {payment_type}): {order.number}"
        )
    order.status = "completed"
    db.commit()
    if is_cash_client:
        department_id = getattr(warehouse, "department_id", None) if warehouse else None
        if not department_id and current_user:
            department_id = getattr(current_user, "department_id", None)
        def _map_pay_type(pt: str) -> str:
            pt = (pt or "").strip().lower()
            if pt == "naqd":
                return "cash"
            if pt == "click":
                return "click"
            if pt == "terminal":
                return "terminal"
            return "card"

        total_to_pay = float(order.total or 0)
        if total_to_pay > 0:
            parts = None
            if payment_type == "split":
                raw = (form.get("payment_splits") or "").strip()
                try:
                    parts = json.loads(raw) if raw else None
                except Exception:
                    parts = None
                if not isinstance(parts, list) or not parts:
                    return RedirectResponse(url="/sales/pos?error=payment", status_code=303)
                cleaned = []
                sum_parts = 0.0
                allowed = ("naqd", "plastik", "click", "terminal")
                for p in parts:
                    if not isinstance(p, dict):
                        continue
                    t = (p.get("type") or "").strip().lower()
                    if t not in allowed:
                        continue
                    try:
                        amt = float(p.get("amount") or 0)
                    except (ValueError, TypeError):
                        amt = 0.0
                    if amt <= 0:
                        continue
                    cleaned.append({"type": t, "amount": amt})
                    sum_parts += amt
                if not cleaned or abs(sum_parts - total_to_pay) >= 0.01:
                    return RedirectResponse(url="/sales/pos?error=payment", status_code=303)
                parts = cleaned
            else:
                parts = [{"type": payment_type, "amount": total_to_pay}]

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
            for part in parts:
                pt = part["type"]
                amt = float(part["amount"] or 0)
                cash_register = _get_pos_cash_register(db, pt, department_id)
                if not cash_register:
                    return RedirectResponse(url="/sales/pos?error=payment", status_code=303)
                pay_number = f"PAY-{today_str}-{seq:04d}"
                seq += 1
                db.add(Payment(
                    number=pay_number,
                    type="income",
                    cash_register_id=cash_register.id,
                    partner_id=order.partner_id,
                    order_id=order.id,
                    amount=amt,
                    payment_type=_map_pay_type(pt),
                    category="sale",
                    description=f"POS sotuv {order.number}",
                    user_id=current_user.id if current_user else None,
                ))
                if getattr(cash_register, "balance", None) is not None:
                    cash_register.balance = (cash_register.balance or 0) + amt
            db.commit()
    else:
        partner.balance = (partner.balance or 0) + (order.total or 0)
        db.commit()
    log_action(db, user=current_user, action="create", entity_type="sale",
               entity_id=order.id, entity_number=order.number,
               details=f"Summa: {order.total:,.0f}, To'lov: {payment_type}, Partner: {partner.name}",
               ip_address=request.client.host if request.client else "")
    db.commit()
    check_low_stock_and_notify(db)
    return RedirectResponse(url="/sales/pos?success=1&number=" + order.number, status_code=303)


@router.get("/pos/receipt", response_class=HTMLResponse)
async def sales_pos_receipt(
    request: Request,
    number: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """POS sotuv cheki — chop etish sahifasi."""
    if not number or not number.strip():
        return HTMLResponse("<html><body><p>Hujjat raqami ko'rsatilmagan.</p></body></html>", status_code=400)
    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product),
            joinedload(Order.partner),
            joinedload(Order.user),
        )
        .filter(Order.number == number.strip(), Order.type == "sale")
        .first()
    )
    if not order:
        return HTMLResponse("<html><body><p>Hujjat topilmadi.</p></body></html>", status_code=404)
    receipt_barcode_b64 = None
    try:
        writer = ImageWriter()
        writer.set_options({
            "module_width": 0.35,
            "module_height": 14,
            "font_size": 10,
            "dpi": 600,
        })
        buf = io.BytesIO()
        code128 = barcode.get("code128", order.number, writer=writer)
        code128.write(buf)
        buf.seek(0)
        receipt_barcode_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        pass
    return templates.TemplateResponse("sales/pos_receipt.html", {
        "request": request,
        "order": order,
        "receipt_barcode_b64": receipt_barcode_b64,
    })


# ---------- Savdodan qaytarish ----------
@router.get("/returns", response_class=HTMLResponse)
async def sales_returns_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    """Savdodan qaytarish — bajarilgan sotuvlar ro'yxati."""
    orders = db.query(Order).filter(
        Order.type == "sale",
        Order.status == "completed"
    ).options(
        joinedload(Order.partner),
        joinedload(Order.warehouse),
    ).order_by(Order.date.desc()).limit(200).all()
    success = request.query_params.get("success")
    number = request.query_params.get("number", "")
    warehouse_name = unquote(request.query_params.get("warehouse", "") or "")
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    return_docs = db.query(Order).filter(
        Order.type == "return_sale"
    ).options(
        joinedload(Order.partner),
        joinedload(Order.warehouse),
    ).order_by(Order.created_at.desc()).limit(100).all()
    return templates.TemplateResponse("sales/returns_list.html", {
        "request": request,
        "orders": orders,
        "return_docs": return_docs,
        "page_title": "Savdodan qaytarish",
        "current_user": current_user,
        "success": success,
        "number": number,
        "warehouse_name": warehouse_name,
        "error": error,
        "error_detail": error_detail,
    })


@router.get("/return/{order_id}", response_class=HTMLResponse)
async def sales_return_form(
    request: Request,
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Savdodan qaytarish — tanlangan sotuv bo'yicha qaytarish miqdorlarini kiritish."""
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.type == "sale",
        Order.status == "completed"
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi yoki bajarilmagan.")
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    return templates.TemplateResponse("sales/return_form.html", {
        "request": request,
        "order": order,
        "page_title": "Savdodan qaytarish",
        "current_user": current_user,
        "error": error,
        "error_detail": error_detail,
    })


@router.post("/return/create")
async def sales_return_create(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Savdodan qaytarishni rasmiylashtirish."""
    form = await request.form()
    order_id_raw = form.get("order_id")
    if not order_id_raw or not str(order_id_raw).strip().isdigit():
        return RedirectResponse(url="/sales/returns?error=empty&detail=" + quote("Sotuv tanlanmadi."), status_code=303)
    order_id = int(order_id_raw)
    sale = db.query(Order).filter(
        Order.id == order_id,
        Order.type == "sale",
        Order.status == "completed"
    ).options(joinedload(Order.items)).first()
    if not sale:
        return RedirectResponse(url="/sales/returns?error=not_found&detail=" + quote("Sotuv topilmadi."), status_code=303)
    product_ids = [int(x) for x in form.getlist("product_id") if str(x).strip().isdigit()]
    quantities_raw = form.getlist("quantity_return")
    quantities = []
    for q in quantities_raw:
        try:
            quantities.append(float(q))
        except (ValueError, TypeError):
            quantities.append(0)
    if not product_ids or all(q <= 0 for q in quantities[:len(product_ids)]):
        return RedirectResponse(
            url="/sales/return/" + str(order_id) + "?error=empty&detail=" + quote("Kamida bitta mahsulot uchun qaytarish miqdorini kiriting."),
            status_code=303
        )
    sale_items_by_product = {item.product_id: item for item in sale.items}
    for i in range(min(len(product_ids), len(quantities))):
        pid, qty = product_ids[i], quantities[i]
        if qty <= 0:
            continue
        item = sale_items_by_product.get(pid)
        if not item:
            prod = db.query(Product).filter(Product.id == pid).first()
            name = prod.name if prod else "#" + str(pid)
            return RedirectResponse(
                url="/sales/return/" + str(order_id) + "?error=qty&detail=" + quote(f"'{name}' ushbu sotuvda yo'q."),
                status_code=303
            )
        sold_qty = item.quantity or 0
        if qty > sold_qty + 1e-6:
            name = (item.product.name if item.product else "") or ("#" + str(pid))
            return RedirectResponse(
                url="/sales/return/" + str(order_id) + "?error=qty&detail=" + quote(f"'{name}' uchun qaytarish miqdori sotilgan miqdordan oshmasin (sotilgan: {sold_qty:.3f}, kiritilgan: {qty:.3f})."),
                status_code=303
            )
    from datetime import date as date_type
    today_start = date_type.today()
    # Do'kon omborlaridan qaytarilsa — o'sha omborga, qolganlaridan — Vozvrat omboriga
    sale_wh = db.query(Warehouse).filter(Warehouse.id == sale.warehouse_id).first()
    if sale_wh and "do'kon" in (sale_wh.name or "").lower():
        return_warehouse_id = sale.warehouse_id
    else:
        vozvrat_wh = db.query(Warehouse).filter(Warehouse.name.ilike("%vozvrat%"), Warehouse.is_active == True).first()
        return_warehouse_id = vozvrat_wh.id if vozvrat_wh else sale.warehouse_id
    if not return_warehouse_id:
        return RedirectResponse(
            url="/sales/returns?error=no_warehouse&detail=" + quote("Ombor topilmadi. Avval ombor yarating."),
            status_code=303
        )
    count = db.query(Order).filter(
        Order.type == "return_sale",
        func.date(Order.created_at) == today_start
    ).count()
    new_number = f"R-{datetime.now().strftime('%Y%m%d')}-{count + 1:04d}"
    return_order = Order(
        number=new_number,
        type="return_sale",
        partner_id=sale.partner_id,
        warehouse_id=return_warehouse_id,
        price_type_id=sale.price_type_id,
        user_id=current_user.id if current_user else None,
        status="completed",
        payment_type=sale.payment_type,
        note=f"Savdodan qaytarish: {sale.number}",
    )
    db.add(return_order)
    db.commit()
    db.refresh(return_order)
    total_return = 0.0
    for i in range(min(len(product_ids), len(quantities))):
        pid, qty = product_ids[i], quantities[i]
        if not pid or qty <= 0:
            continue
        item = sale_items_by_product.get(pid)
        if not item:
            continue
        price = item.price or 0
        total_row = qty * price
        db.add(OrderItem(order_id=return_order.id, product_id=pid, quantity=qty, price=price, total=total_row))
        total_return += total_row
        create_stock_movement(
            db=db,
            warehouse_id=return_warehouse_id,
            product_id=pid,
            quantity_change=+qty,
            operation_type="return_sale",
            document_type="SaleReturn",
            document_id=return_order.id,
            document_number=return_order.number,
            user_id=current_user.id if current_user else None,
            note=f"Savdodan qaytarish: {sale.number} -> {return_order.number}",
        )
    return_order.subtotal = total_return
    return_order.total = total_return
    return_order.paid = total_return
    return_order.debt = 0
    db.commit()
    wh_name = ""
    if return_warehouse_id:
        wh = db.query(Warehouse).filter(Warehouse.id == return_warehouse_id).first()
        wh_name = (wh.name or "").strip()
    params = "success=1&number=" + quote(return_order.number)
    if wh_name:
        params += "&warehouse=" + quote(wh_name)
    return RedirectResponse(url="/sales/returns?" + params, status_code=303)


@router.get("/return/document/{number}", response_class=HTMLResponse)
async def sales_return_document(
    request: Request,
    number: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Qaytarish hujjati (R-...) — ko'rish / chop etish."""
    doc = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product),
            joinedload(Order.partner),
            joinedload(Order.warehouse),
            joinedload(Order.user),
        )
        .filter(Order.number == number.strip(), Order.type == "return_sale")
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Qaytarish hujjati topilmadi.")
    return templates.TemplateResponse("sales/return_document.html", {
        "request": request,
        "doc": doc,
        "page_title": "Qaytarish " + doc.number,
        "current_user": current_user,
    })


@router.post("/return/revert/{return_order_id}")
async def sales_return_revert(
    return_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Qaytarish tasdiqini bekor qilish (faqat admin)."""
    doc = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.id == return_order_id, Order.type == "return_sale")
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Qaytarish hujjati topilmadi.")
    if doc.status != "completed":
        return RedirectResponse(
            url="/sales/returns?error=revert&detail=" + quote("Faqat tasdiqlangan qaytarishning tasdiqini bekor qilish mumkin."),
            status_code=303
        )
    wh_id = doc.warehouse_id
    if not wh_id:
        return RedirectResponse(
            url="/sales/returns?error=revert&detail=" + quote("Hujjatda ombor ko'rsatilmagan."),
            status_code=303
        )
    for item in doc.items:
        create_stock_movement(
            db=db,
            warehouse_id=wh_id,
            product_id=item.product_id,
            quantity_change=-(item.quantity or 0),
            operation_type="return_sale_revert",
            document_type="SaleReturnRevert",
            document_id=doc.id,
            document_number=doc.number,
            user_id=current_user.id if current_user else None,
            note=f"Qaytarish tasdiqini bekor: {doc.number}",
        )
    doc.status = "cancelled"
    db.commit()
    return RedirectResponse(url="/sales/return/document/" + doc.number + "?reverted=1", status_code=303)


@router.post("/return/delete/{return_order_id}")
async def sales_return_delete(
    return_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Qaytarish hujjatini o'chirish (faqat admin)."""
    doc = db.query(Order).filter(Order.id == return_order_id, Order.type == "return_sale").first()
    if not doc:
        raise HTTPException(status_code=404, detail="Qaytarish hujjati topilmadi.")
    if doc.status != "cancelled":
        return RedirectResponse(
            url="/sales/returns?error=delete&detail=" + quote("Faqat tasdiqni bekor qilgandan keyin o'chirish mumkin. Avval tasdiqni bekor qiling."),
            status_code=303
        )
    number = doc.number
    for item in list(doc.items):
        db.delete(item)
    db.delete(doc)
    db.commit()
    return RedirectResponse(url="/sales/returns?deleted=1&number=" + quote(number), status_code=303)


@router.get("/return/edit/{return_order_id}", response_class=HTMLResponse)
async def sales_return_edit_form(
    request: Request,
    return_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Qaytarish hujjatini tahrirlash (faqat tasdiqni bekor qilingan hujjat)."""
    doc = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product),
            joinedload(Order.partner),
            joinedload(Order.warehouse),
        )
        .filter(Order.id == return_order_id, Order.type == "return_sale")
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Qaytarish hujjati topilmadi.")
    if doc.status != "cancelled":
        return RedirectResponse(
            url="/sales/return/document/" + doc.number + "?error=edit&detail=" + quote("Faqat tasdiqni bekor qilingan hujjatni tahrirlash mumkin."),
            status_code=303
        )
    return templates.TemplateResponse("sales/return_edit.html", {
        "request": request,
        "doc": doc,
        "page_title": "Qaytarishni tahrirlash " + doc.number,
        "current_user": current_user,
    })


@router.post("/return/update")
async def sales_return_update(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Qaytarish hujjati qatorlarini yangilash — faqat bekor qilingan hujjat."""
    form = await request.form()
    order_id_raw = form.get("order_id")
    if not order_id_raw or not str(order_id_raw).strip().isdigit():
        return RedirectResponse(url="/sales/returns?error=update", status_code=303)
    return_order_id = int(order_id_raw)
    doc = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.id == return_order_id, Order.type == "return_sale")
        .first()
    )
    if not doc or doc.status != "cancelled":
        return RedirectResponse(url="/sales/returns?error=update&detail=" + quote("Hujjat topilmadi yoki tahrirlash mumkin emas."), status_code=303)
    product_ids = [int(x) for x in form.getlist("product_id") if str(x).strip().isdigit()]
    quantities = []
    for q in form.getlist("quantity"):
        try:
            quantities.append(float(q))
        except (ValueError, TypeError):
            quantities.append(0)
    prices = []
    for p in form.getlist("price"):
        try:
            prices.append(float(p))
        except (ValueError, TypeError):
            prices.append(0)
    items_by_pid = {item.product_id: item for item in doc.items}
    total_return = 0.0
    for i in range(min(len(product_ids), len(quantities))):
        pid, qty = product_ids[i], quantities[i]
        if not pid or qty < 0:
            continue
        item = items_by_pid.get(pid)
        if not item:
            continue
        price = prices[i] if i < len(prices) and prices[i] >= 0 else (item.price or 0)
        item.quantity = qty
        item.price = price
        item.total = qty * price
        total_return += item.total
    doc.subtotal = total_return
    doc.total = total_return
    doc.paid = total_return
    doc.debt = 0
    db.commit()
    return RedirectResponse(url="/sales/return/document/" + doc.number + "?updated=1", status_code=303)


@router.post("/return/confirm/{return_order_id}")
async def sales_return_confirm(
    return_order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Qaytarishni qayta tasdiqlash (faqat bekor qilingan hujjat): omborga qoldiq qo'shish."""
    doc = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.id == return_order_id, Order.type == "return_sale")
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Qaytarish hujjati topilmadi.")
    if doc.status != "cancelled":
        return RedirectResponse(
            url="/sales/returns?error=confirm&detail=" + quote("Faqat bekor qilingan hujjatni qayta tasdiqlash mumkin."),
            status_code=303
        )
    wh_id = doc.warehouse_id
    if not wh_id:
        return RedirectResponse(url="/sales/returns?error=confirm&detail=" + quote("Hujjatda ombor ko'rsatilmagan."), status_code=303)
    for item in doc.items:
        create_stock_movement(
            db=db,
            warehouse_id=wh_id,
            product_id=item.product_id,
            quantity_change=+(item.quantity or 0),
            operation_type="return_sale",
            document_type="SaleReturn",
            document_id=doc.id,
            document_number=doc.number,
            user_id=current_user.id if current_user else None,
            note=f"Qaytarish qayta tasdiqlandi: {doc.number}",
        )
    doc.status = "completed"
    db.commit()
    return RedirectResponse(url="/sales/return/document/" + doc.number + "?confirmed=1", status_code=303)


# ==================== POS: Ta'minotchiga to'lov ====================
@router.post("/pos/pay-supplier")
async def pos_pay_supplier(
    request: Request,
    partner_id: int = Form(...),
    amount: float = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuvchi o'z kassasidan ta'minotchiga to'lov qiladi."""
    if amount <= 0:
        return RedirectResponse(url="/sales/pos?error=payment&detail=Summa+noto'g'ri", status_code=303)
    partner = db.query(Partner).filter(Partner.id == partner_id).first()
    if not partner:
        return RedirectResponse(url="/sales/pos?error=payment&detail=Kontragent+topilmadi", status_code=303)
    # Sotuvchining kassasini topish
    department_id = getattr(current_user, "department_id", None)
    cash_register = _get_pos_cash_register(db, "naqd", department_id)
    if not cash_register:
        return RedirectResponse(url="/sales/pos?error=payment&detail=Kassa+topilmadi", status_code=303)
    # To'lov yaratish (chiqim)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    pay_count = db.query(Payment).filter(Payment.created_at >= today_start).count()
    pay_number = f"PAY-{datetime.now().strftime('%Y%m%d')}-{(pay_count + 1):04d}"
    db.add(Payment(
        number=pay_number,
        type="expense",
        cash_register_id=cash_register.id,
        partner_id=partner_id,
        amount=amount,
        payment_type="naqd",
        category="supplier_payment",
        description=note or f"Ta'minotchiga to'lov: {partner.name}",
        user_id=current_user.id,
    ))
    # Kassa balansini kamaytirish
    if getattr(cash_register, "balance", None) is not None:
        cash_register.balance = (cash_register.balance or 0) - amount
    # Partner balansini yangilash (qarzni kamaytirish)
    if partner.balance is not None:
        partner.balance = (partner.balance or 0) + amount  # balance < 0 — biz qarz, + qo'shsak kamayadi
    db.commit()
    return RedirectResponse(url="/sales/pos?success=1&number=" + quote(f"To'lov: {partner.name} ga {amount:,.0f} so'm"), status_code=303)


# ==================== POS: Harajat yozish ====================
@router.post("/pos/expense")
async def pos_expense(
    request: Request,
    expense_type: str = Form(...),
    amount: float = Form(...),
    note: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuvchi o'z kassasidan harajat yozadi."""
    if amount <= 0:
        return RedirectResponse(url="/sales/pos?error=payment&detail=Summa+noto'g'ri", status_code=303)
    # Harajat turi
    expense_type_name = "Boshqa"
    if expense_type != "other":
        et = db.query(ExpenseType).filter(ExpenseType.id == int(expense_type)).first()
        if et:
            expense_type_name = et.name
    # Sotuvchining kassasini topish
    department_id = getattr(current_user, "department_id", None)
    cash_register = _get_pos_cash_register(db, "naqd", department_id)
    if not cash_register:
        return RedirectResponse(url="/sales/pos?error=payment&detail=Kassa+topilmadi", status_code=303)
    # To'lov yaratish (chiqim — harajat)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    pay_count = db.query(Payment).filter(Payment.created_at >= today_start).count()
    pay_number = f"PAY-{datetime.now().strftime('%Y%m%d')}-{(pay_count + 1):04d}"
    description = f"Harajat: {expense_type_name}"
    if note:
        description += f" — {note}"
    db.add(Payment(
        number=pay_number,
        type="expense",
        cash_register_id=cash_register.id,
        amount=amount,
        payment_type="naqd",
        category="expense",
        description=description,
        user_id=current_user.id,
    ))
    # Kassa balansini kamaytirish
    if getattr(cash_register, "balance", None) is not None:
        cash_register.balance = (cash_register.balance or 0) - amount
    db.commit()
    return RedirectResponse(url="/sales/pos?success=1&number=" + quote(f"Harajat: {expense_type_name} — {amount:,.0f} so'm"), status_code=303)
