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
from sqlalchemy import func, or_

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
    CashTransfer,
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
from app.routes.period_close import is_period_closed
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
from app.services.finance_service import sync_cash_balance as _sync_cash_balance
from app.services.pos_helpers import (
    get_pos_price_type as _get_pos_price_type,
    get_pos_warehouses_for_user as _get_pos_warehouses_for_user,
    get_pos_warehouse_for_user as _get_pos_warehouse_for_user,
    get_pos_partner as _get_pos_partner,
    get_pos_cash_register as _get_pos_cash_register,
)
from app.constants import QUERY_LIMIT_DEFAULT, QUERY_LIMIT_HISTORY

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
    page: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    from urllib.parse import unquote
    from app.utils.pagination import paginate, pagination_query_string
    from sqlalchemy.orm import subqueryload
    q = db.query(Order).options(
        subqueryload(Order.partner), subqueryload(Order.warehouse)
    ).filter(Order.type == "sale")
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

    pg = paginate(q, page or 1, per_page=50)
    orders = pg["items"]

    from sqlalchemy import func as sa_func
    stats_row = db.query(
        sa_func.coalesce(sa_func.sum(Order.total), 0),
        sa_func.coalesce(sa_func.sum(Order.debt), 0),
        sa_func.count(Order.id),
    ).filter(
        Order.type == "sale",
        Order.status.in_(["completed", "confirmed"]),
    )
    if date_from and date_from.strip():
        stats_row = stats_row.filter(Order.date >= date_from.strip()[:10] + " 00:00:00")
    if date_to and date_to.strip():
        stats_row = stats_row.filter(Order.date <= date_to.strip()[:10] + " 23:59:59")
    if wh_id is not None and wh_id > 0:
        stats_row = stats_row.filter(Order.warehouse_id == wh_id)
    total_sum, qarz_sum, completed_count = stats_row.one()
    total_sum = float(total_sum or 0)
    qarz_sum = float(qarz_sum or 0)
    draft_count = pg["total_count"] - completed_count

    pay_stats = db.query(Payment.payment_type, sa_func.sum(Payment.amount)).join(
        Order, Order.id == Payment.order_id
    ).filter(
        Order.type == "sale",
        Order.status.in_(["completed", "confirmed"]),
        Payment.type == "income",
        Payment.status == "confirmed",
    )
    if date_from and date_from.strip():
        pay_stats = pay_stats.filter(Order.date >= date_from.strip()[:10] + " 00:00:00")
    if date_to and date_to.strip():
        pay_stats = pay_stats.filter(Order.date <= date_to.strip()[:10] + " 23:59:59")
    if wh_id is not None and wh_id > 0:
        pay_stats = pay_stats.filter(Order.warehouse_id == wh_id)
    pay_stats = pay_stats.group_by(Payment.payment_type).all()
    pay_map = {(pt or "").strip().lower(): float(s or 0) for pt, s in pay_stats}
    naqd_sum = pay_map.get("cash", 0) + pay_map.get("naqd", 0)
    plastik_sum = pay_map.get("card", 0) + pay_map.get("plastik", 0)
    terminal_sum = pay_map.get("terminal", 0)
    click_sum = pay_map.get("click", 0)

    warehouses = get_warehouses_for_user(db, current_user)
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    info = request.query_params.get("info")
    info_detail = unquote(request.query_params.get("detail", "") or "") if info else ""
    sort_by_val = sort_col if sort_col in ("number", "date", "partner", "warehouse", "total", "status") else "date"
    filter_params = {
        "date_from": (date_from or "").strip()[:10] or "",
        "date_to": (date_to or "").strip()[:10] or "",
        "warehouse_id": str(wh_id) if wh_id else "",
        "status": status_filter or "",
        "sort_by": sort_by_val,
        "sort_dir": sort_order,
    }
    pq = pagination_query_string(filter_params)
    return templates.TemplateResponse("sales/list.html", {
        "request": request,
        "orders": orders,
        "total_sum": total_sum,
        "naqd_sum": naqd_sum,
        "plastik_sum": plastik_sum,
        "terminal_sum": terminal_sum,
        "click_sum": click_sum,
        "qarz_sum": qarz_sum,
        "warehouses": warehouses,
        "date_from": (date_from or "").strip()[:10] or None,
        "date_to": (date_to or "").strip()[:10] or None,
        "selected_warehouse_id": wh_id,
        "selected_status": status_filter,
        "sort_by": sort_by_val,
        "sort_dir": sort_order,
        "filter_params": "&".join(f"{k}={v}" for k, v in filter_params.items() if v),
        "page": pg["page"],
        "per_page": pg["per_page"],
        "total_count": pg["total_count"],
        "total_pages": pg["total_pages"],
        "items_count": pg["items_count"],
        "base_url": "/sales",
        "pagination_query": pq,
        "completed_count": completed_count,
        "draft_count": draft_count,
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
    if is_period_closed(db, order.date):
        return RedirectResponse(url=f"/sales/edit/{order_id}?error=period_closed", status_code=303)
    if order.status != "draft":
        return RedirectResponse(url=f"/sales/edit/{order_id}", status_code=303)

    # Atomik UPDATE WHERE — double-confirm xavfini oldini olish
    from sqlalchemy import text as _text
    claim = db.execute(
        _text("UPDATE orders SET status='confirmed' WHERE id=:id AND type='sale' AND status='draft'"),
        {"id": order_id}
    )
    if claim.rowcount == 0:
        return RedirectResponse(url=f"/sales/edit/{order_id}?already=1", status_code=303)

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
            import traceback
            traceback.print_exc()
            print(f"[Sales production xato] {e}", flush=True)
            return RedirectResponse(
                url=f"/sales/edit/{order_id}?error=production&detail=" + quote(f"Ishlab chiqarish yaratishda xato: {str(e)[:200]}"),
                status_code=303,
            )
    
    # Barcha mahsulotlar yetarli bo'lsa, oddiy sotuv sifatida tasdiqlash
    from app.services.stock_service import create_stock_movement
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        create_stock_movement(
            db=db,
            warehouse_id=wh_id,
            product_id=item.product_id,
            quantity_change=-item.quantity,
            operation_type="sale",
            document_type="Sale",
            document_id=order.id,
            document_number=order.number,
            user_id=current_user.id if current_user else None,
            note=f"Sotuv: {order.number}",
            created_at=order.date,
        )
    order.status = "completed"
    # Qarzdorlikni hisoblash
    order.debt = max(0.0, (order.total or 0) - (order.paid or 0))
    # Partner balansini yangilash
    if order.partner_id and order.debt > 0:
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        if partner:
            order.previous_partner_balance = partner.balance
            partner.balance = (partner.balance or 0) + order.debt
    db.commit()
    check_low_stock_and_notify(db)
    # Telegram bildirish (ELYA CLASSIC — real-time)
    try:
        from app.bot.services.notifier import notify_new_sale, notify_big_sale
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first() if order.partner_id else None
        p_name = partner.name if partner else "Naqd"
        notify_new_sale(order.number, p_name, order.total or 0, order.paid or 0)
        if (order.total or 0) >= 10_000_000:
            notify_big_sale(order.number, p_name, order.total)
    except Exception:
        pass
    try:
        from app.bot.services.audit_watchdog import audit_sale
        audit_sale(order.id)
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
    # Bug 1 — paid > 0 bo'lgan orderni revert qilish taqiqlanadi (refund kerak)
    if (order.paid or 0) > 0:
        return RedirectResponse(
            url=f"/sales/edit/{order_id}?error=paid_block&detail=" + quote(
                f"Bu sotuvga {order.paid:,.0f} so'm to'lov qabul qilingan. Avval refund (qaytarish) hujjati yarating, keyin tasdiqni bekor qilishingiz mumkin."
            ),
            status_code=303,
        )
    status = (getattr(order, "status", None) or "").strip().lower()
    if status in ("waiting_production", "confirmed"):
        # Ombor hisobdan chiqarilmagan — faqat draft ga qaytarish
        order.status = "draft"
        # Confirmed bo'lsa — tegishli yetkazishni ham bekor qilish
        # ('pending', 'in_progress', 'failed' — yetkazilmagan har qanday holat)
        if status == "confirmed":
            from app.models.database import Delivery as DeliveryModel
            for delivery in db.query(DeliveryModel).filter(
                DeliveryModel.order_id == order.id,
                DeliveryModel.status.in_(["pending", "in_progress", "failed"]),
            ).all():
                delivery.status = "cancelled"
        db.commit()
        referer = "/sales/edit/" + str(order_id)
        return RedirectResponse(url=referer, status_code=303)
    if status != "completed":
        return RedirectResponse(
            url=f"/sales/edit/{order_id}?error=revert&detail=" + quote("Faqat bajarilgan sotuvning tasdiqini bekor qilish mumkin."),
            status_code=303,
        )
    from app.services.stock_service import create_stock_movement
    for item in order.items:
        wh_id = item.warehouse_id if item.warehouse_id else order.warehouse_id
        if not wh_id or not item.product_id:
            continue
        create_stock_movement(
            db=db,
            warehouse_id=wh_id,
            product_id=item.product_id,
            quantity_change=float(item.quantity or 0),
            operation_type="sale_revert",
            document_type="Sale",
            document_id=order.id,
            document_number=order.number,
            user_id=current_user.id if current_user else None,
            note=f"Sotuv tasdiqini bekor qilish: {order.number}",
            created_at=order.date or datetime.now(),
        )
    if order.partner_id and (order.debt or 0) > 0:
        partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
        if partner:
            if order.previous_partner_balance is not None:
                partner.balance = order.previous_partner_balance
            else:
                partner.balance = (partner.balance or 0) - order.debt
    order.previous_partner_balance = None
    # Yetkazilmagan delivery larni cancel qilish (cancelled/failed/delivered emasini)
    from app.models.database import Delivery as DeliveryModel
    for delivery in db.query(DeliveryModel).filter(
        DeliveryModel.order_id == order.id,
        DeliveryModel.status.in_(["pending", "in_progress", "failed"]),
    ).all():
        delivery.status = "cancelled"
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


@router.get("/nakladnoy/excel/bulk")
async def sales_nakladnoy_excel_bulk(
    ids: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Bir nechta sotuv yuk xatini bitta Excel da jamlama. ids=1,2,3 formatda."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.worksheet.page import PageMargins
    from openpyxl.worksheet.pagebreak import Break
    from fastapi.responses import StreamingResponse

    try:
        order_ids = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    except Exception:
        order_ids = []
    if not order_ids:
        raise HTTPException(status_code=400, detail="Hech qanday buyurtma tanlanmagan")

    orders = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product).joinedload(Product.unit),
            joinedload(Order.partner),
            joinedload(Order.warehouse),
        )
        .filter(Order.id.in_(order_ids), Order.type.in_(("sale", "return_sale")))
        .order_by(Order.id)
        .all()
    )
    if not orders:
        raise HTTPException(status_code=404, detail="Buyurtmalar topilmadi")

    # Order turi → hujjat sarlavhasi (Sales Doctor uslubida)
    def _doc_label(o):
        if o.type == "return_sale":
            return "QAYTARISH"
        # exchange uchun kelajakda: o.type == "exchange_in" -> "OBMEN (otgruz)", "exchange_out" -> "OBMEN (vozvrat)"
        return "BUYURTMA"

    wb = Workbook()
    ws = wb.active
    ws.title = "Yuk xati (jamlama)"

    # A4 portrait (knijniy) + fit to width — jadval bir sahifa kengligiga sig'adi
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0  # balandligi avtomatik (ko'p sahifa)
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.4, right=0.4, top=0.5, bottom=0.5)
    ws.print_options.horizontalCentered = True

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
    section_fill = PatternFill(start_color="E8F5E9", end_color="E8F5E9", fill_type="solid")
    bold_white = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    right = Alignment(horizontal="right", vertical="center")

    row = 1
    today_str = datetime.now().strftime("%d.%m.%Y")
    # A4 portrait da bitta sahifaga taxminan 68-72 qator sig'adi (default 11pt font, kichik margin)
    # Har Yuk xati: 1 (sarlavha) + 3 (info) + 1 (bo'sh) + 1 (BUYURTMA) + 1 (jadval header) + N (items) + 1 (Jami) + 1 (bo'sh) + 1 (imzo) + 1 (bo'sh) = 11 + items
    ROWS_PER_PAGE = 68
    current_page_used = 0  # joriy sahifada ishlatilgan qatorlar

    for idx, order in enumerate(orders, 1):
        # Hujjat o'lchamini oldindan aniq hisoblash
        items_count = len(order.items)
        order_rows = 11 + items_count

        # Agar joriy sahifaga sig'masa va birinchi hujjat emas — page break qo'yish
        if idx > 1 and current_page_used + order_rows > ROWS_PER_PAGE:
            ws.row_breaks.append(Break(id=row - 1))
            current_page_used = 0

        # Yuk xati sarlavhasi
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        cell = ws.cell(row=row, column=1, value=f"Yuk xati № {order.number}    sana: {order.date.strftime('%d.%m.%Y') if order.date else today_str}")
        cell.font = Font(bold=True, size=13)
        cell.fill = section_fill
        cell.alignment = center
        cell.border = border
        row += 1

        # Kimga/Manzil/Telefon | Narx turi/Ombor/Sana
        partner_name = order.partner.name if order.partner else "Naqd mijoz"
        partner_addr = order.partner.address if (order.partner and order.partner.address) else ""
        partner_phone = order.partner.phone if (order.partner and order.partner.phone) else ""
        wh_name = order.warehouse.name if order.warehouse else "-"
        price_type_name = order.price_type.name if (hasattr(order, 'price_type') and order.price_type) else "Sotuv narxi"

        ws.cell(row=row, column=1, value="Kimga:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        ws.cell(row=row, column=2, value=partner_name)
        ws.cell(row=row, column=5, value="Narx turi:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
        ws.cell(row=row, column=6, value=price_type_name)
        row += 1
        ws.cell(row=row, column=1, value="Manzil:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        ws.cell(row=row, column=2, value=partner_addr)
        ws.cell(row=row, column=5, value="Ombor:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
        ws.cell(row=row, column=6, value=wh_name)
        row += 1
        ws.cell(row=row, column=1, value="Telefon:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        ws.cell(row=row, column=2, value=partner_phone)
        ws.cell(row=row, column=5, value="Sana:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
        ws.cell(row=row, column=6, value=order.date.strftime("%d.%m.%Y %H:%M") if order.date else "-")
        row += 2

        # Hujjat turi sarlavhasi (BUYURTMA / QAYTARISH / OBMEN)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        doc_label = _doc_label(order)
        zakaz_cell = ws.cell(row=row, column=1, value=f"{doc_label} ({order.number})")
        zakaz_cell.font = Font(bold=True, size=11, color="C62828" if order.type == "return_sale" else "000000")
        zakaz_cell.alignment = left
        row += 1

        # Jadval sarlavhasi (7 ustun: №, Kod, Nomi, O'lchov birligi, Soni, Narxi, Summa)
        for col, h in enumerate(["№", "Kodi", "Nomi", "O'lchov birligi", "Soni", "Narxi", "Summa"], 1):
            cell = ws.cell(row=row, column=col, value=h)
            cell.font = bold_white
            cell.fill = header_fill
            cell.alignment = center
            cell.border = border
        row += 1

        # Items
        order_total = 0.0
        order_qty_sum = 0.0
        for i, item in enumerate(order.items, 1):
            prod_name = item.product.name if item.product else f"#{item.product_id}"
            prod_code = item.product.code if (item.product and item.product.code) else ""
            unit = item.product.unit.name if (item.product and item.product.unit) else ""
            qty = float(item.quantity or 0)
            price = float(item.price or 0)
            summa = float(item.total or (qty * price))
            order_total += summa
            order_qty_sum += qty

            ws.cell(row=row, column=1, value=i).alignment = center
            ws.cell(row=row, column=2, value=prod_code).alignment = center
            ws.cell(row=row, column=3, value=prod_name).alignment = left
            ws.cell(row=row, column=4, value=unit).alignment = center
            ws.cell(row=row, column=5, value=qty).alignment = right
            ws.cell(row=row, column=6, value=price).alignment = right
            ws.cell(row=row, column=7, value=summa).alignment = right
            for col in range(1, 8):
                ws.cell(row=row, column=col).border = border
                if col in (6, 7):
                    ws.cell(row=row, column=col).number_format = '#,##0'
            row += 1

        # Jami
        ws.cell(row=row, column=1, value="Jami").font = Font(bold=True)
        ws.cell(row=row, column=1).alignment = left
        ws.cell(row=row, column=1).border = border
        for col in range(2, 8):
            ws.cell(row=row, column=col).border = border
        ws.cell(row=row, column=5, value=order_qty_sum).alignment = right
        ws.cell(row=row, column=5).font = Font(bold=True)
        ws.cell(row=row, column=7, value=order_total).alignment = right
        ws.cell(row=row, column=7).font = Font(bold=True, color="2E7D32")
        ws.cell(row=row, column=7).number_format = '#,##0" so\'m"'
        row += 2

        # Imzo joylari (har yuk xatidan keyin)
        ws.cell(row=row, column=1, value="Topshirdi:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=4)
        ws.cell(row=row, column=2, value="_______________________")
        ws.cell(row=row, column=5, value="Qabul qildi:").font = Font(bold=True)
        ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=7)
        ws.cell(row=row, column=6, value="_______________________")
        row += 2  # imzo qatori + 1 ta bo'sh qator (ajratish uchun)

        # Joriy sahifada ishlatilgan qator sonini yangilash
        current_page_used += order_rows

    # Ustun kengligi — 7 ustun
    widths = [12, 12, 38, 14, 10, 14, 18]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"yuk_xati_jamlama_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{order_id}/nakladnoy/excel")
async def sales_nakladnoy_excel(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Sotuv yuk xatini Excel formatda yuklab olish."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from fastapi.responses import StreamingResponse

    order = (
        db.query(Order)
        .options(
            joinedload(Order.items).joinedload(OrderItem.product).joinedload(Product.unit),
            joinedload(Order.partner),
            joinedload(Order.warehouse),
        )
        .filter(Order.id == order_id, Order.type == "sale")
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")

    wb = Workbook()
    ws = wb.active
    ws.title = "Yuk xati"

    thin = Side(border_style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill(start_color="2E7D32", end_color="2E7D32", fill_type="solid")
    bold_white = Font(bold=True, color="FFFFFF", size=11)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    left = Alignment(horizontal="left", vertical="center", wrap_text=True)
    right = Alignment(horizontal="right", vertical="center")

    # Sarlavha
    ws.merge_cells("A1:F1")
    ws["A1"] = "TOTLI HOLVA — Yuk xati"
    ws["A1"].font = Font(bold=True, size=16)
    ws["A1"].alignment = center

    ws.merge_cells("A2:F2")
    ws["A2"] = f"№ {order.number}    Sana: {order.date.strftime('%d.%m.%Y %H:%M') if order.date else '-'}"
    ws["A2"].font = Font(bold=True, size=11)
    ws["A2"].alignment = center

    # Mijoz va ombor
    ws["A4"] = "Mijoz:"
    ws["A4"].font = Font(bold=True)
    ws.merge_cells("B4:F4")
    ws["B4"] = order.partner.name if order.partner else "Naqd mijoz"

    ws["A5"] = "Telefon:"
    ws["A5"].font = Font(bold=True)
    ws.merge_cells("B5:F5")
    ws["B5"] = (order.partner.phone if order.partner and order.partner.phone else "-")

    ws["A6"] = "Manzil:"
    ws["A6"].font = Font(bold=True)
    ws.merge_cells("B6:F6")
    ws["B6"] = (order.partner.address if order.partner and order.partner.address else "-")

    ws["A7"] = "Ombor:"
    ws["A7"].font = Font(bold=True)
    ws.merge_cells("B7:F7")
    ws["B7"] = order.warehouse.name if order.warehouse else "-"

    # Jadval sarlavhasi
    headers = ["№", "Mahsulot", "Birlik", "Miqdor", "Narx (so'm)", "Summa (so'm)"]
    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=9, column=col, value=h)
        cell.font = bold_white
        cell.fill = header_fill
        cell.alignment = center
        cell.border = border

    # Items
    row = 10
    total = 0.0
    for i, item in enumerate(order.items, 1):
        prod_name = item.product.name if item.product else f"#{item.product_id}"
        unit = item.product.unit.name if (item.product and item.product.unit) else ""
        qty = float(item.quantity or 0)
        price = float(item.price or 0)
        summa = float(item.total or (qty * price))
        total += summa

        ws.cell(row=row, column=1, value=i).alignment = center
        ws.cell(row=row, column=2, value=prod_name).alignment = left
        ws.cell(row=row, column=3, value=unit).alignment = center
        ws.cell(row=row, column=4, value=qty).alignment = right
        ws.cell(row=row, column=5, value=price).alignment = right
        ws.cell(row=row, column=6, value=summa).alignment = right

        for col in range(1, 7):
            ws.cell(row=row, column=col).border = border
            if col in (5, 6):
                ws.cell(row=row, column=col).number_format = '#,##0'
        row += 1

    # JAMI
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    jami_label = ws.cell(row=row, column=1, value="JAMI:")
    jami_label.font = Font(bold=True, size=12)
    jami_label.alignment = right
    jami_label.border = border
    jami_val = ws.cell(row=row, column=6, value=total)
    jami_val.font = Font(bold=True, size=12, color="2E7D32")
    jami_val.alignment = right
    jami_val.number_format = '#,##0'
    jami_val.border = border

    # Imzo joylari
    sig_row = row + 3
    ws.cell(row=sig_row, column=1, value="Topshirdi (omborchi):").font = Font(bold=True)
    ws.merge_cells(start_row=sig_row, start_column=2, end_row=sig_row, end_column=3)
    ws.cell(row=sig_row, column=2, value="_______________________").alignment = left

    ws.cell(row=sig_row, column=4, value="Qabul qildi:").font = Font(bold=True)
    ws.merge_cells(start_row=sig_row, start_column=5, end_row=sig_row, end_column=6)
    ws.cell(row=sig_row, column=5, value="_______________________").alignment = left

    # Ustun kengligi
    widths = [5, 35, 10, 12, 16, 18]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[chr(64 + i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"yuk_xati_{order.number}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/delete/{order_id}")
async def sales_delete(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Sotuvni o'chirish (admin). Qoralama — bekor qilingan qiladi; bekor qilingan — bazadan o'chiradi.
    To'lov bog'langan bo'lsa orphan oldini olish uchun rad etiladi."""
    order = db.query(Order).filter(Order.id == order_id, Order.type == "sale").first()
    if not order:
        raise HTTPException(status_code=404, detail="Sotuv topilmadi")

    from app.services.document_service import delete_sale_fully, DocumentError
    try:
        delete_sale_fully(db, order)
    except DocumentError as e:
        return RedirectResponse(
            url=f"/sales?error=delete&detail=" + quote(e.detail),
            status_code=303,
        )
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
    user_role = (current_user.role or "").strip()
    assigned_partners = []
    if user_with_partners and getattr(user_with_partners, "partners_list", None):
        assigned_partners = [p for p in user_with_partners.partners_list if getattr(p, "is_active", True)]
    if user_role == "sotuvchi":
        # Sotuvchi uchun cheklov SHART — biriktirilgan mijozlar bilan cheklash
        # Bo'sh bo'lsa, default chakana xaridor qo'shiladi (POS ishlashi uchun)
        if assigned_partners:
            pos_partners = sorted(assigned_partners, key=lambda p: (p.name or ""))
        else:
            chakana = db.query(Partner).filter(
                Partner.is_active == True,
                or_(Partner.code == "chakana", Partner.code == "pos"),
            ).first()
            pos_partners = [chakana] if chakana else []
    else:
        # Admin/manager — agar biriktirilgan bo'lsa shu, aks holda barchasi
        if assigned_partners:
            pos_partners = sorted(assigned_partners, key=lambda p: (p.name or ""))
        else:
            pos_partners = db.query(Partner).filter(Partner.is_active == True).order_by(Partner.name).all()
    default_partner = _get_pos_partner(db)
    default_partner_id = default_partner.id if default_partner else None
    if pos_partners and default_partner_id is not None:
        if not any(p.id == default_partner_id for p in pos_partners):
            default_partner_id = pos_partners[0].id if pos_partners else None
    # Harajat turlari (POS expense modal uchun)
    pos_expense_types = db.query(ExpenseType).order_by(ExpenseType.name).all()
    # Kassalar (inkasatsiya "Yangi yuborish" modali uchun)
    pos_cash_registers = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.name).all()
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
        "pos_cash_registers": pos_cash_registers,
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
    q = db.query(Order).filter(
        Order.type == o_type,
        Order.status == "completed",
        func.date(Order.created_at) >= d_from,
        func.date(Order.created_at) <= d_to,
    )
    # Sotuvchi faqat o'z POS ombori sotuvlarini ko'radi (Do'kon 1 ↔ Do'kon 2 ajratish)
    if role == "sotuvchi":
        pos_wh = _get_pos_warehouse_for_user(db, current_user)
        if pos_wh:
            q = q.filter(Order.warehouse_id == pos_wh.id)
        else:
            return []
    orders = q.order_by(Order.created_at.desc()).limit(QUERY_LIMIT_DEFAULT).all()
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
            "payment_type": o.payment_type or "naqd",
        })
    return out


@router.get("/pos/x-report")
async def sales_pos_x_report(
    request: Request,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """X hisobot — sotuvchi smena yakuni: sotuv/qaytarish/bekor, to'lov turi, kassa balansi, inkasatsiya.

    date — YYYY-MM-DD, default=today, max=today.
    """
    from datetime import date as date_type, datetime as dt
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return JSONResponse({"error": "Ruxsat yo'q"}, status_code=403)

    target_date = date_type.today()
    if date:
        try:
            parsed = dt.strptime(date[:10], "%Y-%m-%d").date()
            if parsed > date_type.today():
                return JSONResponse({"error": "Kelajak sanasi bo'lishi mumkin emas"}, status_code=400)
            target_date = parsed
        except ValueError:
            return JSONResponse({"error": "Sana formati xato (YYYY-MM-DD)"}, status_code=400)

    base_q = db.query(Order).filter(func.date(Order.created_at) == target_date)
    pos_wh = None
    if role == "sotuvchi":
        pos_wh = _get_pos_warehouse_for_user(db, current_user)
        if not pos_wh:
            return JSONResponse({"error": "Sizga POS ombor biriktirilmagan"}, status_code=400)
        base_q = base_q.filter(Order.warehouse_id == pos_wh.id)

    completed_q = base_q.filter(Order.status == "completed")
    cancelled_q = base_q.filter(Order.status == "cancelled")
    orders = completed_q.all()
    cancelled_orders = cancelled_q.all()

    sales = [o for o in orders if (o.type or "sale") == "sale"]
    returns = [o for o in orders if o.type == "return_sale"]
    sales_total = sum(float(o.total or 0) for o in sales)
    returns_total = sum(float(o.total or 0) for o in returns)
    cancelled_total = sum(float(o.total or 0) for o in cancelled_orders)

    by_type: dict = {}
    sale_with_payments: set = set()
    sale_order_ids = [o.id for o in sales]
    if sale_order_ids:
        try:
            pmt_q = db.query(Payment).filter(
                Payment.type == "income",
                or_(Payment.status == "confirmed", Payment.status.is_(None)),
                Payment.order_id.in_(sale_order_ids),
            ).all()
            cash_pt_map = {c.id: ((c.payment_type or "naqd").strip().lower()) for c in db.query(CashRegister).all()}
            for p in pmt_q:
                sale_with_payments.add(p.order_id)
                pt = cash_pt_map.get(p.cash_register_id, "naqd")
                if pt == "perechisleniye":
                    pt = "bank"
                if pt not in by_type:
                    by_type[pt] = {"count": 0, "sum": 0.0}
                by_type[pt]["count"] += 1
                by_type[pt]["sum"] += float(p.amount or 0)
        except Exception:
            pass

    qarz_orders = [o for o in sales if o.id not in sale_with_payments]
    if qarz_orders:
        by_type["qarz"] = {
            "count": len(qarz_orders),
            "sum": sum(float(o.total or 0) for o in qarz_orders),
        }

    payment_breakdown = [{"type": k, "count": v["count"], "sum": v["sum"]} for k, v in sorted(by_type.items(), key=lambda x: -x[1]["sum"])]

    by_user: list = []
    if role in ("admin", "manager"):
        bu: dict = {}
        for o in sales:
            uid = o.user_id or 0
            if uid not in bu:
                bu[uid] = {"count": 0, "sum": 0.0, "returns": 0.0}
            bu[uid]["count"] += 1
            bu[uid]["sum"] += float(o.total or 0)
        for o in returns:
            uid = o.user_id or 0
            if uid not in bu:
                bu[uid] = {"count": 0, "sum": 0.0, "returns": 0.0}
            bu[uid]["returns"] += float(o.total or 0)
        if bu:
            user_names = {u.id: (u.full_name or u.username) for u in db.query(User).filter(User.id.in_([uid for uid in bu.keys() if uid])).all()}
            by_user = [
                {
                    "user_id": uid,
                    "user": user_names.get(uid, "-") if uid else "—",
                    "count": v["count"],
                    "sum": v["sum"],
                    "returns": v["returns"],
                    "net": v["sum"] - v["returns"],
                }
                for uid, v in sorted(bu.items(), key=lambda x: -x[1]["sum"])
            ]

    cash_balances: list = []
    inkasatsiya_today = {"count": 0, "sum": 0.0}
    expense_to_partner = {"count": 0, "sum": 0.0}
    expense_other = {"count": 0, "sum": 0.0}
    try:
        from app.services.finance_service import cash_balance_formula
        from sqlalchemy.orm import joinedload
        user_full = db.query(User).options(joinedload(User.cash_registers_list)).filter(User.id == current_user.id).first()
        user_cashes = list(getattr(user_full, "cash_registers_list", None) or []) if user_full else []
        if role == "sotuvchi" and pos_wh:
            wh_dept_id = getattr(pos_wh, "department_id", None)
            shop_cashes = [c for c in user_cashes if getattr(c, "department_id", None) == wh_dept_id] if wh_dept_id else []
            if not shop_cashes and wh_dept_id:
                shop_cashes = db.query(CashRegister).filter(
                    CashRegister.department_id == wh_dept_id,
                    CashRegister.is_active == True,
                ).all()
            for c in shop_cashes:
                bal, inc, exp = cash_balance_formula(db, c.id)
                cash_balances.append({"id": c.id, "name": c.name, "balance": float(bal or 0)})
            cash_ids = [c.id for c in shop_cashes]
            if cash_ids:
                transfers = db.query(CashTransfer).filter(
                    CashTransfer.from_cash_id.in_(cash_ids),
                    CashTransfer.status.in_(("in_transit", "completed")),
                    func.date(CashTransfer.date) == target_date,
                ).all()
                inkasatsiya_today = {
                    "count": len(transfers),
                    "sum": sum(float(t.amount or 0) for t in transfers),
                }

                expenses_q = db.query(Payment).filter(
                    Payment.cash_register_id.in_(cash_ids),
                    Payment.type == "expense",
                    or_(Payment.status == "confirmed", Payment.status.is_(None)),
                    func.date(Payment.created_at) == target_date,
                ).all()
                for e in expenses_q:
                    amt = float(e.amount or 0)
                    if e.partner_id:
                        expense_to_partner["count"] += 1
                        expense_to_partner["sum"] += amt
                    else:
                        expense_other["count"] += 1
                        expense_other["sum"] += amt
    except Exception:
        pass

    qoldiq = sales_total - returns_total - expense_to_partner["sum"] - expense_other["sum"]

    return JSONResponse({
        "date": target_date.strftime("%d.%m.%Y"),
        "date_iso": target_date.strftime("%Y-%m-%d"),
        "user": current_user.full_name or current_user.username,
        "warehouse": pos_wh.name if pos_wh else "Barcha",
        "sales_count": len(sales),
        "sales_total": sales_total,
        "returns_count": len(returns),
        "returns_total": returns_total,
        "cancelled_count": len(cancelled_orders),
        "cancelled_total": cancelled_total,
        "net_total": sales_total - returns_total,
        "payment_breakdown": payment_breakdown,
        "by_user": by_user,
        "cash_balances": cash_balances,
        "inkasatsiya_today": inkasatsiya_today,
        "expense_to_partner": expense_to_partner,
        "expense_other": expense_other,
        "qoldiq": qoldiq,
    })


@router.post("/pos/z-report")
async def sales_pos_z_report(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Z-hisobot — smenani yopish: X-hisobot snapshot data/z_reports/ ga saqlanadi va audit log ga yoziladi."""
    import os
    import json as _json
    from datetime import date as date_type, datetime as dt
    role = (current_user.role or "").strip()
    if role not in ("sotuvchi", "admin", "manager"):
        return JSONResponse({"ok": False, "error": "Ruxsat yo'q"}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    date_str = (body.get("date") or "").strip()
    target_date = date_type.today()
    if date_str:
        try:
            parsed = dt.strptime(date_str[:10], "%Y-%m-%d").date()
            if parsed > date_type.today():
                return JSONResponse({"ok": False, "error": "Kelajak sanasi bo'lishi mumkin emas"}, status_code=400)
            target_date = parsed
        except ValueError:
            return JSONResponse({"ok": False, "error": "Sana formati xato"}, status_code=400)

    pos_wh = None
    base_q = db.query(Order).filter(func.date(Order.created_at) == target_date)
    if role == "sotuvchi":
        pos_wh = _get_pos_warehouse_for_user(db, current_user)
        if not pos_wh:
            return JSONResponse({"ok": False, "error": "Sizga POS ombor biriktirilmagan"}, status_code=400)
        base_q = base_q.filter(Order.warehouse_id == pos_wh.id)

    completed = base_q.filter(Order.status == "completed").all()
    cancelled = base_q.filter(Order.status == "cancelled").all()
    sales = [o for o in completed if (o.type or "sale") == "sale"]
    returns_o = [o for o in completed if o.type == "return_sale"]
    sales_total = sum(float(o.total or 0) for o in sales)
    returns_total = sum(float(o.total or 0) for o in returns_o)

    by_type: dict = {}
    for o in sales:
        pt = (o.payment_type or "naqd").lower()
        if pt not in by_type:
            by_type[pt] = {"count": 0, "sum": 0.0}
        by_type[pt]["count"] += 1
        by_type[pt]["sum"] += float(o.total or 0)

    cash_snapshot: list = []
    try:
        from app.services.finance_service import cash_balance_formula
        from sqlalchemy.orm import joinedload as _jl
        user_full = db.query(User).options(_jl(User.cash_registers_list)).filter(User.id == current_user.id).first()
        user_cashes_z = list(getattr(user_full, "cash_registers_list", None) or []) if user_full else []
        wh_dept_id = getattr(pos_wh, "department_id", None) if pos_wh else None
        if role == "sotuvchi" and wh_dept_id:
            shop_cashes = [c for c in user_cashes_z if getattr(c, "department_id", None) == wh_dept_id]
            if not shop_cashes:
                shop_cashes = db.query(CashRegister).filter(
                    CashRegister.department_id == wh_dept_id,
                    CashRegister.is_active == True,
                ).all()
        else:
            shop_cashes = user_cashes_z
        for c in shop_cashes:
            bal, inc, exp = cash_balance_formula(db, c.id)
            cash_snapshot.append({"id": c.id, "name": c.name, "balance": float(bal or 0), "income": float(inc or 0), "expense": float(exp or 0)})
    except Exception:
        pass

    snapshot = {
        "z_id": f"Z-{target_date.strftime('%Y%m%d')}-U{current_user.id}-{dt.now().strftime('%H%M%S')}",
        "date": target_date.strftime("%Y-%m-%d"),
        "closed_at": dt.now().isoformat(),
        "user_id": current_user.id,
        "user": current_user.full_name or current_user.username,
        "role": role,
        "warehouse_id": pos_wh.id if pos_wh else None,
        "warehouse": pos_wh.name if pos_wh else "Barcha",
        "sales_count": len(sales),
        "sales_total": sales_total,
        "returns_count": len(returns_o),
        "returns_total": returns_total,
        "cancelled_count": len(cancelled),
        "cancelled_total": sum(float(o.total or 0) for o in cancelled),
        "net_total": sales_total - returns_total,
        "payment_breakdown": [{"type": k, "count": v["count"], "sum": v["sum"]} for k, v in by_type.items()],
        "cash_snapshot": cash_snapshot,
        "order_numbers": [o.number for o in completed],
    }

    out_path = None
    try:
        out_dir = os.path.join("data", "z_reports", target_date.strftime("%Y-%m-%d"))
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"{snapshot['z_id']}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            _json.dump(snapshot, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"Snapshot saqlashda xato: {e}"}, status_code=500)

    try:
        log_action(
            db, user=current_user, action="z_report",
            entity_type="pos_shift", entity_id=0, entity_number=snapshot["z_id"],
            details=f"Z-hisobot: {target_date}, Sotuv {sales_total:,.0f}, Qaytarish {returns_total:,.0f}, NET {sales_total - returns_total:,.0f}",
            ip_address=request.client.host if request.client else "",
        )
    except Exception:
        pass

    return JSONResponse({"ok": True, "snapshot_id": snapshot["z_id"], "path": out_path})


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
            note=f"Sotuv (POS {payment_type}): {order.number}",
            created_at=order.date,
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
                cash_register = _get_pos_cash_register(db, pt, department_id, current_user=current_user)
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
                    db.flush()
                    _sync_cash_balance(db, cash_register.id)
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
    try:
        from app.bot.services.audit_watchdog import audit_sale
        audit_sale(order.id)
    except Exception:
        pass
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
    """Savdodan qaytarish — bajarilgan sotuvlar ro'yxati (faqat joriy foydalanuvchi)."""
    q = db.query(Order).filter(
        Order.type == "sale",
        Order.status == "completed"
    )
    # Admin/manager barcha sotuvlarni ko'radi, sotuvchi faqat o'zinikini
    if current_user.role not in ("admin", "manager"):
        q = q.filter(Order.user_id == current_user.id)
    orders = q.options(
        joinedload(Order.partner),
        joinedload(Order.warehouse),
    ).order_by(Order.date.desc()).limit(QUERY_LIMIT_DEFAULT).all()
    success = request.query_params.get("success")
    number = request.query_params.get("number", "")
    warehouse_name = unquote(request.query_params.get("warehouse", "") or "")
    error = request.query_params.get("error")
    error_detail = unquote(request.query_params.get("detail", "") or "")
    rq = db.query(Order).filter(Order.type == "return_sale")
    if current_user.role not in ("admin", "manager"):
        rq = rq.filter(Order.user_id == current_user.id)
    return_docs = rq.options(
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
            created_at=return_order.date,
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
            created_at=doc.date,
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
    # Atomik UPDATE WHERE — double-confirm xavfini oldini olish
    from sqlalchemy import text as _text
    claim = db.execute(
        _text("UPDATE orders SET status='completed' WHERE id=:id AND type='return_sale' AND status='cancelled'"),
        {"id": return_order_id}
    )
    if claim.rowcount == 0:
        return RedirectResponse(url="/sales/returns?error=confirm&detail=" + quote("Hujjat allaqachon tasdiqlangan."), status_code=303)
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
            created_at=doc.date,
        )
    # Status allaqachon atomik UPDATE WHERE bilan o'zgartirildi
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
    cash_register = _get_pos_cash_register(db, "naqd", department_id, current_user=current_user)
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
        db.flush()
        _sync_cash_balance(db, cash_register.id)
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
    cash_register = _get_pos_cash_register(db, "naqd", department_id, current_user=current_user)
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
        db.flush()
        _sync_cash_balance(db, cash_register.id)
    db.commit()
    return RedirectResponse(url="/sales/pos?success=1&number=" + quote(f"Harajat: {expense_type_name} — {amount:,.0f} so'm"), status_code=303)
