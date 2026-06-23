# Universal Logo (Brending) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin paneldan rasm yuklash orqali tizim logosini (asosiy + dumaloq) almashtirish.

**Architecture:** Yangi `AppSetting` key-value ORM jadvali logo fayl nomlarini saqlaydi. `branding_service` DB'dan o'qib, fayl mavjudligini tekshirib, yo'q bo'lsa standartga qaytadi (fallback). Jinja global funksiya orqali barcha templatelarga avtomatik uzatiladi — mavjud route'larga tegilmaydi. Yangi `/admin/branding` route'lari rasm yuklash/qaytarishni boshqaradi (faqat admin).

**Tech Stack:** FastAPI, SQLAlchemy (SQLite), Jinja2, Pillow (rasm validatsiya), pytest.

## Global Constraints

- Faqat **admin** roli branding route'lariga kira oladi (`require_admin`, `app/deps.py:65`).
- Rasm validatsiya `products.py::_validate_and_save_product_image` uslubida: kengaytma whitelist + hajm limiti + Pillow `verify()`.
- Ruxsat etilgan formatlar: `png, jpg, jpeg, webp`. Hajm limiti: **2 MB**.
- Yuklangan fayllar: `app/static/images/branding/`. Eski `logo.png`/`logo_circle.png` ga TEGILMAYDI (fallback).
- Fayl nomiga timestamp qo'shiladi (cache-busting).
- CSRF token barcha POST formalarida majburiy (`csrf_token_from_request`).
- O'zbekcha matn (sof lotin, kirill aralashtirilmaydi).
- Testlar `tests/` da, in-memory SQLite (`db` fixture, `conftest.py`).
- SQLite raw SQL'da `isoformat()`/`localtime` ISHLATILMAYDI.

---

### Task 1: AppSetting modeli + branding_service (sof resolve funksiyasi)

**Files:**
- Modify: `app/models/database.py` (ORM model qo'shish — `AppSetting`)
- Create: `app/services/branding_service.py`
- Test: `tests/test_branding.py`

**Interfaces:**
- Produces:
  - `AppSetting` ORM model: `key: str` (PK), `value: str|None`, `updated_at: datetime`
  - `branding_service.BRANDING_KEYS = ("logo_main", "logo_circle")`
  - `branding_service.DEFAULTS: dict[str, str]`
  - `branding_service.resolve_branding(db) -> dict` — `{"logo_main": url, "logo_circle": url}`

- [ ] **Step 1: Write the failing test**

`tests/test_branding.py`:
```python
"""Universal logo (branding) testlari."""
import os


def test_resolve_branding_defaults_when_empty(db):
    """AppSetting bo'sh -> standart logo yo'llari qaytadi."""
    from app.services.branding_service import resolve_branding, DEFAULTS

    result = resolve_branding(db)

    assert result["logo_main"] == DEFAULTS["logo_main"]
    assert result["logo_circle"] == DEFAULTS["logo_circle"]


def test_resolve_branding_ignores_missing_file(db):
    """AppSetting'da yozuv bor, lekin fayl jismonan yo'q -> standartga qaytadi."""
    from app.models.database import AppSetting
    from app.services.branding_service import resolve_branding, DEFAULTS

    db.add(AppSetting(key="logo_main", value="nonexistent_file_xyz.png"))
    db.commit()

    result = resolve_branding(db)

    assert result["logo_main"] == DEFAULTS["logo_main"]


def test_resolve_branding_uses_existing_file(db, tmp_path, monkeypatch):
    """AppSetting'da yozuv bor va fayl mavjud -> yangi yo'l qaytadi."""
    from app.models.database import AppSetting
    from app.services import branding_service

    # Soxta branding papkasi yaratamiz
    fake_dir = tmp_path / "branding"
    fake_dir.mkdir()
    (fake_dir / "logo_main_123.png").write_bytes(b"PNGDATA")
    monkeypatch.setattr(branding_service, "BRANDING_DIR", str(fake_dir))

    db.add(AppSetting(key="logo_main", value="logo_main_123.png"))
    db.commit()

    result = branding_service.resolve_branding(db)

    assert result["logo_main"] == "/static/images/branding/logo_main_123.png"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_branding.py -v`
Expected: FAIL — `ImportError: cannot import name 'AppSetting'` / `No module named 'app.services.branding_service'`

- [ ] **Step 3: Add AppSetting ORM model**

`app/models/database.py` ichida (boshqa model class'lar yonida, masalan fayl oxiriga yaqin model bloklari orasiga) qo'shing. `Base`, `Column`, `String`, `Text`, `DateTime`, `datetime` allaqachon import qilingan:
```python
class AppSetting(Base):
    """Universal key-value sozlamalar (logo, kelajakda kompaniya nomi/rang va h.k.)."""
    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

> Eslatma: `init_db()` dagi `Base.metadata.create_all(bind=engine)` yangi jadvalni avtomatik yaratadi (mavjud jadvalларga tegmaydi). Alohida `ensure_*` funksiya kerak emas.

- [ ] **Step 4: Create branding_service with resolve_branding**

`app/services/branding_service.py`:
```python
"""Brending (logo) sozlamalari servisi.

resolve_branding(db) -> sof funksiya, DB'dan logo yo'llarini o'qiydi, fayl
mavjudligini tekshiradi, yo'q bo'lsa standartga qaytadi.
get_branding_cached() -> runtime cache wrapper (Jinja global ishlatadi).
"""
import os

BRANDING_KEYS = ("logo_main", "logo_circle")

DEFAULTS = {
    "logo_main": "/static/images/logo.png",
    "logo_circle": "/static/images/logo_circle.png",
}

BRANDING_DIR = os.path.join("app", "static", "images", "branding")


def resolve_branding(db) -> dict:
    """DB'dan logo yo'llarini o'qib qaytaradi. Fayl yo'q/yozuv yo'q -> standart."""
    result = dict(DEFAULTS)
    try:
        from app.models.database import AppSetting
        rows = (
            db.query(AppSetting)
            .filter(AppSetting.key.in_(BRANDING_KEYS))
            .all()
        )
        for row in rows:
            if not row.value:
                continue
            disk_path = os.path.join(BRANDING_DIR, row.value)
            if os.path.isfile(disk_path):
                result[row.key] = f"/static/images/branding/{row.value}"
    except Exception:
        # Har qanday DB xatosida standart logo — hech qachon buzilmaydi
        pass
    return result
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_branding.py -v`
Expected: PASS (3 ta test)

- [ ] **Step 6: Commit**

```bash
git add app/models/database.py app/services/branding_service.py tests/test_branding.py
git commit -m "feat(branding): AppSetting modeli + resolve_branding fallback servisi

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Runtime cache + Jinja global funksiya

**Files:**
- Modify: `app/services/branding_service.py` (cache wrapper qo'shish)
- Modify: `app/core.py` (Jinja global registratsiya)
- Test: `tests/test_branding.py` (cache invalidatsiya testi)

**Interfaces:**
- Consumes: `resolve_branding(db)` (Task 1)
- Produces:
  - `branding_service.get_branding_cached() -> dict` — argumentsiz, runtime cache
  - `branding_service.invalidate_branding_cache() -> None`
  - Jinja global: `branding()` — templatelarda `{{ branding().logo_circle }}`

- [ ] **Step 1: Write the failing test**

`tests/test_branding.py` oxiriga qo'shing:
```python
def test_cache_invalidation(monkeypatch):
    """Cache to'ldiriladi, invalidate'dan keyin qayta yuklanadi."""
    from app.services import branding_service

    calls = {"n": 0}

    def fake_load():
        calls["n"] += 1
        return {"logo_main": f"/x{calls['n']}.png", "logo_circle": "/c.png"}

    monkeypatch.setattr(branding_service, "_load_branding", fake_load)
    branding_service.invalidate_branding_cache()

    first = branding_service.get_branding_cached()
    second = branding_service.get_branding_cached()
    assert first == second           # cache — qayta yuklanmaydi
    assert calls["n"] == 1

    branding_service.invalidate_branding_cache()
    third = branding_service.get_branding_cached()
    assert calls["n"] == 2           # invalidate'dan keyin qayta yuklandi
    assert third != first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_branding.py::test_cache_invalidation -v`
Expected: FAIL — `AttributeError: ... has no attribute '_load_branding'`

- [ ] **Step 3: Add cache wrapper to branding_service**

`app/services/branding_service.py` oxiriga qo'shing:
```python
_cache = None


def _load_branding() -> dict:
    """DB session ochib resolve_branding'ni chaqiradi (runtime)."""
    from app.models.database import SessionLocal
    db = SessionLocal()
    try:
        return resolve_branding(db)
    finally:
        db.close()


def get_branding_cached() -> dict:
    """Runtime cache — Jinja global shuni ishlatadi. Kam o'zgaradi."""
    global _cache
    if _cache is None:
        _cache = _load_branding()
    return _cache


def invalidate_branding_cache() -> None:
    """Logo yangilanganda/qaytarilganda chaqiriladi."""
    global _cache
    _cache = None
```

- [ ] **Step 4: Register Jinja global in core.py**

`app/core.py` oxiriga qo'shing (boshqa `templates.env.globals[...]` yonida):
```python
# Brending (logo) — barcha templatelarga avtomatik. Runtime cache, DB session kerak emas.
from app.services.branding_service import get_branding_cached as _get_branding
templates.env.globals["branding"] = _get_branding
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_branding.py -v`
Expected: PASS (4 ta test). Import xatosi yo'qligini tasdiqlash uchun: `python -c "import app.core"` — xatosiz.

- [ ] **Step 6: Commit**

```bash
git add app/services/branding_service.py app/core.py tests/test_branding.py
git commit -m "feat(branding): runtime cache + Jinja global branding() funksiyasi

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: branding.py route — yuklash/qaytarish/sahifa backend

**Files:**
- Create: `app/routes/branding.py`
- Modify: `main.py` (router include)
- Test: `tests/test_branding.py` (route testlari)

**Interfaces:**
- Consumes: `require_admin` (`app/deps.py`), `get_db` (`app/models.database`), `AppSetting`, `invalidate_branding_cache`, `templates` (`app.core`)
- Produces (HTTP):
  - `GET  /admin/branding` — sahifa (HTML)
  - `POST /admin/branding/upload` — form: `slot` (`logo_main`|`logo_circle`), `image` (UploadFile) -> redirect
  - `POST /admin/branding/reset` — form: `slot` -> redirect (standartga qaytadi)
- Produces (Python): `branding_service.save_branding_image(slot, image_bytes, ext) -> str` (saqlangan fayl nomi)

- [ ] **Step 1: Write the failing test**

`tests/test_branding.py` oxiriga qo'shing:
```python
def test_save_branding_image(tmp_path, monkeypatch):
    """save_branding_image faylni timestamp nomi bilan saqlaydi."""
    from app.services import branding_service

    fake_dir = tmp_path / "branding"
    monkeypatch.setattr(branding_service, "BRANDING_DIR", str(fake_dir))

    fname = branding_service.save_branding_image("logo_main", b"PNGDATA", "png")

    assert fname.startswith("logo_main_")
    assert fname.endswith(".png")
    assert (fake_dir / fname).is_file()


def test_upload_requires_admin(client, db, agent_user):
    """Admin bo'lmagan foydalanuvchi yuklay olmaydi."""
    from app.models.database import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: agent_user
    try:
        resp = client.post(
            "/admin/branding/upload",
            data={"slot": "logo_main"},
            files={"image": ("x.png", b"x", "image/png")},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 401, 403)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
```

> Eslatma: `get_current_user` import yo'lini loyihadagi haqiqiy joydan tasdiqlang (`app/deps.py` yoki `app/models/database.py`). Agar `app.deps` da bo'lsa, `from app.deps import get_current_user`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_branding.py::test_save_branding_image -v`
Expected: FAIL — `AttributeError: ... has no attribute 'save_branding_image'`

- [ ] **Step 3: Add save_branding_image to branding_service**

`app/services/branding_service.py` ga qo'shing (yuqorida, `_cache` dan oldin). `import time` ni fayl tepasidagi importlarga qo'shing:
```python
import time

ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp"}
MAX_SIZE_BYTES = 2 * 1024 * 1024  # 2 MB


def save_branding_image(slot: str, contents: bytes, ext: str) -> str:
    """Rasmni branding papkasiga timestamp nomi bilan saqlaydi. Fayl nomini qaytaradi."""
    os.makedirs(BRANDING_DIR, exist_ok=True)
    ts = int(time.time())
    filename = f"{slot}_{ts}.{ext}"
    with open(os.path.join(BRANDING_DIR, filename), "wb") as f:
        f.write(contents)
    return filename


def cleanup_old_branding(slot: str, keep: str) -> None:
    """slot prefiksli, keep'dan boshqa eski fayllarni o'chiradi."""
    try:
        if not os.path.isdir(BRANDING_DIR):
            return
        for name in os.listdir(BRANDING_DIR):
            if name.startswith(f"{slot}_") and name != keep:
                try:
                    os.remove(os.path.join(BRANDING_DIR, name))
                except OSError:
                    pass
    except Exception:
        pass
```

- [ ] **Step 4: Create branding.py route**

`app/routes/branding.py`:
```python
"""Brending (logo) sozlamalari — admin paneldan logo yuklash/qaytarish."""
import io

from fastapi import APIRouter, Request, Depends, Form, File, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.deps import get_db, require_admin
from app.models.database import AppSetting, User
from app.services import branding_service

router = APIRouter(tags=["branding"])

_SLOTS = {"logo_main", "logo_circle"}


def _upsert_setting(db: Session, key: str, value):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()


@router.get("/admin/branding")
async def branding_page(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    current = branding_service.resolve_branding(db)
    return templates.TemplateResponse(
        "admin/branding.html",
        {
            "request": request,
            "page_title": "Brending sozlamalari",
            "current_user": current_user,
            "current": current,
            "msg": request.query_params.get("msg"),
            "err": request.query_params.get("err"),
        },
    )


@router.post("/admin/branding/upload")
async def branding_upload(
    slot: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if slot not in _SLOTS:
        return RedirectResponse(url="/admin/branding?err=slot", status_code=303)

    filename = (image.filename or "").strip()
    if "." not in filename:
        return RedirectResponse(url="/admin/branding?err=ext", status_code=303)
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in branding_service.ALLOWED_EXTS:
        return RedirectResponse(url="/admin/branding?err=ext", status_code=303)

    contents = await image.read()
    if not contents or len(contents) > branding_service.MAX_SIZE_BYTES:
        return RedirectResponse(url="/admin/branding?err=size", status_code=303)

    # Pillow bilan haqiqiy rasm ekanligini tasdiqlash
    try:
        from PIL import Image
        Image.open(io.BytesIO(contents)).verify()
    except Exception:
        return RedirectResponse(url="/admin/branding?err=invalid", status_code=303)

    new_name = branding_service.save_branding_image(slot, contents, ext)
    _upsert_setting(db, slot, new_name)
    branding_service.cleanup_old_branding(slot, keep=new_name)
    branding_service.invalidate_branding_cache()
    return RedirectResponse(url="/admin/branding?msg=saved", status_code=303)


@router.post("/admin/branding/reset")
async def branding_reset(
    slot: str = Form(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if slot not in _SLOTS:
        return RedirectResponse(url="/admin/branding?err=slot", status_code=303)
    _upsert_setting(db, slot, None)
    branding_service.cleanup_old_branding(slot, keep="")
    branding_service.invalidate_branding_cache()
    return RedirectResponse(url="/admin/branding?msg=reset", status_code=303)
```

> `get_db`, `get_current_user`, `require_admin` `app/deps.py` da. Agar `get_db` u yerda bo'lmasa `from app.models.database import get_db` ishlating (mavjud route'lardan tasdiqlang).

- [ ] **Step 5: Include router in main.py**

`main.py` da boshqa route importlari yonida import qo'shing va include qiling. Mavjud uslubga moslang (masalan `from app.routes import branding as branding_routes`), keyin boshqa `app.include_router(...)` qatorlari yoniga (134-qator atrofi):
```python
app.include_router(branding_routes.router)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_branding.py -v`
Expected: PASS (barcha testlar). Import tekshiruvi: `python -c "import main"` — xatosiz.

- [ ] **Step 7: Commit**

```bash
git add app/routes/branding.py app/services/branding_service.py main.py tests/test_branding.py
git commit -m "feat(branding): /admin/branding upload/reset route + admin ruxsat

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Admin sahifa template + sidebar menyu havolasi

**Files:**
- Create: `app/templates/admin/branding.html`
- Modify: `app/templates/base.html` (sidebar menyuga "Brending" havolasi)

**Interfaces:**
- Consumes: `current` dict (`{logo_main, logo_circle}`), `csrf_token_from_request(request)`, `msg`/`err` query
- Produces: HTML sahifa `/admin/branding`

- [ ] **Step 1: Create branding.html template**

`app/templates/admin/branding.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-3">
  <h3 class="mb-3"><i class="bi bi-image"></i> Brending sozlamalari</h3>

  {% if msg == "saved" %}<div class="alert alert-success">Logo saqlandi.</div>{% endif %}
  {% if msg == "reset" %}<div class="alert alert-info">Standart logoga qaytarildi.</div>{% endif %}
  {% if err == "ext" %}<div class="alert alert-danger">Faqat PNG / JPG / WEBP qabul qilinadi.</div>{% endif %}
  {% if err == "size" %}<div class="alert alert-danger">Rasm hajmi 2 MB dan oshmasligi kerak.</div>{% endif %}
  {% if err == "invalid" %}<div class="alert alert-danger">Fayl haqiqiy rasm emas yoki buzilgan.</div>{% endif %}
  {% if err == "slot" %}<div class="alert alert-danger">Noto'g'ri logo turi.</div>{% endif %}

  <div class="row g-3">
    {% set slots = [
        ("logo_main", "Asosiy logo", "Favicon va bildirishnomalar uchun (to'rtburchak).", current.logo_main),
        ("logo_circle", "Dumaloq logo", "Yon panel (sidebar) va kirish sahifasi uchun.", current.logo_circle)
    ] %}
    {% for slot, title, hint, src in slots %}
    <div class="col-md-6">
      <div class="card h-100">
        <div class="card-body text-center">
          <h5 class="card-title">{{ title }}</h5>
          <p class="text-muted small">{{ hint }}</p>
          <img src="{{ src }}?v={{ range(100000) | random }}" alt="{{ title }}"
               style="max-width: 160px; max-height: 160px; object-fit: contain;"
               class="mb-3 border rounded p-2">
          <form action="/admin/branding/upload" method="post" enctype="multipart/form-data" class="mb-2">
            <input type="hidden" name="csrf_token" value="{{ csrf_token_from_request(request) }}">
            <input type="hidden" name="slot" value="{{ slot }}">
            <input type="file" name="image" accept="image/png,image/jpeg,image/webp" required class="form-control mb-2">
            <button type="submit" class="btn btn-primary w-100">
              <i class="bi bi-upload"></i> Yuklash
            </button>
          </form>
          <form action="/admin/branding/reset" method="post"
                onsubmit="return confirm('Standart logoga qaytarilsinmi?');">
            <input type="hidden" name="csrf_token" value="{{ csrf_token_from_request(request) }}">
            <input type="hidden" name="slot" value="{{ slot }}">
            <button type="submit" class="btn btn-outline-secondary btn-sm w-100">
              <i class="bi bi-arrow-counterclockwise"></i> Standartga qaytarish
            </button>
          </form>
        </div>
      </div>
    </div>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

> Eslatma: `block content` nomini base.html'dagi haqiqiy block nomi bilan moslang. Agar base.html `{% block body %}` ishlatsa, shuni yozing. Tasdiqlash: `grep -n "block " app/templates/base.html`.

- [ ] **Step 2: Add sidebar menu link in base.html**

`base.html` sidebar menyusida, mavjud admin-only havolalar yonida (`{% if current_user.role == 'admin' %}` bloki ichida — mavjud pattern bilan moslang) qo'shing:
```html
<li class="nav-item">
  <a class="nav-link" href="/admin/branding">
    <i class="bi bi-image"></i> Brending
  </a>
</li>
```

> Sidebar'dagi admin havolalar qanday o'ralganini tasdiqlang: `grep -n "admin/periods\|admin/exchange" app/templates/base.html` — yangi havolani shu blokка qo'ying.

- [ ] **Step 3: Manual smoke — sahifa ochiladi**

Server ishlab turgan bo'lsa (yoki test client orqali), `/admin/branding` admin sifatida 200 qaytarishini tekshiring:
```bash
python -m pytest tests/test_branding.py -v
```
Qo'shimcha: `python -c "import main"` xatosiz.

- [ ] **Step 4: Commit**

```bash
git add app/templates/admin/branding.html app/templates/base.html
git commit -m "feat(branding): admin sahifa template + sidebar Brending havolasi

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Templatelarda logoni dinamik qilish

**Files:**
- Modify: `app/templates/base.html` (3 joy: favicon, sidebar img, bildirishnoma ikon)
- Modify: `app/templates/login.html` (1 joy: logo img)
- Test: `tests/test_branding.py` (render smoke testi)

**Interfaces:**
- Consumes: Jinja global `branding()` (Task 2)

- [ ] **Step 1: Write the failing test (render smoke)**

`tests/test_branding.py` oxiriga qo'shing:
```python
def test_login_page_uses_branding(client):
    """Login sahifasi branding() global'ini ishlatadi — xatosiz render bo'ladi."""
    resp = client.get("/login")
    assert resp.status_code == 200
    # Standart holatda dumaloq logo yo'li ko'rinishi kerak
    assert "/static/images/" in resp.text
```

> `/login` route yo'lini tasdiqlang (`grep -n "login" app/routes/auth.py`). Agar boshqacha bo'lsa, mos URL ishlating.

- [ ] **Step 2: Run test to verify current state**

Run: `python -m pytest tests/test_branding.py::test_login_page_uses_branding -v`
Expected: Hozir PASS bo'lishi mumkin (statik yo'l hali ham bor). Bu test regressiyani ushlash uchun — Step 3 dan keyin ham PASS qolishi shart.

- [ ] **Step 3: Replace hardcoded logo paths**

`app/templates/base.html`:
- Qator 8 (favicon):
  ```html
  <link rel="icon" href="{{ branding().logo_main }}" type="image/png">
  ```
- Qator ~892 (sidebar img — `src` ni almashtiring, `width/height/style` saqlab qoling):
  ```html
  <img src="{{ branding().logo_circle }}" alt="TOTLI HOLVA"
       style="width: 240px; height: 240px; object-fit: contain; display: block;">
  ```
- Qator ~1801 (bildirishnoma ikon — JS ichida):
  ```javascript
  new Notification(title, { body: message, icon: '{{ branding().logo_main }}' });
  ```

`app/templates/login.html`:
- Qator ~167 (logo img — `src` ni almashtiring):
  ```html
  <img src="{{ branding().logo_circle }}" alt="TOTLI HOLVA"
  ```
  (qolgan atributlarni o'zgartirmang)

- [ ] **Step 4: Run test to verify it still passes**

Run: `python -m pytest tests/test_branding.py -v`
Expected: PASS (barcha testlar, jumladan render smoke). Qo'shimcha: `python -c "import main"` xatosiz.

- [ ] **Step 5: Full smoke (regressiya yo'qligini tasdiqlash)**

Run: `python -m pytest tests/test_smoke.py tests/test_endpoints_smoke.py -v`
Expected: PASS (yoki avvalgi holatdek — yangi xato yo'q).

- [ ] **Step 6: Commit**

```bash
git add app/templates/base.html app/templates/login.html tests/test_branding.py
git commit -m "feat(branding): logo yo'llarini dinamik branding() ga ulash

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Yakuniy tekshiruv (barcha tasklardan keyin)

- [ ] To'liq test: `python -m pytest tests/test_branding.py -v` — hammasi PASS
- [ ] Import: `python -c "import main"` — xatosiz
- [ ] Qo'lda: admin sifatida `/admin/branding` ga kirish, PNG yuklash, sidebar/login/favicon yangilanganini ko'rish, "Standartga qaytarish" ishlashini tekshirish
- [ ] Branch tayyor → merge qarori (finishing-a-development-branch skill)

## Self-Review natijasi (spec qamrovi)

| Spec talabi | Qamrovchi task |
|-------------|----------------|
| AppSetting key-value jadvali | Task 1 |
| 2 logo slot (asosiy + dumaloq) | Task 3 (slot), Task 4 (UI) |
| branding.py route, admin ruxsat | Task 3 |
| Pillow validatsiya, 2MB, format whitelist | Task 3 |
| branding papkaga timestamp bilan saqlash | Task 3 |
| eski fayl tozalash | Task 3 (`cleanup_old_branding`) |
| Jinja global, 100+ route'ga tegmaslik | Task 2 |
| fallback (yozuv/fayl yo'q -> standart) | Task 1 (`resolve_branding`) |
| reset (standartga qaytarish) | Task 3 |
| sidebar menyu havolasi | Task 4 |
| 4 template joyi dinamik | Task 5 |
