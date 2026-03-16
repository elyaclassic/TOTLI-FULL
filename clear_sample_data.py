# ============================================
# TOTLI HOLVA - Namunaviy ma'lumotlarni o'chirish
# ============================================

import os
from app.models.database import (
    engine, SessionLocal, Base,
    User, Category, Unit, Warehouse, Product, CashRegister, Partner, Employee,
    Agent, AgentLocation, Driver, DriverLocation, PartnerLocation,
    Recipe, RecipeItem, Purchase, PurchaseItem, Stock
)

def clear_sample_data():
    """Barcha namunaviy ma'lumotlarni o'chirish (faqat admin qoldiriladi)"""
    
    db = SessionLocal()
    try:
        print("=" * 60)
        print("  NAMUNAVIY MA'LUMOTLARNI O'CHIRISH")
        print("=" * 60)
        print()
        
        # 1. Retseptlar va tarkibi
        recipe_items_count = db.query(RecipeItem).count()
        db.query(RecipeItem).delete()
        print(f"✅ Retsept tarkibi o'chirildi: {recipe_items_count} ta")
        
        recipes_count = db.query(Recipe).count()
        db.query(Recipe).delete()
        print(f"✅ Retseptlar o'chirildi: {recipes_count} ta")
        
        # 2. Tovar kirimi
        purchase_items_count = db.query(PurchaseItem).count()
        db.query(PurchaseItem).delete()
        print(f"✅ Kirim qatorlari o'chirildi: {purchase_items_count} ta")
        
        purchases_count = db.query(Purchase).count()
        db.query(Purchase).delete()
        print(f"✅ Tovar kirimlari o'chirildi: {purchases_count} ta")
        
        # 3. Ombor qoldiqlari
        stocks_count = db.query(Stock).count()
        db.query(Stock).delete()
        print(f"✅ Ombor qoldiqlari o'chirildi: {stocks_count} ta")
        
        # 4. Lokatsiyalar
        partner_loc_count = db.query(PartnerLocation).count()
        db.query(PartnerLocation).delete()
        print(f"✅ Mijoz lokatsiyalari o'chirildi: {partner_loc_count} ta")
        
        driver_loc_count = db.query(DriverLocation).count()
        db.query(DriverLocation).delete()
        print(f"✅ Haydovchi lokatsiyalari o'chirildi: {driver_loc_count} ta")
        
        agent_loc_count = db.query(AgentLocation).count()
        db.query(AgentLocation).delete()
        print(f"✅ Agent lokatsiyalari o'chirildi: {agent_loc_count} ta")
        
        # 5. Haydovchilar
        drivers_count = db.query(Driver).count()
        db.query(Driver).delete()
        print(f"✅ Haydovchilar o'chirildi: {drivers_count} ta")
        
        # 6. Agentlar
        agents_count = db.query(Agent).count()
        db.query(Agent).delete()
        print(f"✅ Agentlar o'chirildi: {agents_count} ta")
        
        # 7. Xodimlar
        employees_count = db.query(Employee).count()
        db.query(Employee).delete()
        print(f"✅ Xodimlar o'chirildi: {employees_count} ta")
        
        # 8. Mahsulotlar
        products_count = db.query(Product).count()
        db.query(Product).delete()
        print(f"✅ Mahsulotlar o'chirildi: {products_count} ta")
        
        # 9. Kategoriyalar
        categories_count = db.query(Category).count()
        db.query(Category).delete()
        print(f"✅ Kategoriyalar o'chirildi: {categories_count} ta")
        
        # 10. O'lchov birliklari
        units_count = db.query(Unit).count()
        db.query(Unit).delete()
        print(f"✅ O'lchov birliklari o'chirildi: {units_count} ta")
        
        # 11. Omborlar
        warehouses_count = db.query(Warehouse).count()
        db.query(Warehouse).delete()
        print(f"✅ Omborlar o'chirildi: {warehouses_count} ta")
        
        # 12. Kassalar
        cash_count = db.query(CashRegister).count()
        db.query(CashRegister).delete()
        print(f"✅ Kassalar o'chirildi: {cash_count} ta")
        
        # 13. Kontragentlar
        partners_count = db.query(Partner).count()
        db.query(Partner).delete()
        print(f"✅ Kontragentlar o'chirildi: {partners_count} ta")
        
        # 14. Foydalanuvchilar (admin qoldiriladi)
        users_count = db.query(User).filter(User.username != "admin").count()
        db.query(User).filter(User.username != "admin").delete()
        print(f"✅ Foydalanuvchilar o'chirildi: {users_count} ta (admin qoldirildi)")
        
        db.commit()
        
        print()
        print("=" * 60)
        print("  ✅ BARCHA NAMUNAVIY MA'LUMOTLAR O'CHIRILDI!")
        print("=" * 60)
        print()
        print("📋 HAQIQIY MA'LUMOTLARNI KIRITING:")
        print()
        print("1️⃣  O'lchov birliklari (kg, dona, litr, ...)")
        print("2️⃣  Kategoriyalar (Halva, Konfet, Xom ashyo, ...)")
        print("3️⃣  Omborlar (Asosiy ombor, Tayyor mahsulot, ...)")
        print("4️⃣  Kassalar (Asosiy kassa, ...)")
        print("5️⃣  Mahsulotlar (Halva, Shakar, Kunjut, ...)")
        print("6️⃣  Kontragentlar (Mijozlar, Yetkazuvchilar)")
        print("7️⃣  Xodimlar")
        print("8️⃣  Agentlar")
        print("9️⃣  Haydovchilar")
        print("🔟 Retseptlar")
        print()
        _pwd = os.getenv("TEST_ADMIN_PASSWORD", "admin123")
        print("💡 Admin foydalanuvchi saqlab qolindi:")
        print("   Username: admin")
        print("   Password:", _pwd)
        print()
        
    except Exception as e:
        db.rollback()
        print(f"❌ Xatolik: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    clear_sample_data()
