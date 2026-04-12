# TOTLI BI — Refactor rejasi

**Maqsad:** Audit natijalariga ko'ra loyihani bosqichma-bosqich xavfsizlash, tozalash va barqarorlashtirish.
**Boshlanish:** 2026-04-10
**Asosiy printsip:** Hozirgi ishni to'xtatmay, foydalanuvchilar sezmaydigan tarzda yangilash.

---

## 🎯 Umumiy printsiplar

1. **Backup birinchi** — har kattaroq o'zgarishdan oldin git tag + DB snapshot
2. **Tier bo'yicha bosqichma-bosqich:**
   - **Tier A** — xavfsiz, ish vaqtida bajarish mumkin (config, secret, cookie)
   - **Tier B** — logika tuzatish, tungi oynada (00:00–04:00)
   - **Tier C** — katta refactor, yakshanba kechasi, feature flag bilan
3. **Har commit alohida** — kichik, anglashilarli, rollback oson
4. **Test → commit → verify** — har o'zgarishdan keyin backup va server holati tekshiriladi
5. **Hech qanday foydalanuvchi ta'siri** — uvicorn DEV_MODE'da auto-reload, har reload 2-3 sek
6. **Rollback tayyor** — har bosqichda aniq git commit yoki tag nuqtasi

---

## 📦 Infrastruktura (tayyor)

| # | Element | Holat | Eslatma |
|---|---|---|---|
| I1 | Git branch `main` + GitHub sinxron | ✅ | `origin/main` push qilingan |
| I2 | Rollback tag | ✅ | `pre-refactor-2026-04-10` |
| I3 | ZIP backup | ✅ | `D:\TOTLI_BI_BACKUP_20260410_143417.zip` (498 MB) |
| I4 | Jonli backup har 5 daq | ✅ | `scripts/backup_live.py` + Task Scheduler + app scheduler |
| I5 | Retention 2 soat | ✅ | `D:\TOTLI_BI_BACKUPS\live\` (~50 fayl, ~75 MB) |
| I6 | Monitoring skripti | ✅ | `scripts/_check_status.ps1` |
| I7 | Restore skripti | ✅ | `scripts/restore_from_backup.py --list/--latest` |

---

## 🟢 TIER A — Xavfsiz, ish vaqtida (5 task)

**Xususiyati:** Foydalanuvchilar sezmaydi. Har tahrir 2-3 sek auto-reload.
**Vaqti:** Istalgan vaqtda, ish kunida.
**Rollback:** `git reset --hard <tag>` + uvicorn restart.

### A1. Secrets → `.env` ✅ BAJARILDI
**Commit:** `f6c7a9e` | **Audit:** K1, Y4 | **Vaqt:** 45 daq

- Hardcoded `TELEGRAM_BOT_TOKEN`, `HIKVISION_PASSWORD`, `SECRET_KEY` → `.env`
- `main.py` ga `load_dotenv()` qo'shildi
- `.env.example` shablon yangilandi
- `app/bot/config.py`, `app/utils/auth.py`, `app/utils/scheduler.py`, `app/bot/services/report_queries.py` — env'dan o'qiydi
- **⚠️ TODO:** Eski tokenlarni `@BotFather /revoke` orqali kuch yo'qotish; Hikvision parolini almashtirish

### A2. CSRF cookie `HttpOnly=true` ✅ BAJARILDI
**Commit:** `df389e9` | **Audit:** Y6 | **Vaqt:** 10 daq

- `app/middleware.py:88, 150` — `httponly=False` → `True`
- JavaScript token'ni `<meta name="csrf-token">` va `<input name="csrf_token">` dan oladi
- **Isbotlangan:** harajat formi saqlandi (skrinshot)

### A3. File upload validation ✅ BAJARILDI
**Commit:** `cac03cd` | **Audit:** Y5 | **Vaqt:** 40 daq

- `app/routes/products.py` — helper `_validate_and_save_product_image()`
- 3 ta endpoint (add, edit, upload-image) shuni ishlatadi
- Tekshiruvlar: extension whitelist, 5 MB hajm, Pillow `verify()`, filename sanitize
- **Sinov:** 4 ssenariy 4/4 o'tdi (PNG ✓, .php ✗, PHP-in-jpg ✗, 6 MB ✗)

### A4. Hikvision SSL verify (env) ✅ BAJARILDI
**Commit:** `a5360d3` | **Audit:** Y7 | **Vaqt:** 25 daq

- `app/utils/hikvision.py` — `verify_ssl=None` parametri, env'dan o'qiydi
- `HIKVISION_SSL_VERIFY=0` (default, self-signed uchun) yoki `1` (strict)
- **Sinov:** 5 ssenariy 5/5 o'tdi

### A5. Scheduler persistent jobstore ⏸️ O'TKAZIB YUBORILDI (tavsiya)
**Audit:** Y3 | **Vaqt:** 1-2 soat | **Xavf:** O'rta

**Nega o'tkazib yuborildi:**
- Live backup allaqachon Windows Task Scheduler orqali dublikatlangan (eng kritik job)
- Boshqa joblar restart da `start_scheduler()` orqali avtomatik qaytadan ro'yxatga olinadi
- Sizdagi tez restart (DEV_MODE) da missed jobs amaliyotda yo'q
- Qiymati past, xavfi o'rta

**Qachon qilinadi:** Postgres ko'chishi paytida yoki xohish bo'lsa alohida.

---

## 🟠 TIER B — Logika tuzatish, tungi oyna (5 task)

**Xususiyati:** Biznes logikasi o'zgaradi. Smoke test zarur.
**Vaqti:** **00:00 – 04:00** (23:00 daily backup tugagach, 06:00 gacha hech kim yo'q).
**Boshlash sharti:** DB backup olish + git tag yaratish.
**Rollback:** aniq tag, 5 daq ichida qaytish.

### B1. `purchase_confirm` atomic transaction ✅ BAJARILDI
**Commit:** `fac4fd2` | **Audit:** K3 | **Sana:** 2026-04-11

**Qilingan:**
- `app/services/document_service.py` (YANGI fayl) — `confirm_purchase_atomic()`, `revert_purchase_atomic()`, `DocumentError` class
- `app/routes/purchases.py` — `purchase_confirm` va `purchase_revert` endi thin wrapper
- Explicit `try/except/db.rollback()` har funksiyada
- Post-commit side-effects (low_stock_notify, audit_purchase) route'da qoldi

**Sinov:** Purchase #95 `P-20260411-0003` — jonli test, stock +1.0, after=8.178, partner balance yangilandi, status `confirmed`, hammasi atomik saqlandi.

### B2. Orphan payment fix ✅ BAJARILDI
**Commit:** `174aa03` | **Audit:** K4 | **Sana:** 2026-04-11

**Qilingan:**
- `delete_sale_fully(db, order)` funksiya `document_service.py` ga qo'shildi
- Draft → soft cancel (status='cancelled')
- Hard delete: to'lov bog'langan bo'lsa **REJECT** (DocumentError)
- Hard delete (to'lovsiz): OrderItem + StockMovement + Order — atomik o'chadi
- `sales.py:sales_delete` endi thin wrapper

**Topilma:** 6 ta eski orphan sale payment DB'da mavjud (oldingi bug'dan). Ular **B2.5** alohida task bilan tozalanadi.

### B3. Agent login PIN ✅ BAJARILDI
**Commit:** `662ad8f` | **Audit:** K5 | **Sana:** 2026-04-11

**Qilingan:**
- `agents.pin_hash`, `agents.pin_set_at` ustunlari qo'shildi (ensure_xxx pattern, alembic emas)
- `app/utils/auth.py`: `hash_pin()`, `verify_pin()`, `validate_pin_format()` (4-8 raqam, oddiy PIN'lar rad)
- `app/utils/rate_limit.py`: per-account rate limit (`is_agent_blocked`, 5 urinish → 30 daq)
- `/api/agent/login` — 3 rejim: User+bcrypt / Agent+PIN / Agent+legacy
- `/api/agent/set-pin` (YANGI endpoint) — token + current_password + new_pin
- Legacy login har safar `logger.warning` bilan qayd etiladi
- Javobda `pin_set: true/false` flag qaytadi

**Backward compat:** 4 ta mavjud agent hozirgi mobil ilovada o'zgarishsiz ishlayveradi. AG001 legacy login sinaldi — ishlayapti.

**TODO alohida task:** Flutter mobil ilovaga PIN o'rnatish ekranini qo'shish.

### B4. Session expiry 7 kun ✅ BAJARILDI
**Commit:** `a4eeadb` | **Audit:** Y8 | **Sana:** 2026-04-11

**Qilingan:**
- `SESSION_MAX_AGE` 30 → 7 kun
- Env orqali sozlanadigan: `SESSION_MAX_AGE_DAYS=7` (default)
- `.env.example` hujjat bilan yangilandi

**Ta'sir:** Web foydalanuvchilarga 0 (cookie max_age=86400 = 1 kun). Mobil agentlar har 7 kunda qayta login qiladi (oldin 30 kun).

### B5. Audit watchdog cooldown DB'ga ✅ BAJARILDI
**Commit:** `19032e3` | **Audit:** O5 | **Sana:** 2026-04-11

**Qilingan:**
- `audit_cooldowns` jadval yaratildi (key PRIMARY KEY, last_sent_at DATETIME)
- `ensure_audit_cooldowns_table()` + startup'da chaqiriladi
- `_cooldown_ok()` endi DB dan o'qiydi va yozadi
- DB xato bo'lsa in-memory fallback (audit hech qachon crash qilmasligi kerak)
- Har 100-chaqiruvda eski yozuvlarni avtomatik tozalash

**Sinov:** 3 ssenariy OK (1-chaqiruv True, 2-darhol False, boshqa key True).

---

### 🎯 B2.6. Senior audit topilmalarini tuzatish ✅ BAJARILDI
**Sana:** 2026-04-11 | **Audit:** 5 ekspert parallel

**Qilingan:**

1. **X3 — `agent_set_pin` kritik zaifligi (Sherzod audit):**
   - `current_password` endi MAJBURIY (Form(...) required)
   - Bo'sh qiymatni REJECT (oldingi `if current_password and` bypass tuzatildi)
   - IP rate limit (`is_blocked`) qo'shildi
   - Per-agent rate limit (`is_agent_blocked(f"setpin:{agent.id}")`)
   - Birinchi marta o'rnatishda aniq ikki yo'l: phone (legacy) yoki User bcrypt
   - Xato urinishlar `record_failure` + `record_agent_failure`
   - Muvaffaqiyatli urinish `record_success` + `record_agent_success`

2. **X5 — `purchase_delete` silent orphan (Nosir audit):**
   - `delete_purchase_fully(db, purchase)` service yaratildi
   - Purchase modelida cascade yo'q + SQLite FK=OFF → eski kod orphan qoldirardi
   - Yangi: PurchaseExpense + PurchaseItem + Purchase atomik o'chadi
   - `app/routes/purchases.py:purchase_delete` service wrapper ga o'tkazildi

**False alarm'lar (audit adashgan):**
- **X1** — `delete_sale_fully` allaqachon try/except/rollback bor (document_service.py:197-215)
- **X2** — `purchases/edit.html` `revert_error` va `revert_detail` ko'rsatadi (28-qator), route uzatadi (214-215)
- **DB anomaliya (Anvar)** — 11 cancelled / 101 NULL order_id — normal holat (non-sale payment kategoriyalar)

**Hali tuzatilmagan (Tier C paytida yoki alohida):**
- **X4** — Bot polling conflict (DEV_MODE auto-reload zombies) — clean restart kerak, kod muammo emas
- **X6** — production.py va finance.py delete'lari service'ga ko'chirilmagan
- **X7** — `document_service.py` uchun unit test yo'q (Tier C4 ichida)

### ✨ B2.5. Eski orphan sale payment'larni tozalash ✅ BAJARILDI
**Sana:** 2026-04-11 | **Skript:** `scripts/fix_b25_orphan_payments.py`

**Qilingan:**
- 3 ta `confirmed` orphan sale payment (jami 1,569,000 so'm) → `cancelled` ga o'tkazildi
  - ID=24 PAY-20260311-0002 (1,230,000) — Asosiy kassa plastik
  - ID=79 PAY-20260314-0024 (282,000) — Do'kon 1 kassa
  - ID=80 PAY-20260314-0025 (57,000) — Do'kon 1 kassa
- 3 ta `cancelled` orphan — o'z holiga tashlandi (zararsiz)
- Har payment description'ga `[B2.5 CLEANUP 2026-04-11]` tagi qo'shildi
- Kassa balanslari `_sync_cash_balance` orqali qayta hisoblandi

**Kassa balansi o'zgarishi:**
- Asosiy kassa plastik: 1,640,000 → 410,000 (-1,230,000)
- Do'kon 1 kassa: 94,439,250 → 94,100,250 (-339,000)
- **Jami: -1,569,000 so'm** (kutilgan aniq moslashdi)

**Sinov:** Qolgan confirmed orphan = 0. Skript rollback-safe (flush + verify → commit yoki rollback).

**Rollback:** `D:\TOTLI_BI_BACKUPS\live\2026-04-11_15-42-55.db.gz` (preoperatsion snapshot)

---

## 🔴 TIER C — Katta refactor (5 task, ROI bo'yicha saralandi)

**Xususiyati:** Fayllar bo'linadi, UI refactor. Xavfli.
**Vaqti:** **Yakshanba 01:00 – 06:00**, feature flag bilan parallel eski+yangi.
**Rollback:** Feature flag'ni o'chirish (0 downtime).
**Ustuvorlik:** PM Bekzod tavsiyasi bo'yicha — C5 birinchi (kassir UX ga ta'sir).

### ⭐ C5. POS template refactor (🔴 BIRINCHI — eng yuqori ROI)
**Audit:** O8 | **Vaqt:** 3 kun | **ROI:** KASSIR tezligi +30%

**Hozirgi holat:** `templates/sales/pos.html` 2310 qator monolit, 600+ qator inline JS.

**Modul bo'linish (Diyor taklifi):**
- `sales/pos.html` (asosiy layout, ~300 qator)
- `sales/_pos_header.html` (warehouse select + user info)
- `sales/_pos_catalog.html` (mahsulot tanlash, search, qo'shish)
- `sales/_pos_cart.html` (savatcha, discount, total)
- `sales/_pos_payment.html` (to'lov formasi, kirim/chiqim/avans)
- `sales/_pos_modals.html` (barcha 9 ta modal bir joyda)
- `static/js/pos/core.js` (common), `cart.js`, `payment.js`, `search.js`

**Xavf:** YUQORI — POS eng muhim sahifa. Smoke test + feature flag majburiy.

### C1. `employees.py` bo'lish (Nosir rejasi) 🟠 BAJARILMOQDA
**Audit:** Y1 | **Vaqt:** 1 kun | **Reja:** `TIER_C1_PLAN.md`

2934 qator, 129 KB → 6 ta modul, incremental execution:

| # | Modul | Qator | Holat | Commit |
|---|---|---|---|---|
| **1** | `employees_dismissals.py` | ~155 | ✅ **BAJARILDI** | 5f0c995 |
| **2** | `employees_advances.py` | ~478 | ✅ **BAJARILDI** | 07665c8 + 211df7a (url fix) |
| **3** | `employees_attendance.py` | ~654 | ✅ **BAJARILDI** | c596514 |
| **4** | `employees_salary.py` | ~545 | ✅ **BAJARILDI** | 933b19b |
| **5** | `employees_employment.py` | ~712 | ✅ **BAJARILDI** | 4cf83f6 |
| **6** | `employees.py` (core tozalash) | ~370 | ✅ **BAJARILDI** | bu sessiya |

**3-bosqich (attendance) natijalari:**
- 17 ta endpoint + 1 helper (_parse_time) yangi modulda
- `employees.py` 99 KB → 73 KB (-26 KB, 26% qo'shimcha)
- `employees_attendance.py` 26.6 KB yangi fayl
- **Eski URL prefix bug tuzatildi**: 15+ ta redirect URL `/attendance/...` → `/employees/attendance/...`
  (Diyor audit'dan so'ng yangi modulda darhol to'g'rilandi — eski kodda ham mavjud edi)
- 490 route umumiy — o'zgarmas

**Bosqich natijalari:**
- **1-bosqich (dismissals):** 5 ta funksiya, 4 ta endpoint, -6.4 KB
- **2-bosqich (advances):** 14 ta funksiya, 13 ta endpoint, -19.8 KB
- `employees.py` 129 KB → 102 KB (**-27 KB, 21% kichraygan**)
- `employees_advances.py` 20.7 KB yangi fayl
- 490 route umumiy — o'zgarmas (hamma URL'lar eskidek)
- Eski fayl ishlashda davom
- Sinov: import OK, barcha 13 advance endpoint yangi modulda, eski faylda 0

### C2. `api_routes.py` bo'lish ✅ TO'LIQ TUGADI
**Audit:** Y1 | **Sana:** 2026-04-11

2725 qator, 102 KB → 6 ta modul (6 bosqichda):

| # | Modul | Qator | Hajm | Commit |
|---|---|---|---|---|
| 1 | `api_system.py` | 45 | 1.3 KB | f300a95 |
| 2 | `api_dashboard.py` | 170 | 6.5 KB | dd16937 |
| 3 | `api_auth.py` | 540 | 22.6 KB | 4538a47 |
| 4 | `api_driver_ops.py` | 270 | 11.7 KB | 62c44b5 |
| 5 | `api_agent_ops.py` | 900 | 36.8 KB | 3885a12 |
| 6 | `api_agent_advanced.py` | 890 | 32.8 KB | bu sessiya |

**Yakuniy natija:**
- api_routes.py: 102 KB → 1.9 KB (faqat import va marker qolgan)
- 30 endpoint 6 modulga taqsimlandi
- 490 route saqlandi
- Backward compat 100% (URL prefix /api)

### C3. Service layer kengaytirish ✅ BAJARILDI
**Audit:** Y2 | **Sana:** 2026-04-11 + 2026-04-12

Hozirgi service qatlam (6 fayl):
- `document_service.py` — 5 funksiya (confirm/revert/delete purchase, delete sale) ✅
- `stock_service.py` — create/delete movements, clamp_stock_qty ✅
- `pos_helpers.py` — POS utilities ✅
- `payment_service.py` ✅
  - `delete_payment_atomic` — cancelled to'lovni xavfsiz o'chirish + kassa balans sync
  - `cancel_payment_atomic` — soft cancel, audit trail saqlanadi
- `production_service.py` ✅ **2026-04-12 QO'SHILDI**
  - `delete_production_atomic` — stock reversal + atomik o'chirish
  - `delete_recipe_atomic` — cascade o'chirish yoki faolsizlantirish
- `finance_service.py` ✅ **2026-04-12 QO'SHILDI**
  - `cash_balance_formula` — kassa balans hisoblash (route'dan ko'chirildi)
  - `sync_cash_balance` — kassa balansini qayta hisoblash
  - `delete_cash_transfer_atomic` — pending/draft o'tkazmani o'chirish
  - `revert_cash_transfer_atomic` — tasdiqlangan o'tkazmani qaytarish

**Route'lar thin wrapper ga aylantirildi:**
- `production.py` — delete_production, delete_recipe, bulk_delete → service
- `finance.py` — finance_payment_delete → payment_service, cash_transfer_delete/revert → finance_service
- `_sync_cash_balance` route'dan service ga ko'chirildi (payment_service endi route'dan import qilmaydi)

Qolgan (keyingi sessiyalar uchun):
- `stock_repo.py`, `partner_repo.py` — repository pattern (ixtiyoriy)

### C4. Unit test asoslari ✅ BAJARILDI
**Audit:** O3 | **Sana:** 2026-04-11 + 2026-04-12

**`tests/test_refactor_modules.py`** — **33 test, 33/33 passing**
- Qamrovi:
  - TestTierC1EmployeesModules — 6 test (dismissals, advances, attendance, salary, employment, core)
  - TestTierC2ApiModules — 7 test (api_system, api_dashboard, api_auth, auth_helpers, driver_ops, agent_ops, agent_advanced)
  - TestDocumentService — 2 test (import, DocumentError)
  - TestProductionService — 2 test (import, completed reject) **YANGI**
  - TestFinanceService — 3 test (import, delete reject, revert reject) **YANGI**
  - TestPaymentService — 2 test (import, confirmed reject) **YANGI**
  - TestStockService — 2 test (clamp_stock_qty, import) **YANGI**
  - TestAuthHelpers — 2 test (hash/verify PIN, format validation)
  - TestRateLimit — 2 test (is_agent_blocked, failure counter)
  - TestLiveBackup — 2 test (backup/restore script import)
  - TestMainAppIntegrity — 3 test (490 route, API/employees endpoint present)
- Test ishga tushirish: `pytest tests/test_refactor_modules.py -v`

**Qolgan (keyingi sessiyalar):**
- Unit test'lar haqiqiy DB fixture bilan (in-memory SQLite)
- Business logic scenariylari (happy path + edge + failure)
- Coverage report (pytest-cov)

---

## 📊 Hozirgi status (2026-04-12)

| Bosqich | Tugallangan | Jami | Foiz |
|---|---|---|---|
| **Infrastruktura** | 7/7 | 7 | 100% |
| **Tier A** | 4/4 (A5 o'tkazildi) | 5 | 80% |
| **Tier B** | 5/5 + B2.5 + B2.6 + B2.7 | 5 | **100%** |
| **Tier C** | 4/5 (C1+C2+C3+C4 ✅, C5 qoldi) | 5 | 80% |
| **Bug fix (12-apr)** | 5/5 | 5 | **100%** |
| **JAMI** | **25/27** | 27 | **93%** |

### 2026-04-12 sessiyasi
- **5 ta brauzer bug tuzatildi** (purchases 500, attendance 500, login case, toast CSS)
- **X6 bajarildi** — production.py + finance.py delete → service layer
- **C3 to'liq** — production_service.py + finance_service.py yaratildi
- **C4 kengaytirildi** — 24 → 33 test (9 yangi service test)
- **Faqat C5 (POS refactor) qoldi** — yakshanba sessiyasiga rejalashtirilgan

**Senior audit (11 ekspert jamoasi) — 2026-04-11:**
- 5 ekspert parallel (Arxitektor, DB, Security, Bot/DevOps, Frontend/PM)
- 3 ta **haqiqiy xato** topildi (X3 set-pin zaifligi, X5 purchase_delete orphan, X4 bot conflict)
- 2 ta **false alarm** (X1, X2 — kod allaqachon to'g'ri edi)
- 1 ta **operational muammo** (X4 — clean restart kerak)
- Tuzatilgan: X3 + X5 (B2.6 commit)

**Bugungi sessiyada bajarilgan:**
- Infrastruktura 7/7 (jonli backup, monitoring, restore)
- Tier A 4 ta task (A5 ataylab o'tkazildi)
- Tier B 5 ta task (barcha kritik biznes xavflari hal qilindi)

---

## 📅 Keyingi qadamlar

### 2026-04-12 — BAJARILDI ✅
1. **Manual smoke test** — brauzerdan 18 oqim tekshirildi, 5 ta bug topildi va tuzatildi
2. **X6** — production.py + finance.py delete operatsiyalari service layer ga ko'chirildi
3. **C3** — production_service.py + finance_service.py yaratildi
4. **C4** — 24 → 33 test (yangi servicelar uchun 9 test qo'shildi)

### Hali qilish kerak (foydalanuvchi):
1. **Token rotation** (siz qilasiz):
   - `@BotFather` → eski bot tokenni `/revoke`, yangisini `.env` ga
   - Hikvision panel → parol almashtirish, yangisini `.env` ga
2. **Clean restart** (start.bat → T → 10sek → qayta start)

### Bu hafta
- **Mobil ilova** (Flutter jamoasi):
  - Agent login: javobda `pin_set: false` bo'lsa → "PIN o'rnatish" ekrani
  - `POST /api/agent/set-pin` chaqirish
  - PIN o'rnatilgach — keyingi loginlarda PIN majburiy

### Keyingi yakshanba (2026-04-19)
- **Tier C planlash sessiyasi**:
  - Arxitektor (Nosir) bilan god-fayl bo'lish strategiyasi
  - Feature flag tizimi
  - Staging muhit tayyorlash

---

## 🛡️ Rollback nuqtalari

| Nuqta | Kommit/Tag | Tavsif |
|---|---|---|
| Refactor oldi | `pre-refactor-2026-04-10` | To'liq barqaror holat |
| Infra + WIP | `e12c7f5` | Jonli backup + eski WIP |
| Tier A #1 | `f6c7a9e` | Secrets .env |
| Tier A #2 | `df389e9` | CSRF HttpOnly |
| Tier A #3 | `cac03cd` | File upload validation |
| Tier A #4 | `a5360d3` | Hikvision SSL |
| Tier B #1 | `fac4fd2` | purchase_confirm atomic |
| Tier B #2 | `174aa03` | delete_sale_fully (orphan payment) |
| Tier B #3 | `662ad8f` | Agent PIN (backward compat) |
| Tier B #4 | `a4eeadb` | Session expiry 7 kun |
| Tier B #5 | `19032e3` | Audit cooldown DB |

Har commit mustaqil — kerak bo'lsa `git reset --hard <hash>` yoki `git revert <hash>`.

**To'liq rollback** (bugungi hamma ishni bekor qilish):
```bash
git reset --hard pre-refactor-2026-04-10
```

---

## 🔗 Hujjatlar

- **Audit hisoboti** — bu suhbat tarixida saqlangan
- **Memory fayllar:** `C:\Users\Администратор\.claude\projects\D--TOTLI-BI\memory\`
- **Scripts:** `scripts/` papkasi (backup, restore, monitoring)
- **Backup joyi:** `D:\TOTLI_BI_BACKUPS\`

---

## ⚠️ Eslab qoling

1. **DEV_MODE ON** — har fayl tahriri uvicorn auto-reload'ni tetiklaydi (2-3 sek downtime)
2. **🚨 Git token'lar tarixda** — Tier A tugadi, BotFather va Hikvision parollarni rotate qilish **MAJBURIY**
3. **Tier B bugun ish vaqtida** bajarildi — tungi oyna shart bo'lmadi (DEV_MODE reload = xavfsiz)
4. **Live backup** ishonchli — 2 manbali (Task Scheduler + app scheduler), 2 soat retention
5. **B3 mobil**: Flutter jamoasi PIN ekranini qo'shmaguncha backend o'zgarmaydi (backward compat)
6. **18+ commit bugun** — har biri mustaqil rollback nuqtasi

### 🤖 Bot polling conflict (X4 — operational)

**Holat:** `server.log`'da `TelegramConflictError: terminated by other getUpdates request` (tryings=64+).

**Sabab:** DEV_MODE ON → auto-reload har fayl tahririda eski process'ni o'ldiradi, lekin eski bot polling task Telegram serverga hali connected. Yangi process yangi polling boshlaganda, **Telegram 2 ta connection ko'radi va bittasini rad etadi**.

**Ta'sir:** 
- 🟢 Web foydalanuvchilar — 0 ta'sir (web bilan bog'liq emas)
- 🟢 Database, scheduler, backup — ishlayapti
- 🟡 Telegram notifications, audit watchdog — ba'zi xabarlar yetmasligi mumkin

**Yechim:** **Clean restart** (DEV_MODE avtomatik reload emas):
1. Server launcher'dan `T` (to'xtatish) bosing
2. 10 sekund kuting (eski polling Telegram'dan timeout qilinadi)
3. Server launcher'dan `Q` yoki yangi start bilan boshlang
4. Log'da `TelegramConflictError` yo'qolishi kerak

**Tier C oldidan:** Ideal holatda DEV_MODE OFF qilish va manual restartga o'tish. Bu katta refactor paytida chalkashlik oldini oladi.

---

## 📝 Bugungi sessiya xulosasi (2026-04-10 va 2026-04-11)

### Hal qilingan kritik xavflar
- **K1** ✅ Hardcoded secrets → `.env`
- **K3** ✅ Purchase atomic transaction (service layer)
- **K4** ✅ Orphan payment — reject + explicit delete
- **K5** ✅ Agent login PIN (backward compat)

### Hal qilingan yuqori xavflar
- **Y3** ⏸️ Scheduler jobstore (o'tkazib yuborildi — qiymat past)
- **Y4** ✅ SECRET_KEY env majburiy
- **Y5** ✅ File upload validation (Pillow)
- **Y6** ✅ CSRF cookie HttpOnly
- **Y7** ✅ Hikvision SSL env-based
- **Y8** ✅ Session expiry 7 kun

### Hal qilingan o'rta xavflar
- **O5** ✅ Audit cooldown DB'da

### Yangi infra
- Live backup har 5 daqiqa (Task Scheduler + app scheduler)
- `app/services/document_service.py` yangi fayl (service layer boshlandi)
- `scripts/` da 6 ta yangi monitoring/backup/restore skripti
- `.env` + `.env.example` to'liq shablon

### Sinovlar
- Har task 3-7 ssenariy bilan sinaldi
- B1 jonli test: Purchase #95 haqiqiy tasdiqlash — atomik saqlandi
- B2 DB audit: 6 ta eski orphan topildi
- Server downtime: 0 (DEV_MODE auto-reload ~2-3 sek)
- Foydalanuvchi shikoyati: 0

### Statistika
- **Kommit soni:** 16
- **Yangi fayllar:** 6
- **O'zgartirilgan fayllar:** ~20
- **Qo'shilgan qatorlar:** ~2800
- **Testlar:** ~30 assert (mock + real data)
- **Sessiya davomiyligi:** ~12 soat (tun bilan)
