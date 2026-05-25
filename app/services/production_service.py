"""
Production service — ishlab chiqarish operatsiyalari uchun atomik wrapper'lar.

Tier C3: production.py dagi delete logikasini markazlashtirish.
"""
from sqlalchemy.orm import Session

from datetime import datetime as _dt

from app.models.database import (
    Production, Recipe, RecipeItem, RecipeStage,
    Stock, StockMovement, Order,
)
from app.services.document_service import DocumentError


def delete_production_atomic(db: Session, production: Production) -> dict:
    """
    Ishlab chiqarish buyurtmasini atomik o'chirish.

    1. Tasdiqlangan (completed) buyurtma rad etiladi — avval revert kerak
    2. Stock movementlar teskari qaytariladi (stock tiklanadi)
    3. Production o'chiriladi
    4. Linked Order (agar waiting_production'da bo'lsa va boshqa aktiv PR yo'q) → confirmed'ga qaytariladi
    5. Atomik: xato bo'lsa rollback
    """
    if production.status == "completed":
        raise DocumentError(
            "Tasdiqlangan buyurtmani o'chirish uchun avval «Tasdiqni bekor qilish» bosing."
        )

    # Drift xavfsizligi: net stok ta'siri ≠ 0 movementlar bor bo'lsa rad etish.
    # Reverted completed da net=0 (consumption + output + revert pair) — xavfsiz.
    movements = db.query(StockMovement).filter(
        StockMovement.document_type == "Production",
        StockMovement.document_id == production.id,
    ).all()
    if movements:
        net = sum(float(m.quantity_change or 0) for m in movements)
        if abs(net) > 1e-6:
            raise DocumentError(
                f"Bu buyurtmaning stock harakatlari net={net:+.2f} (≠ 0). "
                f"Avval «Tasdiqni bekor qilish» orqali revert qiling, keyin o'chiring."
            )

    try:
        # Net=0 movementlarni o'chirish xavfsiz (revert juftligi bilan teng)
        for m in movements:
            db.delete(m)

        # Linked order'ni waiting_production'dan qaytarish (orphan oldini olish)
        order_id = production.order_id
        pr_number = production.number
        db.delete(production)
        if order_id:
            _restore_orphan_order(db, order_id, deleted_pr_number=pr_number)

        db.commit()
        return {"ok": True, "number": pr_number}
    except DocumentError:
        raise
    except Exception:
        db.rollback()
        raise


def _restore_orphan_order(db: Session, order_id: int, deleted_pr_number: str) -> None:
    """Production o'chirilganda, agar bog'liq Order waiting_production'da bo'lsa va
    boshqa aktiv Production qolmagan bo'lsa — orderni confirmed'ga qaytarish.

    Aktiv = status != 'cancelled' (cancelled PR'lar hisobga olinmaydi).
    Admin keyin orderni qayta dispatch qilishi yoki cancel qilishi mumkin.
    """
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order or order.status != "waiting_production":
        return

    other_active = db.query(Production).filter(
        Production.order_id == order_id,
        Production.status != "cancelled",
    ).first()
    if other_active:
        return  # Boshqa aktiv PR bor, orderni o'zgartirmaymiz

    note_extra = (
        f"\n\n[AUTO-RESTORE {_dt.now().strftime('%Y-%m-%d %H:%M')}]: "
        f"{deleted_pr_number} o'chirildi → waiting_production'dan confirmed'ga qaytarildi. "
        f"Qayta dispatch qiling yoki cancel qiling."
    )
    order.status = "confirmed"
    order.pending_driver_id = None
    order.delivery_date = None
    order.note = (order.note or "") + note_extra


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
