"""
Ishlab chiqarish uchun minimal ma'lumotlar — omborlar va retseptlar.
Mavjud ma'lumotlarni O'CHIRMAYDI, faqat yo'q bo'lganlarni qo'shadi.
"""
import sys
sys.path.insert(0, ".")

from app.models.database import (
    SessionLocal, Unit, Category, Warehouse, Product,
    Recipe, RecipeItem
)


def seed_production():
    db = SessionLocal()
    try:
        added = []
        
        # 1. O'lchov birligi (kg)
        kg_unit = db.query(Unit).filter(Unit.code == "kg").first()
        if not kg_unit:
            kg_unit = Unit(code="kg", name="Kilogramm")
            db.add(kg_unit)
            db.flush()
            added.append("Unit: kg")
        
        # 2. Kategoriyalar
        xom_cat = db.query(Category).filter(Category.code == "XOM_ASHYO").first()
        if not xom_cat:
            xom_cat = Category(code="XOM_ASHYO", name="Xom ashyo", type="hom_ashyo")
            db.add(xom_cat)
            db.flush()
            added.append("Category: Xom ashyo")
        
        halva_cat = db.query(Category).filter(Category.code == "HALVA").first()
        if not halva_cat:
            halva_cat = Category(code="HALVA", name="Halva", type="tayyor")
            db.add(halva_cat)
            db.flush()
            added.append("Category: Halva")
        
        # 3. Omborlar (ishlab chiqarish uchun)
        wh_codes = {
            "RAW": ("Xom ashyo ombori", "Xom ashyo"),
            "SEMI": ("Yarim tayyor ombori", "Yarim tayyor"),
            "PROD": ("Tayyor mahsulot", "Ishlab chiqarish"),
            "MAIN": ("Asosiy ombor", "Toshkent"),
        }
        for code, (name, addr) in wh_codes.items():
            if not db.query(Warehouse).filter(Warehouse.code == code).first():
                db.add(Warehouse(name=name, code=code, address=addr))
                added.append(f"Warehouse: {name}")
        
        db.commit()
        
        # 4. Xom ashyo mahsulotlar
        shakar = db.query(Product).filter(Product.code == "XA001").first()
        if not shakar:
            shakar = Product(
                name="Shakar", code="XA001", type="hom_ashyo",
                category_id=xom_cat.id if xom_cat else None,
                unit_id=kg_unit.id if kg_unit else None,
                purchase_price=12000, sale_price=0
            )
            db.add(shakar)
            db.flush()
            added.append("Product: Shakar")
        
        kunjut = db.query(Product).filter(Product.code == "XA002").first()
        if not kunjut:
            kunjut = Product(
                name="Kunjut", code="XA002", type="hom_ashyo",
                category_id=xom_cat.id if xom_cat else None,
                unit_id=kg_unit.id if kg_unit else None,
                purchase_price=45000, sale_price=0
            )
            db.add(kunjut)
            db.flush()
            added.append("Product: Kunjut")
        
        # 5. Tayyor mahsulot (halva)
        halva = db.query(Product).filter(Product.code == "H001").first()
        if not halva:
            halva = Product(
                name="Halva oddiy", code="H001", type="tayyor",
                category_id=halva_cat.id if halva_cat else None,
                unit_id=kg_unit.id if kg_unit else None,
                purchase_price=25000, sale_price=35000
            )
            db.add(halva)
            db.flush()
            added.append("Product: Halva oddiy")
        
        db.commit()
        
        # 6. Retseptlar
        raw_wh = db.query(Warehouse).filter(Warehouse.code == "RAW").first()
        semi_wh = db.query(Warehouse).filter(Warehouse.code == "SEMI").first()
        if not semi_wh:
            semi_wh = db.query(Warehouse).filter(Warehouse.code == "PROD").first()
        
        if halva and not db.query(Recipe).filter(Recipe.name == "Halva oddiy").first():
            r1 = Recipe(
                name="Halva oddiy",
                product_id=halva.id,
                output_quantity=1,
                description="Klassik halva retsepti",
                is_active=True,
                default_warehouse_id=raw_wh.id if raw_wh else None,
                default_output_warehouse_id=semi_wh.id if semi_wh else None,
            )
            db.add(r1)
            db.flush()
            if shakar:
                db.add(RecipeItem(recipe_id=r1.id, product_id=shakar.id, quantity=0.5))
            if kunjut:
                db.add(RecipeItem(recipe_id=r1.id, product_id=kunjut.id, quantity=0.4))
            added.append("Recipe: Halva oddiy")
        
        # Mavjud retseptlarga default omborlarni o'rnatish (agar bo'sh bo'lsa)
        for rec in db.query(Recipe).filter(Recipe.is_active == True).all():
            updated = False
            if not rec.default_warehouse_id and raw_wh:
                rec.default_warehouse_id = raw_wh.id
                updated = True
            if not rec.default_output_warehouse_id and semi_wh:
                rec.default_output_warehouse_id = semi_wh.id
                updated = True
            if updated:
                added.append(f"Recipe {rec.name}: default omborlar qo'shildi")
        
        db.commit()
        
        if added:
            print("Qo'shildi:", ", ".join(added))
        else:
            print("Barcha ma'lumotlar allaqachon mavjud.")
        
    except Exception as e:
        db.rollback()
        print(f"Xatolik: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_production()
