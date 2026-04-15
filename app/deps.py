"""
Umumiy dependency lar — get_db, get_current_user, require_auth, require_admin.
Routerlar shu moduldan import qiladi.
"""
from typing import Optional, Any
from fastapi import Depends, Cookie
from sqlalchemy.orm import Session

from app.models.database import get_db, User
from app.utils.auth import get_user_from_token


def _extract_user_id(user_data: Any) -> Optional[int]:
    """
    Token payload turli formatda kelishi mumkin:
    - {"user_id": 1, ...}
    - {"user_id": {"user_id": 1, "username": "...", "role": "..."}}
    - {"id": 1, ...}
    Noto'g'ri bo'lsa None qaytaradi.
    """
    if not user_data:
        return None
    if isinstance(user_data, int):
        return int(user_data)
    if not isinstance(user_data, dict):
        return None
    uid = user_data.get("user_id", None)
    if isinstance(uid, dict):
        uid = uid.get("user_id", None) or uid.get("id", None)
    if uid is None:
        uid = user_data.get("id", None)
    try:
        return int(uid)
    except (ValueError, TypeError):
        return None


def get_current_user(
    session_token: Optional[str] = Cookie(None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Cookie dan foydalanuvchini olish"""
    if not session_token:
        return None
    user_data = get_user_from_token(session_token)
    if not user_data:
        return None
    user_id = _extract_user_id(user_data)
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        return None
    return user


def require_auth(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """Login talab qilish"""
    if not current_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Login talab qilindi")
    return current_user


def require_admin(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """Faqat admin"""
    if not current_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Login talab qilindi")
    if (getattr(current_user, "role", None) or "").strip().lower() != "admin":
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Faqat administrator uchun ruxsat")
    return current_user


def require_admin_or_manager(current_user: Optional[User] = Depends(get_current_user)) -> User:
    """Admin yoki menejer"""
    if not current_user:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Login talab qilindi")
    if (getattr(current_user, "role", None) or "").strip().lower() not in ("admin", "manager", "menejer"):
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Faqat administrator yoki menejer uchun ruxsat")
    return current_user
