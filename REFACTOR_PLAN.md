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

### B1. `purchase_confirm` atomic transaction 🔴 YUQORI PRIORITET
**Audit:** K3 | **Vaqt:** 2-3 soat | **Xavf:** O'rta

**Muammo:** `app/routes/purchases.py:376-438` — stock movement + partner balance + purchase_price 3 alohida operatsiya, lekin 1 commit. Xato bo'lsa yarim saqlangan holat.

**Oldingi incident:** `project_purchase_double_bug.md` — 173 stock buzilgan edi (29.03–05.04).

**Yechim:**
1. `app/services/document_service.py` yaratish — `save_purchase_with_stock_and_balance()` wrapper
2. Bitta `try/db.commit()/except db.rollback()` ichida barcha 3 operatsiya
3. `create_stock_movement()` ichidan commit olib tashlash (caller qo'lida commit)
4. Smoke test: yangi purchase yaratish → stock/balance/price hammasi to'g'ri yoki hammasi orqaga qaytgan

**Test fayllari:**
- `tests/test_purchase_atomic.py` (yangi) — happy path + network fail scenario

### B2. Orphan payment fix 🔴 YUQORI PRIORITET
**Audit:** K4 | **Vaqt:** 2-3 soat | **Xavf:** O'rta

**Muammo:** `app/services/stock_service.py:107` — `delete_stock_movements_for_document` faqat movement o'chiradi, Payment qoladi.

**Oldingi incident:** `project_doc_links_and_export.md` — orphan payment muammosi.

**Yechim:**
1. `app/services/document_service.py` ga `delete_document_fully()` qo'shish
2. Bu funksiya: Stock movement + Payment + Balance adjust bir joyda
3. Hujjat o'chirish endpointlari (`purchase`, `sale`, `expense`, `income`) shu funksiyaga o'tadi
4. Migration yo'q — faqat kod o'zgarishi

**Test fayllari:**
- `tests/test_delete_document.py` (yangi) — hujjat o'chganda payment ham yo'qolishi

### B3. Agent login PIN 🟠 O'RTA PRIORITET
**Audit:** K5 | **Vaqt:** 2-3 soat | **Xavf:** O'rta (UX)

**Muammo:** `app/routes/api_routes.py:~485` — agent paroli = telefon raqami. Brute-force 10 daqiqa.

**Yechim:**
1. `Agent` jadvaliga `pin_hash` ustun qo'shish (alembic migration)
2. Birinchi loginda PIN o'rnatish majburiy (4-6 raqam)
3. Keyingi login: telefon + PIN
4. Rate limiter: 5 urinish → 15 daq blok
5. **Eslatma:** mobil ilova ham yangilanishi kerak — yangi flow bilan moslashtirish

**Alembic migration:**
- `alembic/versions/add_agent_pin_hash.py` — `ALTER TABLE agents ADD COLUMN pin_hash VARCHAR(255) NULL`
- Backward compat: eski agentlar birinchi logindan keyin PIN o'rnatadi

**Mobil ilova:** **alohida task** — backend tayyor, mobil ilovaga yangi screen qo'shish kerak.

### B4. Session expiry 7 kun (mobil uchun refresh) 🟡 PAST PRIORITET
**Audit:** Y8 | **Vaqt:** 1 soat | **Xavf:** Past

**Muammo:** `app/utils/auth.py:17` — `SESSION_MAX_AGE = 86400 * 30` (30 kun). Mobil token leak xavfi.

**Yechim:**
1. `SESSION_MAX_AGE = 86400 * 7` (7 kun)
2. Refresh token pattern: agar < 1 kun qoldi → yangi token beriladi
3. Mobil ilova o'rnatilgan foydalanuvchilar logout bo'lmasligi uchun migration: eski tokenlarga 7 kun grace

**Eslatma:** Bu sinovsiz qilinsa — aktiv mobil sessiyalar shilinib ketadi. **Ertalabda, barcha agent/driver qayta login qilishi kutilishi kerak.**

### B5. Audit watchdog cooldown DB'ga 🟡 PAST PRIORITET
**Audit:** O5 | **Vaqt:** 1 soat | **Xavf:** Past

**Muammo:** `app/bot/services/audit_watchdog.py:71` — cooldown in-memory, process restart da 2 marta xabar.

**Yechim:** `Notification` yoki yangi `AuditCooldown` jadvaliga timestamp yozish. Restart da DB dan o'qiladi.

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

## 📊 Hozirgi status (2026-04-11)

| Bosqich | Tugallangan | Jami | Foiz |
|---|---|---|---|
| **Infrastruktura** | 7/7 | 7 | 100% |
| **Tier A** | 4/4 (A5 o'tkazildi) | 5 | 80% |
| **Tier B** | 0/5 | 5 | 0% |
| **Tier C** | 0/5 | 5 | 0% |
| **JAMI** | 11/22 | 22 | 50% |

---

## 📅 Keyingi qadamlar (tavsiya)

### Bu hafta
1. ✅ Tier A tugadi
2. 🔜 **Tier B1** (purchase_confirm atomic) — **tungi oynada**, bugun 00:00–04:00 da
3. 🔜 **Tier B2** (orphan payment) — ertaga tungi oynada

### Keyingi hafta
4. **Tier B3** (agent PIN) — mobil ilova jamoasi bilan birga
5. **Tier B4** (session expiry) — agentlarga oldindan xabar berib

### Yakshanba
6. **Tier C1** (employees.py bo'lish) — feature flag bilan

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

Har commit mustaqil — kerak bo'lsa `git reset --hard <hash>` yoki `git revert <hash>`.

---

## 🔗 Hujjatlar

- **Audit hisoboti** — bu suhbat tarixida saqlangan
- **Memory fayllar:** `C:\Users\Администратор\.claude\projects\D--TOTLI-BI\memory\`
- **Scripts:** `scripts/` papkasi (backup, restore, monitoring)
- **Backup joyi:** `D:\TOTLI_BI_BACKUPS\`

---

## ⚠️ Eslab qoling

1. **DEV_MODE ON** — har fayl tahriri uvicorn auto-reload'ni tetiklaydi (2-3 sek downtime)
2. **Git token'lar tarixda** — Tier A tugagach BotFather va Hikvision parollarni rotate qilish majburiy
3. **Tungi oyna** Tier B uchun — 00:00–04:00 eng xavfsiz vaqt
4. **Live backup** ishonchli — 2 manbali (Task Scheduler + app scheduler)
