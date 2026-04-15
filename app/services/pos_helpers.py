"""POS (sotuv oynasi) uchun yordamchi funksiyalar: ombor, narx turi, mijoz, kassa."""
from typing import Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from app.models.database import (
    User,
    Warehouse,
    PriceType,
    Partner,
    CashRegister,
)


def get_sales_warehouse(db: Session):
    """Umumiy fallback: code/nomida 'sotuv' yoki birinchi ombor (admin tekshiruvi uchun)."""
    wh = db.query(Warehouse).filter(
        Warehouse.is_active == True,
        or_(Warehouse.code.ilike("%sotuv%"), Warehouse.name.ilike("%sotuv%"))
    ).first()
    if wh:
        return wh
    return db.query(Warehouse).filter(Warehouse.is_active == True).order_by(Warehouse.id).first()


def get_pos_price_type(db: Session):
    """POS (chakana savdo) uchun narx turi: code='chakana' bo'lgani, yo'q bo'lsa birinchi faol narx turi."""
    pt = (
        db.query(PriceType)
        .filter(PriceType.is_active == True, PriceType.code.ilike("chakana"))
        .order_by(PriceType.id)
        .first()
    )
    if pt:
        return pt
    return db.query(PriceType).filter(PriceType.is_active == True).order_by(PriceType.id).first()


def get_pos_warehouses_for_user(db: Session, current_user: User):
    """Foydalanuvchiga tegishli omborlar ro'yxati (POS tepada ko'rsatish va tanlash uchun)."""
    if not current_user:
        return []
    role = (current_user.role or "").strip()
    if role == "admin" or role == "manager":
        return db.query(Warehouse).filter(Warehouse.is_active == True).order_by(Warehouse.name).all()
    if role != "sotuvchi":
        return []
    user = db.query(User).options(
        joinedload(User.warehouses_list),
        joinedload(User.departments_list),
    ).filter(User.id == current_user.id).first()
    if not user:
        return []
    seen = set()
    result = []
    for w in (user.warehouses_list or []):
        if w and w.id not in seen and (getattr(w, "is_active", True)):
            seen.add(w.id)
            result.append(w)
    for dept in (user.departments_list or []):
        if not dept:
            continue
        for w in db.query(Warehouse).filter(
            Warehouse.department_id == dept.id,
            Warehouse.is_active == True
        ).order_by(Warehouse.name).all():
            if w.id not in seen:
                seen.add(w.id)
                result.append(w)
    if user.warehouse_id and user.warehouse_id not in seen:
        wh = db.query(Warehouse).filter(Warehouse.id == user.warehouse_id, Warehouse.is_active == True).first()
        if wh:
            seen.add(wh.id)
            result.append(wh)
    if user.department_id and user.department_id not in (getattr(d, "id", None) for d in (user.departments_list or [])):
        for w in db.query(Warehouse).filter(
            Warehouse.department_id == user.department_id,
            Warehouse.is_active == True
        ).order_by(Warehouse.name).all():
            if w.id not in seen:
                seen.add(w.id)
                result.append(w)
    return result


def get_pos_warehouse_for_user(db: Session, current_user: User):
    """Foydalanuvchi uchun default ombor: avval user.warehouse_id, keyin fallback."""
    if not current_user:
        return None
    role = (current_user.role or "").strip()
    # Avval foydalanuvchiga biriktirilgan omborni qaytarish
    if current_user.warehouse_id:
        wh = db.query(Warehouse).filter(
            Warehouse.id == current_user.warehouse_id,
            Warehouse.is_active == True
        ).first()
        if wh:
            return wh
    if role == "admin" or role == "manager":
        return get_sales_warehouse(db)
    if role != "sotuvchi":
        return None
    user = db.query(User).options(
        joinedload(User.warehouses_list),
        joinedload(User.departments_list),
    ).filter(User.id == current_user.id).first()
    if not user:
        return None
    if user.warehouses_list:
        return user.warehouses_list[0]
    if user.departments_list:
        dept = user.departments_list[0]
        wh = db.query(Warehouse).filter(
            Warehouse.department_id == dept.id,
            Warehouse.is_active == True
        ).order_by(Warehouse.id).first()
        if wh:
            return wh
    if user.warehouse_id:
        wh = db.query(Warehouse).filter(
            Warehouse.id == user.warehouse_id,
            Warehouse.is_active == True
        ).first()
        if wh:
            return wh
    if user.department_id:
        wh = db.query(Warehouse).filter(
            Warehouse.department_id == user.department_id,
            Warehouse.is_active == True
        ).order_by(Warehouse.id).first()
        if wh:
            return wh
    return None


def get_pos_partner(db: Session):
    """POS uchun default mijoz (Chakana xaridor)."""
    p = db.query(Partner).filter(Partner.is_active == True, or_(Partner.code == "chakana", Partner.code == "pos")).first()
    if p:
        return p
    return db.query(Partner).filter(Partner.is_active == True).order_by(Partner.id).first()


def get_pos_cash_register(
    db: Session,
    payment_type: str,
    department_id: Optional[int] = None,
    current_user: Optional[User] = None,
):
    """POS to'lov: savdo qaysi bo'limdan bo'lsa o'sha bo'lim kassasiga.
    Sotuvchi uchun — faqat unga biriktirilgan kassalar ichidan tanlanadi."""
    payment_type = (payment_type or "").strip().lower()
    key = payment_type if payment_type in ("naqd", "plastik", "click", "terminal") else "plastik"
    q = db.query(CashRegister).filter(CashRegister.is_active == True)
    if department_id:
        q = q.filter(CashRegister.department_id == department_id)
    active = q.order_by(CashRegister.id).all()
    if not active and department_id:
        active = db.query(CashRegister).filter(CashRegister.is_active == True).order_by(CashRegister.id).all()
    if not active:
        return None

    # Sotuvchi uchun cheklov — faqat biriktirilgan kassalar
    role = ((current_user.role if current_user else "") or "").strip()
    if role == "sotuvchi" and current_user is not None:
        user = db.query(User).options(joinedload(User.cash_registers_list)).filter(User.id == current_user.id).first()
        assigned_ids = {c.id for c in (getattr(user, "cash_registers_list", None) or []) if c}
        if assigned_ids:
            filtered = [c for c in active if c.id in assigned_ids]
            if filtered:
                active = filtered
            # else: bo'sh natija — pastdagi mantiq active dan tanlaydi (fallback)

    for c in active:
        if getattr(c, "payment_type", None) and (c.payment_type or "").strip().lower() == key:
            return c
    for c in active:
        if c.name and key in (c.name or "").lower():
            return c
    if key in ("click", "terminal"):
        for c in active:
            if getattr(c, "payment_type", None) and (c.payment_type or "").strip().lower() == "plastik":
                return c
        for c in active:
            if c.name and "plastik" in (c.name or "").lower():
                return c
    return active[0]
