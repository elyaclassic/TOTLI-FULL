"""Server-side jadval saralash uchun helper.

URL `?sort=col&order=asc|desc` parametrlarini parse qiladi va whitelist orqali
SQL injection'dan himoya qiladi.

Misol:
    sort_col, sort_dir = parse_sort(
        sort, order,
        allowed={"name": Partner.name, "phone": Partner.phone, "balance": Partner.balance},
        default_col=Partner.name,
        default_dir="asc",
    )
    query = query.order_by(sort_col.asc() if sort_dir == "asc" else sort_col.desc())
"""
from typing import Optional


def parse_sort(
    sort: Optional[str],
    order: Optional[str],
    allowed: dict,
    default_col,
    default_dir: str = "asc",
):
    """Sort parametrlarini validate qilib (column, direction) qaytaradi.

    Args:
        sort: URL'dan kelgan ustun nomi (string)
        order: URL'dan "asc" yoki "desc"
        allowed: {column_name: SQLAlchemy_column} mapping (whitelist)
        default_col: agar sort bo'lmasa shu ustun
        default_dir: "asc" yoki "desc"

    Returns:
        (column, direction_string) tuple
    """
    col = allowed.get((sort or "").strip().lower()) if sort else None
    if col is None:
        col = default_col
    direction = (order or "").strip().lower()
    if direction not in ("asc", "desc"):
        direction = default_dir
    return col, direction


def apply_sort(query, sort_col, sort_dir: str):
    """Query'ga ORDER BY qo'shadi."""
    if sort_dir == "desc":
        return query.order_by(sort_col.desc())
    return query.order_by(sort_col.asc())


def sort_query_string(current_sort: str, current_order: str, new_sort: str) -> str:
    """Sortable TH link uchun query string qaytaradi.

    Agar current_sort == new_sort bo'lsa, order'ni almashinadi (toggle).
    Aks holda new_sort bilan asc.

    Returns: "sort=name&order=asc"
    """
    if current_sort == new_sort:
        new_order = "desc" if current_order == "asc" else "asc"
    else:
        new_order = "asc"
    return f"sort={new_sort}&order={new_order}"
