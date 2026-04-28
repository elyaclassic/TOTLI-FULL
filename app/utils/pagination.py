from typing import Any
from urllib.parse import urlencode


def paginate(query, page: int = 1, per_page: int = 50) -> dict:
    page = max(1, int(page or 1))
    total_count = query.count()
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    page = min(page, total_pages)
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total_count": total_count,
        "total_pages": total_pages,
        "items_count": len(items),
    }


def pagination_query_string(params: dict) -> str:
    filtered = {k: v for k, v in params.items() if v and k != "page"}
    return ("?" + urlencode(filtered)) if filtered else "?"
