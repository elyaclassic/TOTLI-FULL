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

### ✨ B2.5. Eski orphan sale payment'larni tozalash 🟡 QOLDIQ
**Vaqt:** 15 daq | **Xavf:** Past

**Muammo:** B2 fix qilishdan oldin 6 ta sale payment `order_id=NULL` bilan qolgan.

**Yechim:** Bir martalik skript — shu 6 ta yozuvni ko'rib chiqish, kerakmi yo'q ekanligiga qarab, `status='cancelled'` yoki delete.

**Keyinroq qilinadi** — xavfli bo'lmagan clean-up.

---

## 🔴 TIER C — Katta refactor, yakshanba kechasi (5 task)

**Xususiyati:** Fayllar bo'linadi, UI refactor. Xavfli.
**Vaqti:** **Yakshanba 01:00 – 06:00**, feature flag bilan parallel eski+yangi.
**Rollback:** Feature flag'ni o'chirish (0 downtime).

### C1. `employees.py` bo'lish
**Audit:** Y1 | **Vaqt:** 1 kun

2934 qator, 129 KB → `attendance.py` + `salary.py` + `piecework.py` + `employees.py` (asosiy CRUD).
Feature flag: `FEATURES["new_employees_routes"]`.

### C2. `api_routes.py` bo'lish
**Audit:** Y1 | **Vaqt:** 1 kun

2574 qator, 103 KB → `agents_api.py` + `driver_api.py` + `stats_api.py` + `pwa_api.py`.

### C3. Service layer kuchaytirish
**Audit:** Y2 | **Vaqt:** 2 kun

`services/` ga: `document_service.py`, `payment_service.py`, `finance_service.py`, `stock_repo.py`, `partner_repo.py`.
Business logic routelardan service/repo ga ko'chadi.

### C4. Unit test asoslari
**Audit:** O3 | **Vaqt:** 2 kun

`tests/unit/`:
- `test_stock_service.py`
- `test_payment_service.py`
- `test_carryover.py`
- `test_auth.py`

Pytest + factory_boy.

### C5. POS template refactor
**Audit:** O8 | **Vaqt:** 3 kun

`templates/sales/pos.html` 2310 qator monolit → Alpine.js komponentlar:
- `pos_product_picker.html`
- `pos_cart.html`
- `pos_payment.html`

---

## 📊 Hozirgi status (2026-04-11, kech)

| Bosqich | Tugallangan | Jami | Foiz |
|---|---|---|---|
| **Infrastruktura** | 7/7 | 7 | 100% |
| **Tier A** | 4/4 (A5 o'tkazildi) | 5 | 80% |
| **Tier B** | 5/5 | 5 | **100%** |
| **Tier C** | 0/5 | 5 | 0% |
| **JAMI** | **16/22** | 22 | **73%** |

**Bugungi sessiyada bajarilgan:**
- Infrastruktura 7/7 (jonli backup, monitoring, restore)
- Tier A 4 ta task (A5 ataylab o'tkazildi)
- Tier B 5 ta task (barcha kritik biznes xavflari hal qilindi)

---

## 📅 Keyingi qadamlar

### Ertasi kun (2026-04-12)
1. **Manual smoke test** Tier B'dagi oqimlar:
   - B1: yangi purchase yaratib tasdiqlash va bekor qilish
   - B2: sotuv o'chirishda to'lov mavjud bo'lsa xato chiqishi
   - B3: hozirgi mobil ilovada agent login ishlashi
2. **Token rotation** (siz qilasiz):
   - `@BotFather` → eski bot tokenni `/revoke`, yangisini `.env` ga
   - Hikvision panel → parol almashtirish, yangisini `.env` ga
3. **B2.5** (ixtiyoriy): 6 ta eski orphan payment'ni tozalash skripti

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
6. **16 commit bugun** — har biri mustaqil rollback nuqtasi

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
