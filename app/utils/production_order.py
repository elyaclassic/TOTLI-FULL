"""
Buyurtma va ishlab chiqarish integratsiyasi funksiyalari
"""
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func

from datetime import timedelta

from app.models.database import (
    Order,
    OrderItem,
    Product,
    Recipe,
    RecipeItem,
    Production,
    ProductionItem,
    ProductionStage,
    Stock,
    Warehouse,
    User,
    Department,
    Notification,
)
from app.utils.notifications import create_notification


def get_semi_finished_warehouse(db: Session):
    """Yarim tayyor omborini topish (nomi yoki kodida 'yarim' yoki 'semi' bo'lgan)."""
    return db.query(Warehouse).filter(
        func.lower(Warehouse.name).contains("yarim") |
        func.lower(Warehouse.name).contains("semi") |
        func.lower(Warehouse.code).contains("yarim") |
        func.lower(Warehouse.code).contains("semi")
    ).first()


def get_product_stock_in_warehouse(db: Session, warehouse_id: int, product_id: int) -> float:
    """Berilgan omborda mahsulot qoldig'ini qaytaradi."""
    stock = db.query(Stock).filter(
        Stock.warehouse_id == warehouse_id,
        Stock.product_id == product_id,
    ).first()
    return float(stock.quantity if stock else 0.0)


def _get_users_by_role(db: Session, *roles: str):
    """Berilgan rollar bo'yicha faol foydalanuvchilarni qaytaradi."""
    return db.query(User).filter(
        User.is_active == True,
        User.role.in_(list(roles)),
    ).all()


def notify_operator_semi_finished_available(
    db: Session,
    order_number: str,
    order_id: int,
    product_name: str,
):
    """Eski nom — orqaga moslik uchun saqlandi. notify_cutting_packing_operators ni chaqiradi."""
    notify_cutting_packing_operators(db, order_number, order_id, product_name)


def notify_qiyom_operators(
    db: Session,
    order_number: str,
    order_id: int,
    product_name: str,
):
    """
    Yarim tayyor omborda mahsulot yetarli emas —
    qiyom operatorlariga bildirish.
    """
    users = _get_users_by_role(db, "production", "operator", "rahbar", "raxbar")
    since = datetime.now() - timedelta(hours=24)
    msg_text = (
        f"Sotuv {order_number} uchun «{product_name}» "
        f"yarim tayyor omborda yetarli emas. Qiyom tayyorlang."
    )
    for user in users:
        # 24 soat ichida bir xil bildirishnoma yaratilmasin
        existing = db.query(Notification).filter(
            Notification.title == "Qiyom tayyorlash kerak",
            Notification.user_id == user.id,
            Notification.related_entity_id == order_id,
            Notification.created_at >= since,
        ).first()
        if existing:
            continue
        create_notification(
            db=db,
            title="Qiyom tayyorlash kerak",
            message=msg_text,
            notification_type="warning",
            user_id=user.id,
            priority="high",
            action_url="/production",
            related_entity_type="order",
            related_entity_id=order_id,
        )


def notify_cutting_packing_operators(
    db: Session,
    order_number: str,
    order_id: int,
    product_name: str,
):
    """
    Yarim tayyor omborda mahsulot yetarli —
    kesuvchi va qadoqlovchilarga bildirish.
    """
    users = _get_users_by_role(db, "production", "qadoqlash", "operator", "rahbar", "raxbar")
    for user in users:
        create_notification(
            db=db,
            title="Kesish va qadoqlash kerak",
            message=(
                f"Sotuv {order_number} uchun «{product_name}» "
                f"yarim tayyor omborda mavjud. Kesib qadoqlang."
            ),
            notification_type="info",
            user_id=user.id,
            priority="high",
            action_url=f"/sales/edit/{order_id}",
            related_entity_type="order",
            related_entity_id=order_id,
        )


def notify_next_stage_operators(db: Session, production, completed_stage: int):
    """
    Bosqich yakunlanganda keyingi bosqich operatorlarini xabardor qilish:
      - Bosqich 1 yoki 2 (qiyom) tugasa  → kesuvchi + qadoqlovchi
      - Bosqich 3 (kesish) tugasa         → faqat qadoqlovchi
      - Bosqich 4+ (oxirgi)               → bu funksiya chaqirilmaydi
    """
    recipe = db.query(Recipe).filter(Recipe.id == production.recipe_id).first()
    product_name = "Mahsulot"
    if recipe and recipe.product_id:
        p = db.query(Product).filter(Product.id == recipe.product_id).first()
        if p:
            product_name = p.name or product_name

    if completed_stage <= 2:
        users = _get_users_by_role(db, "production", "qadoqlash", "operator", "rahbar", "raxbar")
        title = "Qiyom tayyor — kesish va qadoqlash navbati"
        message = (
            f"«{product_name}» qiyom bosqichi yakunlandi. "
            f"Kesish va qadoqlashni boshlang. (#{production.number})"
        )
    elif completed_stage == 3:
        users = _get_users_by_role(db, "qadoqlash", "operator", "rahbar", "raxbar")
        title = "Kesish tugadi — qadoqlash navbati"
        message = (
            f"«{product_name}» kesish yakunlandi. "
            f"Qadoqlashni boshlang. (#{production.number})"
        )
    else:
        return

    for user in users:
        create_notification(
            db=db,
            title=title,
            message=message,
            notification_type="info",
            user_id=user.id,
            priority="high",
            action_url="/production/orders",
            related_entity_type="production",
            related_entity_id=production.id,
        )


def is_qiyom_recipe(recipe) -> bool:
    """Retsept 'qiyom' (oralama mahsulot) bo'lsa — jamida hisoblanmasin (shablon: qiyom hisobga olinmaydi)."""
    if not recipe or not getattr(recipe, "name", None):
        return False
    return "qiyom" in (recipe.name or "").lower()


def recipe_kg_per_unit(recipe: Optional[Recipe]) -> float:
    """Retsept uchun 1 dona (birlik) ning og'irligi kg da. Nomidan gramm/kg aniqlanadi."""
    import re
    if not recipe:
        return 1.0
    name = (recipe.name or "").lower()
    # Grammlarni aniqlash: 150gr, 250 gr, 400gr, 500g, (600g), ...
    m_gr = re.search(r'(\d+)\s*gr', name)
    if m_gr:
        return int(m_gr.group(1)) / 1000.0
    m_g = re.search(r'(\d+)\s*g(?:\b|\))', name)
    if m_g:
        return int(m_g.group(1)) / 1000.0
    # Kilogrammlarni aniqlash: 1kg, 1.8kg, 2.5kg, 3 kg, ...
    m_kg = re.search(r'([\d.]+)\s*kg', name)
    if m_kg:
        return float(m_kg.group(1))
    return float(recipe.output_quantity or 1.0)


def production_output_quantity_for_stock(db: Session, production, recipe) -> float:
    """Tayyor mahsulot uchun qoldiq/harakatda yoziladigan miqdor: dona mahsulotda production.quantity, kg mahsulotda production.quantity * recipe_kg_per_unit(recipe)."""
    if not recipe:
        return 0.0
    output_product = db.query(Product).filter(Product.id == recipe.product_id).first()
    if not output_product:
        _unit_str = ""
    else:
        unit = getattr(output_product, "unit", None)
        name = (getattr(unit, "name", None) or "") if unit else ""
        code = (getattr(unit, "code", None) or "") if unit else ""
        _unit_str = (name + " " + code).lower()
    if "dona" in _unit_str:
        return float(production.quantity or 0)
    return float(production.quantity or 0) * recipe_kg_per_unit(recipe)


def check_semi_finished_stock(
    db: Session,
    recipe: Recipe,
    required_quantity: float,
    semi_finished_warehouse_id: Optional[int] = None,
) -> Tuple[float, Optional[int]]:
    """
    Yarim tayyor mahsulot omborida yetarli yarim tayyor mahsulot bormi tekshirish.
    
    Args:
        db: Database session
        recipe: Retsept
        required_quantity: Kerakli miqdor (tayyor mahsulot uchun)
        semi_finished_warehouse_id: Yarim tayyor ombor ID (agar None bo'lsa, avtomatik topiladi)
    
    Returns:
        Tuple[float, Optional[int]]: (mavjud miqdor, yarim_tayyor_ombor_id)
    """
    # Agar yarim tayyor ombor ID berilmagan bo'lsa, topishga harakat qilamiz
    if semi_finished_warehouse_id is None:
        # Yarim tayyor omborini topish (nomi yoki kodida "yarim" yoki "semi" bo'lgan)
        semi_warehouse = db.query(Warehouse).filter(
            func.lower(Warehouse.name).contains("yarim") |
            func.lower(Warehouse.name).contains("semi") |
            func.lower(Warehouse.code).contains("yarim") |
            func.lower(Warehouse.code).contains("semi")
        ).first()
        if semi_warehouse:
            semi_finished_warehouse_id = semi_warehouse.id
        else:
            return (0.0, None)
    
    # Retseptdan yarim tayyor mahsulotni topish
    # Retseptning 2-bosqichida yarim tayyor mahsulot yaratiladi
    # Shuning uchun retseptning output mahsuloti yarim tayyor bo'lishi mumkin
    # Yoki retsept items ichida yarim tayyor mahsulot bo'lishi mumkin
    
    recipe_product = db.query(Product).filter(Product.id == recipe.product_id).first()
    if not recipe_product:
        return (0.0, semi_finished_warehouse_id)
    
        # Agar retsept mahsuloti yarim tayyor bo'lsa, uni tekshiramiz
    if recipe_product and hasattr(recipe_product, 'type') and recipe_product.type == "yarim_tayyor":
        stock = db.query(Stock).filter(
            Stock.warehouse_id == semi_finished_warehouse_id,
            Stock.product_id == recipe.product_id,
        ).first()
        available = stock.quantity if stock else 0.0
        return (available, semi_finished_warehouse_id)
    
    # Aks holda, retsept items ichida yarim tayyor mahsulot qidiramiz
    recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
    for item in recipe_items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product and product.type == "yarim_tayyor":
            stock = db.query(Stock).filter(
                Stock.warehouse_id == semi_finished_warehouse_id,
                Stock.product_id == product.id,
            ).first()
            available = stock.quantity if stock else 0.0
            # Retseptda qancha yarim tayyor kerak?
            # Agar retsept 1 kg tayyor mahsulot uchun X kg yarim tayyor kerak bo'lsa:
            required_semi = item.quantity * required_quantity
            return (available, semi_finished_warehouse_id)
    
    return (0.0, semi_finished_warehouse_id)


def create_production_from_order(
    db: Session,
    order: Order,
    insufficient_items: List[Dict],
    current_user: Optional[User] = None,
) -> Tuple[List[Production], List[str]]:
    """
    Yetarli bo'lmagan mahsulotlar uchun ishlab chiqarish buyurtmalari yaratish.
    
    Args:
        db: Database session
        order: Buyurtma
        insufficient_items: Yetarli bo'lmagan mahsulotlar ro'yxati
            [{"product": Product, "required": float, "available": float}]
        current_user: Joriy foydalanuvchi
    
    Returns:
        List[Production]: Yaratilgan ishlab chiqarish buyurtmalari
    """
    productions: List[Production] = []
    missing: List[str] = []
    
    # Omborlarni topish
    # Xom ashyo ombori (materiallar shu yerdan olinadi)
    raw_material_warehouse = db.query(Warehouse).filter(
        func.lower(Warehouse.name).contains("xom") |
        func.lower(Warehouse.name).contains("material") |
        func.lower(Warehouse.code).contains("xom") |
        func.lower(Warehouse.code).contains("mat")
    ).first()
    
    # Yarim tayyor ombori
    semi_finished_warehouse = db.query(Warehouse).filter(
        func.lower(Warehouse.name).contains("yarim") |
        func.lower(Warehouse.name).contains("semi") |
        func.lower(Warehouse.code).contains("yarim") |
        func.lower(Warehouse.code).contains("semi")
    ).first()
    
    # Tayyor mahsulot ombori (buyurtma ombori)
    finished_warehouse_id = order.warehouse_id
    
    # Agar omborlar topilmasa, default omborlardan foydalanamiz
    if not raw_material_warehouse:
        raw_material_warehouse = db.query(Warehouse).first()
    if not semi_finished_warehouse:
        semi_finished_warehouse = raw_material_warehouse  # Fallback
    
    for item_data in insufficient_items:
        product = item_data["product"]
        required = item_data["required"]
        available = item_data["available"]
        needed = required - available
        
        # Retseptni topish
        recipe = db.query(Recipe).filter(
            Recipe.product_id == product.id,
            Recipe.is_active == True
        ).first()
        
        if not recipe:
            # Retsept topilmasa, caller xabar berishi uchun yig'amiz
            missing.append(product.name if product and getattr(product, "name", None) else f"#{getattr(product, 'id', '')}")
            continue
        
        # Yarim tayyor mahsulot tekshiruvi
        semi_available, semi_warehouse_id = check_semi_finished_stock(
            db, recipe, needed, semi_finished_warehouse.id if semi_finished_warehouse else None
        )
        
        # Retseptdan yarim tayyor mahsulot kerak miqdorini hisoblash
        recipe_items = db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).all()
        required_semi_quantity = 0.0
        semi_product_id = None
        
        for r_item in recipe_items:
            r_product = db.query(Product).filter(Product.id == r_item.product_id).first()
            if r_product and r_product.type == "yarim_tayyor":
                required_semi_quantity = r_item.quantity * needed
                semi_product_id = r_product.id
                break
        
        # Agar retsept mahsuloti o'zi yarim tayyor bo'lsa
        recipe_output_product = db.query(Product).filter(Product.id == recipe.product_id).first()
        if recipe_output_product and hasattr(recipe_output_product, 'type') and recipe_output_product.type == "yarim_tayyor":
            required_semi_quantity = needed
            semi_product_id = recipe.product_id
        
        # Ishlab chiqarish bosqichlarini aniqlash
        max_stage = _recipe_max_stage(recipe)
        start_stage = 1
        
        if semi_available >= required_semi_quantity and semi_product_id:
            # Yarim tayyor yetarli → kesish + qadoqlash (bosqich 3-4)
            start_stage = 3
            notification_stages = ["kesish", "qadoqlash"]
        else:
            # Yarim tayyor yetmasa → to'liq jarayon (bosqich 1-4)
            start_stage = 1
            notification_stages = ["qiyom"]
        
        # Ishlab chiqarish buyurtmasi yaratish
        today = datetime.now()
        count = db.query(Production).filter(
            Production.date >= today.replace(hour=0, minute=0, second=0)
        ).count()
        number = f"PR-{today.strftime('%Y%m%d')}-{str(count + 1).zfill(3)}"
        
        production = Production(
            number=number,
            recipe_id=recipe.id,
            warehouse_id=raw_material_warehouse.id if raw_material_warehouse else order.warehouse_id,
            output_warehouse_id=finished_warehouse_id,
            quantity=needed,
            status="draft",
            current_stage=start_stage,
            max_stage=max_stage,
            user_id=current_user.id if current_user else order.user_id,
            order_id=order.id,
            note=f"Buyurtma {order.number} uchun avtomatik yaratilgan",
        )
        db.add(production)
        db.flush()  # ID olish uchun
        
        # Ishlab chiqarish bosqichlarini yaratish
        for stage_num in range(start_stage, max_stage + 1):
            db.add(ProductionStage(
                production_id=production.id,
                stage_number=stage_num
            ))
        
        # Retsept items dan ProductionItem yaratish
        for r_item in recipe_items:
            db.add(ProductionItem(
                production_id=production.id,
                product_id=r_item.product_id,
                quantity=r_item.quantity * needed
            ))
        
        productions.append(production)
        
        # Notification yuborish - tegishli bo'lim foydalanuvchilariga
        notify_production_users(
            db=db,
            stages=notification_stages,
            order_number=order.number,
            production_number=production.number,
            product_name=product.name if product else "Mahsulot"
        )
    
    # commit'ni caller qiladi (transaction nazorati shu yerda emas)
    return productions, missing


def _recipe_max_stage(recipe) -> int:
    """Retseptdagi maksimal bosqich sonini topish"""
    if not recipe or not recipe.stages:
        return 4  # Default: 4 bosqich
    return max(s.stage_number for s in recipe.stages)


def notify_production_users(
    db: Session,
    stages: List[str],
    order_number: str,
    production_number: str,
    product_name: str,
):
    """
    Ishlab chiqarish bosqichlari foydalanuvchilariga habar yuborish.
    
    Args:
        db: Database session
        stages: Bosqichlar ro'yxati (masalan: ["qiyom", "kesish", "qadoqlash"])
        order_number: Buyurtma raqami
        production_number: Ishlab chiqarish raqami
        product_name: Mahsulot nomi
    """
    # Bosqich nomlarini o'zbek tiliga tarjima qilish
    stage_names = {
        "qiyom": "Qiyom tayyorlash",
        "kesish": "Holva kesish",
        "qadoqlash": "Qadoqlash",
    }
    
    stage_display = ", ".join([stage_names.get(s, s) for s in stages])
    
    # Ishlab chiqarish bo'limidagi barcha foydalanuvchilarga habar yuborish
    production_department = db.query(Department).filter(
        func.lower(Department.name).contains("ishlab") |
        func.lower(Department.name).contains("chiqarish") |
        func.lower(Department.code).contains("prod")
    ).first()
    
    if production_department:
        # Bo'limga biriktirilgan foydalanuvchilar
        users = db.query(User).filter(
            User.department_id == production_department.id,
            User.is_active == True
        ).all()
        
        for user in users:
            create_notification(
                db=db,
                title=f"🔄 Yangi ishlab chiqarish buyurtmasi",
                message=f"Buyurtma {order_number} uchun {product_name} mahsulotini ishlab chiqarish kerak. "
                       f"Bosqichlar: {stage_display}. "
                       f"Ishlab chiqarish raqami: {production_number}",
                notification_type="info",
                user_id=user.id,
                priority="high",
                action_url=f"/production/orders/{production_number}",
                related_entity_type="production",
            )
    else:
        # Agar bo'lim topilmasa, barcha faol foydalanuvchilarga yuborish
        users = db.query(User).filter(User.is_active == True).limit(10).all()
        for user in users:
            create_notification(
                db=db,
                title=f"🔄 Yangi ishlab chiqarish buyurtmasi",
                message=f"Buyurtma {order_number} uchun {product_name} mahsulotini ishlab chiqarish kerak. "
                       f"Bosqichlar: {stage_display}.",
                notification_type="info",
                user_id=user.id,
                priority="normal",
                action_url=f"/production/orders",
                related_entity_type="production",
            )


def notify_managers_production_ready(db: Session, production) -> None:
    """
    Ishlab chiqarish buyurtmasi operator tomonidan yakunlanganda menejerlarga ovozli push (high priority) bildirishnoma.
    """
    if not production:
        return
    order_number = ""
    if getattr(production, "order_id", None):
        order = db.query(Order).filter(Order.id == production.order_id).first()
        if order:
            order_number = order.number or ""
    recipe = db.query(Recipe).filter(Recipe.id == production.recipe_id).first()
    product_name = "Mahsulot"
    if recipe and recipe.product_id:
        p = db.query(Product).filter(Product.id == recipe.product_id).first()
        if p:
            product_name = p.name or product_name
    managers = db.query(User).filter(
        User.is_active == True,
        User.role.in_(["manager", "admin"]),
    ).all()
    for user in managers:
        create_notification(
            db=db,
            title="Ishlab chiqarish tayyor",
            message=f"Buyurtma {order_number} uchun «{product_name}» tayyorlandi. Ishlab chiqarish raqami: {production.number}",
            notification_type="success",
            user_id=user.id,
            priority="high",
            action_url=f"/production/orders",
            related_entity_type="production",
            related_entity_id=production.id,
        )
