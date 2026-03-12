"""
Mahsulot narxlarini hisoblash funksiyalari
- Oxirgi kirib kelgan narx
- O'rtacha tannarx (Weighted Average Cost)
"""
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.database import Product, Purchase, PurchaseItem, Stock


def get_last_purchase_price(db: Session, product_id: int, warehouse_id: int = None) -> float:
    """
    Mahsulotning oxirgi kirib kelgan narxini topish.
    
    Args:
        db: Database session
        product_id: Mahsulot ID
        warehouse_id: Ombor ID (ixtiyoriy, agar None bo'lsa barcha omborlardan qidiradi)
    
    Returns:
        float: Oxirgi kirib kelgan narx (yoki 0)
    """
    query = db.query(PurchaseItem.price).join(
        Purchase, PurchaseItem.purchase_id == Purchase.id
    ).filter(
        PurchaseItem.product_id == product_id,
        Purchase.status == "confirmed"
    ).order_by(Purchase.date.desc())
    
    if warehouse_id:
        query = query.filter(Purchase.warehouse_id == warehouse_id)
    
    last_price = query.first()
    return float(last_price[0]) if last_price and last_price[0] else 0.0


def calculate_average_cost(
    db: Session, 
    product_id: int, 
    warehouse_id: int,
    new_quantity: float,
    new_price: float,
    new_expense_share: float = 0.0
) -> float:
    """
    O'rtacha tannarxni hisoblash (Weighted Average Cost).
    
    Formula:
    O'rtacha tannarx = (Eski miqdor * Eski narx + Yangi miqdor * Yangi narx) / (Eski miqdor + Yangi miqdor)
    
    Args:
        db: Database session
        product_id: Mahsulot ID
        warehouse_id: Ombor ID
        new_quantity: Yangi kirib kelgan miqdor
        new_price: Yangi narx (bitta birlik uchun)
        new_expense_share: Yangi xarajatlar ulushi (bitta birlik uchun)
    
    Returns:
        float: O'rtacha tannarx
    """
    # Yangi narx (xarajatlar bilan)
    new_cost_per_unit = new_price + (new_expense_share / new_quantity if new_quantity > 0 else 0)
    new_total_cost = new_quantity * new_cost_per_unit
    
    # Eski qoldiq va narx
    stock = db.query(Stock).filter(
        Stock.warehouse_id == warehouse_id,
        Stock.product_id == product_id
    ).first()
    
    product = db.query(Product).filter(Product.id == product_id).first()
    old_quantity = stock.quantity if stock else 0.0
    old_price = product.purchase_price if product and product.purchase_price else 0.0
    
    # Agar eski qoldiq yo'q bo'lsa, yangi narxni qaytarish
    if old_quantity <= 0 or old_price <= 0:
        return new_cost_per_unit
    
    # O'rtacha tannarx hisoblash
    old_total_cost = old_quantity * old_price
    total_quantity = old_quantity + new_quantity
    total_cost = old_total_cost + new_total_cost
    
    if total_quantity > 0:
        average_cost = total_cost / total_quantity
        return average_cost
    
    return new_cost_per_unit


def get_suggested_price(
    db: Session,
    product_id: int,
    warehouse_id: int = None,
    use_average: bool = True
) -> float:
    """
    Mahsulot uchun taklif qilingan narxni olish.
    
    Args:
        db: Database session
        product_id: Mahsulot ID
        warehouse_id: Ombor ID
        use_average: True bo'lsa o'rtacha tannarx, False bo'lsa oxirgi narx
    
    Returns:
        float: Taklif qilingan narx
    """
    if use_average:
        # O'rtacha tannarx uchun joriy qoldiq va narxni olish
        product = db.query(Product).filter(Product.id == product_id).first()
        if product and product.purchase_price and product.purchase_price > 0:
            # Agar mahsulotda o'rtacha tannarx saqlangan bo'lsa, uni qaytarish
            return float(product.purchase_price)
    
    # Oxirgi kirib kelgan narx
    last_price = get_last_purchase_price(db, product_id, warehouse_id)
    if last_price > 0:
        return last_price
    
    # Agar oxirgi narx ham yo'q bo'lsa, mahsulotdagi narxni qaytarish
    product = db.query(Product).filter(Product.id == product_id).first()
    if product and product.purchase_price:
        return float(product.purchase_price)
    
    return 0.0
