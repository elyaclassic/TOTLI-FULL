# Mijoz Telegram boti — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mijozlar uchun alohida Telegram bot — mijoz telefon raqami orqali ulanadi, admin tasdiqlaydi, keyin o'z buyurtmalari, to'lovlari va qarz/avans qoldig'ini faqat o'qiy oladi; muhim hodisalarda (buyurtma tasdiq, yuklash, yetkazish, to'lov) push xabar oladi.

**Architecture:** Mustaqil aiogram 3.x process (o'z tokeni, socket-lock 47893). Toza logika (telefon normallashtirish, partner matching, DB so'rovlari, xabar matni) Telegram I/O dan ajratilgan — bu qism pytest bilan testlanadi. Web ilova 4 ta route'da `notify_customer()` ni fire-and-forget chaqiradi (jonli tizimga 0 ta'sir). Mijoz↔Telegram bog'lanishi yangi additive `customer_bot_links` jadvalida.

**Tech Stack:** Python, aiogram 3.27, SQLAlchemy, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-05-29-customer-telegram-bot-design.md`

---

## Boshlanishidan oldin: izolyatsiya

Bu reja `safe-fix-customer-bot` branch (yoki worktree) da bajariladi — `main` ga tegilmaydi. Commitlar feature branch'ga boradi. `main` ga merge va prod deploy — **tungi oyna (00:00–04:00)**, foydalanuvchi tasdig'i bilan (Tier B hooklar bor).

Tekshirish buyrug'i (har test uchun): in-memory SQLite, live DB ga tegmaydi.
```
cd "D:\TOTLI BI"
python -m pytest tests/test_customer_bot.py -v
```

---

## Fayl tuzilishi

| Fayl | Vazifa |
|---|---|
| `app/models/database.py` | `CustomerBotLink` model (additive) |
| `app/bot/customer_bot/__init__.py` | bo'sh paket marker |
| `app/bot/customer_bot/config.py` | env: token, admin ids, lock port |
| `app/bot/customer_bot/phone.py` | `normalize_phone()` — toza |
| `app/bot/customer_bot/registration.py` | partner matching + link lifecycle (DB) |
| `app/bot/customer_bot/queries.py` | balans/buyurtma/hisobot so'rovlari + matn (DB+toza) |
| `app/bot/customer_bot/notify.py` | `notify_customer()` I/O + xabar matni quruvchilar |
| `app/bot/customer_bot/handlers.py` | aiogram handlerlar (I/O) |
| `app/bot/customer_bot/bot.py` | Bot+Dispatcher+polling |
| `scripts/customer_bot_standalone.py` | socket-lock + runner |
| `tests/test_customer_bot.py` | barcha unit testlar |
| `app/routes/sales.py` | 2 hook (confirm, dispatch) |
| `app/routes/api_driver_ops.py` | 1 hook (delivered) |
| `app/routes/delivery_routes.py` | 1 hook (agent payment confirm) |
| `start.bat` | launch/kill bloklari |

---

## Task 1: CustomerBotLink model

**Files:**
- Modify: `app/models/database.py` (yangi class qo'shish, ChatTelegramLink yonida)
- Test: `tests/test_customer_bot.py`

- [ ] **Step 1: Failing test yozish**

```python
# tests/test_customer_bot.py
from datetime import datetime


def test_customer_bot_link_create(db):
    from app.models.database import CustomerBotLink
    link = CustomerBotLink(
        telegram_id="111222333",
        telegram_username="akbar",
        telegram_full_name="Akbarjon",
        phone="905565959",
        status="pending",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    assert link.id is not None
    assert link.status == "pending"
    assert link.partner_id is None
    assert link.requested_at is not None
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py::test_customer_bot_link_create -v`
Expected: FAIL — `ImportError: cannot import name 'CustomerBotLink'`

- [ ] **Step 3: Model qo'shish**

`app/models/database.py` da `ChatTelegramLink` class'idan keyin (taxminan :236 atrofida) qo'shing:

```python
class CustomerBotLink(Base):
    """Mijoz Telegram boti — mijoz (Partner) <-> Telegram bog'lanishi."""
    __tablename__ = "customer_bot_links"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), unique=True, index=True)
    telegram_username = Column(String(100), nullable=True)
    telegram_full_name = Column(String(200), nullable=True)
    phone = Column(String(20))
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True, index=True)
    status = Column(String(20), default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.now)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(100), nullable=True)
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py::test_customer_bot_link_create -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/database.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): CustomerBotLink model (additive)"
```

---

## Task 2: Telefon normallashtirish

**Files:**
- Create: `app/bot/customer_bot/__init__.py` (bo'sh)
- Create: `app/bot/customer_bot/phone.py`
- Test: `tests/test_customer_bot.py`

- [ ] **Step 1: Failing testlar**

```python
def test_normalize_phone_formats():
    from app.bot.customer_bot.phone import normalize_phone
    # turli format — barchasi oxirgi 9 raqamga keladi
    assert normalize_phone("+998905565959") == "905565959"
    assert normalize_phone("998905565959") == "905565959"
    assert normalize_phone("99899 652 82 60") == "996528260"  # oxirgi 9
    assert normalize_phone("+998 90 556 59 59") == "905565959"


def test_normalize_phone_invalid():
    from app.bot.customer_bot.phone import normalize_phone
    assert normalize_phone("0.....") is None     # 9 raqamdan kam
    assert normalize_phone("") is None
    assert normalize_phone(None) is None
    assert normalize_phone("12345") is None       # 5 raqam
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k normalize_phone -v`
Expected: FAIL — `ModuleNotFoundError: app.bot.customer_bot.phone`

- [ ] **Step 3: Implementatsiya**

`app/bot/customer_bot/__init__.py` — bo'sh fayl yarating.

`app/bot/customer_bot/phone.py`:
```python
import re


def normalize_phone(raw):
    """Raqamni faqat raqamlarga keltirib, oxirgi 9 xonani (milliy qism) qaytaradi.

    +998905565959 / 998905565959 / "99899 652 82 60" -> oxirgi 9 raqam.
    9 raqamdan kam bo'lsa (soxta '0.....') -> None.
    """
    digits = re.sub(r"\D", "", raw or "")
    return digits[-9:] if len(digits) >= 9 else None
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k normalize_phone -v`
Expected: PASS (2 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/__init__.py app/bot/customer_bot/phone.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): normalize_phone (oxirgi 9 raqam matching)"
```

---

## Task 3: Partner matching

**Files:**
- Create: `app/bot/customer_bot/registration.py`
- Test: `tests/test_customer_bot.py`

Eslatma: type bo'yicha filtr QILMAYMIZ (DB'da type qiymatlari noaniq bo'lishi mumkin; admin tasdiq baribir gate). Faqat `is_active == True` + telefon mosligi.

- [ ] **Step 1: Failing testlar**

```python
def _mk_partner(db, name, phone, phone2=None, active=True):
    from app.models.database import Partner
    p = Partner(name=name, phone=phone, phone2=phone2, is_active=active, balance=0)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_find_matching_partner_diff_formats(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Gellet Market", "+998902924002")
    _mk_partner(db, "olmos market", "998910558888")
    # Telegram '998902924002' yuboradi -> +998902924002 ga mos
    res = find_matching_partners(db, "998902924002")
    assert len(res) == 1
    assert res[0].name == "Gellet Market"


def test_find_matching_partner_phone2(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Benazir", "+998938000458", phone2="+998331777727")
    res = find_matching_partners(db, "998331777727")
    assert len(res) == 1
    assert res[0].name == "Benazir"


def test_find_matching_partner_none(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Gellet Market", "+998902924002")
    assert find_matching_partners(db, "998000000000") == []
    assert find_matching_partners(db, "0.....") == []


def test_find_matching_partner_skips_inactive(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Eski", "+998905565959", active=False)
    assert find_matching_partners(db, "998905565959") == []


def test_find_matching_partner_multiple(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Do'kon A", "+998905565959")
    _mk_partner(db, "Do'kon B", "905565959")
    res = find_matching_partners(db, "998905565959")
    assert len(res) == 2
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k find_matching -v`
Expected: FAIL — `ModuleNotFoundError: registration`

- [ ] **Step 3: Implementatsiya**

`app/bot/customer_bot/registration.py`:
```python
from datetime import datetime

from app.models.database import Partner, CustomerBotLink
from app.bot.customer_bot.phone import normalize_phone


def find_matching_partners(db, phone):
    """Telefon mos keluvchi aktiv partnerlar ro'yxati (phone yoki phone2)."""
    norm = normalize_phone(phone)
    if not norm:
        return []
    partners = db.query(Partner).filter(Partner.is_active == True).all()  # noqa: E712
    return [
        p for p in partners
        if normalize_phone(p.phone) == norm or normalize_phone(p.phone2) == norm
    ]
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k find_matching -v`
Expected: PASS (5 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/registration.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): find_matching_partners (phone+phone2)"
```

---

## Task 4: Link lifecycle (create/approve/reject/get)

**Files:**
- Modify: `app/bot/customer_bot/registration.py`
- Test: `tests/test_customer_bot.py`

- [ ] **Step 1: Failing testlar**

```python
def test_link_lifecycle(db):
    from app.bot.customer_bot import registration as reg
    p = _mk_partner(db, "Gellet", "+998902924002")

    # mavjud emas
    assert reg.get_link_by_telegram(db, "555") is None

    # pending yaratish
    link = reg.create_pending_link(db, "555", "akbar", "Akbarjon", "902924002")
    assert link.status == "pending"
    assert reg.get_link_by_telegram(db, "555").id == link.id

    # tasdiqlash
    approved = reg.approve_link(db, link.id, p.id, "admin1340")
    assert approved.status == "approved"
    assert approved.partner_id == p.id
    assert approved.approved_at is not None
    assert approved.approved_by == "admin1340"


def test_link_reject(db):
    from app.bot.customer_bot import registration as reg
    link = reg.create_pending_link(db, "777", None, "Test", "900000000")
    rejected = reg.reject_link(db, link.id, "admin1340")
    assert rejected.status == "rejected"


def test_approved_link_lookup_by_partner(db):
    from app.bot.customer_bot import registration as reg
    p = _mk_partner(db, "Gellet", "+998902924002")
    link = reg.create_pending_link(db, "555", "a", "A", "902924002")
    reg.approve_link(db, link.id, p.id, "admin")
    ids = reg.approved_telegram_ids_for_partner(db, p.id)
    assert ids == ["555"]
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k "link" -v`
Expected: FAIL — `AttributeError: get_link_by_telegram`

- [ ] **Step 3: Implementatsiya — registration.py ga qo'shish**

```python
def get_link_by_telegram(db, telegram_id):
    return db.query(CustomerBotLink).filter(
        CustomerBotLink.telegram_id == str(telegram_id)
    ).first()


def create_pending_link(db, telegram_id, username, full_name, phone):
    link = get_link_by_telegram(db, telegram_id)
    if link is None:
        link = CustomerBotLink(telegram_id=str(telegram_id))
        db.add(link)
    link.telegram_username = username
    link.telegram_full_name = full_name
    link.phone = phone
    link.status = "pending"
    link.partner_id = None
    link.requested_at = datetime.now()
    db.commit()
    db.refresh(link)
    return link


def approve_link(db, link_id, partner_id, approved_by):
    link = db.query(CustomerBotLink).filter(CustomerBotLink.id == link_id).first()
    link.status = "approved"
    link.partner_id = partner_id
    link.approved_at = datetime.now()
    link.approved_by = str(approved_by)
    db.commit()
    db.refresh(link)
    return link


def reject_link(db, link_id, approved_by):
    link = db.query(CustomerBotLink).filter(CustomerBotLink.id == link_id).first()
    link.status = "rejected"
    link.approved_by = str(approved_by)
    db.commit()
    db.refresh(link)
    return link


def approved_telegram_ids_for_partner(db, partner_id):
    rows = db.query(CustomerBotLink).filter(
        CustomerBotLink.partner_id == partner_id,
        CustomerBotLink.status == "approved",
    ).all()
    return [r.telegram_id for r in rows]
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k "link" -v`
Expected: PASS (3 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/registration.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): link lifecycle (create/approve/reject)"
```

---

## Task 5: Matn formatlash (toza)

**Files:**
- Create: `app/bot/customer_bot/queries.py`
- Test: `tests/test_customer_bot.py`

- [ ] **Step 1: Failing testlar**

```python
def test_fmt_money():
    from app.bot.customer_bot.queries import fmt_money
    assert fmt_money(1493000) == "1 493 000"
    assert fmt_money(0) == "0"
    assert fmt_money(1493000.0) == "1 493 000"


def test_balance_text():
    from app.bot.customer_bot.queries import balance_text

    class P:
        pass
    p = P()
    p.balance = 1493000
    assert "Qarz" in balance_text(p) and "1 493 000" in balance_text(p)
    p.balance = -50000
    assert "Avans" in balance_text(p) and "50 000" in balance_text(p)
    p.balance = 0
    assert "yo'q" in balance_text(p).lower()


def test_order_status_label():
    from app.bot.customer_bot.queries import order_status_label
    assert order_status_label("confirmed") == "Qabul qilindi"
    assert order_status_label("out_for_delivery") == "Yo'lda"
    assert order_status_label("delivered") == "Yetkazildi"
    assert order_status_label("cancelled") == "Bekor qilindi"
    assert order_status_label("waiting_production") == "Ishlab chiqarishda"
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k "fmt_money or balance_text or status_label" -v`
Expected: FAIL — `ModuleNotFoundError: queries`

- [ ] **Step 3: Implementatsiya**

`app/bot/customer_bot/queries.py`:
```python
from sqlalchemy import func as sa_func

from app.models.database import Order, OrderItem, Payment, Partner

_STATUS_LABELS = {
    "draft": "Qoralama",
    "confirmed": "Qabul qilindi",
    "waiting_production": "Ishlab chiqarishda",
    "out_for_delivery": "Yo'lda",
    "delivered": "Yetkazildi",
    "completed": "Yetkazildi",
    "cancelled": "Bekor qilindi",
}


def fmt_money(amount):
    return f"{int(round(amount or 0)):,}".replace(",", " ")


def balance_text(partner):
    bal = partner.balance or 0
    if bal > 0:
        return f"💰 Qarzingiz: <b>{fmt_money(bal)}</b> so'm"
    if bal < 0:
        return f"💰 Avans qoldig'ingiz: <b>{fmt_money(-bal)}</b> so'm"
    return "✅ Qarzdorlik yo'q"


def order_status_label(status):
    return _STATUS_LABELS.get(status, status or "")
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k "fmt_money or balance_text or status_label" -v`
Expected: PASS (3 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/queries.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): matn formatlash (fmt_money/balance/status)"
```

---

## Task 6: Buyurtma va hisobot so'rovlari (DB)

**Files:**
- Modify: `app/bot/customer_bot/queries.py`
- Test: `tests/test_customer_bot.py`

- [ ] **Step 1: Failing testlar**

```python
def _mk_order(db, partner_id, number, total, paid, status, date_str):
    from datetime import datetime
    from app.models.database import Order
    o = Order(
        number=number, partner_id=partner_id, type="sale", source="agent",
        subtotal=total, total=total, paid=paid, debt=total - paid, status=status,
        date=datetime.strptime(date_str, "%Y-%m-%d"),
    )
    db.add(o)
    db.commit()
    db.refresh(o)
    return o


def test_recent_orders_limit_and_order(db):
    from app.bot.customer_bot.queries import recent_orders
    p = _mk_partner(db, "Gellet", "+998902924002")
    _mk_order(db, p.id, "AGT-1", 100000, 0, "delivered", "2026-05-01")
    _mk_order(db, p.id, "AGT-2", 200000, 0, "confirmed", "2026-05-10")
    res = recent_orders(db, p.id, limit=10)
    assert [o.number for o in res] == ["AGT-2", "AGT-1"]  # yangi birinchi


def test_statement_totals_in_range(db):
    from datetime import date
    from app.models.database import Payment
    from app.bot.customer_bot.queries import statement
    p = _mk_partner(db, "Gellet", "+998902924002")
    _mk_order(db, p.id, "AGT-1", 100000, 0, "delivered", "2026-05-05")
    _mk_order(db, p.id, "AGT-2", 50000, 0, "delivered", "2026-04-20")  # oraliqdan tashqari
    pay = Payment(number="PAY-1", type="income", partner_id=p.id, amount=30000,
                  status="confirmed", category="sale")
    from datetime import datetime
    pay.date = datetime(2026, 5, 6)
    db.add(pay)
    db.commit()

    st = statement(db, p.id, date(2026, 5, 1), date(2026, 5, 31))
    assert st["total_orders"] == 100000      # faqat AGT-1
    assert st["total_paid"] == 30000
    assert len(st["orders"]) == 1
    assert len(st["payments"]) == 1
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k "recent_orders or statement" -v`
Expected: FAIL — `AttributeError: recent_orders`

- [ ] **Step 3: Implementatsiya — queries.py ga qo'shish**

```python
def recent_orders(db, partner_id, limit=10):
    return (
        db.query(Order)
        .filter(Order.partner_id == partner_id, Order.type == "sale")
        .order_by(Order.date.desc(), Order.id.desc())
        .limit(limit)
        .all()
    )


def statement(db, partner_id, date_from, date_to):
    """date_from/date_to — datetime.date. Tashkent local vaqt: sa_func.date ishlatamiz."""
    orders = (
        db.query(Order)
        .filter(
            Order.partner_id == partner_id,
            Order.type == "sale",
            sa_func.date(Order.date) >= date_from,
            sa_func.date(Order.date) <= date_to,
        )
        .order_by(Order.date.asc())
        .all()
    )
    payments = (
        db.query(Payment)
        .filter(
            Payment.partner_id == partner_id,
            Payment.type == "income",
            Payment.status == "confirmed",
            sa_func.date(Payment.date) >= date_from,
            sa_func.date(Payment.date) <= date_to,
        )
        .order_by(Payment.date.asc())
        .all()
    )
    return {
        "orders": orders,
        "payments": payments,
        "total_orders": sum(o.total or 0 for o in orders),
        "total_paid": sum(p.amount or 0 for p in payments),
    }
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k "recent_orders or statement" -v`
Expected: PASS (2 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/queries.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): recent_orders + statement (sana oraliq)"
```

---

## Task 6B: parse_date_uz — sana matnini o'qish (toza)

**Files:**
- Modify: `app/bot/customer_bot/queries.py`
- Test: `tests/test_customer_bot.py`

Qo'lda oraliq tanlash uchun mijoz yozgan sanani parse qilamiz.

- [ ] **Step 1: Failing testlar**

```python
def test_parse_date_uz():
    from datetime import date
    from app.bot.customer_bot.queries import parse_date_uz
    assert parse_date_uz("15.05.2026") == date(2026, 5, 15)
    assert parse_date_uz("15.5.2026") == date(2026, 5, 15)
    assert parse_date_uz("2026-05-15") == date(2026, 5, 15)
    assert parse_date_uz("15/05/2026") == date(2026, 5, 15)


def test_parse_date_uz_invalid():
    from app.bot.customer_bot.queries import parse_date_uz
    assert parse_date_uz("salom") is None
    assert parse_date_uz("32.13.2026") is None
    assert parse_date_uz("") is None
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k parse_date -v`
Expected: FAIL — `AttributeError: parse_date_uz`

- [ ] **Step 3: Implementatsiya — queries.py ga qo'shish (yuqorida `from datetime import date` qo'shing)**

```python
from datetime import date as _date


def parse_date_uz(text):
    """'15.05.2026' / '15.5.2026' / '2026-05-15' / '15/05/2026' -> date yoki None."""
    s = (text or "").strip()
    for sep in (".", "/", "-"):
        parts = s.split(sep)
        if len(parts) == 3:
            try:
                a, b, c = (int(x) for x in parts)
            except ValueError:
                continue
            try:
                if len(parts[0]) == 4:  # yyyy-mm-dd
                    return _date(a, b, c)
                return _date(c, b, a)   # dd.mm.yyyy
            except ValueError:
                return None
    return None
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k parse_date -v`
Expected: PASS (2 ta test)

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/queries.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): parse_date_uz (qo'lda oraliq uchun)"
```

---

## Task 7: Bildirishnoma xabar matnlari (toza)

**Files:**
- Create: `app/bot/customer_bot/notify.py`
- Test: `tests/test_customer_bot.py`

- [ ] **Step 1: Failing testlar**

```python
def test_notify_messages():
    from app.bot.customer_bot.notify import (
        msg_order_confirmed, msg_order_dispatched,
        msg_order_delivered, msg_agent_payment,
    )

    class O:
        pass
    o = O(); o.number = "AGT-20260529-001"; o.total = 250000; o.paid = 100000

    assert "AGT-20260529-001" in msg_order_confirmed(o)
    assert "250 000" in msg_order_confirmed(o)

    assert "yo'lda" in msg_order_dispatched(o).lower()
    assert "AGT-20260529-001" in msg_order_dispatched(o)

    dm = msg_order_delivered(o, balance=150000)
    assert "yetkazildi" in dm.lower()
    assert "100 000" in dm        # to'langan
    assert "150 000" in dm        # qoldiq

    am = msg_agent_payment("AG-001", "Akbarjon", 500000, balance=150000)
    assert "AG-001" in am and "Akbarjon" in am
    assert "500 000" in am and "150 000" in am
```

- [ ] **Step 2: Test ishlamasligini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k notify_messages -v`
Expected: FAIL — `ModuleNotFoundError: notify`

- [ ] **Step 3: Implementatsiya (xabar quruvchilar — I/O qismi keyingi taskda)**

`app/bot/customer_bot/notify.py`:
```python
from app.bot.customer_bot.queries import fmt_money


def msg_order_confirmed(order):
    return (
        f"✅ Buyurtmangiz qabul qilindi\n"
        f"№ {order.number}\n"
        f"Summa: <b>{fmt_money(order.total)}</b> so'm"
    )


def msg_order_dispatched(order):
    return (
        f"🚚 Buyurtmangiz yo'lda\n"
        f"№ {order.number}\n"
        f"Tez orada yetkaziladi."
    )


def msg_order_delivered(order, balance):
    return (
        f"📦 Buyurtma yetkazildi\n"
        f"№ {order.number}\n"
        f"To'langan: <b>{fmt_money(order.paid)}</b> so'm\n"
        f"Joriy qoldiq: <b>{fmt_money(balance)}</b> so'm"
    )


def msg_agent_payment(agent_code, agent_name, amount, balance):
    return (
        f"💰 To'lov qabul qilindi\n"
        f"Agent {agent_code} {agent_name} <b>{fmt_money(amount)}</b> so'm to'lov qabul qildi.\n"
        f"Joriy qoldiq: <b>{fmt_money(balance)}</b> so'm"
    )
```

- [ ] **Step 4: Test o'tishini tekshirish**

Run: `python -m pytest tests/test_customer_bot.py -k notify_messages -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/notify.py tests/test_customer_bot.py
git commit -m "feat(customer-bot): bildirishnoma xabar matnlari"
```

---

## Task 8: notify_customer() — Telegram I/O (fire-and-forget)

**Files:**
- Modify: `app/bot/customer_bot/notify.py`
- Create: `app/bot/customer_bot/config.py`

Bu funksiya jonli tizimdan chaqiriladi — **HECH QACHON exception ko'tarmasligi va so'rovni bloklamasligi shart**. notifier.py'dagi `_send_to_chats_sync` patterniga amal qiladi: ishlаётган event loop ichida bo'lsa daemon thread, aks holda inline.

- [ ] **Step 1: config.py yaratish**

`app/bot/customer_bot/config.py`:
```python
import os

BOT_TOKEN = os.environ.get("CUSTOMER_BOT_TOKEN", "")
LOCK_PORT = int(os.environ.get("CUSTOMER_BOT_LOCK_PORT", "47893"))


def admin_ids():
    raw = os.environ.get("CUSTOMER_BOT_ADMIN_IDS", "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().isdigit()}
```

- [ ] **Step 2: notify_customer() qo'shish — notify.py**

```python
import asyncio
import logging
import threading

from app.bot.customer_bot.config import BOT_TOKEN

logger = logging.getLogger(__name__)


def _send_via_token(chat_ids, text):
    """Yangi Bot instance ochib yuboradi, sessiyani yopadi. Sync kontekst."""
    if not BOT_TOKEN or not chat_ids:
        return

    async def _run():
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
        try:
            for cid in chat_ids:
                try:
                    await bot.send_message(int(cid), text)
                except Exception as e:
                    logger.warning(f"customer_bot send fail {cid}: {e}")
        finally:
            await bot.session.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        threading.Thread(target=lambda: asyncio.run(_run()), daemon=True).start()
    else:
        asyncio.run(_run())


def notify_customer(partner_id, text):
    """Partner'ning approved Telegram linklariga xabar. Fire-and-forget, hech qachon raise qilmaydi."""
    try:
        from app.models.database import SessionLocal
        from app.bot.customer_bot.registration import approved_telegram_ids_for_partner
        db = SessionLocal()
        try:
            chat_ids = approved_telegram_ids_for_partner(db, partner_id)
        finally:
            db.close()
        _send_via_token(chat_ids, text)
    except Exception as e:
        logger.warning(f"notify_customer error: {e}")
```

Eslatma: `SessionLocal` ni `app/models/database.py` dan import qilamiz. Agar nomi farq qilsa (`Session`, `get_db`), real nomga moslang — Step 3 da tekshiring.

- [ ] **Step 3: SessionLocal nomini tekshirish**

Run: `python -c "from app.models.database import SessionLocal; print('OK')"`
Expected: `OK`. Agar `ImportError` bo'lsa, `app/models/database.py` da session factory nomini toping (`grep -n "sessionmaker\|SessionLocal" app/models/database.py`) va `notify.py` dagi importni moslang.

- [ ] **Step 4: Import smoke**

Run: `python -c "from app.bot.customer_bot.notify import notify_customer; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/bot/customer_bot/config.py app/bot/customer_bot/notify.py
git commit -m "feat(customer-bot): notify_customer fire-and-forget I/O"
```

---

## Task 9: aiogram handlerlar

**Files:**
- Create: `app/bot/customer_bot/handlers.py`

Bu qism Telegram I/O — unit test o'rniga qo'lda smoke (Task 13). Toza logika allaqachon testlangan (Task 2-7).

- [ ] **Step 1: handlers.py yozish**

`app/bot/customer_bot/handlers.py`:
```python
import logging
from datetime import date, timedelta

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, KeyboardButton, ReplyKeyboardMarkup,
    InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery,
)

from app.models.database import SessionLocal, Partner
from app.bot.customer_bot.config import admin_ids
from app.bot.customer_bot import registration as reg
from app.bot.customer_bot import queries as q

logger = logging.getLogger(__name__)
router = Router()


def _contact_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni ulashish", request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )


def _menu_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📦 Buyurtmalarim"), KeyboardButton(text="💰 Qarz/Avans qoldig'i")],
            [KeyboardButton(text="📅 Hisobot"), KeyboardButton(text="ℹ️ Yordam")],
        ],
        resize_keyboard=True,
    )


def _approved_partner(db, tg_id):
    link = reg.get_link_by_telegram(db, tg_id)
    if link and link.status == "approved" and link.partner_id:
        return db.query(Partner).filter(Partner.id == link.partner_id).first()
    return None


@router.message(CommandStart())
async def on_start(message: Message):
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
    finally:
        db.close()
    if p:
        await message.answer(f"Assalomu alaykum, {p.name}!", reply_markup=_menu_kb())
    else:
        await message.answer(
            "👋 Assalomu alaykum!\n\nBu — TOTLI HOLVA mijozlar boti. "
            "Buyurtmalaringiz va qarz/avans qoldig'ingizni kuzatishingiz mumkin.\n\n"
            "Boshlash uchun telefon raqamingizni ulashing 👇",
            reply_markup=_contact_kb(),
        )


@router.message(F.contact)
async def on_contact(message: Message):
    # faqat O'ZINING raqamini qabul qilamiz (boshqa kontaktni emas)
    if message.contact.user_id != message.from_user.id:
        await message.answer("Iltimos, o'zingizning raqamingizni ulashing.")
        return
    phone = message.contact.phone_number
    db = SessionLocal()
    try:
        matches = reg.find_matching_partners(db, phone)
        if not matches:
            await message.answer(
                "❌ Raqamingiz tizimda topilmadi. Iltimos, agentingizga murojaat qiling."
            )
            return
        link = reg.create_pending_link(
            db, message.from_user.id, message.from_user.username,
            message.from_user.full_name, q.fmt_money  # placeholder almashtiriladi
            if False else (message.contact.phone_number),
        )
        await message.answer(
            f"✅ Raqamingiz qabul qilindi: {phone}\n\n"
            "So'rovingiz administratorga yuborildi. Tasdiqlangach xabar beramiz. ⏳",
            reply_markup=ReplyKeyboardMarkup(keyboard=[[]], resize_keyboard=True),
        )
        # adminlarga tasdiq tugmalari
        for cand in matches:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text=f"✅ Tasdiqlash: {cand.name}",
                    callback_data=f"cbapprove:{link.id}:{cand.id}",
                ),
                InlineKeyboardButton(text="❌ Rad etish", callback_data=f"cbreject:{link.id}"),
            ]])
            text = (
                f"🆕 Yangi mijoz so'rovi\n"
                f"Do'kon: <b>{cand.name}</b>\n"
                f"Telefon: {phone}\n"
                f"Telegram: @{message.from_user.username or '—'} ({message.from_user.id})"
            )
            from app.bot.customer_bot.notify import _send_via_token
            _send_via_token(list(admin_ids()), text + f"\n<code>{cand.id}</code>")
            # inline tugmali xabarni alohida yuborish:
            await message.bot.send_message(list(admin_ids())[0], text, reply_markup=kb) \
                if admin_ids() else None
    finally:
        db.close()


@router.callback_query(F.data.startswith("cbapprove:"))
async def on_approve(cb: CallbackQuery):
    if cb.from_user.id not in admin_ids():
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    _, link_id, partner_id = cb.data.split(":")
    db = SessionLocal()
    try:
        link = reg.approve_link(db, int(link_id), int(partner_id), cb.from_user.id)
        tg = link.telegram_id
    finally:
        db.close()
    await cb.message.edit_text(cb.message.text + "\n\n✅ TASDIQLANDI")
    try:
        await cb.bot.send_message(
            int(tg), "🎉 Tabriklaymiz, ulandingiz!", reply_markup=_menu_kb()
        )
    except Exception as e:
        logger.warning(f"approve notify fail: {e}")
    await cb.answer("Tasdiqlandi")


@router.callback_query(F.data.startswith("cbreject:"))
async def on_reject(cb: CallbackQuery):
    if cb.from_user.id not in admin_ids():
        await cb.answer("Ruxsat yo'q", show_alert=True)
        return
    _, link_id = cb.data.split(":")
    db = SessionLocal()
    try:
        link = reg.reject_link(db, int(link_id), cb.from_user.id)
        tg = link.telegram_id
    finally:
        db.close()
    await cb.message.edit_text(cb.message.text + "\n\n❌ RAD ETILDI")
    try:
        await cb.bot.send_message(
            int(tg), "Kechirasiz, so'rovingiz tasdiqlanmadi. Agentingizga murojaat qiling."
        )
    except Exception:
        pass
    await cb.answer("Rad etildi")


@router.message(F.text == "💰 Qarz/Avans qoldig'i")
async def on_balance(message: Message):
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
        if not p:
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
        await message.answer(q.balance_text(p))
    finally:
        db.close()


@router.message(F.text == "📦 Buyurtmalarim")
async def on_orders(message: Message):
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
        if not p:
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
        orders = q.recent_orders(db, p.id, limit=10)
        if not orders:
            await message.answer("Buyurtmalar topilmadi.")
            return
        lines = ["📦 <b>Oxirgi buyurtmalar:</b>\n"]
        for o in orders:
            d = o.date.strftime("%d.%m.%Y") if o.date else ""
            lines.append(
                f"№ {o.number} — {d}\n"
                f"  {q.fmt_money(o.total)} so'm · {q.order_status_label(o.status)}"
            )
        await message.answer("\n".join(lines))
    finally:
        db.close()


@router.message(F.text == "📅 Hisobot")
async def on_report_menu(message: Message):
    db = SessionLocal()
    try:
        if not _approved_partner(db, message.from_user.id):
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
    finally:
        db.close()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Bugun", callback_data="cbrep:today"),
         InlineKeyboardButton(text="Shu hafta", callback_data="cbrep:week")],
        [InlineKeyboardButton(text="Shu oy", callback_data="cbrep:month"),
         InlineKeyboardButton(text="30 kun", callback_data="cbrep:30")],
    ])
    await message.answer("📅 Davrni tanlang:", reply_markup=kb)


def _range_for(key):
    today = date.today()
    if key == "today":
        return today, today
    if key == "week":
        return today - timedelta(days=today.weekday()), today
    if key == "month":
        return today.replace(day=1), today
    return today - timedelta(days=30), today  # "30"


@router.callback_query(F.data.startswith("cbrep:"))
async def on_report(cb: CallbackQuery):
    key = cb.data.split(":")[1]
    d_from, d_to = _range_for(key)
    db = SessionLocal()
    try:
        p = _approved_partner(db, cb.from_user.id)
        if not p:
            await cb.answer("Avval ulaning", show_alert=True)
            return
        st = q.statement(db, p.id, d_from, d_to)
    finally:
        db.close()
    lines = [
        f"📅 <b>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</b>\n",
        f"Buyurtmalar: <b>{q.fmt_money(st['total_orders'])}</b> so'm ({len(st['orders'])} ta)",
        f"To'langan: <b>{q.fmt_money(st['total_paid'])}</b> so'm ({len(st['payments'])} ta)\n",
    ]
    for o in st["orders"][:30]:
        lines.append(f"  № {o.number} — {q.fmt_money(o.total)} so'm · {q.order_status_label(o.status)}")
    await cb.message.answer("\n".join(lines))
    await cb.answer()


@router.message(F.text == "ℹ️ Yordam")
async def on_help(message: Message):
    await message.answer(
        "ℹ️ Bu bot orqali buyurtmalaringiz, to'lovlaringiz va qarz/avans "
        "qoldig'ingizni ko'rishingiz mumkin. Savollar uchun agentingizga murojaat qiling."
    )


@router.message()
async def on_other(message: Message):
    db = SessionLocal()
    try:
        if _approved_partner(db, message.from_user.id):
            await message.answer("Quyidagi menyudan tanlang 👇", reply_markup=_menu_kb())
        else:
            await message.answer(
                "Boshlash uchun telefon raqamingizni ulashing 👇", reply_markup=_contact_kb()
            )
    finally:
        db.close()
```

**MUHIM tozalash:** `on_contact` da `create_pending_link` chaqiruvida placeholder hazil qoldi — uni soddalashtiring:
```python
        link = reg.create_pending_link(
            db, message.from_user.id, message.from_user.username,
            message.from_user.full_name, message.contact.phone_number,
        )
```
Va admin xabarini bir marta yuboring (inline tugma bilan) — `_send_via_token` qatorini olib tashlang, faqat `message.bot.send_message(admin_id, text, reply_markup=kb)` har bir adminga loop bilan:
```python
        for admin in admin_ids():
            for cand in matches:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=f"✅ {cand.name}", callback_data=f"cbapprove:{link.id}:{cand.id}"),
                    InlineKeyboardButton(text="❌ Rad", callback_data=f"cbreject:{link.id}"),
                ]])
                await message.bot.send_message(
                    admin,
                    f"🆕 Yangi mijoz so'rovi\nDo'kon: <b>{cand.name}</b>\n"
                    f"Telefon: {phone}\nTelegram: @{message.from_user.username or '—'} ({message.from_user.id})",
                    reply_markup=kb,
                )
```

- [ ] **Step 2: Import smoke**

Run: `python -c "from app.bot.customer_bot.handlers import router; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/bot/customer_bot/handlers.py
git commit -m "feat(customer-bot): aiogram handlerlar (start/contact/menyu/hisobot)"
```

---

## Task 9B: Qo'lda sana oraliq tanlash (FSM)

**Files:**
- Modify: `app/bot/customer_bot/handlers.py`

Mijoz "Oraliq tanlash" tugmasini bossa → boshlanish sanasi so'raladi → tugash sanasi → hisobot. `parse_date_uz` (Task 6B) ishlatiladi.

- [ ] **Step 1: on_report_menu ga "Oraliq tanlash" tugmasi qo'shish**

`on_report_menu` dagi inline klaviaturaga yangi qator qo'shing:
```python
        [InlineKeyboardButton(text="🗓 Oraliq tanlash", callback_data="cbrep:custom")],
```

- [ ] **Step 2: FSM state va handlerlar qo'shish — handlers.py**

Import qatorlariga qo'shing:
```python
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
```

Fayl oxiriga (lekin umumiy `@router.message()` "on_other" handleridan **oldin** — filter tartibi muhim) qo'shing:
```python
class ReportRange(StatesGroup):
    waiting_from = State()
    waiting_to = State()


@router.callback_query(F.data == "cbrep:custom")
async def on_custom_range_start(cb: CallbackQuery, state: FSMContext):
    db = SessionLocal()
    try:
        if not _approved_partner(db, cb.from_user.id):
            await cb.answer("Avval ulaning", show_alert=True)
            return
    finally:
        db.close()
    await state.set_state(ReportRange.waiting_from)
    await cb.message.answer("🗓 Boshlanish sanasini kiriting (masalan 01.05.2026):")
    await cb.answer()


@router.message(ReportRange.waiting_from)
async def on_range_from(message: Message, state: FSMContext):
    d = q.parse_date_uz(message.text)
    if not d:
        await message.answer("Sana noto'g'ri. Masalan: 01.05.2026")
        return
    await state.update_data(d_from=d.isoformat())
    await state.set_state(ReportRange.waiting_to)
    await message.answer("Tugash sanasini kiriting (masalan 15.05.2026):")


@router.message(ReportRange.waiting_to)
async def on_range_to(message: Message, state: FSMContext):
    from datetime import date
    d_to = q.parse_date_uz(message.text)
    if not d_to:
        await message.answer("Sana noto'g'ri. Masalan: 15.05.2026")
        return
    data = await state.get_data()
    d_from = date.fromisoformat(data["d_from"])
    await state.clear()
    if d_to < d_from:
        d_from, d_to = d_to, d_from
    db = SessionLocal()
    try:
        p = _approved_partner(db, message.from_user.id)
        if not p:
            await message.answer("Avval telefon raqamingizni ulashing.", reply_markup=_contact_kb())
            return
        st = q.statement(db, p.id, d_from, d_to)
    finally:
        db.close()
    lines = [
        f"📅 <b>{d_from.strftime('%d.%m.%Y')} — {d_to.strftime('%d.%m.%Y')}</b>\n",
        f"Buyurtmalar: <b>{q.fmt_money(st['total_orders'])}</b> so'm ({len(st['orders'])} ta)",
        f"To'langan: <b>{q.fmt_money(st['total_paid'])}</b> so'm ({len(st['payments'])} ta)\n",
    ]
    for o in st["orders"][:30]:
        lines.append(f"  № {o.number} — {q.fmt_money(o.total)} so'm · {q.order_status_label(o.status)}")
    await message.answer("\n".join(lines), reply_markup=_menu_kb())
```

- [ ] **Step 3: Import smoke**

Run: `python -c "from app.bot.customer_bot.handlers import router, ReportRange; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add app/bot/customer_bot/handlers.py
git commit -m "feat(customer-bot): qo'lda sana oraliq tanlash (FSM)"
```

---

## Task 10: bot.py + standalone runner (socket-lock)

**Files:**
- Create: `app/bot/customer_bot/bot.py`
- Create: `scripts/customer_bot_standalone.py`

`scripts/senior_bots_standalone.py` patterniga amal qiladi (socket singleton lock).

- [ ] **Step 1: bot.py**

`app/bot/customer_bot/bot.py`:
```python
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.customer_bot.config import BOT_TOKEN
from app.bot.customer_bot.handlers import router

logger = logging.getLogger(__name__)


async def run_polling():
    if not BOT_TOKEN:
        logger.error("CUSTOMER_BOT_TOKEN yo'q — mijoz bot ishga tushmaydi")
        return
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Mijoz bot polling boshlandi")
    await dp.start_polling(bot)
```

- [ ] **Step 2: standalone runner (socket-lock)**

`scripts/customer_bot_standalone.py`:
```python
"""Mijoz Telegram boti — mustaqil jarayon (socket singleton lock).

Ishga tushirish: python scripts/customer_bot_standalone.py
"""
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("customer_bot")

LOCK_PORT = int(os.environ.get("CUSTOMER_BOT_LOCK_PORT", "47893"))


def _acquire_singleton():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        s.listen(1)
        return s
    except OSError:
        logger.error(f"Port {LOCK_PORT} band — bot allaqachon ishlamoqda. Chiqish.")
        sys.exit(1)


def main():
    _lock = _acquire_singleton()  # noqa: F841 — GC bo'lmasligi uchun ushlab turamiz
    from app.bot.customer_bot.bot import run_polling
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Import + lock smoke (token bilan)**

Run (token .env da bo'lsa):
```
python -c "import asyncio; from app.bot.customer_bot.bot import run_polling; print('import OK')"
```
Expected: `import OK`

To'liq polling smoke — Task 13 da (Telegram bilan).

- [ ] **Step 4: Commit**

```bash
git add app/bot/customer_bot/bot.py scripts/customer_bot_standalone.py
git commit -m "feat(customer-bot): bot.py + standalone runner (socket-lock 47893)"
```

---

## Task 11: Web hooklar — 4 ta notify chaqiruvi (Tier B)

**Files:**
- Modify: `app/routes/sales.py` (sales_confirm agent branch, sales_dispatch)
- Modify: `app/routes/api_driver_ops.py` (driver_delivery_status delivered)
- Modify: `app/routes/delivery_routes.py` (supervisor_confirm_agent_payment)

Har hook **try/except bilan o'ralgan, fire-and-forget** — jonli operatsiyani buzmaydi. Aniq qator raqamlari o'zgargan bo'lishi mumkin — funksiya nomi bo'yicha toping.

- [ ] **Step 1: sales_confirm (agent branch) — buyurtma tasdiqlandi hook**

`app/routes/sales.py` da `sales_confirm` funksiyasida, agent buyurtmasi `status='confirmed'` ga o'tgan atomik UPDATE'dan **keyin**, commit'dan keyin:
```python
            try:
                from app.bot.customer_bot.notify import notify_customer, msg_order_confirmed
                notify_customer(order.partner_id, msg_order_confirmed(order))
            except Exception:
                pass
```

- [ ] **Step 2: sales_dispatch — yo'lda hook**

`app/routes/sales.py` `sales_dispatch` da, `out_for_delivery` ga o'tib commit bo'lgandan keyin:
```python
            try:
                from app.bot.customer_bot.notify import notify_customer, msg_order_dispatched
                notify_customer(order.partner_id, msg_order_dispatched(order))
            except Exception:
                pass
```

- [ ] **Step 3: driver_delivery_status (delivered) — yetkazildi hook**

`app/routes/api_driver_ops.py` `driver_delivery_status` delivered branch'da, `partner.balance += order.debt` va commit'dan **keyin** (balans yangilangach):
```python
            try:
                from app.bot.customer_bot.notify import notify_customer, msg_order_delivered
                notify_customer(order.partner_id, msg_order_delivered(order, partner.balance))
            except Exception:
                pass
```

- [ ] **Step 4: supervisor_confirm_agent_payment — agent to'lov hook**

`app/routes/delivery_routes.py` `supervisor_confirm_agent_payment` da, `partner.balance -= ap.amount` va commit'dan **keyin**:
```python
            try:
                from app.bot.customer_bot.notify import notify_customer, msg_agent_payment
                agent = db.query(Agent).filter(Agent.id == ap.agent_id).first()
                notify_customer(
                    ap.partner_id,
                    msg_agent_payment(
                        agent.code if agent else "", agent.full_name if agent else "",
                        ap.amount, partner.balance,
                    ),
                )
            except Exception:
                pass
```
Eslatma: `Agent` import qatorda bormi tekshiring; `partner` o'zgaruvchisi shu scope'da mavjudligini tasdiqlang (yo'q bo'lsa `db.query(Partner).get(ap.partner_id)`).

- [ ] **Step 5: Sintaksis + import tekshiruvi**

Run:
```
python -c "import ast; [ast.parse(open(f, encoding='utf-8').read()) for f in ['app/routes/sales.py','app/routes/api_driver_ops.py','app/routes/delivery_routes.py']]; print('AST OK')"
```
Expected: `AST OK`

- [ ] **Step 6: Regression — mavjud testlar buzilmadi**

Run: `python -m pytest tests/test_dispatch_flow.py tests/test_atomic_confirm.py tests/test_exchange_driver_flow.py -v`
Expected: oldingi holatdek PASS (hooklar try/except bilan, sinmaydi)

- [ ] **Step 7: Commit**

```bash
git add app/routes/sales.py app/routes/api_driver_ops.py app/routes/delivery_routes.py
git commit -m "feat(customer-bot): 4 notify hook (confirm/dispatch/deliver/agent-pay)"
```

---

## Task 12: start.bat — launch/kill bloklari

**Files:**
- Modify: `start.bat`

`:start_senior_bots_if_needed` / `:kill_senior_bots` bloklarini namuna qilib oling. **Faqat ASCII** (kirill yo'q — bat parser sinadi).

- [ ] **Step 1: Launch blok qo'shish**

`start.bat` da senior bots launch blokidan keyin, `netstat ... :47893` tekshiruvi bilan yangi blok (`scripts/_customer_bot_runner.bat` yozadi yoki to'g'ridan-to'g'ri pythonw bilan ishga tushiradi). Mavjud `:start_senior_bots_if_needed` blokidagi naqshni 47893 portga moslab nusxalang. `:do_restart` va `:do_stop` ga `call :kill_customer_bot` / `call :start_customer_bot_if_needed` qo'shing.

- [ ] **Step 2: Qo'lda tekshirish (RDP'da, prod deploy paytida)**

```
python scripts\customer_bot_standalone.py
```
boshqa oynada:
```
netstat -ano | findstr :47893
```
Expected: `LISTENING` qatori ko'rinadi.

- [ ] **Step 3: Commit**

```bash
git add start.bat
git commit -m "chore(customer-bot): start.bat launch/kill bloklari (port 47893)"
```

---

## Task 13: To'liq test + smoke

- [ ] **Step 1: Barcha unit testlar**

Run: `python -m pytest tests/test_customer_bot.py -v`
Expected: hamma PASS (~17 test)

- [ ] **Step 2: Butun suite regression**

Run: `python -m pytest tests/ -q`
Expected: yangi sinish yo'q (avvalgi holatga nisbatan)

- [ ] **Step 3: Telegram qo'lda smoke (token .env da, bot ishlab turibdi)**

1. Test partner yarating (veb-panel) — telefon: o'zingizning Telegram raqamingiz
2. Botga `/start` → contact ulashing → admin (siz) tasdiq tugmasini bosing
3. "Ulandingiz" + menyu kelishini tekshiring
4. 💰 Qarz/Avans → balans to'g'ri ko'rsatilsin
5. 📦 Buyurtmalarim, 📅 Hisobot (Bugun/Shu oy) — ishlashini tekshiring
6. Test buyurtma: agent yarating → admin tasdiq → "qabul qilindi" xabari kelsin
7. Dispatch → "yo'lda"; driver yetkazdi → "yetkazildi + qoldiq"; agent to'lov → supervisor tasdiq → "to'lov qabul qilindi"

- [ ] **Step 4: Yakuniy holat — finishing-a-development-branch**

Smoke o'tgach, `superpowers:finishing-a-development-branch` skill bilan merge/PR qaroriga o'ting. **Prod deploy tungi oynada (00:00–04:00)** + `.env` ga `CUSTOMER_BOT_TOKEN` qo'shilgan + `start.bat` ishga tushirilgan bo'lsin.

---

## Self-Review natijasi (reja muallifi)

**Spec qamrovi:**
- Ro'yxatdan o'tish + admin tasdiq → Task 4, 9 ✅
- Telefon mosligi (oxirgi 9 raqam, phone+phone2) → Task 2, 3 ✅
- Balans (ilova mustaqil) → Task 5 (`balance_text`, to'g'ridan-to'g'ri partner.balance) ✅
- Buyurtmalar ro'yxati → Task 6, 9 ✅
- Sana oraliq hisobot (tez tugmalar + qo'lda oraliq) → Task 6, 6B, 9, 9B ✅
- 4 push xabar → Task 7, 11 ✅
- Mustaqil process + socket-lock → Task 10 ✅
- start.bat → Task 12 ✅

**Placeholder skan:** Task 9 dagi `q.fmt_money ... if False else` hazil **ataylab** belgilangan va "MUHIM tozalash" bilan to'g'rilangan — executor uni soddalashtiradi.

**Tur muvofiqligi:** `notify_customer(partner_id, text)`, `msg_*` quruvchilar imzolari Task 7 (ta'rif) va Task 11 (chaqiruv) da bir xil ✅. `approved_telegram_ids_for_partner` Task 4 da ta'riflanib Task 8 da ishlatiladi ✅.

**Ochiq nuqta (executor uchun):** yo'q — barcha spec talablari qoplandi (qo'lda oraliq Task 6B+9B bilan qo'shildi).
