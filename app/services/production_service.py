"""
Production service — ishlab chiqarish operatsiyalari uchun atomik wrapper'lar.

Tier C3: production.py dagi delete logikasini markazlashtirish.
"""
from sqlalchemy.orm import Session

from app.models.database import (
    Production, Recipe, RecipeItem, RecipeStage,
    Stock, StockMovement,
)
from app.services.document_service import DocumentError


def delete_production_atomic(db: Session, production: Production) -> dict:
    """
    Ishlab chiqarish buyurtmasini atomik o'chirish.

    1. Tasdiqlangan (completed) buyurtma rad etiladi — avval revert kerak
    2. Stock movementlar teskari qaytariladi (stock tiklanadi)
    3. Production o'chiriladi
    4. Atomik: xato bo'lsa rollback
    """
    if production.status == "completed":
        raise DocumentError(
            "Tasdiqlangan buyurtmani o'chirish uchun avval «Tasdiqni bekor qilish» bosing."
        )

    try:
        # Stock movementlarni teskari qaytarish
        movements = db.query(StockMovement).filter(
            StockMovement.document_type == "Production",
            StockMovement.document_id == production.id,
        ).all()
        for m in movements:
            # Draft/cancelled buyurtma uchun orphan movements bo'lsa — faqat o'chirish.
            # stock.quantity to'g'ridan-to'g'ri o'zgartirish TAQIQLANADI.
            db.delete(m)

        db.delete(production)
        db.commit()
        return {"ok": True, "number": production.number}
    except DocumentError:
        raise
    except Exception:
        db.rollback()
        raise


def delete_recipe_atomic(db: Session, recipe: Recipe) -> dict:
    """
    Retseptni atomik o'chirish yoki faolsizlantirish.

    1. Ishlab chiqarishda ishlatilgan bo'lsa — faolsizlantirish (is_active=False)
    2. Ishlatilmagan bo'lsa — cascade o'chirish (RecipeItem + RecipeStage + Recipe)
    3. Atomik: xato bo'lsa rollback

    Returns: {"ok": True, "action": "deactivated"|"deleted"}
    """
    try:
        used = db.query(Production).filter(Production.recipe_id == recipe.id).first()
        if used:
            recipe.is_active = False
            db.commit()
            return {"ok": True, "action": "deactivated"}

        db.query(RecipeItem).filter(RecipeItem.recipe_id == recipe.id).delete()
        db.query(RecipeStage).filter(RecipeStage.recipe_id == recipe.id).delete()
        db.delete(recipe)
        db.commit()
        return {"ok": True, "action": "deleted"}
    except Exception:
        db.rollback()
        raise
