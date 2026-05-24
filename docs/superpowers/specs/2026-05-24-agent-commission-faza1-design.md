# Agent Commission — Faza 1 Schema Dizayni

**Sana:** 2026-05-24
**Status:** DRAFT — foydalanuvchi tasdig'i kutilmoqda
**Tier:** B (additive schema, kichik risk)
**Bog'liq brainstorm:** `[[agent-commission-brainstorm-20260524]]`

---

## 1. Maqsad

Agentlarga oylik sotuv foizi (commission) hisoblash imkoniyatini qo'shish. Faza 1 da **faqat ma'lumot to'plash** — hisob-kitob va UI keyingi fazalarda.

**Variant B (brainstormdan tasdiqlangan):**
- Per-agent `commission_percent` (foiz, %)
- Oyda **delivered + paid** sotuvlardan hisoblanadi (Order.total ustidan)
- **Net** (shu oy ichida qaytarilgan ayiriladi)
- Foiz tarixini saqlamaslik — joriy % ishlatiladi (oddiy snapshot yo'q)

---

## 2. Scope (Faza 1)

**O'z ichiga oladi:**
1. `agents.commission_percent` ustuni qo'shish (FLOAT, default 0.0)
2. ORM model (`app/models/database.py`) yangilash
3. `ensure_agents_commission_percent_column()` helper yozish
4. Agent edit form (`templates/info/agents_edit.html`) ga commission_percent input qo'shish
5. Agent create form'ga ham qo'shish

**Bu fazada YO'Q:**
- Commission hisob-kitob logikasi (Faza 2)
- /agents/commissions sahifa (Faza 2)
- Dashboard widget (Faza 2)
- Employee link va salary integratsiya (Faza 3)

---

## 3. Schema o'zgarishi

### 3.1 Yangi ustun

```sql
ALTER TABLE agents ADD COLUMN commission_percent FLOAT DEFAULT 0.0;
```

| Field | Type | Constraints | Default | Sabab |
|---|---|---|---|---|
| commission_percent | FLOAT | NULL ruxsat | 0.0 | NULL=eski yozuvlar, 0=foiz yo'q (boshlang'ich holat) |

**FLOAT sababi:** kasrli foiz (2.5%, 1.75%) talab bo'lishi mumkin. Aniqlik kafolatlanadi (FLOAT 6-7 raqam yetadi).

### 3.2 ORM model (app/models/database.py:1404)

```python
class Agent(Base):
    # ... mavjud field'lar ...
    pin_set_at = Column(DateTime, nullable=True)
    commission_percent = Column(Float, default=0.0, nullable=True)  # YANGI
```

**Eslatma:** `Float` SQLAlchemy import qiling (boshqa joylarda allaqachon import qilingan).

### 3.3 ensure_*_column helper (app/utils/db_schema.py)

```python
def ensure_agents_commission_percent_column(db: Session) -> None:
    """Agar agents jadvalida commission_percent ustuni bo'lmasa, qo'shadi."""
    try:
        db.execute(text("ALTER TABLE agents ADD COLUMN commission_percent FLOAT DEFAULT 0.0"))
        db.commit()
    except OperationalError as e:
        db.rollback()
        if "duplicate column" not in str(e).lower():
            raise
    except Exception:
        db.rollback()
```

**Chaqirish joyi:** `app/main.py` startup'ida boshqa `ensure_*_column`'lar qatorida.

**Why pattern:** ORM-DB schema drift'ni oldini olish ([[orm-db-schema-drift]]). Ensure helper'lar pending tranzaksiya'siz chaqirilishi kerak ([[schema-migration-pattern]]).

---

## 4. UI o'zgarishi

### 4.1 Agent edit form

`app/templates/info/agents_edit.html` (yoki tegishli template):

```html
<div class="mb-3">
  <label for="commission_percent" class="form-label">Komissiya foizi (%)</label>
  <input type="number" step="0.01" min="0" max="100"
         class="form-control" id="commission_percent" name="commission_percent"
         value="{{ agent.commission_percent or 0 }}">
  <div class="form-text">Oyda delivered+paid sotuvlardan ushbu foiz commission sifatida hisoblanadi.</div>
</div>
```

### 4.2 Backend route

`app/routes/agents_routes.py` (yoki info'da agents edit handler):

```python
agent.commission_percent = float(form.get("commission_percent", 0) or 0)
```

Validatsiya: `0 <= value <= 100` (chegarada). Agar tashqarida bo'lsa — `400 Bad Request` yoki UI'da error.

### 4.3 Agent list (joriy /info da)

Faza 1 da list'ga commission_percent ustunini ko'rsatish ixtiyoriy. Tavsiya: KO'RSATISH (admin uchun foydali audit).

---

## 5. Migration strategiyasi

**Tier B (additive):**
1. Server ishlayotgan paytda `ensure_*_column` chaqirilganda jim ravishda `ALTER TABLE` bajariladi
2. SQLite `ALTER TABLE ADD COLUMN` jonli — server qulflanmaydi
3. ORM model yangilanishi bilan server restart kerak (yangi Column'ni o'qishi uchun)
4. Restart - tungi oyna (00:00-04:00) yoki kunduzgi tezkor restart (5 sek)

**Rollback:**
SQLite `DROP COLUMN` qo'llab-quvvatlamaydi. Agar bekor qilish kerak bo'lsa:
- ORM'dan `commission_percent` ni olib tashlash (ustun DB'da qoladi, lekin ignore qilinadi)
- Yoki backup'dan tiklash (`backups/pre_commission_faza1.db`)

---

## 6. Backwards compatibility

- Mavjud agentlar (Akbarjon, Murodjon) `commission_percent=0.0` bilan to'ladi (default)
- Eski code commission_percent'ni ko'rmaydi → ta'sir 0
- Mobil app `Agent.user_id` orqali ishlashda davom etadi → ta'sir 0

---

## 7. Testing

**Smoke test (Faza 1 yakunida):**
1. `/info/agents` ochiladi (200 OK)
2. Akbarjon edit form'ida commission_percent ko'rinadi (0.0)
3. Murodjon edit form'ida commission_percent ko'rinadi (0.0)
4. Akbar uchun 5.5% saqlash → DB tekshirish → ko'rinishi
5. 150% kiritish — rad etiladi (400 yoki UI error)
6. `-1` kiritish — rad etiladi

**Regression:**
- Mobil agent login (Murodjon, Akbar) — sinadi
- POS order create (agent siz) — sinadi
- /info/agents list ko'rinadi

---

## 8. Ochiq savollar

| # | Savol | Default taklif |
|---|---|---|
| Q1 | commission_percent default qiymati? | **0.0** (NULL emas) |
| Q2 | Akbarjon va Murodjon uchun boshlang'ich % qancha? | Akbar uchun ? %, Murodjon uchun ? % — foydalanuvchi aytadi |
| Q3 | Foiz tarixini saqlash kerakmi (audit log)? | YO'Q (Faza 1 da), agar kerak bo'lsa Faza 3 da AgentCommissionRate jadvali |
| Q4 | UI joylashuvi: agent edit yoki alohida "Commission" tab? | Edit form ichida (oddiy) |
| Q5 | List sahifada ko'rsataylikmi? | HA (admin audit uchun foydali) |

---

## 9. Deploy plani

**Tier B:**
1. Branch: `feat-agent-commission-faza1`
2. Commit: schema + model + ensure helper + UI input + route
3. Local smoke test
4. Tungi oyna yoki kunduzgi tezkor restart (5 sek window)
5. Post-smoke: agent edit + DB tekshirish

**Yoki:** feat-bulk-dispatch tungi merge'ga qo'shish (chunki branch allaqachon mavjud).

Tavsiya: **alohida branch** — bulk-dispatch katta, alohida verify oson.

---

## 10. Faza 2/3 preview (out of scope, lekin bog'liq)

**Faza 2 (~1 soat):**
- `/agents/commissions` sahifa — har agent uchun joriy oy commission hisoblanadi (read-only)
- Dashboard widget — top agent + total commission

**Faza 3 (~30 daq):**
- Akbar va Murodjon uchun Employee yaratish (`position='Agent'`, `salary=0`)
- `agents.employee_id` link to'ldirish
- `/employees/salary` integratsiya — commission bonus row sifatida

---

## 11. Risklar

| Risk | Ehtimollik | Ta'sir | Mitigatsiya |
|---|---|---|---|
| ORM-DB drift | Past | O'rta | ensure_*_column helper |
| FLOAT precision | Juda past | Past | 0-100 oraliq, 2 raqam yetarli |
| UI input xato | O'rta | Past | min/max validatsiya |
| Eski mobil app crash | Juda past | Yo'q | Field optional, app ko'rmaydi |

---

## 12. Tasdiq olish

Foydalanuvchi shu spec'ni o'qib quyidagilarni tasdiqlasin:
- [ ] Schema (1 ustun, FLOAT default 0.0)
- [ ] UI joylashuvi (edit form ichida + list ustuni)
- [ ] Ochiq savollar (Q1-Q5)
- [ ] Alohida branch yoki bulk-dispatch ga qo'shish

Tasdiqdan keyin: `writing-plans` skill bilan implementation plan, keyin subagent-driven yoki ketma-ket bajarish.
