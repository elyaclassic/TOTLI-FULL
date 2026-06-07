# Kadr o'zgarishi buyrug'i (Employee Change Order) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xodim ish haqi/lavozim/bo'lim o'zgarishini effective-date'li hujjat (buyruq) sifatida yozish; oylik hisob o'sha oyga (oy 1-sanasiga) kuchda bo'lgan stavkani ishlatsin.

**Architecture:** Yangi `EmployeeChangeDoc` modeli (eski→yangi + effective_date + user_id + draft/confirm). Markaziy `get_effective_salary(db, emp_id, as_of_date)` helper hire (`EmploymentDoc`) + barcha tasdiqlangan change'larni hisobga oladi. Oylik hisob (`employees_salary.py`) bu helperni oy 1-sanasi bilan chaqiradi. Oy o'rtasidagi o'zgarish keyingi oydan kuchga kiradi.

**Tech Stack:** FastAPI, SQLAlchemy, SQLite, Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-06-07-employee-change-order-design.md`

---

## File Structure

| Fayl | Mas'uliyat |
|------|-----------|
| `app/models/database.py` (MODIFY) | `EmployeeChangeDoc` model + `ensure_employee_change_docs()` + init'da chaqirish |
| `app/services/employee_salary_service.py` (YANGI) | `get_effective_salary(db, emp_id, as_of_date)` |
| `tests/test_employee_change_order.py` (YANGI) | model + helper + payroll testlari |
| `app/routes/employees_changes.py` (YANGI) | list/new/create/confirm/cancel/print |
| `app/main.py` (MODIFY) | yangi router'ni ulash |
| `app/routes/employees_salary.py` (MODIFY) | `latest_doc_salary` → effective lookup (oy 1-sanasi) |
| `app/templates/employees/changes_list.html` (YANGI) | buyruqlar ro'yxati |
| `app/templates/employees/change_form.html` (YANGI) | yangi buyruq formasi |
| `app/templates/employees/change_print.html` (YANGI) | chop etish |
| `app/templates/employees/detail.html` (MODIFY) | "Kadr o'zgarishlari" bo'lim + tugma |

---

## Task 1: EmployeeChangeDoc model + migratsiya

**Files:**
- Modify: `app/models/database.py` (EmploymentDoc'dan keyin, ~1404; ensure-block ~2099/2164)

- [ ] **Step 1: Model qo'shish** — `app/models/database.py` da `EmploymentDoc` klassidan keyin (production_group_members'dan oldin) QO'SHING:
```python
class EmployeeChangeDoc(Base):
    """Kadr o'zgarishi buyrug'i — ish haqi/lavozim/bo'lim o'zgarishi (effective-date'li)."""
    __tablename__ = "employee_change_docs"

    id = Column(Integer, primary_key=True, index=True)
    number = Column(String(50), unique=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    doc_date = Column(Date, nullable=False)          # buyruq sanasi
    effective_date = Column(Date, nullable=False)    # qachondan kuchga kiradi
    change_salary = Column(Boolean, default=False)
    old_salary = Column(Float, nullable=True)
    new_salary = Column(Float, nullable=True)
    change_salary_type = Column(Boolean, default=False)
    old_salary_type = Column(String(50), nullable=True)
    new_salary_type = Column(String(50), nullable=True)
    change_position = Column(Boolean, default=False)
    old_position = Column(String(100), nullable=True)
    new_position = Column(String(100), nullable=True)
    change_department = Column(Boolean, default=False)
    old_department = Column(String(100), nullable=True)
    new_department = Column(String(100), nullable=True)
    reason = Column(String(500), nullable=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String(20), default="draft")     # draft, confirmed, cancelled
    confirmed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    employee = relationship("Employee", backref="change_docs")
    user = relationship("User")
```

- [ ] **Step 2: ensure migratsiya funksiyasi** — `ensure_employee_salary_type` (~1882) yonida QO'SHING:
```python
def ensure_employee_change_docs():
    """employee_change_docs jadvali bo'lishini ta'minlash."""
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS employee_change_docs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number VARCHAR(50) UNIQUE,
                    employee_id INTEGER NOT NULL,
                    doc_date DATE NOT NULL,
                    effective_date DATE NOT NULL,
                    change_salary BOOLEAN DEFAULT 0,
                    old_salary FLOAT,
                    new_salary FLOAT,
                    change_salary_type BOOLEAN DEFAULT 0,
                    old_salary_type VARCHAR(50),
                    new_salary_type VARCHAR(50),
                    change_position BOOLEAN DEFAULT 0,
                    old_position VARCHAR(100),
                    new_position VARCHAR(100),
                    change_department BOOLEAN DEFAULT 0,
                    old_department VARCHAR(100),
                    new_department VARCHAR(100),
                    reason VARCHAR(500),
                    user_id INTEGER,
                    status VARCHAR(20) DEFAULT 'draft',
                    confirmed_at DATETIME,
                    created_at DATETIME
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_ecd_emp ON employee_change_docs (employee_id)"))
    except Exception as e:
        print(f"ensure_employee_change_docs: {e}")
```

- [ ] **Step 3: init'da chaqirish** — `ensure_employee_salary_type()` chaqirilgan joyga (~2099) yondosh QO'SHING:
```python
    ensure_employee_change_docs()
```

- [ ] **Step 4: Import OK** — `python -c "import app.models.database as d; d.ensure_employee_change_docs(); print('OK', d.EmployeeChangeDoc.__tablename__)"` → `OK employee_change_docs`.

- [ ] **Step 5: Commit**
```bash
git add app/models/database.py
git commit -m "feat(hr): EmployeeChangeDoc model + migratsiya (kadr o'zgarishi)"
```

---

## Task 2: get_effective_salary helper (TDD)

**Files:**
- Create: `app/services/employee_salary_service.py`
- Test: `tests/test_employee_change_order.py`

- [ ] **Step 1: Failing test** — `tests/test_employee_change_order.py`:
```python
"""Kadr o'zgarishi buyrug'i: effective salary + payroll."""
from datetime import date
from app.models.database import Employee, EmploymentDoc, EmployeeChangeDoc


def _emp(db, salary=1_000_000, position="Ishchi"):
    e = Employee(full_name="Test Xodim", salary=salary, position=position, salary_type="oylik", is_active=True)
    db.add(e); db.flush()
    return e


def _hire(db, emp, salary, d):
    doc = EmploymentDoc(number=f"IQ-{emp.id}", employee_id=emp.id, doc_date=d, hire_date=d,
                        salary=salary, salary_type="oylik", confirmed_at="2026-01-01 00:00:00")
    db.add(doc); db.flush()
    return doc


def _change(db, emp, new_salary, eff, status="confirmed"):
    doc = EmployeeChangeDoc(number=f"KO-{emp.id}-{eff}", employee_id=emp.id, doc_date=eff,
                            effective_date=eff, change_salary=True, old_salary=emp.salary,
                            new_salary=new_salary, status=status,
                            confirmed_at=("2026-01-01 00:00:00" if status == "confirmed" else None))
    db.add(doc); db.flush()
    return doc


def test_effective_hire_only(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    sal, _ = get_effective_salary(db, e.id, date(2026, 3, 1))
    assert sal == 1_000_000


def test_effective_after_change(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    _change(db, e, 1_500_000, date(2026, 3, 1))
    # mart 1 dan oldin = eski, keyin = yangi
    assert get_effective_salary(db, e.id, date(2026, 2, 1))[0] == 1_000_000
    assert get_effective_salary(db, e.id, date(2026, 3, 1))[0] == 1_500_000


def test_effective_ignores_future_and_unconfirmed(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    _change(db, e, 2_000_000, date(2026, 6, 1))                 # kelajak
    _change(db, e, 9_000_000, date(2026, 2, 1), status="draft")  # tasdiqlanmagan
    sal, _ = get_effective_salary(db, e.id, date(2026, 3, 1))
    assert sal == 1_000_000  # kelajak ham, draft ham hisobga olinmaydi


def test_effective_latest_of_two_changes(db):
    from app.services.employee_salary_service import get_effective_salary
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, date(2026, 1, 1))
    _change(db, e, 1_500_000, date(2026, 2, 1))
    _change(db, e, 1_800_000, date(2026, 4, 1))
    assert get_effective_salary(db, e.id, date(2026, 5, 1))[0] == 1_800_000
    assert get_effective_salary(db, e.id, date(2026, 3, 1))[0] == 1_500_000
```

- [ ] **Step 2: Run, FAIL** — `python -m pytest tests/test_employee_change_order.py -q` → ImportError.

- [ ] **Step 3: Helper** — `app/services/employee_salary_service.py`:
```python
"""Xodim effective ish haqi — hire (EmploymentDoc) + kadr o'zgarishlari (EmployeeChangeDoc)."""
from datetime import date

from app.models.database import Employee, EmploymentDoc, EmployeeChangeDoc


def get_effective_salary(db, employee_id, as_of_date):
    """as_of_date sanasiga kuchda bo'lgan (salary, salary_type) ni qaytaradi.

    Ustuvorlik: effective_date <= as_of_date bo'lgan eng so'nggi tasdiqlangan
    EmployeeChangeDoc → bo'lmasa eng so'nggi tasdiqlangan EmploymentDoc (hire)
    → bo'lmasa Employee.salary (fallback). salary_type ham shu tartibda.
    """
    salary = None
    salary_type = None

    # 1) Kadr o'zgarishi (effective)
    ch_q = (
        db.query(EmployeeChangeDoc)
        .filter(
            EmployeeChangeDoc.employee_id == employee_id,
            EmployeeChangeDoc.status == "confirmed",
            EmployeeChangeDoc.effective_date <= as_of_date,
        )
        .order_by(EmployeeChangeDoc.effective_date.desc(), EmployeeChangeDoc.id.desc())
        .all()
    )
    for ch in ch_q:
        if salary is None and ch.change_salary and ch.new_salary is not None:
            salary = float(ch.new_salary)
        if salary_type is None and ch.change_salary_type and ch.new_salary_type:
            salary_type = ch.new_salary_type
        if salary is not None and salary_type is not None:
            break

    # 2) Hire hujjati (eng so'nggi tasdiqlangan)
    if salary is None or salary_type is None:
        hire = (
            db.query(EmploymentDoc)
            .filter(EmploymentDoc.employee_id == employee_id, EmploymentDoc.confirmed_at.isnot(None))
            .order_by(EmploymentDoc.doc_date.desc(), EmploymentDoc.id.desc())
            .first()
        )
        if hire:
            if salary is None and hire.salary:
                salary = float(hire.salary)
            if salary_type is None and hire.salary_type:
                salary_type = hire.salary_type

    # 3) Employee fallback
    if salary is None or salary_type is None:
        emp = db.query(Employee).filter(Employee.id == employee_id).first()
        if emp:
            if salary is None:
                salary = float(emp.salary or 0)
            if salary_type is None:
                salary_type = emp.salary_type

    return float(salary or 0), salary_type
```

- [ ] **Step 4: Run, PASS** — `python -m pytest tests/test_employee_change_order.py -q` → 4 passed.

- [ ] **Step 5: Commit**
```bash
git add app/services/employee_salary_service.py tests/test_employee_change_order.py
git commit -m "feat(hr): get_effective_salary helper + testlar"
```

---

## Task 3: Routes — list + new + create (draft)

**Files:**
- Create: `app/routes/employees_changes.py`
- Modify: `app/main.py` (router ulash)

Mavjud naqsh: `app/routes/employees_employment.py` (number-gen `IQ-YYYYMMDD-NNNN`, RedirectResponse, templates). Shu uslubni KO- bilan takrorlang.

- [ ] **Step 1: Router fayli** — `app/routes/employees_changes.py`:
```python
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, Employee, EmployeeChangeDoc, User
from app.deps import require_auth
from app.services.employee_salary_service import get_effective_salary

router = APIRouter(prefix="/employees", tags=["employee-changes"])

_ALLOWED = ("admin", "manager", "menejer", "rahbar", "raxbar")


def _can(user):
    return user and (getattr(user, "role", None) or "").strip().lower() in _ALLOWED


@router.get("/changes", response_class=HTMLResponse)
async def changes_list(request: Request, employee_id: int = None,
                       db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    q = db.query(EmployeeChangeDoc).order_by(EmployeeChangeDoc.doc_date.desc(), EmployeeChangeDoc.id.desc())
    if employee_id:
        q = q.filter(EmployeeChangeDoc.employee_id == employee_id)
    docs = q.limit(500).all()
    emp_map = {e.id: e for e in db.query(Employee).all()}
    return templates.TemplateResponse("employees/changes_list.html", {
        "request": request, "docs": docs, "emp_map": emp_map,
        "selected_employee_id": employee_id, "current_user": current_user,
        "page_title": "Kadr o'zgarishlari",
    })


@router.get("/change/new", response_class=HTMLResponse)
async def change_new_page(request: Request, employee_id: int,
                          db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _can(current_user):
        return RedirectResponse(url="/employees?error=" + quote("Ruxsat yo'q"), status_code=303)
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=" + quote("Xodim topilmadi"), status_code=303)
    cur_salary, cur_type = get_effective_salary(db, emp.id, datetime.now().date())
    return templates.TemplateResponse("employees/change_form.html", {
        "request": request, "emp": emp, "cur_salary": cur_salary, "cur_type": cur_type,
        "today": datetime.now().date().isoformat(), "current_user": current_user,
        "page_title": "Yangi kadr o'zgarishi",
    })


@router.post("/change/create")
async def change_create(
    request: Request,
    employee_id: int = Form(...),
    doc_date: str = Form(...),
    effective_date: str = Form(...),
    change_salary: int = Form(0),
    new_salary: float = Form(0),
    change_salary_type: int = Form(0),
    new_salary_type: str = Form(""),
    change_position: int = Form(0),
    new_position: str = Form(""),
    change_department: int = Form(0),
    new_department: str = Form(""),
    reason: str = Form(""),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
):
    if not _can(current_user):
        return RedirectResponse(url="/employees?error=" + quote("Ruxsat yo'q"), status_code=303)
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        return RedirectResponse(url="/employees?error=" + quote("Xodim topilmadi"), status_code=303)
    try:
        doc_d = datetime.strptime(doc_date, "%Y-%m-%d").date()
        eff_d = datetime.strptime(effective_date, "%Y-%m-%d").date()
    except ValueError:
        return RedirectResponse(url=f"/employees/change/new?employee_id={employee_id}&error=" + quote("Noto'g'ri sana"), status_code=303)
    if not (change_salary or change_salary_type or change_position or change_department):
        return RedirectResponse(url=f"/employees/change/new?employee_id={employee_id}&error=" + quote("Kamida bitta o'zgarish belgilang"), status_code=303)

    cur_salary, cur_type = get_effective_salary(db, emp.id, datetime.now().date())
    count = db.query(EmployeeChangeDoc).filter(
        EmployeeChangeDoc.number.like(f"KO-{doc_d.strftime('%Y%m%d')}-%")
    ).count()
    number = f"KO-{doc_d.strftime('%Y%m%d')}-{count + 1:04d}"

    doc = EmployeeChangeDoc(
        number=number, employee_id=emp.id, doc_date=doc_d, effective_date=eff_d,
        change_salary=bool(change_salary), old_salary=cur_salary if change_salary else None,
        new_salary=float(new_salary) if change_salary else None,
        change_salary_type=bool(change_salary_type), old_salary_type=cur_type if change_salary_type else None,
        new_salary_type=(new_salary_type or None) if change_salary_type else None,
        change_position=bool(change_position), old_position=emp.position if change_position else None,
        new_position=(new_position or None) if change_position else None,
        change_department=bool(change_department), old_department=emp.department if change_department else None,
        new_department=(new_department or None) if change_department else None,
        reason=(reason or None), user_id=current_user.id if current_user else None,
        status="draft",
    )
    db.add(doc)
    db.commit()
    return RedirectResponse(url=f"/employees/changes?employee_id={employee_id}&created=1", status_code=303)
```

- [ ] **Step 2: Router'ni ulash** — `app/main.py` da boshqa `employees_*` router include qilingan joyni toping (`grep -n "employees_employment\|employees_salary" app/main.py`) va yondosh QO'SHING:
```python
from app.routes import employees_changes
app.include_router(employees_changes.router)
```
(Mavjud import/include uslubiga moslang — agar `from app.routes import (...)` bloki bo'lsa, ro'yxatga qo'shing.)

- [ ] **Step 3: Sintaksis** — `python -m py_compile app/routes/employees_changes.py app/main.py && echo OK`.

- [ ] **Step 4: Commit**
```bash
git add app/routes/employees_changes.py app/main.py
git commit -m "feat(hr): kadr o'zgarishi route'lari (list/new/create draft)"
```

---

## Task 4: Routes — confirm + cancel (Employee kesh yangilanishi)

**Files:**
- Modify: `app/routes/employees_changes.py`

- [ ] **Step 1: Helper — Employee joriy keshini qayta hisoblash** — `employees_changes.py` oxiriga QO'SHING:
```python
def _refresh_employee_current(db, emp):
    """Employee.salary/position/department keshini bugungi effective holatga keltiradi."""
    from datetime import datetime as _dt
    today = _dt.now().date()
    sal, st = get_effective_salary(db, emp.id, today)
    emp.salary = sal
    if st:
        emp.salary_type = st
    # lavozim/bo'lim: bugungi effective change'dan
    last = (
        db.query(EmployeeChangeDoc)
        .filter(EmployeeChangeDoc.employee_id == emp.id,
                EmployeeChangeDoc.status == "confirmed",
                EmployeeChangeDoc.effective_date <= today)
        .order_by(EmployeeChangeDoc.effective_date.desc(), EmployeeChangeDoc.id.desc())
        .all()
    )
    pos_set = dep_set = False
    for ch in last:
        if not pos_set and ch.change_position and ch.new_position:
            emp.position = ch.new_position; pos_set = True
        if not dep_set and ch.change_department and ch.new_department:
            emp.department = ch.new_department; dep_set = True
        if pos_set and dep_set:
            break
```

- [ ] **Step 2: confirm + cancel route'lar** — `employees_changes.py` oxiriga QO'SHING:
```python
@router.post("/change/{doc_id}/confirm")
async def change_confirm(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _can(current_user):
        return RedirectResponse(url="/employees/changes?error=" + quote("Ruxsat yo'q"), status_code=303)
    doc = db.query(EmployeeChangeDoc).filter(EmployeeChangeDoc.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/employees/changes?error=" + quote("Hujjat topilmadi"), status_code=303)
    if doc.status == "confirmed":
        return RedirectResponse(url=f"/employees/changes?employee_id={doc.employee_id}", status_code=303)
    doc.status = "confirmed"
    doc.confirmed_at = datetime.now()
    db.flush()
    emp = db.query(Employee).filter(Employee.id == doc.employee_id).first()
    if emp:
        _refresh_employee_current(db, emp)  # effective_date <= bugun bo'lsa kesh yangilanadi
    db.commit()
    return RedirectResponse(url=f"/employees/changes?employee_id={doc.employee_id}&confirmed=1", status_code=303)


@router.post("/change/{doc_id}/cancel")
async def change_cancel(doc_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    if not _can(current_user):
        return RedirectResponse(url="/employees/changes?error=" + quote("Ruxsat yo'q"), status_code=303)
    doc = db.query(EmployeeChangeDoc).filter(EmployeeChangeDoc.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/employees/changes?error=" + quote("Hujjat topilmadi"), status_code=303)
    doc.status = "cancelled"
    doc.confirmed_at = None
    db.flush()
    emp = db.query(Employee).filter(Employee.id == doc.employee_id).first()
    if emp:
        _refresh_employee_current(db, emp)  # qolgan effective holatdan qayta hisob
    db.commit()
    return RedirectResponse(url=f"/employees/changes?employee_id={doc.employee_id}&cancelled=1", status_code=303)
```

- [ ] **Step 3: Test (confirm Employee keshini yangilaydi)** — `tests/test_employee_change_order.py` ga QO'SHING:
```python
def test_confirm_refreshes_employee_cache(db):
    from app.routes.employees_changes import _refresh_employee_current
    from datetime import date as _d
    e = _emp(db, salary=1_000_000, position="Ishchi")
    _hire(db, e, 1_000_000, _d(2026, 1, 1))
    # bugungi sanadan oldin effective o'zgarish (tasdiqlangan)
    ch = EmployeeChangeDoc(number="KO-x", employee_id=e.id, doc_date=_d(2026, 1, 1),
                           effective_date=_d(2026, 1, 1), change_salary=True, old_salary=1_000_000,
                           new_salary=1_700_000, change_position=True, old_position="Ishchi",
                           new_position="Brigadir", status="confirmed", confirmed_at="2026-01-01 00:00:00")
    db.add(ch); db.flush()
    _refresh_employee_current(db, e)
    assert e.salary == 1_700_000
    assert e.position == "Brigadir"
```

- [ ] **Step 4: Run, PASS** — `python -m pytest tests/test_employee_change_order.py -q` → 5 passed.

- [ ] **Step 5: Commit**
```bash
git add app/routes/employees_changes.py tests/test_employee_change_order.py
git commit -m "feat(hr): kadr o'zgarishi confirm/cancel + Employee kesh yangilash"
```

---

## Task 5: Oylik hisob integratsiyasi (effective salary)

**Files:**
- Modify: `app/routes/employees_salary.py` (latest_doc_salary qurilishi ~96-127)

**Maqsad:** `latest_doc_salary[emp_id]` ni oy 1-sanasiga effective stavka bilan to'ldirish (downstream 338/346/351/361 o'zgarmaydi — bir xil dict shakli).

- [ ] **Step 1: year/month aniqligini tekshir** — `employees_salary.py` da `employee_salary_page` ichida `year`/`month` o'zgaruvchilari borligini ko'ring (`grep -n "year\|month" app/routes/employees_salary.py | head`). Oddatda forma paramlari yoki `datetime.now()`. Effective sanasi = `date(year, month, 1)`.

- [ ] **Step 2: latest_doc_salary blokini almashtirish** — `employees_salary.py` da `latest_doc_salary = {}` dan boshlanib EmploymentDoc subquery bilan to'ldiradigan blokni (~96-127, `missing` qismigacha) TOPING va BUTUNICHA almashtiring:
```python
    from datetime import date as _date
    from app.services.employee_salary_service import get_effective_salary
    _eff_ref = _date(int(year), int(month), 1)
    latest_doc_salary = {}
    for _eid in emp_ids:
        _sal, _ = get_effective_salary(db, _eid, _eff_ref)
        if _sal:
            latest_doc_salary[_eid] = float(_sal)
```
(`emp_ids` o'sha funksiyada allaqachon aniqlangan. `year`/`month` Step 1'dagi nomlarga moslang — agar `sel_year`/`sel_month` bo'lsa, shu nomlarni ishlating.)

- [ ] **Step 3: Payroll test (change'dan keyingi oy yangi stavka)** — `tests/test_employee_change_order.py` ga QO'SHING:
```python
def test_payroll_uses_effective_by_month(db):
    from app.services.employee_salary_service import get_effective_salary
    from datetime import date as _d
    e = _emp(db, salary=1_000_000)
    _hire(db, e, 1_000_000, _d(2026, 1, 1))
    _change(db, e, 1_500_000, _d(2026, 4, 1))  # 1-apreldan
    # mart (1-mart) oyligi = eski; aprel (1-aprel) = yangi
    assert get_effective_salary(db, e.id, _d(2026, 3, 1))[0] == 1_000_000
    assert get_effective_salary(db, e.id, _d(2026, 4, 1))[0] == 1_500_000
    # oy o'rtasida (15-mart) kiritilgan o'zgarish keyingi oydan:
    _change(db, e, 2_000_000, _d(2026, 5, 15))
    assert get_effective_salary(db, e.id, _d(2026, 5, 1))[0] == 1_500_000  # may 1: hali yo'q
    assert get_effective_salary(db, e.id, _d(2026, 6, 1))[0] == 2_000_000  # iyun 1: kuchda
```

- [ ] **Step 4: Run, PASS + sintaksis** — `python -m pytest tests/test_employee_change_order.py -q` → 6 passed; `python -m py_compile app/routes/employees_salary.py && echo OK`.

- [ ] **Step 5: Commit**
```bash
git add app/routes/employees_salary.py tests/test_employee_change_order.py
git commit -m "feat(hr): oylik hisob effective salary (oy 1-sanasi) ishlatsin"
```

---

## Task 6: Templatelar — ro'yxat + forma + chop etish

**Files:**
- Create: `app/templates/employees/changes_list.html`, `change_form.html`, `change_print.html`

Mavjud `app/templates/employees/` dagi hujjat templatelari uslubini (base extend, jadval, badge) nusxalang.

- [ ] **Step 1: changes_list.html** — `app/templates/employees/changes_list.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container-fluid py-3">
  <h4 class="mb-3">Kadr o'zgarishlari</h4>
  {% if request.query_params.get('error') %}<div class="alert alert-danger py-2">{{ request.query_params.get('error') }}</div>{% endif %}
  <table class="table table-sm">
    <thead><tr>
      <th>№</th><th>Xodim</th><th>Sana</th><th>Kuchga kiradi</th><th>O'zgarish</th><th>Sabab</th><th>Kim</th><th>Holat</th><th></th>
    </tr></thead>
    <tbody>
      {% for d in docs %}
      <tr>
        <td>{{ d.number }}</td>
        <td>{{ emp_map[d.employee_id].full_name if d.employee_id in emp_map else d.employee_id }}</td>
        <td>{{ d.doc_date.strftime('%d.%m.%Y') if d.doc_date else '' }}</td>
        <td>{{ d.effective_date.strftime('%d.%m.%Y') if d.effective_date else '' }}</td>
        <td class="small">
          {% if d.change_salary %}Ish haqi: {{ "{:,.0f}".format(d.old_salary or 0) }} → {{ "{:,.0f}".format(d.new_salary or 0) }}<br>{% endif %}
          {% if d.change_position %}Lavozim: {{ d.old_position or '—' }} → {{ d.new_position or '—' }}<br>{% endif %}
          {% if d.change_department %}Bo'lim: {{ d.old_department or '—' }} → {{ d.new_department or '—' }}<br>{% endif %}
          {% if d.change_salary_type %}Tur: {{ d.old_salary_type or '—' }} → {{ d.new_salary_type or '—' }}{% endif %}
        </td>
        <td class="small">{{ d.reason or '' }}</td>
        <td class="small">{{ d.user.username if d.user else '' }}</td>
        <td>
          {% if d.status == 'confirmed' %}<span class="badge bg-success">Tasdiqlangan</span>
          {% elif d.status == 'cancelled' %}<span class="badge bg-secondary">Bekor</span>
          {% else %}<span class="badge bg-warning text-dark">Qoralama</span>{% endif %}
        </td>
        <td>
          <a href="/employees/change/{{ d.id }}/print" class="btn btn-sm btn-outline-secondary" title="Chop etish"><i class="bi bi-printer"></i></a>
          {% if d.status == 'draft' and user_can_override(current_user) %}
          <form method="post" action="/employees/change/{{ d.id }}/confirm" class="d-inline" onsubmit="return confirm('Tasdiqlaysizmi?');">
            <button class="btn btn-sm btn-success">Tasdiq</button>
          </form>
          {% elif d.status == 'confirmed' and user_can_override(current_user) %}
          <form method="post" action="/employees/change/{{ d.id }}/cancel" class="d-inline" onsubmit="return confirm('Bekor qilasizmi? Joriy holat qayta hisoblanadi.');">
            <button class="btn btn-sm btn-outline-danger">Bekor</button>
          </form>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 2: change_form.html** — `app/templates/employees/change_form.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-3" style="max-width:640px;">
  <h4 class="mb-3">Yangi kadr o'zgarishi — {{ emp.full_name }}</h4>
  {% if request.query_params.get('error') %}<div class="alert alert-danger py-2">{{ request.query_params.get('error') }}</div>{% endif %}
  <form method="post" action="/employees/change/create">
    <input type="hidden" name="csrf_token" value="{{ csrf_token_from_request(request) }}">
    <input type="hidden" name="employee_id" value="{{ emp.id }}">
    <div class="row g-2 mb-3">
      <div class="col"><label class="form-label">Buyruq sanasi</label><input type="date" name="doc_date" class="form-control" value="{{ today }}" required></div>
      <div class="col"><label class="form-label">Qachondan kuchga kiradi</label><input type="date" name="effective_date" class="form-control" value="{{ today }}" required></div>
    </div>
    <div class="card mb-2"><div class="card-body py-2">
      <label class="form-check"><input type="checkbox" name="change_salary" value="1" class="form-check-input"> Ish haqi (joriy: {{ "{:,.0f}".format(cur_salary or 0) }})</label>
      <input type="number" step="any" name="new_salary" class="form-control mt-1" placeholder="Yangi ish haqi">
    </div></div>
    <div class="card mb-2"><div class="card-body py-2">
      <label class="form-check"><input type="checkbox" name="change_position" value="1" class="form-check-input"> Lavozim (joriy: {{ emp.position or '—' }})</label>
      <input type="text" name="new_position" class="form-control mt-1" placeholder="Yangi lavozim">
    </div></div>
    <div class="card mb-2"><div class="card-body py-2">
      <label class="form-check"><input type="checkbox" name="change_department" value="1" class="form-check-input"> Bo'lim (joriy: {{ emp.department or '—' }})</label>
      <input type="text" name="new_department" class="form-control mt-1" placeholder="Yangi bo'lim">
    </div></div>
    <div class="card mb-2"><div class="card-body py-2">
      <label class="form-check"><input type="checkbox" name="change_salary_type" value="1" class="form-check-input"> Ish haqi turi (joriy: {{ cur_type or '—' }})</label>
      <select name="new_salary_type" class="form-select mt-1"><option value="">—</option><option value="oylik">oylik</option><option value="soatlik">soatlik</option><option value="bo'lak">bo'lak</option></select>
    </div></div>
    <div class="mb-3"><label class="form-label">Sabab</label><input type="text" name="reason" class="form-control" placeholder="Masalan: ish haqi oshirildi"></div>
    <button type="submit" class="btn btn-primary">Saqlash (qoralama)</button>
    <a href="/employees/changes?employee_id={{ emp.id }}" class="btn btn-outline-secondary">Bekor</a>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 3: change_print.html (sodda chop)** — `app/templates/employees/change_print.html`:
```html
{% extends "base.html" %}
{% block content %}
<div class="container py-4" style="max-width:700px;">
  <h4 class="text-center">KADR O'ZGARISHI BUYRUG'I</h4>
  <p class="text-center">№ {{ doc.number }} — {{ doc.doc_date.strftime('%d.%m.%Y') if doc.doc_date else '' }}</p>
  <p><b>Xodim:</b> {{ emp.full_name if emp else doc.employee_id }}</p>
  <p><b>Kuchga kirish sanasi:</b> {{ doc.effective_date.strftime('%d.%m.%Y') if doc.effective_date else '' }}</p>
  <table class="table table-bordered">
    <tr><th></th><th>Eski</th><th>Yangi</th></tr>
    {% if doc.change_salary %}<tr><td>Ish haqi</td><td>{{ "{:,.0f}".format(doc.old_salary or 0) }}</td><td>{{ "{:,.0f}".format(doc.new_salary or 0) }}</td></tr>{% endif %}
    {% if doc.change_position %}<tr><td>Lavozim</td><td>{{ doc.old_position or '—' }}</td><td>{{ doc.new_position or '—' }}</td></tr>{% endif %}
    {% if doc.change_department %}<tr><td>Bo'lim</td><td>{{ doc.old_department or '—' }}</td><td>{{ doc.new_department or '—' }}</td></tr>{% endif %}
    {% if doc.change_salary_type %}<tr><td>Ish haqi turi</td><td>{{ doc.old_salary_type or '—' }}</td><td>{{ doc.new_salary_type or '—' }}</td></tr>{% endif %}
  </table>
  <p><b>Sabab:</b> {{ doc.reason or '' }}</p>
  <p><b>Kim:</b> {{ doc.user.username if doc.user else '' }}</p>
  <button class="btn btn-primary d-print-none" onclick="window.print()">Chop etish</button>
</div>
{% endblock %}
```

- [ ] **Step 4: print route** — `app/routes/employees_changes.py` ga QO'SHING:
```python
@router.get("/change/{doc_id}/print", response_class=HTMLResponse)
async def change_print(doc_id: int, request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    doc = db.query(EmployeeChangeDoc).filter(EmployeeChangeDoc.id == doc_id).first()
    if not doc:
        return RedirectResponse(url="/employees/changes?error=" + quote("Hujjat topilmadi"), status_code=303)
    emp = db.query(Employee).filter(Employee.id == doc.employee_id).first()
    return templates.TemplateResponse("employees/change_print.html", {
        "request": request, "doc": doc, "emp": emp, "current_user": current_user,
        "page_title": doc.number,
    })
```

- [ ] **Step 5: Jinja sintaksis** — `python -c "from jinja2 import Environment, FileSystemLoader; e=Environment(loader=FileSystemLoader('app/templates')); [e.get_template('employees/'+t) for t in ('changes_list.html','change_form.html','change_print.html')]; print('OK')"`.

- [ ] **Step 6: Commit**
```bash
git add app/routes/employees_changes.py app/templates/employees/changes_list.html app/templates/employees/change_form.html app/templates/employees/change_print.html
git commit -m "feat(hr): kadr o'zgarishi templatelari + print route"
```

---

## Task 7: Xodim sahifasiga ulanish + yakun

**Files:**
- Modify: `app/templates/employees/detail.html` (yoki xodim ro'yxati/edit sahifasi — mavjudini toping)

- [ ] **Step 1: Xodim sahifasini topish** — `grep -rl "employee" app/templates/employees/*.html` va xodim detali/edit sahifasini aniqlang (masalan `detail.html` yoki `edit.html`). Unda xodim `emp`/`employee` o'zgaruvchisi bo'lgan joyga havola QO'SHING:
```html
{% if user_can_override(current_user) %}
<a href="/employees/change/new?employee_id={{ employee.id }}" class="btn btn-sm btn-outline-primary"><i class="bi bi-pencil-square"></i> Kadr o'zgarishi</a>
<a href="/employees/changes?employee_id={{ employee.id }}" class="btn btn-sm btn-outline-secondary"><i class="bi bi-clock-history"></i> O'zgarishlar tarixi</a>
{% endif %}
```
(`employee` o'zgaruvchi nomini sahifadagi haqiqiy nomga moslang — `emp` bo'lishi mumkin.)

- [ ] **Step 2: To'liq regressiya** — `python -m pytest tests/test_employee_change_order.py -q` → 6 passed. So'ng `python -m pytest tests/ -q` (flaky teardown bo'lsa shubhalilarni alohida tekshir — [[feedback-flaky-fullsuite-teardown]]).

- [ ] **Step 3: Commit**
```bash
git add app/templates/employees/
git commit -m "feat(hr): xodim sahifasida kadr o'zgarishi tugmalari"
```

- [ ] **Step 4: Deploy eslatma** — Tier B. Backup → main merge → restart (deterministik: PID server.log 1-qatordan, kill, schtasks retry, yangi PID + ~18s startup — [[reference-remote-restart-from-elyor]], schtasks "Access denied" bo'lsa retry/watchdog). Backup: `totli_holva.db.bak_pre_change_order_deploy`. Yangi jadval migratsiyasi serverda ishga tushganda yaratiladi (ensure_employee_change_docs).

---

## Self-Review

**Spec coverage:**
- §5 model → Task 1 ✓ · §4 effective semantikasi (oy 1-sanasi, keyingi oy) → Task 2 + Task 5 (+ test_payroll_uses_effective_by_month) ✓ · §6 lifecycle (create/confirm/cancel) → Task 3+4 ✓ · §7 fayllar → barcha tasklar ✓ · §8 ruxsat (admin/manager/rahbar) → `_can` + `user_can_override` ✓ · §9 edge (kelajak/draft/2 o'zgarish) → Task 2 testlari ✓ · §10 test → Task 2/4/5 ✓.
- Tarix UI (§6.4) → Task 6 changes_list + Task 7 havola ✓.

**Placeholder scan:** Task 3 Step 2 (main.py include) va Task 5 Step 1-2 (year/month nomi) va Task 7 Step 1 (employee o'zgaruvchi nomi) — bular mavjud kodga MOSLASH ko'rsatmalari (aniq grep bilan), placeholder emas. Qolgan barcha kod to'liq.

**Type consistency:** `get_effective_salary(db, emp_id, as_of_date) -> (salary, salary_type)` Task 2/4/5'da izchil. `EmployeeChangeDoc` maydonlari Task 1 modeli bilan mos (status, change_*, old_*/new_*, effective_date). `_refresh_employee_current`, `_can` Task 3/4'da izchil. number `KO-YYYYMMDD-NNNN`.

**Eslatma:** Employee.salary kesh kelajak-sanali change uchun darhol yangilanmaydi (faqat effective_date≤bugun). Oylik hisob `get_effective_salary` ishlatgani uchun baribir to'g'ri; display kesh effective bo'lganda keyingi confirm/cancel yoki tegishli amalda yangilanadi. Bu spec §9 bilan mos.
