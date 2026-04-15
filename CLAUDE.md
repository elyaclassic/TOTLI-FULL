# TOTLI BI — Loyiha konteksti

**TOTLI BI** — halva/qandolatchilik ishlab chiqarish korxonasi uchun biznes-intellekt tizimi.

## Tech stack

- **Backend:** Python, FastAPI, SQLAlchemy, Alembic
- **DB:** SQLite (`totli_holva.db`, serverda joylashgan)
- **Frontend:** Jinja2 templates, PWA (push notifications, audio TTS)
- **Mobile:** Flutter (`totli_mobile/`)
- **Bot:** Telegram botlar (`app/bot/`, `external/telegram_sheets_bot/`)
- **Xarita:** Leaflet/OpenStreetMap
- **Davomat:** Hikvision kameralar integratsiyasi
- **Deploy:** Windows Server, `start.bat` orqali ishga tushadi

## Asosiy modullar

- **POS** (sotuv nuqtasi) — `app/routes/sales.py`, `app/services/pos_helpers.py`
- **Production** (ishlab chiqarish, retseptlar, bosqichlar) — `app/routes/production.py`, `app/services/production_service.py`
- **Stock** (ombor, xom ashyo, mahsulot harakati) — `app/routes/qoldiqlar.py`, `app/routes/warehouse.py`, `app/services/stock_service.py`
- **Agents** (agentlar, tashriflar, xarita) — `app/routes/agents_routes.py`
- **Supervisor dashboard**
- **Kunlik tabel** (davomat) — Hikvision orqali avtomatik
- **Foyda/zarar hisobotlari** — `app/routes/finance.py`, `app/routes/reports.py`
- **Push bildirishnomalar** (ovozli TTS)

## Muloqot uslubi

- **O'zbek tilida** javob berish
- **Qisqa va aniq** javoblar — ortiqcha tushuntirish yo'q
- Har o'zgarishdan keyin xotirani yangilab qo'yish (agar xotira tizimi ulangan bo'lsa)

## Kodda muhim qoidalar

### Stock (qoldiq) tizimi

- **Yagona haqiqat manbai:** `Stock.quantity == sum(StockMovement.quantity_change)` — har doim `create_stock_movement()` orqali o'zgartirish
- **To'g'ridan-to'g'ri `stock.quantity = X` yozish TAQIQLANADI** (faqat initial balance, merge, import kabi alohida hollardan tashqari)
- **Manfiy qoldiqni yashirma:** `max(0, ...)` clamp ma'lumot yo'qolishiga olib keladi — epsilon tozalash uchun `epsilon_clean_qty()` ishlating
- **Revert operatsiyalarida:** delta ayirib/qo'shish emas, balki teskari `create_stock_movement()` chaqiring
- **Inventarizatsiya (INV) vs Qoldiq kiritish (QLD):** INV aniq raqamga almashtiradi, QLD mavjud qoldiqqa qo'shadi

### Kassa va balans

- Kassa balansi doim `cash_balance_formula()` orqali hisoblanadi: `opening + income - expense`
- Kontragent/xodim balansi hujjatda `previous_balance` snapshot sifatida saqlanadi (revert uchun)

### Middleware whitelist

Yangi `/api/agent/*` yoki `/api/driver/*` endpoint qo'shilganda **ikkita joyda** whitelist qilish kerak:
- `app/middleware.py` CSRF whitelist (~99-qator)
- `app/middleware.py` Auth whitelist (~170-qator)

### Foydalanuvchi ID lari

- `token.user_id` → `users.id`
- `Agent.user_id == user_id` orqali `agents.id` topiladi (teng emas!)
- `Driver.code == user.username` orqali `drivers.id` topiladi
- **HECH QACHON** `user_id` ni to'g'ridan-to'g'ri `agent_id` yoki `driver_id` sifatida ishlatmang

### Jinja2 shablonlar

- Custom `tojson` filter doimo `Markup(json.dumps(val))` qaytarsin (HTML escape qilmasin)
- HTML attribute ichida `tojson` ishlatganda **single quote** kerak: `onclick='func({{ val | tojson }})'`

### Server restart

- Route yoki middleware o'zgarganda server qayta ishga tushishi kerak
- `--reload` rejimi ba'zan ishlamaydi — qo'lda `taskkill //IM python.exe //F` keyin `start.bat` ishonchli
- Port: `8080`

## Xavfsiz deploy strategiyasi

TOTLI BI prod serveri **jonli foydalanilmoqda** (har 5 daqiqada yozuv). Har qanday tuzatish ish jarayoniga ta'sir qilmasligi kerak.

**Tier taqsimot:**

- **Tier A** (xavfsiz, istalgan vaqt): config, env variable, cookie flag — ta'sir 0
- **Tier B** (logika tuzatish): atomik transaction, orphan cleanup — **tungi oyna 00:00-04:00** (23:00 backup tugagach)
- **Tier C** (katta refactor): schema change, template refactor — **yakshanba kechasi**, feature flag bilan

**Majburiy qadamlar:**
1. Git branch (`safe-fix`) — asosiy `main` ga tegilmaydi
2. Backup oldin (git tag + DB dump)
3. Rollback skripti tayyor
4. Smoke test: login, asosiy sahifalar, test sale

**Migratsiya:** Faqat qo'shuvchi (additive) — ustun o'chirish TAQIQLANADI. `nullable=True` + default qiymat, downgrade skripti majburiy.

## Mobil build (Flutter)

- Gradle **kirill harfli katalogdan ishlamaydi** — `GRADLE_USER_HOME=C:\gradle_home` ishlatish
- `appVersion` va `appBuild` konstantalari `pubspec.yaml` bilan har doim birga yangilansin — aks holda cheksiz yangilanish loop
- connectivity_plus v6+ da `checkConnectivity()` → `List<ConnectivityResult>` (v5.x → yolg'iz enum)
- APK ni faqat `Directory.systemTemp.path` (cache) ichiga saqlash — FileProvider shu joyni taniydi

## Kod yozish tamoyillari

- **Kamroq kod yaxshiroq:** keraksiz xatolik ushlagichlar, fallback, abstraksiya qo'shmaslik
- **Komment yozmaslik:** faqat "nega" aniq bo'lmaganda qisqa bir qator yozish
- **Faqat chegarada validatsiya:** ichki kod va framework kafolatlariga ishonish
- **Boshqa ishlar kiritmaslik:** bug fix da refactor qilmaslik, featurega yangi abstraksiya qo'shmaslik

## O'zgaruvchan ma'lumotlar

Batafsil loyiha holati, xodimlar, infrastruktura va incident tarixi xotira tizimida (`MEMORY.md` + yordamchi `.md` fayllari) saqlanadi. Agar xotira tizimi ulangan bo'lsa, qo'shimcha kontekst shu yerdan o'qiladi.
