"""
Loyiha uchun umumiy obyektlar — template, keyinchalik config.
"""
import json
from datetime import datetime, date
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
templates.env.globals["getattr"] = getattr


def _fmt_date(value, fmt="%d.%m.%Y"):
    """Jinja filtri: sana formatlash (ISO string yoki datetime -> DD.MM.YYYY).
    Ishlatish: {{ date_from | fmt_date }} yoki {{ obj.created_at | fmt_date('%d.%m.%Y %H:%M') }}
    """
    if not value:
        return ""
    if isinstance(value, str):
        # ISO format stringni parse qilish
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                value = datetime.strptime(value.strip()[:19], pattern)
                break
            except (ValueError, TypeError):
                continue
        else:
            return str(value)
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return str(value)


templates.env.filters["fmt_date"] = _fmt_date


def _csrf_token_from_request(request):
    """Jinja uchun: request.state dan csrf_token olish (getattr ishlatilmasin)."""
    if request is None:
        return ""
    return getattr(request.state, "csrf_token", "") or ""


templates.env.globals["csrf_token_from_request"] = _csrf_token_from_request


def _tojson(val):
    """Jinja filtri: obyektni JSON qatoriga aylantirish (transfer_form, movement va b.)."""
    from markupsafe import Markup
    return Markup(json.dumps(val))


templates.env.filters["tojson"] = _tojson
