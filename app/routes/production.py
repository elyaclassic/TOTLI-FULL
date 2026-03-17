"""
Ishlab chiqarish — retseptlar, buyurtmalar, xom ashyo, bosqichlar, tasdiq/revert.
"""
import json
from datetime import datetime
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text, func

from app.core import templates
from app.logging_config import get_logger

logger = get_logger("production")
from app.models.database import (
    get_db,
    User,
    Warehouse,
    Product,
    Recipe,
    RecipeItem,
    RecipeStage,
    Production,
    ProductionItem,
    ProductionStage,
    Stock,
    StockMovement,
    Machine,
    Employee,
    PRODUCTION_STAGE_NAMES,
)
from app.deps import require_auth, require_admin, get_current_user
from app.utils.notifications import check_low_stock_and_notify
from app.utils.production_order import recipe_kg_per_unit, production_output_quantity_for_stock, notify_managers_production_ready, is_qiyom_recipe, notify_next_stage_operators
from app.utils.user_scope import get_warehouses_for_user

router = APIRouter(prefix="/production", tags=["production"])


def _recipe_max_stage(recipe) -> int:
    if not recipe or not recipe.stages:
        return 2
    return max(s.stage_number for s in recipe.stages)


def _calculate_recipe_cost_per_kg(db, recipe_id):
    """Retsept bo'yicha 1 kg uchun tannarxni hisoblash (rekursiv - yarim tayyor mahsulotlar uchun ham)."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe or not recipe.items:
        return 0.0
    
    total_cost = 0.0
    for item in recipe.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if not product:
            continue
        
        # Agar yarim tayyor mahsulot bo'lsa, uning retsept tannarxini olamiz
        if getattr(product, 'type', None) == 'yarim_tayyor':
            # Yarim tayyor mahsulotning retseptini topamiz
            semi_recipe = db.query(Recipe).filter(Recipe.product_id == product.id, Recipe.is_active == True).first()
            if semi_recipe:
                semi_cost_per_kg = _calculate_recipe_cost_per_kg(db, semi_recipe.id)
                total_cost += (item.quantity or 0) * semi_cost_per_kg
            else:
                # Retsept topilmasa, purchase_price yoki Stock.cost_price ishlatamiz
                cost = product.purchase_price or 0
                stock = db.query(Stock).filter(Stock.product_id == product.id).first()
                if stock and getattr(stock, 'cost_price', None) and stock.cost_price > 0:
                    cost = stock.cost_price
                total_cost += (item.quantity or 0) * cost
        else:
            # Oddiy xom ashyo uchun purchase_price yoki Stock.cost_price
            cost = product.purchase_price or 0
            stock = db.query(Stock).filter(Stock.product_id == product.id).first()
            if stock and getattr(stock, 'cost_price', None) and stock.cost_price > 0:
                cost = stock.cost_price
            total_cost += (item.quantity or 0) * cost
    
    # 1 kg uchun tannarx (birlik og'irligi: 400gr -> 0.4, 1kg -> 1)
    output_qty = recipe_kg_per_unit(recipe)
    return total_cost / output_qty if output_qty > 0 else 0.0


def calculate_production_tannarx(db, production, recipe):
    """Jami xarajat (faqat xom ashyo) va tannarx = jami ÷ ishlab chiqarish miqdori. Narx: Product.purchase_price yoki shu ombordagi Stock.cost_price."""
    if production.production_items:
        items_to_use = [(pi.product_id, float(pi.quantity or 0)) for pi in production.production_items]
    else:
        items_to_use = [(item.product_id, float(item.quantity or 0) * float(production.quantity or 0)) for item in recipe.items]
    total_material_cost = 0.0
    for product_id, qty in items_to_use:
        if qty <= 0:
            continue
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            continue
        wh_id = _warehouse_id_for_ingredient(db, product_id, production)
        if getattr(product, "type", None) == "yarim_tayyor":
            semi_recipe = db.query(Recipe).filter(Recipe.product_id == product.id, Recipe.is_active == True).first()
            if semi_recipe:
                cost_per_kg = _calculate_recipe_cost_per_kg(db, semi_recipe.id)
                total_material_cost += qty * cost_per_kg
            else:
                cost = product.purchase_price or 0
                st = db.query(Stock).filter(Stock.warehouse_id == wh_id, Stock.product_id == product_id).first()
                if st and getattr(st, "cost_price", None) and st.cost_price > 0:
                    cost = st.cost_price
                total_material_cost += qty * cost
        else:
            cost = product.purchase_price or 0
            st = db.query(Stock).filter(Stock.warehouse_id == wh_id, Stock.product_id == product_id).first()
            if st and getattr(st, "cost_price", None) and st.cost_price > 0:
                cost = st.cost_price
            total_material_cost += qty * cost
    output_units = production_output_quantity_for_stock(db, production, recipe)
    cost_per_unit = (total_material_cost / output_units) if output_units > 0 else 0.0
    return total_material_cost, output_units, cost_per_unit


def _warehouse_id_for_ingredient(db, product_id, production):
    """Yarim tayyor mahsulot bo'lsa — nomida 'yarim'/'semi' bor ombordan, aks holda 1-ombor (xom ashyo)."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product or getattr(product, "type", None) != "yarim_tayyor":
        return production.warehouse_id
    stocks = db.query(Stock).filter(Stock.product_id == product_id, Stock.quantity > 0).all()
    for st in stocks:
        wh = db.query(Warehouse).filter(Warehouse.id == st.warehouse_id).first()
        if wh and st.warehouse_id:
            name = (wh.name or "").lower()
            code = (getattr(wh, "code", None) or "").lower()
            if "yarim" in name or "semi" in name or "yarim" in code or "semi" in code:
                return st.warehouse_id
    if stocks:
        return stocks[0].warehouse_id
    return production.warehouse_id


def _do_complete_production_stock(db, production, recipe):
    """Kerak=0 bo'lsa o'tkazib yuboriladi; yetmasa borini tortadi (min(kerak, mavjud)).
    Xom ashyo 1-ombordan, yarim tayyor mahsulotlar nomida 'yarim'/'semi' bor ombordan chiqariladi."""
    if production.production_items:
        items_to_use = [(pi.product_id, pi.quantity) for pi in production.production_items]
    else:
        items_to_use = [(item.product_id, item.quantity * production.quantity) for item in recipe.items]
    items_actual = []
    for product_id, required in items_to_use:
        if required is None or required <= 0:
            items_actual.append((product_id, 0.0))
            continue
        wh_id = _warehouse_id_for_ingredient(db, product_id, production)
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == product_id,
        ).first()
        available = (stock.quantity if stock else 0) or 0
        actual_use = min(required, available)
        items_actual.append((product_id, actual_use))
    for product_id, actual_use in items_actual:
        if actual_use <= 0:
            continue
        wh_id = _warehouse_id_for_ingredient(db, product_id, production)
        stock = db.query(Stock).filter(
            Stock.warehouse_id == wh_id,
            Stock.product_id == product_id,
        ).first()
        if stock:
            stock.quantity -= actual_use
    total_material_cost = 0.0
    for product_id, actual_use in items_actual:
        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            continue
        
        # Yarim tayyor mahsulot uchun retsept tannarxini olamiz
        if getattr(product, 'type', None) == 'yarim_tayyor':
            semi_recipe = db.query(Recipe).filter(Recipe.product_id == product.id, Recipe.is_active == True).first()
            if semi_recipe:
                cost_per_kg = _calculate_recipe_cost_per_kg(db, semi_recipe.id)
                total_material_cost += actual_use * cost_per_kg
            else:
                # Retsept topilmasa, purchase_price yoki Stock.cost_price
                cost = product.purchase_price or 0
                stock = db.query(Stock).filter(Stock.product_id == product_id).first()
                if stock and getattr(stock, 'cost_price', None) and stock.cost_price > 0:
                    cost = stock.cost_price
                total_material_cost += actual_use * cost
        else:
            # Oddiy xom ashyo uchun purchase_price yoki Stock.cost_price
            cost = product.purchase_price or 0
            stock = db.query(Stock).filter(Stock.product_id == product_id).first()
            if stock and getattr(stock, 'cost_price', None) and stock.cost_price > 0:
                cost = stock.cost_price
            total_material_cost += actual_use * cost
    output_units = production_output_quantity_for_stock(db, production, recipe)
    cost_per_unit = (total_material_cost / output_units) if output_units > 0 else 0
    out_wh_id = production.output_warehouse_id if production.output_warehouse_id else production.warehouse_id
    product_stock = db.query(Stock).filter(
        Stock.warehouse_id == out_wh_id,
        Stock.product_id == recipe.product_id,
    ).first()
    if product_stock:
        product_stock.quantity += output_units
        qty_old = (product_stock.quantity or 0) - output_units
        cost_old = getattr(product_stock, "cost_price", None) or 0
        if qty_old <= 0 or cost_old <= 0:
            product_stock.cost_price = cost_per_unit
        else:
            product_stock.cost_price = (qty_old * cost_old + output_units * cost_per_unit) / (product_stock.quantity or 1)
    else:
        new_stock = Stock(warehouse_id=out_wh_id, product_id=recipe.product_id, quantity=output_units)
        if hasattr(Stock, "cost_price"):
            new_stock.cost_price = cost_per_unit
        db.add(new_stock)
    output_product = db.query(Product).filter(Product.id == recipe.product_id).first()
    if output_product:
        product_stock = db.query(Stock).filter(
            Stock.warehouse_id == out_wh_id,
            Stock.product_id == recipe.product_id,
        ).first()
        old_price = output_product.purchase_price or 0
        old_qty = (product_stock.quantity - output_units) if product_stock else 0
        if old_qty > 0 and old_price > 0 and output_units > 0:
            output_product.purchase_price = (old_qty * old_price + output_units * cost_per_unit) / (old_qty + output_units)
        elif cost_per_unit > 0:
            output_product.purchase_price = cost_per_unit
    return None


def _is_operator_role(user) -> bool:
    role = (getattr(user, "role", None) or "").strip().lower()
    return role in ("production", "qadoqlash", "rahbar", "raxbar", "operator")


@router.get("", response_class=HTMLResponse)
async def production_index_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    # Default qiymatlar
    warehouses = []
    recipes = []
    total_recipes = 0
    today_quantity = 0
    pending_productions = 0
    recent_productions = []
    current_user_employee = db.query(Employee).filter(Employee.user_id == current_user.id).first() if current_user else None
    filter_by_operator = _is_operator_role(current_user) and current_user_employee

    try:
        # Omborlar — foydalanuvchiga belgilangan
        try:
            warehouses = get_warehouses_for_user(db, current_user)
        except Exception as e:
            logger.warning("Warehouses query error: %s", e)
            warehouses = []
        
        # Recipes
        try:
            recipes_raw = db.query(Recipe).filter(Recipe.is_active == True).all()
            from app.models.database import Unit
            recipes = []
            for recipe in recipes_raw:
                try:
                    if recipe.product_id:
                        product = db.query(Product).filter(Product.id == recipe.product_id).first()
                        if product and product.unit_id:
                            unit = db.query(Unit).filter(Unit.id == product.unit_id).first()
                            if unit:
                                product.unit = unit
                        recipe.product = product
                    recipes.append(recipe)
                except Exception as recipe_error:
                    logger.warning("Recipe %s yuklashda xatolik: %s", recipe.id, recipe_error)
                    recipes.append(recipe)
        except Exception as e:
            logger.warning("Recipes query error: %s", e)
            recipes = []
        
        # Total recipes
        try:
            total_recipes = db.query(Recipe).filter(Recipe.is_active == True).count()
        except Exception as e:
            logger.warning("Total recipes count error: %s", e)
            total_recipes = len(recipes)
        
        today = datetime.now().date()
        
        # Bugungi ishlab chiqarishlar — operator bo'lsa faqat o'zining; miqdor kg da (recipe_kg_per_unit)
        try:
            from sqlalchemy import text
            today_sql = """
                SELECT p.id, p.number, p.date, p.recipe_id, p.warehouse_id, p.output_warehouse_id,
                       p.quantity, p.status, p.current_stage, p.max_stage, p.user_id, p.operator_id, p.note, p.created_at
                FROM productions p
                LEFT JOIN warehouses w ON p.output_warehouse_id = w.id
                WHERE DATE(p.date) = :today_date
                  AND p.status = :status
                  AND p.output_warehouse_id IS NOT NULL
                  AND w.id IS NOT NULL
                  AND (
                      (w.name IS NOT NULL AND (LOWER(w.name) LIKE '%yarim%' OR LOWER(w.name) LIKE '%semi%' OR LOWER(w.name) LIKE '%tayyor%' OR LOWER(w.name) LIKE '%finished%'))
                      OR (w.code IS NOT NULL AND (LOWER(w.code) LIKE '%yarim%' OR LOWER(w.code) LIKE '%semi%' OR LOWER(w.code) LIKE '%tayyor%' OR LOWER(w.code) LIKE '%finished%'))
                  )
            """
            params = {"today_date": today, "status": "completed"}
            if filter_by_operator:
                today_sql += " AND p.operator_id = :operator_id"
                params["operator_id"] = current_user_employee.id
            today_productions_result = db.execute(text(today_sql), params).fetchall()
            today_quantity = 0.0
            if today_productions_result:
                for row in today_productions_result:
                    rec = db.query(Recipe).filter(Recipe.id == row.recipe_id).first() if row.recipe_id else None
                    kg_per = recipe_kg_per_unit(rec) if rec else 1.0
                    today_quantity += float(row.quantity or 0) * (kg_per if kg_per and kg_per > 0 else 1.0)
        except Exception as e:
            today_quantity = 0
            logger.warning("Today productions query error: %s", e)
        
        # Kutilmoqdagi buyurtmalar — operator bo'lsa faqat o'zining
        try:
            from sqlalchemy import text
            pending_sql = "SELECT COUNT(*) as count FROM productions WHERE status = :status"
            pending_params = {"status": "draft"}
            if filter_by_operator:
                pending_sql += " AND operator_id = :operator_id"
                pending_params["operator_id"] = current_user_employee.id
            pending_count = db.execute(text(pending_sql), pending_params).scalar()
            pending_productions = pending_count or 0
        except Exception as e:
            pending_productions = 0
            logger.warning("Pending productions query error: %s", e)
        
        # Oxirgi ishlab chiqarishlar — operator bo'lsa faqat o'zi ishlab chiqarganlari
        try:
            from sqlalchemy import text
            recent_sql = """
                SELECT p.id, p.number, p.date, p.recipe_id, p.warehouse_id, p.output_warehouse_id,
                       p.quantity, p.status, p.current_stage, p.max_stage, p.user_id, p.operator_id, p.note, p.created_at
                FROM productions p
                LEFT JOIN warehouses w ON p.output_warehouse_id = w.id
                WHERE p.output_warehouse_id IS NOT NULL
                  AND w.id IS NOT NULL
                  AND (
                      (w.name IS NOT NULL AND (LOWER(w.name) LIKE '%yarim%' OR LOWER(w.name) LIKE '%semi%' OR LOWER(w.name) LIKE '%tayyor%' OR LOWER(w.name) LIKE '%finished%'))
                      OR (w.code IS NOT NULL AND (LOWER(w.code) LIKE '%yarim%' OR LOWER(w.code) LIKE '%semi%' OR LOWER(w.code) LIKE '%tayyor%' OR LOWER(w.code) LIKE '%finished%'))
                  )
            """
            recent_params = {"limit": 10}
            if filter_by_operator:
                recent_sql += " AND p.operator_id = :operator_id"
                recent_params["operator_id"] = current_user_employee.id
            recent_sql += " ORDER BY p.date DESC LIMIT :limit"
            recent_productions_result = db.execute(text(recent_sql), recent_params).fetchall()
            
            # Production obyektlarini yaratish (faqat mavjud ustunlar bilan)
            # DB driver ba'zida date/datetime ni str qaytaradi — shablon strftime uchun datetime kerak
            def _ensure_datetime(v):
                if v is None:
                    return None
                if isinstance(v, datetime):
                    return v
                if isinstance(v, str):
                    s = (v or "").strip()
                    for fmt, size in [("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%dT%H:%M:%S", 19), ("%Y-%m-%d", 10)]:
                        try:
                            return datetime.strptime(s[:size], fmt)
                        except (ValueError, TypeError):
                            continue
                return None
            recent_productions_raw = []
            for row in recent_productions_result:
                prod = Production()
                prod.id = row.id
                prod.number = row.number
                prod.date = _ensure_datetime(row.date)
                prod.recipe_id = row.recipe_id
                prod.warehouse_id = row.warehouse_id
                prod.output_warehouse_id = row.output_warehouse_id
                prod.quantity = row.quantity
                prod.status = row.status
                prod.current_stage = row.current_stage
                prod.max_stage = row.max_stage
                prod.user_id = row.user_id
                prod.note = row.note
                prod.created_at = row.created_at
                recent_productions_raw.append(prod)
            
            from app.models.database import Unit

            # N+1 muammosini hal qilish: barcha bog'liq ma'lumotlarni bitta so'rovda yuklash
            recipe_ids = [p.recipe_id for p in recent_productions_raw if p.recipe_id]
            recipes_map = {}
            product_ids = []
            if recipe_ids:
                recipes = db.query(Recipe).filter(Recipe.id.in_(recipe_ids)).all()
                recipes_map = {r.id: r for r in recipes}
                product_ids = [r.product_id for r in recipes if r.product_id]

            products_map = {}
            unit_ids = []
            if product_ids:
                products = db.query(Product).filter(Product.id.in_(product_ids)).all()
                products_map = {p.id: p for p in products}
                unit_ids = [p.unit_id for p in products if p.unit_id]

            units_map = {}
            if unit_ids:
                units = db.query(Unit).filter(Unit.id.in_(unit_ids)).all()
                units_map = {u.id: u for u in units}

            recent_productions = []
            for prod in recent_productions_raw:
                try:
                    recipe = recipes_map.get(prod.recipe_id) if prod.recipe_id else None
                    if recipe:
                        product = products_map.get(recipe.product_id) if recipe.product_id else None
                        if product:
                            product.unit = units_map.get(product.unit_id) if product.unit_id else None
                            recipe.product = product
                        prod.recipe = recipe
                    recent_productions.append(prod)
                except Exception as prod_error:
                    logger.warning("Production %s yuklashda xatolik: %s", getattr(prod, 'id', 'unknown'), prod_error)
                    continue
        except Exception as e:
            recent_productions = []
            logger.exception("Recent productions query error: %s", e)

    except Exception as e:
        error_msg = str(e)
        logger.exception("Production index page error: %s", error_msg)
    
    # Operator / ishlab chiqarish / qadoqlash kabi foydalanuvchilarga Retseptlar bloki ko'rinmasin (faqat o'zining oxirgi ishlab chiqarishlari ko'rinadi)
    show_recipes_section = not filter_by_operator
    try:
        resp = templates.TemplateResponse("production/index.html", {
            "request": request,
            "current_user": current_user,
            "total_recipes": total_recipes,
            "today_quantity": today_quantity,
            "pending_productions": pending_productions,
            "recent_productions": recent_productions,
            "recipes": recipes,
            "warehouses": warehouses,
            "show_recipes_section": show_recipes_section,
            "page_title": "Ishlab chiqarish",
            "now": datetime.now(),
        })
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp
    except Exception as template_error:
        import traceback
        error_msg = str(template_error)
        pass  # logged above
        # Xavfsiz fallback
        resp = templates.TemplateResponse("production/index.html", {
            "request": request,
            "current_user": current_user,
            "total_recipes": 0,
            "today_quantity": 0,
            "pending_productions": 0,
            "recent_productions": [],
            "recipes": [],
            "warehouses": [],
            "show_recipes_section": True,
            "page_title": "Ishlab chiqarish",
            "now": datetime.now(),
            "error": f"Xatolik: {error_msg[:200]}",
        })
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        return resp


@router.get("/recipes", response_class=HTMLResponse)
async def production_recipes(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    warehouses = get_warehouses_for_user(db, current_user)
    recipes = (
        db.query(Recipe)
        .options(
            joinedload(Recipe.product).joinedload(Product.unit),
            joinedload(Recipe.items).joinedload(RecipeItem.product).joinedload(Product.unit),
        )
        .all()
    )
    products = db.query(Product).filter(Product.type.in_(["tayyor", "yarim_tayyor"])).all()
    materials = db.query(Product).filter(Product.type == "hom_ashyo").all()
    recipe_products_json = json.dumps([
        {"id": p.id, "name": (p.name or ""), "unit": (p.unit.name or p.unit.code if p.unit else "kg")}
        for p in products
    ]).replace("<", "\\u003c")
    return templates.TemplateResponse("production/recipes.html", {
        "request": request,
        "current_user": current_user,
        "recipes": recipes,
        "products": products,
        "recipe_products_json": recipe_products_json,
        "materials": materials,
        "warehouses": warehouses,
        "page_title": "Retseptlar",
    })


@router.get("/recipes/{recipe_id}", response_class=HTMLResponse)
async def production_recipe_detail(
    request: Request,
    recipe_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    recipe = (
        db.query(Recipe)
        .options(
            joinedload(Recipe.product).joinedload(Product.unit),
            joinedload(Recipe.items).joinedload(RecipeItem.product).joinedload(Product.unit),
        )
        .filter(Recipe.id == recipe_id)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    materials = db.query(Product).filter(Product.type.in_(["hom_ashyo", "yarim_tayyor", "tayyor"])).all()
    recipe_stages = sorted(recipe.stages, key=lambda s: s.stage_number) if recipe.stages else []
    warehouses = get_warehouses_for_user(db, current_user)
    # Yarim tayyor mahsulotlar uchun retsept tannarxini hisoblash (ko'rsatish uchun)
    item_recipe_costs = {}
    for item in recipe.items or []:
        if not item.product_id:
            continue
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product and getattr(product, "type", None) == "yarim_tayyor":
            semi_recipe = db.query(Recipe).filter(Recipe.product_id == product.id, Recipe.is_active == True).first()
            if semi_recipe:
                item_recipe_costs[item.product_id] = _calculate_recipe_cost_per_kg(db, semi_recipe.id)
    return templates.TemplateResponse("production/recipe_detail.html", {
        "request": request,
        "current_user": current_user,
        "recipe": recipe,
        "materials": materials,
        "recipe_stages": recipe_stages,
        "warehouses": warehouses,
        "item_recipe_costs": item_recipe_costs,
        "page_title": f"Retsept: {recipe.name}",
    })


@router.post("/recipes/add")
async def add_recipe(
    request: Request,
    name: str = Form(...),
    product_id: int = Form(...),
    output_quantity: float = Form(1),
    description: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if output_quantity <= 0:
        raise HTTPException(status_code=400, detail="Chiqish miqdori 0 dan katta bo'lishi kerak")
    recipe = Recipe(
        name=name,
        product_id=product_id,
        output_quantity=output_quantity,
        description=description,
        is_active=True,
    )
    db.add(recipe)
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe.id}", status_code=303)


@router.post("/recipes/{recipe_id}/add-item")
async def add_recipe_item(
    recipe_id: int,
    product_id: int = Form(...),
    quantity: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Miqdor musbat bo'lishi kerak")
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    db.add(RecipeItem(recipe_id=recipe_id, product_id=product_id, quantity=quantity))
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.post("/recipes/{recipe_id}/set-name")
async def set_recipe_name(
    recipe_id: int,
    name: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Retsept nomini o'zgartirish."""
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    recipe.name = (name or "").strip() or recipe.name
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.post("/recipes/{recipe_id}/set-warehouses")
async def set_recipe_warehouses(
    recipe_id: int,
    default_warehouse_id: Optional[int] = Form(None),
    default_output_warehouse_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    recipe.default_warehouse_id = default_warehouse_id
    recipe.default_output_warehouse_id = default_output_warehouse_id
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.post("/recipes/{recipe_id}/edit-item/{item_id}")
async def edit_recipe_item(
    recipe_id: int,
    item_id: int,
    product_id: int = Form(...),
    quantity: float = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if quantity <= 0:
        raise HTTPException(status_code=400, detail="Miqdor musbat bo'lishi kerak")
    item = db.query(RecipeItem).filter(
        RecipeItem.id == item_id,
        RecipeItem.recipe_id == recipe_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Tarkib qatori topilmadi")
    item.product_id = product_id
    item.quantity = quantity
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.post("/recipes/{recipe_id}/add-stage")
async def add_recipe_stage(
    recipe_id: int,
    stage_number: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    db.add(RecipeStage(recipe_id=recipe_id, stage_number=stage_number, name=(name or "").strip()))
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.post("/recipes/{recipe_id}/delete-stage/{stage_id}")
async def delete_recipe_stage(
    recipe_id: int,
    stage_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    stage = db.query(RecipeStage).filter(
        RecipeStage.id == stage_id,
        RecipeStage.recipe_id == recipe_id,
    ).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Bosqich topilmadi")
    db.delete(stage)
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.post("/recipes/{recipe_id}/delete-item/{item_id}")
async def delete_recipe_item(
    recipe_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    item = db.query(RecipeItem).filter(
        RecipeItem.id == item_id,
        RecipeItem.recipe_id == recipe_id,
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Tarkib qatori topilmadi")
    db.delete(item)
    db.commit()
    return RedirectResponse(url=f"/production/recipes/{recipe_id}", status_code=303)


@router.get("/api/quick-recipes")
async def production_api_quick_recipes(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Tezkor ishlab chiqarish uchun retseptlar ro'yxati (JSON). Sahifada quickRecipes bo'sh bo'lsa brauzer shu API orqali yuklaydi."""
    recipes = (
        db.query(Recipe)
        .options(
            joinedload(Recipe.product).joinedload(Product.unit),
        )
        .filter(Recipe.is_active == True)
        .all()
    )
    out = []
    for r in recipes:
        unit = "kg"
        if r.product and getattr(r.product, "unit", None):
            u = r.product.unit
            unit = (getattr(u, "name", None) or getattr(u, "code", None) or "kg") or "kg"
        out.append({
            "id": r.id,
            "name": r.name or "",
            "unit": unit,
            "wh": str(r.default_warehouse_id) if r.default_warehouse_id else "",
            "whOut": str(r.default_output_warehouse_id) if r.default_output_warehouse_id else "",
        })
    return out


@router.get("/by-operator", response_class=HTMLResponse)
async def production_by_operator(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Operator bo'yicha ishlab chiqarish (yakunlanganlar, sana bo'yicha)."""
    from collections import defaultdict
    from datetime import date as date_type

    if not current_user:
        return RedirectResponse(url="/login?next=/production/by-operator", status_code=303)
    today = date_type.today()
    if not (date_from or "").strip():
        date_from = today.replace(day=1).strftime("%Y-%m-%d")
    if not (date_to or "").strip():
        date_to = today.strftime("%Y-%m-%d")
    d_from = d_to = None
    try:
        d_from = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        d_from = today.replace(day=1)
    try:
        d_to = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        d_to = today

    qry = (
        db.query(Production)
        .options(
            joinedload(Production.recipe).joinedload(Recipe.product).joinedload(Product.unit),
            joinedload(Production.operator),
            joinedload(Production.user),
        )
        .filter(Production.status == "completed")
        .filter(func.date(Production.date) >= d_from)
        .filter(func.date(Production.date) <= d_to)
        .order_by(Production.date.desc())
    )
    productions_raw = qry.all()
    seen = {}
    for p in productions_raw:
        if p.id not in seen:
            seen[p.id] = p
    productions = list(seen.values())
    productions.sort(key=lambda x: (x.date or datetime.min), reverse=True)

    user_ids_from_productions = {p.user_id for p in productions if p.user_id and not p.operator_id}
    user_to_employee = {}
    if user_ids_from_productions:
        for emp in db.query(Employee).filter(Employee.user_id.in_(user_ids_from_productions)).all():
            if emp.user_id:
                user_to_employee[emp.user_id] = emp.id

    totals_by_name = defaultdict(float)
    name_to_employee_id = {}
    for p in productions:
        if is_qiyom_recipe(p.recipe):
            continue
        op_name = "—"
        if p.operator:
            op_name = getattr(p.operator, "full_name", None) or str(p.operator_id)
            if p.operator_id and op_name != "—":
                name_to_employee_id[op_name] = p.operator_id
        elif p.user:
            op_name = getattr(p.user, "full_name", None) or str(p.user_id)
            if p.user_id and op_name != "—":
                emp_id = user_to_employee.get(p.user_id)
                if emp_id:
                    name_to_employee_id[op_name] = emp_id
        kg = (p.quantity or 0) * recipe_kg_per_unit(p.recipe)
        totals_by_name[op_name] += kg
    operator_totals = sorted(totals_by_name.items(), key=lambda x: -x[1])

    return templates.TemplateResponse("production/by_operator.html", {
        "request": request,
        "current_user": current_user,
        "productions": productions,
        "operator_totals": operator_totals,
        "name_to_employee_id": name_to_employee_id,
        "user_to_employee": user_to_employee,
        "filter_date_from": (date_from or "").strip()[:10],
        "filter_date_to": (date_to or "").strip()[:10],
        "page_title": "Operator bo'yicha ishlab chiqarish",
    })


@router.get("/{prod_id}/movements", response_class=HTMLResponse)
async def production_movements_page(
    prod_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    """Shu ishlab chiqarish buyurtmasi uchun ombor harakati tarixi (xom ashyo chiqimi, tayyor mahsulot kirimi)."""
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production:
        return RedirectResponse(
            url="/production/orders?error=not_found&detail=" + quote("Buyurtma topilmadi."),
            status_code=303,
        )
    movements = (
        db.query(StockMovement)
        .options(
            joinedload(StockMovement.warehouse),
            joinedload(StockMovement.product),
        )
        .filter(
            StockMovement.document_type == "Production",
            StockMovement.document_id == prod_id,
        )
        .order_by(StockMovement.created_at.asc())
        .all()
    )
    rows = []
    for m in movements:
        wh_name = (m.warehouse.name if m.warehouse else "") or "—"
        prod_name = (m.product.name if m.product else "") or "—"
        code = (m.product.code if m.product else "") or ""
        qty = float(m.quantity_change or 0)
        rows.append({
            "warehouse_name": wh_name,
            "product_name": prod_name,
            "product_code": code,
            "quantity_change": qty,
            "quantity_after": float(m.quantity_after or 0),
            "created_at": m.created_at.strftime("%d.%m.%Y %H:%M") if m.created_at else "—",
        })
    return templates.TemplateResponse("production/movements.html", {
        "request": request,
        "current_user": current_user,
        "production": production,
        "rows": rows,
        "page_title": f"Harakat tarixi — {production.number}",
    })


@router.get("/{prod_id}/materials", response_class=HTMLResponse)
async def production_edit_materials(
    prod_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    production = (
        db.query(Production)
        .options(
            joinedload(Production.production_items).joinedload(ProductionItem.product).joinedload(Product.unit),
        )
        .filter(Production.id == prod_id)
        .first()
    )
    if not production:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    if production.status == "completed" and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Yakunlangan buyurtmani faqat administrator ko'ra oladi")
    if production.status not in ("draft", "completed"):
        raise HTTPException(status_code=400, detail="Faqat kutilmoqdagi yoki yakunlangan buyurtmani ko'rish mumkin")
    recipe = (
        db.query(Recipe)
        .options(joinedload(Recipe.items).joinedload(RecipeItem.product).joinedload(Product.unit))
        .filter(Recipe.id == production.recipe_id)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    if not production.production_items:
        for item in recipe.items:
            db.add(ProductionItem(
                production_id=production.id,
                product_id=item.product_id,
                quantity=item.quantity * production.quantity,
            ))
        db.commit()
        db.refresh(production)
    read_only = production.status == "completed"
    return templates.TemplateResponse("production/edit_materials.html", {
        "request": request,
        "current_user": current_user,
        "production": production,
        "recipe": recipe,
        "read_only": read_only,
        "page_title": f"Xom ashyo: {production.number}",
    })


@router.post("/{prod_id}/materials")
async def production_save_materials(
    prod_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production or production.status != "draft":
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi yoki tahrirlab bo'lmaydi")
    form = await request.form()
    for key, value in form.items():
        if key.startswith("qty_"):
            try:
                item_id = int(key.replace("qty_", ""))
                qty = float(value.replace(",", "."))
            except (ValueError, TypeError):
                continue
            pi = db.query(ProductionItem).filter(
                ProductionItem.id == item_id,
                ProductionItem.production_id == prod_id,
            ).first()
            if pi and qty >= 0:
                pi.quantity = qty
    db.commit()
    return RedirectResponse(url="/production/orders", status_code=303)


def _parse_optional_int(value) -> Optional[int]:
    """Query/form dan kelgan bo'sh string yoki noto'g'ri qiymatni None qilib, haqiqiy sonlarni int qaytaradi."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


@router.get("/orders", response_class=HTMLResponse)
async def production_orders(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    number: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    recipe: Optional[str] = None,
    operator_id: Optional[str] = None,
):
    from urllib.parse import unquote
    from sqlalchemy import func
    from datetime import datetime
    operator_id = _parse_optional_int(operator_id)
    q = (
        db.query(Production)
        .options(
            joinedload(Production.recipe).joinedload(Recipe.stages),
            joinedload(Production.recipe).joinedload(Recipe.product).joinedload(Product.unit),
            joinedload(Production.production_items),
            joinedload(Production.user),
            joinedload(Production.operator),
            joinedload(Production.warehouse),
            joinedload(Production.output_warehouse),
            joinedload(Production.machine),
        )
        .order_by(Production.date.desc())
    )
    current_user_employee = db.query(Employee).filter(Employee.user_id == current_user.id).first() if current_user else None
    role = (getattr(current_user, "role", None) or "").strip().lower()
    is_operator_role = role in ("production", "qadoqlash", "rahbar", "raxbar", "operator")
    # Operator: faqat o'zi ishlab chiqargan buyurtmalarni ko'radi (operator_id = joriy xodim)
    if current_user and role != "admin":
        if is_operator_role and current_user_employee and (operator_id is None or int(operator_id or 0) == 0):
            q = q.filter(Production.operator_id == current_user_employee.id)
        elif not is_operator_role:
            q = q.filter(Production.user_id == current_user.id)
    if operator_id is not None and int(operator_id) > 0:
        q = q.filter(Production.operator_id == int(operator_id))
    if number and str(number).strip():
        num_filter = "%" + str(number).strip() + "%"
        q = q.filter(func.lower(Production.number).like(func.lower(num_filter)))
    if recipe and str(recipe).strip():
        q = q.join(Recipe, Production.recipe_id == Recipe.id)
        recipe_filter = "%" + str(recipe).strip() + "%"
        q = q.filter(func.lower(Recipe.name).like(func.lower(recipe_filter)))
    if date_from and str(date_from).strip():
        try:
            d_from = datetime.strptime(str(date_from).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(func.date(Production.date) >= d_from)
        except (ValueError, TypeError):
            pass
    if date_to and str(date_to).strip():
        try:
            d_to = datetime.strptime(str(date_to).strip()[:10], "%Y-%m-%d").date()
            q = q.filter(func.date(Production.date) <= d_to)
        except (ValueError, TypeError):
            pass
    productions = q.all()
    total_output_kg = 0.0
    total_yarim_tayyor_kg = 0.0
    for p in productions:
        out_wh_name = (getattr(p.output_warehouse, "name", None) or "").lower()
        is_yarim_tayyor_output = "yarim" in out_wh_name
        out_kg = recipe_kg_per_unit(p.recipe) * (float(p.quantity or 0))
        inp_kg = sum(float(pi.quantity or 0) for pi in (p.production_items or []))
        completed_only = getattr(p, "status", None) == "completed"
        if is_yarim_tayyor_output:
            p.output_kg = 0.0
            is_qiyom = p.recipe and "qiyom" in (getattr(p.recipe, "name", None) or "").lower()
            if is_qiyom:
                p.yarim_tayyor_kg = 0.0  # qiyom retseptlari Y.t.kg da ko'rsatilmaydi va jamiga kiritilmaydi
            else:
                p.yarim_tayyor_kg = inp_kg
                if completed_only:
                    total_yarim_tayyor_kg += inp_kg
        else:
            p.output_kg = out_kg
            p.yarim_tayyor_kg = 0.0
            if completed_only:
                total_output_kg += out_kg
    machines = db.query(Machine).filter(Machine.is_active == True).all()
    employees = db.query(Employee).filter(Employee.is_active == True).all()
    error = request.query_params.get("error")
    detail = unquote(request.query_params.get("detail", "") or "")
    return templates.TemplateResponse("production/orders.html", {
        "request": request,
        "current_user": current_user,
        "productions": productions,
        "total_output_kg": total_output_kg,
        "total_yarim_tayyor_kg": total_yarim_tayyor_kg,
        "machines": machines,
        "employees": employees,
        "current_user_employee_id": current_user_employee.id if current_user_employee else None,
        "page_title": "Ishlab chiqarish buyurtmalari",
        "error": error,
        "error_detail": detail,
        "stage_names": PRODUCTION_STAGE_NAMES,
        "filter_number": (number or "").strip(),
        "filter_recipe": (recipe or "").strip(),
        "filter_date_from": (date_from or "").strip()[:10] if date_from else "",
        "filter_date_to": (date_to or "").strip()[:10] if date_to else "",
        "filter_operator_id": int(operator_id) if (operator_id is not None and int(operator_id) > 0) else None,
        "filter_q": "",
        "user_id_to_employee_id": {},
    })


@router.post("/orders/fix-dates-from-numbers")
async def production_orders_fix_dates_from_numbers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Admin: barcha ishlab chiqarish hujjatlarida sanani hujjat raqamidan (PR-YYYYMMDD-NNN) tuzatish. Tasdiqni bekor qilib qayta tasdiqlaganda sana o'zgargan yozuvlar uchun."""
    import re
    from urllib.parse import quote
    productions = db.query(Production).all()
    updated = 0
    for p in productions:
        if not p.number:
            continue
        m = re.match(r"PR-(\d{8})-\d+", str(p.number).strip())
        if not m:
            continue
        try:
            y, mo, d = int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8])
            from datetime import datetime as dt
            new_date = dt(y, mo, d, 0, 0, 0)
            if p.date is None or p.date.date() != new_date.date():
                p.date = new_date
                updated += 1
        except (ValueError, IndexError):
            continue
    db.commit()
    msg = quote(f"Hujjat raqamidan sana tuzatildi: {updated} ta yangilandi.")
    return RedirectResponse(url=f"/production/orders?fix_dates={msg}", status_code=303)


def _production_revert_one(db, production) -> Optional[str]:
    """Bitta buyurtmani tasdiqdan qaytaradi. Muvaffaqiyat bo'lsa None, xato bo'lsa xabar qaytaradi."""
    if production.status != "completed":
        return None
    recipe = db.query(Recipe).filter(Recipe.id == production.recipe_id).first()
    if not recipe:
        return "Retsept topilmadi"
    items_to_use = (
        [(pi.product_id, float(pi.quantity or 0)) for pi in (production.production_items or [])]
        if production.production_items
        else [(item.product_id, float(item.quantity or 0) * float(production.quantity or 0)) for item in (recipe.items or [])]
    )
    output_units = production_output_quantity_for_stock(db, production, recipe)
    out_wh_id = production.output_warehouse_id if production.output_warehouse_id else production.warehouse_id
    product_stock = db.query(Stock).filter(
        Stock.warehouse_id == out_wh_id,
        Stock.product_id == recipe.product_id,
    ).first()
    current_qty = float(product_stock.quantity or 0) if product_stock else 0
    if not product_stock or current_qty < output_units:
        out_wh = db.query(Warehouse).filter(Warehouse.id == out_wh_id).first()
        out_product = db.query(Product).filter(Product.id == recipe.product_id).first()
        wh_name = (out_wh.name if out_wh else "2-ombor") or "2-ombor"
        prod_name = (out_product.name if out_product else "tayyor mahsulot") or "tayyor mahsulot"
        return f"«{wh_name}» da «{prod_name}» dan kerak: {output_units:,.1f}, mavjud: {current_qty:,.1f}"
    product_stock.quantity = current_qty - output_units
    for product_id, required in items_to_use:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == production.warehouse_id,
            Stock.product_id == product_id,
        ).first()
        if stock:
            stock.quantity = float(stock.quantity or 0) + required
        else:
            db.add(Stock(warehouse_id=production.warehouse_id, product_id=product_id, quantity=required))
    production.status = "draft"
    movements = db.query(StockMovement).filter(
        StockMovement.document_type == "Production",
        StockMovement.document_id == production.id,
    ).all()
    for m in movements:
        db.delete(m)
    return None


@router.post("/orders/bulk-revert")
async def production_orders_bulk_revert(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    form = await request.form()
    raw_ids = form.getlist("prod_ids")
    prod_ids = [int(x) for x in raw_ids if str(x).strip().isdigit()]
    if not prod_ids:
        return RedirectResponse(
            url="/production/orders?error=revert&detail=" + quote("Hech qaysi buyurtma tanlanmagan."),
            status_code=303,
        )
    reverted = 0
    for pid in prod_ids:
        production = db.query(Production).filter(Production.id == pid).first()
        if not production:
            continue
        err = _production_revert_one(db, production)
        if err:
            db.rollback()
            return RedirectResponse(
                url="/production/orders?error=revert&detail=" + quote(f"{production.number}: {err}"),
                status_code=303,
            )
        reverted += 1
    db.commit()
    return RedirectResponse(url="/production/orders?bulk_reverted=" + str(reverted), status_code=303)


@router.post("/orders/bulk-complete")
async def production_orders_bulk_complete(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    form = await request.form()
    raw_ids = form.getlist("prod_ids")
    prod_ids = [int(x) for x in raw_ids if str(x).strip().isdigit()]
    if not prod_ids:
        return RedirectResponse(
            url="/production/orders?error=complete&detail=" + quote("Hech qaysi buyurtma tanlanmagan."),
            status_code=303,
        )
    completed = 0
    for pid in prod_ids:
        production = db.query(Production).filter(Production.id == pid).first()
        if not production or production.status not in ("draft", "in_progress"):
            continue
        recipe = db.query(Recipe).filter(Recipe.id == production.recipe_id).first()
        if not recipe:
            return RedirectResponse(
                url="/production/orders?error=complete&detail=" + quote(f"{production.number}: Retsept topilmadi."),
                status_code=303,
            )
        err = _do_complete_production_stock(db, production, recipe)
        if err:
            db.rollback()
            return err
        production.status = "completed"
        production.current_stage = _recipe_max_stage(recipe)
        completed += 1
    db.commit()
    check_low_stock_and_notify(db)
    for pid in prod_ids:
        production = db.query(Production).filter(Production.id == pid).first()
        if production and production.status == "completed":
            notify_managers_production_ready(db, production)
    return RedirectResponse(url="/production/orders?bulk_completed=" + str(completed), status_code=303)


@router.get("/new", response_class=HTMLResponse)
async def production_new(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    warehouses = get_warehouses_for_user(db, current_user)
    recipes = db.query(Recipe).filter(Recipe.is_active == True).all()
    machines = db.query(Machine).filter(Machine.is_active == True).all()
    employees = db.query(Employee).filter(Employee.is_active == True).all()
    current_user_employee = db.query(Employee).filter(Employee.user_id == current_user.id).first() if current_user else None
    return templates.TemplateResponse("production/new_order.html", {
        "request": request,
        "current_user": current_user,
        "recipes": recipes,
        "warehouses": warehouses,
        "machines": machines,
        "employees": employees,
        "current_user_employee_id": current_user_employee.id if current_user_employee else None,
        "page_title": "Yangi ishlab chiqarish",
    })


@router.get("/create")
async def production_create_get():
    """GET /production/create — formani POST qilish kerak; brauzerda ochilsa asosiy oynaga yo'naltirish."""
    return RedirectResponse(url="/production", status_code=303)


@router.post("/create")
async def create_production(
    request: Request,
    recipe_id: int = Form(...),
    warehouse_id: Optional[int] = Form(None),
    output_warehouse_id: Optional[int] = Form(None),
    quantity: float = Form(...),
    note: str = Form(""),
    machine_id: Optional[int] = Form(None),
    operator_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Ombor tanlanmasa, FastAPI 422 JSON qaytarib yubormasdan foydalanuvchini orqaga qaytaramiz.
    if warehouse_id is None:
        return RedirectResponse(url="/production?error=warehouse", status_code=303)
    if quantity <= 0:
        return RedirectResponse(url="/production?error=quantity", status_code=303)
    if output_warehouse_id is None:
        output_warehouse_id = warehouse_id
    recipe = db.query(Recipe).options(joinedload(Recipe.stages)).filter(Recipe.id == recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    # Operator: forma orqali tanlangan yoki joriy foydalanuvchiga bog'langan xodim
    effective_operator_id = int(operator_id) if operator_id else None
    if effective_operator_id is None and current_user:
        current_user_employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
        effective_operator_id = current_user_employee.id if current_user_employee else None
    max_stage = _recipe_max_stage(recipe)
    today = datetime.now()
    count = db.query(Production).filter(
        Production.date >= today.replace(hour=0, minute=0, second=0)
    ).count()
    number = f"PR-{today.strftime('%Y%m%d')}-{str(count + 1).zfill(3)}"
    production = Production(
        number=number,
        recipe_id=recipe_id,
        warehouse_id=warehouse_id,
        output_warehouse_id=output_warehouse_id,
        quantity=quantity,
        note=note,
        status="draft",
        current_stage=1,
        max_stage=max_stage,
        user_id=current_user.id if current_user else None,
        machine_id=int(machine_id) if machine_id else None,
        operator_id=effective_operator_id,
    )
    db.add(production)
    db.commit()
    db.refresh(production)
    for stage_num in range(1, max_stage + 1):
        db.add(ProductionStage(production_id=production.id, stage_number=stage_num))
    db.commit()
    recipe = db.query(Recipe).filter(Recipe.id == recipe_id).first()
    if recipe:
        for item in recipe.items:
            db.add(ProductionItem(
                production_id=production.id,
                product_id=item.product_id,
                quantity=item.quantity * quantity,
            ))
        db.commit()
    return RedirectResponse(url="/production/orders", status_code=303)


@router.post("/{prod_id}/complete-stage")
async def complete_production_stage(
    prod_id: int,
    stage_number: int = Form(...),
    machine_id: Optional[int] = Form(None),
    operator_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production:
        raise HTTPException(status_code=404, detail="Topilmadi")
    recipe = (
        db.query(Recipe)
        .options(joinedload(Recipe.stages))
        .filter(Recipe.id == production.recipe_id)
        .first()
    )
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    max_stage = _recipe_max_stage(recipe)
    if stage_number < 1 or stage_number > max_stage:
        raise HTTPException(status_code=400, detail=f"Bosqich 1–{max_stage} oralig'ida bo'lishi kerak")
    if production.status == "completed":
        return RedirectResponse(url="/production", status_code=303)
    current = getattr(production, "current_stage", None) or 1
    if current > max_stage:
        err = _do_complete_production_stock(db, production, recipe)
        if err:
            return err
        production.status = "completed"
        production.current_stage = max_stage
        db.commit()
        check_low_stock_and_notify(db)
        notify_managers_production_ready(db, production)
        return RedirectResponse(url="/production", status_code=303)
    if stage_number != current:
        return RedirectResponse(
            url=f"/production/orders?error=stage&detail=Keyingi bosqich {current}",
            status_code=303,
        )
    # Operator: forma orqali tanlangan yoki joriy foydalanuvchi (xodim) avtomatik
    effective_operator_id = int(operator_id) if operator_id else None
    if effective_operator_id is None and current_user:
        current_user_employee = db.query(Employee).filter(Employee.user_id == current_user.id).first()
        effective_operator_id = current_user_employee.id if current_user_employee else None
    if current_user and effective_operator_id is None:
        production.user_id = current_user.id  # Ustunda foydalanuvchi nomi ko'rinsin
    stage_row = db.query(ProductionStage).filter(
        ProductionStage.production_id == prod_id,
        ProductionStage.stage_number == stage_number,
    ).first()
    now = datetime.now()
    if stage_row:
        if not stage_row.started_at:
            stage_row.started_at = now
        stage_row.completed_at = now
        stage_row.machine_id = int(machine_id) if machine_id else None
        stage_row.operator_id = effective_operator_id
    production.operator_id = effective_operator_id
    if stage_number < max_stage:
        production.current_stage = stage_number + 1
        production.status = "in_progress"
        db.commit()
        # Bosqich tugagach keyingi bosqich operatorlarini xabardor qilish
        notify_next_stage_operators(db, production, stage_number)
        return RedirectResponse(url="/production/orders", status_code=303)
    err = _do_complete_production_stock(db, production, recipe)
    if err:
        return err
    production.status = "completed"
    production.current_stage = max_stage
    db.commit()
    check_low_stock_and_notify(db)
    # Oxirgi bosqich (qadoqlash) tugadi — admin va menejerga bildirish
    notify_managers_production_ready(db, production)
    return RedirectResponse(url="/production", status_code=303)


@router.post("/{prod_id}/complete")
async def complete_production(
    prod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production:
        raise HTTPException(status_code=404, detail="Topilmadi")
    recipe = db.query(Recipe).filter(Recipe.id == production.recipe_id).first()
    if not recipe:
        raise HTTPException(status_code=404, detail="Retsept topilmadi")
    err = _do_complete_production_stock(db, production, recipe)
    if err:
        return err
    production.status = "completed"
    production.current_stage = _recipe_max_stage(recipe)
    db.commit()
    check_low_stock_and_notify(db)
    notify_managers_production_ready(db, production)
    return RedirectResponse(url="/production", status_code=303)


@router.post("/{prod_id}/revert")
async def production_revert(
    prod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production:
        raise HTTPException(status_code=404, detail="Topilmadi")
    if production.status != "completed":
        return RedirectResponse(
            url="/production/orders?error=revert&detail=" + quote("Faqat yakunlangan buyurtmaning tasdiqini bekor qilish mumkin."),
            status_code=303,
        )
    recipe = db.query(Recipe).filter(Recipe.id == production.recipe_id).first()
    if not recipe:
        return RedirectResponse(
            url="/production/orders?error=revert&detail=" + quote("Retsept topilmadi."),
            status_code=303,
        )
    items_to_use = (
        [(pi.product_id, float(pi.quantity or 0)) for pi in (production.production_items or [])]
        if production.production_items
        else [(item.product_id, float(item.quantity or 0) * float(production.quantity or 0)) for item in (recipe.items or [])]
    )
    output_units = production_output_quantity_for_stock(db, production, recipe)
    out_wh_id = production.output_warehouse_id if production.output_warehouse_id else production.warehouse_id
    product_stock = db.query(Stock).filter(
        Stock.warehouse_id == out_wh_id,
        Stock.product_id == recipe.product_id,
    ).first()
    current_qty = float(product_stock.quantity or 0) if product_stock else 0
    if not product_stock or current_qty < output_units:
        out_wh = db.query(Warehouse).filter(Warehouse.id == out_wh_id).first()
        out_product = db.query(Product).filter(Product.id == recipe.product_id).first()
        wh_name = (out_wh.name if out_wh else "2-ombor") or "2-ombor"
        prod_name = (out_product.name if out_product else "tayyor mahsulot") or "tayyor mahsulot"
        detail = f"«{wh_name}» da «{prod_name}» dan kerak: {output_units:,.1f}, mavjud: {current_qty:,.1f}. Mahsulot sotilgan yoki ko'chirilgan bo'lishi mumkin — tasdiqni bekor qilish uchun 2-omborda shu miqdorda qoldiq bo'lishi kerak."
        return RedirectResponse(
            url="/production/orders?error=revert&detail=" + quote(detail),
            status_code=303,
        )
    product_stock.quantity = current_qty - output_units
    for product_id, required in items_to_use:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == production.warehouse_id,
            Stock.product_id == product_id,
        ).first()
        if stock:
            stock.quantity = float(stock.quantity or 0) + required
        else:
            db.add(Stock(warehouse_id=production.warehouse_id, product_id=product_id, quantity=required))
    movements = db.query(StockMovement).filter(
        StockMovement.document_type == "Production",
        StockMovement.document_id == production.id,
    ).all()
    for m in movements:
        db.delete(m)
    production.status = "draft"
    db.commit()
    return RedirectResponse(url="/production/orders", status_code=303)


@router.post("/{prod_id}/cancel")
async def cancel_production(prod_id: int, db: Session = Depends(get_db)):
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production:
        raise HTTPException(status_code=404, detail="Topilmadi")
    production.status = "cancelled"
    db.commit()
    return RedirectResponse(url="/production/orders", status_code=303)


@router.post("/{prod_id}/delete")
async def delete_production(
    prod_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    production = db.query(Production).filter(Production.id == prod_id).first()
    if not production:
        raise HTTPException(status_code=404, detail="Buyurtma topilmadi")
    # Shu buyurtmaga bog'liq barcha StockMovement yozuvlarini topib, qoldiqni teskari yangilash va yozuvlarni o'chirish
    movements = db.query(StockMovement).filter(
        StockMovement.document_type == "Production",
        StockMovement.document_id == prod_id,
    ).all()
    for m in movements:
        stock = db.query(Stock).filter(
            Stock.warehouse_id == m.warehouse_id,
            Stock.product_id == m.product_id,
        ).first()
        if stock:
            # Harakatni bekor qilish: qoldiqdan quantity_change ni ayirish
            new_qty = (stock.quantity or 0) - (m.quantity_change or 0)
            stock.quantity = max(0.0, new_qty)
        db.delete(m)
    db.delete(production)
    db.commit()
    return RedirectResponse(url="/production/orders", status_code=303)
