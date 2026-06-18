"""
Loyiha uchun umumiy obyektlar — template, keyinchalik config.
"""
import json
from datetime import datetime, date
from fastapi.templating import Jinja2Templates
import starlette as _starlette

# Starlette versiyasi: 0.29+ da TemplateResponse signature (request, name, context) ga
# o'zgardi (eski (name, context) 0.36+ da olib tashlandi). Kod hamma joyda eski usulda
# `TemplateResponse("x.html", {...})` yozadi — quyidagi compat ikkala versiyada ham ishlaydi
# (eski starlette'da asl xatti-harakat, yangisida eski signature -> yangiga avtomatik moslanadi).
_st_ver = tuple(int(p) for p in _starlette.__version__.split(".")[:2] if p.isdigit())


class _CompatJinja2Templates(Jinja2Templates):
    def TemplateResponse(self, *args, **kwargs):
        if _st_ver >= (0, 29) and args and isinstance(args[0], str):
            name = args[0]
            context = args[1] if len(args) > 1 else (kwargs.pop("context", None) or {})
            kwargs.pop("context", None)
            request = context.get("request")
            return super().TemplateResponse(request, name, context, **kwargs)
        return super().TemplateResponse(*args, **kwargs)


templates = _CompatJinja2Templates(directory="app/templates")
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
    """Jinja filtri: obyektni JSON ga aylantirish. </script> ni escape qiladi (XSS)."""
    from markupsafe import Markup
    return Markup(json.dumps(val).replace("</", "<\\/"))


templates.env.filters["tojson"] = _tojson


# Reservation override rol-tekshiruvi — markazlashtirilgan (stock_reservation.OVERRIDE_ROLES).
# Template'lar `{% if user_can_override(current_user) %}` deb ishlatadi (5 joyda rol ro'yxati DRY).
from app.services.stock_reservation import user_can_override as _user_can_override
templates.env.globals["user_can_override"] = _user_can_override
