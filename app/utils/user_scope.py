"""
Foydalanuvchi ko'ruvchi ombor va bo'limlar: admin/raxbar barcha, qolganlar faqat sozlamada belgilangan.
"""
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import select
from sqlalchemy.exc import OperationalError, ProgrammingError

from app.models.database import User, Warehouse, Department, user_warehouses, user_departments


def _get_warehouse_ids_from_tables(db: Session, user_id: int):
    """user_warehouses va user_departments jadvallaridan ombor id larini olish. Jadval yo'q bo'lsa bo'sh."""
    ids = []
    try:
        rows = db.execute(select(user_warehouses.c.warehouse_id).where(user_warehouses.c.user_id == user_id)).fetchall()
        for r in rows:
            if r[0] and r[0] not in ids:
                ids.append(r[0])
    except (OperationalError, ProgrammingError):
        pass
    u = db.query(User).filter(User.id == user_id).first()
    if u and getattr(u, "warehouse_id", None) and u.warehouse_id not in ids:
        ids.append(u.warehouse_id)
    try:
        dept_rows = db.execute(select(user_departments.c.department_id).where(user_departments.c.user_id == user_id)).fetchall()
        dept_ids = [r[0] for r in dept_rows if r[0]]
    except (OperationalError, ProgrammingError):
        dept_ids = []
    if u and getattr(u, "department_id", None) and (not dept_ids or u.department_id not in dept_ids):
        dept_ids.append(u.department_id)
    if dept_ids:
        whs = db.query(Warehouse).filter(
            Warehouse.department_id.in_(dept_ids),
            Warehouse.is_active == True,
        ).all()
        for w in whs:
            if w.id not in ids:
                ids.append(w.id)
    return ids


def get_warehouses_for_user(db: Session, user) -> list:
    """
    Foydalanuvchi uchun ko'rinadigan omborlar ro'yxati.
    Admin, raxbar, rahbar: barcha omborlar.
    Boshqalar: faqat user_warehouses va user_departments (va warehouse_id, department_id) orqali belgilangan omborlar.
    """
    if not user:
        return []
    role = (getattr(user, "role", None) or "").strip().lower()
    # Faqat admin, rahbar, raxbar barcha omborlarni ko'radi — manager hech qachon barchani ko'rmaydi
    if role in ("admin", "rahbar", "raxbar"):
        return db.query(Warehouse).filter(Warehouse.is_active == True).order_by(Warehouse.name).all()

    user_id = getattr(user, "id", None)
    if not user_id:
        return []
    ids = _get_warehouse_ids_from_tables(db, user_id)

    if not ids:
        return []
    return db.query(Warehouse).filter(Warehouse.id.in_(ids), Warehouse.is_active == True).order_by(Warehouse.name).all()


def get_departments_for_user(db: Session, user) -> list:
    """
    Foydalanuvchi uchun ko'rinadigan bo'limlar ro'yxati.
    Admin, raxbar, rahbar: barcha bo'limlar.
    Boshqalar: faqat foydalanuvchi sozlamasida belgilangan bo'limlar (departments_list, department_id).
    Agar hech narsa belgilanmagan bo'lsa — barcha.
    """
    if not user:
        return []
    role = (getattr(user, "role", None) or "").strip().lower()
    if role in ("admin", "rahbar", "raxbar"):
        return db.query(Department).filter(Department.is_active == True).order_by(Department.name).all()
    u = db.query(User).options(joinedload(User.departments_list)).filter(User.id == user.id).first()
    if not u:
        return []
    ids = [d.id for d in (getattr(u, "departments_list", None) or []) if d and getattr(d, "is_active", True)]
    if getattr(u, "department_id", None) and u.department_id not in ids:
        ids.append(u.department_id)
    # Hech narsa belgilanmagan bo'lsa — bo'sh ro'yxat
    if not ids:
        return []
    return db.query(Department).filter(Department.id.in_(ids), Department.is_active == True).order_by(Department.name).all()
