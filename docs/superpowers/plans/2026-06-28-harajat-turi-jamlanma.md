# Harajat turi bo'yicha filtr + jamlanma — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/finance/harajatlar` sahifasida harajatlarni *haqiqiy harajat turi* bo'yicha filtrlash va har bir tur qancha summa bo'lganini ko'rsatadigan jamlanma jadvalini qo'shish.

**Architecture:** Agregatsiya mantig'i alohida pure servis funksiyaga (`app/services/expense_breakdown.py`) ajratiladi — `db` fixture bilan auth'siz unit-test qilinadi. Route shu funksiyadan ham jamlanma jadvalini, ham 3 ta statistika kartasini oziqlantiradi (bitta haqiqat manbai, double-count'siz). Template'da "Tur" dropdown "Harajat turi"ga almashtiriladi va jamlanma jadvali qo'shiladi.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, SQLite, pytest.

## Global Constraints

- O'zgarish OLDIN backup: tegiladigan fayllarning `.bak_pre_<feature>_<sana>` nusxasini ol (loyiha qoidasi).
- SMB cache: yangi yozilgan fayllarni Bash ko'rmaydi — git operatsiyalarini PowerShell orqali bajar.
- Kod izohlari/matni: faqat sof o'zbek lotin, kirill aralashtirilmaydi.
- Testlar `db`/`client` fixture'lardan foydalanadi (in-memory SQLite); jonli `totli_holva.db` ga tegmaydi.
- Pul ko'rsatish formati mavjud uslub bilan bir xil: `"{:,.0f}".format(...)`.

---

### Task 1: Agregatsiya servisi (`expense_breakdown.py`)

**Files:**
- Create: `app/services/expense_breakdown.py`
- Test: `tests/test_expense_breakdown.py`

**Interfaces:**
- Produces:
  - `PAY_CATEGORY_LABELS: dict[str, str]` — PAY kategoriya kodi → o'zbekcha label.
  - `pay_label(code: str | None) -> str` — kod uchun label (NULL/noma'lum → "Turkumlanmagan" / raw kod).
  - `parse_etype(etype: str | None) -> tuple[str, int] | tuple[str, str | None] | None` — `"et:5"`→`("et",5)`, `"cat:other"`→`("cat","other")`, `"cat:"`→`("cat",None)`, aks holda `None`.
  - `compute_type_breakdown(db, *, date_from, date_to_excl, cash_id=None, direction_id=None, department_id=None, etype=None) -> dict` — qaytaradi `{"rows": [{"key","label","source","count","amount","share"}], "hd_total": float, "pay_total": float, "grand_total": float}`. `rows` summa bo'yicha kamayish tartibida.

- [ ] **Step 1: Backup yo'q (yangi fayl) — to'g'ridan test yoz**

`tests/test_expense_breakdown.py`:

```python
"""Harajat turi jamlanma agregatsiyasi testlari."""
from datetime import datetime, date


def _make_data(db):
    """HD (2 tur) + PAY (2 kategoriya) + HD-linked Payment yaratadi."""
    from app.models.database import (
        CashRegister, ExpenseType, ExpenseDoc, ExpenseDocItem, Payment,
    )
    cash = CashRegister(name="K1", payment_type="naqd", is_active=True, opening_balance=0)
    db.add(cash); db.flush()

    t_salary = ExpenseType(name="ish haqqi", is_active=True)
    t_food = ExpenseType(name="oziq ovqatga", is_active=True)
    db.add_all([t_salary, t_food]); db.flush()

    # Tasdiqlangan HD: 100k ish haqqi + 40k oziq-ovqat = 140k, linked Payment
    pay_hd = Payment(type="expense", amount=140000, category="expense",
                     date=datetime(2026, 6, 10, 10, 0), cash_register_id=cash.id,
                     status="confirmed")
    db.add(pay_hd); db.flush()
    doc = ExpenseDoc(number="HD-1", date=datetime(2026, 6, 10, 10, 0),
                     cash_register_id=cash.id, status="confirmed",
                     total_amount=140000, payment_id=pay_hd.id)
    db.add(doc); db.flush()
    db.add_all([
        ExpenseDocItem(expense_doc_id=doc.id, expense_type_id=t_salary.id, amount=100000),
        ExpenseDocItem(expense_doc_id=doc.id, expense_type_id=t_food.id, amount=40000),
    ])

    # Mustaqil PAY chiqimlari (HD bilan bog'lanmagan)
    db.add_all([
        Payment(type="expense", amount=500000, category="other",
                date=datetime(2026, 6, 11, 9, 0), cash_register_id=cash.id, status="confirmed"),
        Payment(type="expense", amount=30000, category="sale_return",
                date=datetime(2026, 6, 12, 9, 0), cash_register_id=cash.id, status="confirmed"),
    ])
    db.commit()
    return cash


def test_parse_etype():
    from app.services.expense_breakdown import parse_etype
    assert parse_etype("et:5") == ("et", 5)
    assert parse_etype("cat:other") == ("cat", "other")
    assert parse_etype("cat:") == ("cat", None)
    assert parse_etype("") is None
    assert parse_etype(None) is None
    assert parse_etype("garbage") is None


def test_breakdown_totals_and_rows(db):
    from app.services.expense_breakdown import compute_type_breakdown
    _make_data(db)
    res = compute_type_breakdown(
        db, date_from=date(2026, 6, 1), date_to_excl=date(2026, 7, 1),
    )
    assert res["hd_total"] == 140000      # 100k + 40k items
    assert res["pay_total"] == 530000     # 500k + 30k
    assert res["grand_total"] == 670000
    labels = {r["label"]: r["amount"] for r in res["rows"]}
    assert labels["ish haqqi"] == 100000
    assert labels["oziq ovqatga"] == 40000
    assert labels["Boshqa to'lov"] == 500000
    assert labels["Sotuv qaytarish"] == 30000
    # eng katta birinchi (kamayish tartibi)
    assert res["rows"][0]["label"] == "Boshqa to'lov"
    # HD-linked Payment double-count qilinmaydi (PAY'da 140k yo'q)
    assert all(r["amount"] != 140000 for r in res["rows"])


def test_breakdown_filter_by_expense_type(db):
    from app.services.expense_breakdown import compute_type_breakdown
    from app.models.database import ExpenseType
    _make_data(db)
    salary = db.query(ExpenseType).filter_by(name="ish haqqi").first()
    res = compute_type_breakdown(
        db, date_from=date(2026, 6, 1), date_to_excl=date(2026, 7, 1),
        etype=f"et:{salary.id}",
    )
    assert res["pay_total"] == 0          # cat tomon bo'sh
    assert res["hd_total"] == 100000
    assert len(res["rows"]) == 1
    assert res["rows"][0]["label"] == "ish haqqi"


def test_breakdown_filter_by_pay_category(db):
    from app.services.expense_breakdown import compute_type_breakdown
    _make_data(db)
    res = compute_type_breakdown(
        db, date_from=date(2026, 6, 1), date_to_excl=date(2026, 7, 1),
        etype="cat:other",
    )
    assert res["hd_total"] == 0
    assert res["pay_total"] == 500000
    assert len(res["rows"]) == 1
```

- [ ] **Step 2: Testni ishga tushir — fail bo'lishini tasdiqla**

Run: `python -m pytest tests/test_expense_breakdown.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.expense_breakdown'`

- [ ] **Step 3: Servis faylini yoz**

`app/services/expense_breakdown.py`:

```python
"""Harajat turi bo'yicha jamlanma agregatsiyasi.

Ikki manbadan yig'adi va double-count'dan qochadi:
  - HD: ExpenseDocItem.amount -> expense_type_id bo'yicha
  - PAY: HD bilan bog'lanmagan Payment.amount -> category bo'yicha
"""
from datetime import datetime

from sqlalchemy import func, or_

from app.models.database import (
    ExpenseDoc, ExpenseDocItem, ExpenseType, Payment,
)

# PAY kategoriya kodi -> o'zbekcha label
PAY_CATEGORY_LABELS = {
    "expense": "Oddiy harajat",
    "other": "Boshqa to'lov",
    "sale_return": "Sotuv qaytarish",
    "delivery": "Yetkazib berish",
    "agent_collection": "Agent inkassa",
    "purchase_expense": "Xarid xarajati",
}


def pay_label(code):
    """PAY kategoriya kodi uchun label."""
    if not code:
        return "Turkumlanmagan"
    return PAY_CATEGORY_LABELS.get(code, code)


def parse_etype(etype):
    """Filtr qiymatini ajratadi.

    "et:5" -> ("et", 5); "cat:other" -> ("cat", "other");
    "cat:" -> ("cat", None); boshqa/bo'sh -> None.
    """
    if not etype:
        return None
    etype = etype.strip()
    if etype.startswith("et:"):
        try:
            return ("et", int(etype[3:]))
        except ValueError:
            return None
    if etype.startswith("cat:"):
        code = etype[4:].strip()
        return ("cat", code or None)
    return None


def compute_type_breakdown(db, *, date_from, date_to_excl,
                           cash_id=None, direction_id=None,
                           department_id=None, etype=None):
    """Harajat turlari bo'yicha jamlanma (filtrlarga bo'ysunadi)."""
    parsed = parse_etype(etype)
    dt_from = datetime.combine(date_from, datetime.min.time())
    dt_to = datetime.combine(date_to_excl, datetime.min.time())
    dirdept = bool(direction_id or department_id)

    rows = []

    # ---- HD qismi: ExpenseDocItem -> expense_type ----
    if parsed is None or parsed[0] == "et":
        q = (
            db.query(
                ExpenseType.id,
                ExpenseType.name,
                func.count(ExpenseDocItem.id),
                func.coalesce(func.sum(ExpenseDocItem.amount), 0),
            )
            .join(ExpenseDoc, ExpenseDocItem.expense_doc_id == ExpenseDoc.id)
            .join(ExpenseType, ExpenseDocItem.expense_type_id == ExpenseType.id)
            .filter(
                ExpenseDoc.status == "confirmed",
                ExpenseDoc.date >= dt_from,
                ExpenseDoc.date < dt_to,
            )
        )
        if cash_id:
            q = q.filter(ExpenseDoc.cash_register_id == cash_id)
        if direction_id:
            q = q.filter(ExpenseDoc.direction_id == direction_id)
        if department_id:
            q = q.filter(ExpenseDoc.department_id == department_id)
        if parsed and parsed[0] == "et":
            q = q.filter(ExpenseType.id == parsed[1])
        q = q.group_by(ExpenseType.id, ExpenseType.name)
        for tid, name, cnt, total in q.all():
            if total:
                rows.append({
                    "key": f"et:{tid}", "label": name, "source": "HD",
                    "count": int(cnt or 0), "amount": float(total or 0),
                })

    # ---- PAY qismi: HD bilan bog'lanmagan Payment -> category ----
    # dirdept o'rnatilsa, oddiy PAY (yo'nalishsiz) chiqariladi
    if (parsed is None or parsed[0] == "cat") and not dirdept:
        hd_pid_subq = (
            db.query(ExpenseDoc.payment_id)
            .filter(ExpenseDoc.payment_id.isnot(None),
                    ExpenseDoc.status != "deleted")
        )
        q = (
            db.query(
                Payment.category,
                func.count(Payment.id),
                func.coalesce(func.sum(Payment.amount), 0),
            )
            .filter(
                Payment.type == "expense",
                Payment.date >= dt_from,
                Payment.date < dt_to,
                or_(Payment.status == "confirmed", Payment.status.is_(None)),
                or_(Payment.category != "audit_correction",
                    Payment.category.is_(None)),
                Payment.id.notin_(hd_pid_subq),
            )
        )
        if cash_id:
            q = q.filter(Payment.cash_register_id == cash_id)
        if parsed and parsed[0] == "cat":
            if parsed[1] is None:
                q = q.filter(Payment.category.is_(None))
            else:
                q = q.filter(Payment.category == parsed[1])
        q = q.group_by(Payment.category)
        for cat, cnt, total in q.all():
            if total:
                rows.append({
                    "key": f"cat:{cat or ''}", "label": pay_label(cat),
                    "source": "PAY", "count": int(cnt or 0),
                    "amount": float(total or 0),
                })

    rows.sort(key=lambda r: r["amount"], reverse=True)
    hd_total = sum(r["amount"] for r in rows if r["source"] == "HD")
    pay_total = sum(r["amount"] for r in rows if r["source"] == "PAY")
    grand_total = hd_total + pay_total
    for r in rows:
        r["share"] = (r["amount"] / grand_total * 100.0) if grand_total else 0.0
    return {
        "rows": rows, "hd_total": hd_total,
        "pay_total": pay_total, "grand_total": grand_total,
    }
```

- [ ] **Step 4: Testni ishga tushir — pass bo'lishini tasdiqla**

Run: `python -m pytest tests/test_expense_breakdown.py -v`
Expected: PASS (4 ta test)

- [ ] **Step 5: Commit**

```powershell
git add app/services/expense_breakdown.py tests/test_expense_breakdown.py
git commit -m "feat(finance): harajat turi jamlanma agregatsiya servisi"
```

---

### Task 2: Route'ni `etype` ga ulash (`finance.py`)

**Files:**
- Modify: `app/routes/finance.py` (funksiya `finance_harajatlar`, ~291-658)
- Test: `tests/test_harajatlar_etype.py`

**Interfaces:**
- Consumes: `compute_type_breakdown`, `PAY_CATEGORY_LABELS`, `parse_etype` (Task 1).
- Produces (template context kalitlari): `type_breakdown` (dict), `expense_types` (ExpenseType ro'yxati), `pay_category_options` (list[tuple[str,str]] — `(code,label)`), `sel_etype` (str). `kind`/`kind_options` olib tashlanadi.

- [ ] **Step 1: Backup ol**

```powershell
Copy-Item "app/routes/finance.py" "app/routes/finance.py.bak_pre_etype_breakdown_20260628"
```

- [ ] **Step 2: Endpoint testini yoz**

`tests/test_harajatlar_etype.py`:

```python
"""Harajatlar jurnali — etype filtr + jamlanma endpoint testi."""
from datetime import datetime


def _setup(db):
    from app.models.database import (
        CashRegister, ExpenseType, ExpenseDoc, ExpenseDocItem, Payment,
    )
    cash = CashRegister(name="K1", payment_type="naqd", is_active=True, opening_balance=0)
    db.add(cash); db.flush()
    t = ExpenseType(name="ish haqqi", is_active=True)
    db.add(t); db.flush()
    pay_hd = Payment(type="expense", amount=100000, category="expense",
                     date=datetime(2026, 6, 10, 10, 0), cash_register_id=cash.id,
                     status="confirmed")
    db.add(pay_hd); db.flush()
    doc = ExpenseDoc(number="HD-1", date=datetime(2026, 6, 10, 10, 0),
                     cash_register_id=cash.id, status="confirmed",
                     total_amount=100000, payment_id=pay_hd.id)
    db.add(doc); db.flush()
    db.add(ExpenseDocItem(expense_doc_id=doc.id, expense_type_id=t.id, amount=100000))
    db.add(Payment(type="expense", amount=500000, category="other",
                   date=datetime(2026, 6, 11, 9, 0), cash_register_id=cash.id,
                   status="confirmed"))
    db.commit()
    return t


def _auth(client, admin_user):
    from app.utils.auth import create_session_token
    from app.deps import get_current_user
    from main import app
    token = create_session_token(admin_user.id, user_type="user")
    app.dependency_overrides[get_current_user] = lambda: admin_user
    client.cookies.set("session_token", token)


def test_harajatlar_shows_breakdown(client, db, admin_user):
    _setup(db)
    _auth(client, admin_user)
    from main import app
    try:
        resp = client.get("/finance/harajatlar?show_all=1", follow_redirects=False)
        assert resp.status_code == 200
        assert "ish haqqi" in resp.text          # HD turi jamlanmada
        assert "Boshqa to'lov" in resp.text       # PAY kategoriya labeli
    finally:
        app.dependency_overrides.clear()


def test_harajatlar_etype_filter_pay(client, db, admin_user):
    _setup(db)
    _auth(client, admin_user)
    from main import app
    try:
        resp = client.get("/finance/harajatlar?show_all=1&etype=cat:other",
                          follow_redirects=False)
        assert resp.status_code == 200
        # faqat PAY 'other' qatori — HD turi jamlanmadan tushib qoladi
        assert "Boshqa to'lov" in resp.text
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 3: Testni ishga tushir — fail bo'lishini tasdiqla**

Run: `python -m pytest tests/test_harajatlar_etype.py -v`
Expected: FAIL — `type_breakdown` / "ish haqqi" topilmaydi (yoki jamlanma jadvali yo'q).

- [ ] **Step 4: Import qo'sh** (`app/routes/finance.py` yuqorisidagi importlar bo'limiga, mavjud `from app.services...` importlari yoniga)

```python
from app.services.expense_breakdown import (
    compute_type_breakdown, parse_etype, PAY_CATEGORY_LABELS,
)
```

- [ ] **Step 5: Funksiya imzosida `kind` -> `etype`**

`finance.py:302` ni almashtirish:

```python
    etype: Optional[str] = None,
```

(`kind: Optional[str] = None,` qatori o'rniga)

- [ ] **Step 6: `kind` normalizatsiyasini almashtirish**

`finance.py:322` (`kind = (kind or "").strip() or None`) o'rniga:

```python
    etype = (etype or "").strip() or None
    _parsed_etype = parse_etype(etype)
```

- [ ] **Step 7: HD ro'yxati filtrini almashtirish**

`finance.py:349-352` (`_show_hd = kind in (...)` bloki) o'rniga:

```python
    # Tur filtri (HD): 'et:<id>' -> shu turdagi qatori bor hujjatlar; 'cat:*' -> HD yashiriladi
    if _parsed_etype and _parsed_etype[0] == "et":
        _item_exists = db.query(ExpenseDocItem.id).filter(
            ExpenseDocItem.expense_doc_id == ExpenseDoc.id,
            ExpenseDocItem.expense_type_id == _parsed_etype[1],
        ).exists()
        expense_docs_q = expense_docs_q.filter(_item_exists)
    elif _parsed_etype and _parsed_etype[0] == "cat":
        expense_docs_q = expense_docs_q.filter(ExpenseDoc.id == -1)
```

`ExpenseDocItem` import bo'lganini tekshir — yo'q bo'lsa `finance.py` modeldan importiga qo'sh.

- [ ] **Step 8: O'lik xarid `kind` filtrini olib tashlash**

`finance.py:384-386` (`_show_xarid = kind in (...)` va `if not _show_xarid:` bloki) o'chiriladi (purchases_with_expenses baribir `[]` ga o'rnatiladi — o'lik kod).

- [ ] **Step 9: PAY ro'yxati filtrini almashtirish**

`finance.py:445-446` (`if kind: q = q.filter(Payment.category == kind)`) o'rniga:

```python
    if _parsed_etype and _parsed_etype[0] == "cat":
        if _parsed_etype[1] is None:
            q = q.filter(Payment.category.is_(None))
        else:
            q = q.filter(Payment.category == _parsed_etype[1])
    elif _parsed_etype and _parsed_etype[0] == "et":
        q = q.filter(Payment.id == -1)
```

- [ ] **Step 10: O'lik purchase_expenses `kind` filtrini olib tashlash**

`finance.py:480-481` (`if kind and kind != "supplier_payment":` bloki) o'chiriladi (`purchase_expenses_list` baribir `[]`).

- [ ] **Step 11: Stats hisobini jamlanmadan oziqlantirish**

`finance.py:584-630` oralig'idagi `_apply_stat_filters` / `period_payments` / `docs_sum` / `other_sum` / `stats` bloki o'rniga (stat_from / stat_to_excl hisobidan KEYIN, ya'ni 582-qatordan keyin):

```python
    type_breakdown = compute_type_breakdown(
        db, date_from=stat_from, date_to_excl=stat_to_excl,
        cash_id=cash_id, direction_id=direction_id,
        department_id=department_id, etype=etype,
    )
    stats = {
        "today_income": 0,
        "today_expense": type_breakdown["grand_total"],
        "today_expense_docs": type_breakdown["hd_total"],
        "today_expense_other": type_breakdown["pay_total"],
    }
```

`_apply_stat_filters`, `period_payments`, `payment_ids`, `hd_payment_ids`, `docs_sum`, `other_sum` qatorlari (584-624) o'chiriladi. `or_` / `OperationalError` importlari boshqa joyda ishlatilmasa qolaversa zarari yo'q.

- [ ] **Step 12: Dropdown ma'lumotlari + context kalitlarini almashtirish**

`finance.py:331` yonidagi `directions`/`departments` so'rovlari yoniga qo'sh:

```python
    expense_types = db.query(ExpenseType).filter(
        ExpenseType.is_active == True
    ).order_by(ExpenseType.name).all()
    pay_category_options = list(PAY_CATEGORY_LABELS.items())
```

`ExpenseType` import bo'lganini tekshir.

`TemplateResponse` context'ida (`finance.py:631-658`) `"kind_options": [...]` (648-654) va `"sel_kind": kind or ""` (647) o'rniga:

```python
        "sel_etype": etype or "",
        "expense_types": expense_types,
        "pay_category_options": pay_category_options,
        "type_breakdown": type_breakdown,
```

- [ ] **Step 13: Sintaksis tekshir + testni ishga tushir**

Run: `python -c "import ast; ast.parse(open('app/routes/finance.py', encoding='utf-8').read()); print('OK')"`
Expected: `OK`

Run: `python -m pytest tests/test_harajatlar_etype.py tests/test_expense_breakdown.py -v`
Expected: Task 1 testlari PASS; `test_harajatlar_shows_breakdown` hozircha "ish haqqi" topa olmasligi mumkin (jadval template'da yo'q) — Task 3 da hal bo'ladi. `test_harajatlar_etype_filter_pay` 200 qaytarishi kerak. Status 200 lar PASS bo'lsin; matn assertlari Task 3 dan keyin yashil bo'ladi.

> Eslatma: agar matn assertlari (`"ish haqqi" in resp.text`) hali fail bo'lsa — bu kutilgan, Task 3 jadvalni qo'shgach o'tadi. Status `== 200` PASS bo'lishi shart.

- [ ] **Step 14: Commit**

```powershell
git add app/routes/finance.py tests/test_harajatlar_etype.py
git commit -m "feat(finance): harajatlar route etype filtr + jamlanma stats"
```

---

### Task 3: Template — "Harajat turi" dropdown + jamlanma jadvali

**Files:**
- Modify: `app/templates/finance/harajatlar.html` (filtr bloki 78-86; stats'dan keyin 108)

**Interfaces:**
- Consumes (Task 2 context): `expense_types`, `pay_category_options`, `sel_etype`, `type_breakdown`.

- [ ] **Step 1: Backup ol**

```powershell
Copy-Item "app/templates/finance/harajatlar.html" "app/templates/finance/harajatlar.html.bak_pre_etype_breakdown_20260628"
```

- [ ] **Step 2: "Tur" dropdown'ni "Harajat turi"ga almashtir**

`harajatlar.html:78-86` (`<div class="col-auto"> ... name="kind" ... </div>`) bloki o'rniga:

```html
        <div class="col-auto">
            <label class="form-label small mb-1">Harajat turi</label>
            <select name="etype" class="form-select form-select-sm">
                <option value="">— Barchasi —</option>
                <optgroup label="Harajat turlari (HD)">
                    {% for t in expense_types %}
                    <option value="et:{{ t.id }}" {% if sel_etype == 'et:' ~ t.id|string %}selected{% endif %}>{{ t.name }}</option>
                    {% endfor %}
                </optgroup>
                <optgroup label="To'lov kategoriyalari (PAY)">
                    {% for code, lbl in pay_category_options %}
                    <option value="cat:{{ code }}" {% if sel_etype == 'cat:' ~ code %}selected{% endif %}>{{ lbl }}</option>
                    {% endfor %}
                </optgroup>
            </select>
        </div>
```

- [ ] **Step 3: Jamlanma jadvalini qo'sh**

`harajatlar.html:108` (stats `</div>` — mini-stats blokining yopilishi) dan KEYIN, "Harajat hujjatlari" jadvalidan (`<!-- Harajat hujjatlari -->`, 110) OLDIN qo'sh:

```html
    <!-- Tur bo'yicha jamlanma -->
    <div class="data-table mb-4">
        <div class="card-header">
            <span><i class="bi bi-pie-chart text-muted me-1"></i> Tur bo'yicha jamlanma</span>
        </div>
        <div class="table-responsive">
            <table class="table table-sm table-hover mb-0">
                <thead>
                    <tr>
                        <th>Tur</th>
                        <th width="80">Manba</th>
                        <th width="80" class="text-end">Soni</th>
                        <th class="text-end">Summa (so'm)</th>
                        <th width="90" class="text-end">Ulush</th>
                    </tr>
                </thead>
                <tbody>
                    {% for r in type_breakdown.rows %}
                    <tr>
                        <td>{{ r.label }}</td>
                        <td><span class="badge {% if r.source == 'HD' %}bg-primary{% else %}bg-secondary{% endif %}">{{ r.source }}</span></td>
                        <td class="text-end muted-cell">{{ r.count }}</td>
                        <td class="sum-cell text-danger text-end">{{ "{:,.0f}".format(r.amount) }}</td>
                        <td class="text-end muted-cell">{{ "{:.0f}".format(r.share) }}%</td>
                    </tr>
                    {% else %}
                    <tr><td colspan="5" class="text-center text-muted py-3">Tanlangan oraliqda harajat yo'q.</td></tr>
                    {% endfor %}
                </tbody>
                {% if type_breakdown.rows %}
                <tfoot>
                    <tr class="fw-bold">
                        <td colspan="3">JAMI</td>
                        <td class="sum-cell text-danger text-end">{{ "{:,.0f}".format(type_breakdown.grand_total) }}</td>
                        <td class="text-end">100%</td>
                    </tr>
                </tfoot>
                {% endif %}
            </table>
        </div>
    </div>
```

- [ ] **Step 4: Endpoint testlarini ishga tushir — pass bo'lishini tasdiqla**

Run: `python -m pytest tests/test_harajatlar_etype.py -v`
Expected: PASS (2 ta test — endi "ish haqqi" va "Boshqa to'lov" jadvalda ko'rinadi)

- [ ] **Step 5: To'liq test to'plamini ishga tushir (regress yo'qligini tekshir)**

Run: `python -m pytest tests/test_expense_breakdown.py tests/test_harajatlar_etype.py -v`
Expected: barcha testlar PASS

- [ ] **Step 6: Commit**

```powershell
git add app/templates/finance/harajatlar.html
git commit -m "feat(finance): Harajat turi dropdown + Tur bo'yicha jamlanma jadvali"
```

---

## Self-Review natijasi

**Spec coverage:**
- Filtr "Tur" → "Harajat turi" (optgroup, et:/cat:) → Task 2 (route), Task 3 (template). ✔
- Jamlanma jadvali (Tur/Manba/Soni/Summa/Ulush, double-count'siz, JAMI mos) → Task 1 (servis), Task 3 (jadval). ✔
- Barcha filtrlarga bo'ysunish (sana/kassa/yo'nalish/bo'lim) → `compute_type_breakdown` parametrlari + Task 2 Step 11. ✔
- Bekor qilingan to'lovlar kirmaydi → servis `status` filtri. ✔
- YAGNI (eksport/grafik/oylik-avans ajratish yo'q) → rejaga kiritilmadi. ✔

**Placeholder scan:** TBD/TODO yo'q; har kod qadami to'liq kod bilan. ✔

**Type consistency:** `compute_type_breakdown` qaytaradigan kalitlar (`rows/hd_total/pay_total/grand_total`, qator ichida `key/label/source/count/amount/share`) Task 1 da aniqlangan va Task 2/3 da bir xil ishlatilgan. `parse_etype` natijasi (`("et",int)`/`("cat",str|None)`/`None`) barcha tasklarda izchil. ✔

## Deploy eslatma (reja tashqarisida, ixtiyoriy)

Server xavfsiz qayta ishga tushirilishi kerak (loyiha runbook). O'zgarish faqat 1 ta yangi servis + 1 route + 1 template — tungi oyna shart emas, lekin tasdiqlangandan keyin smoke (`/finance/harajatlar`) tekshiruvi tavsiya etiladi.
