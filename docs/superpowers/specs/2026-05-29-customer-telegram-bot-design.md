# Mijoz Telegram boti — Dizayn hujjati

**Sana:** 2026-05-29
**Muallif:** Elyor + AI senior arxitektor
**Holat:** Tasdiqlash kutilmoqda

## 1. Maqsad

Mijozlar (kontragentlar) uchun alohida Telegram bot. Mijoz o'z buyurtmalari, to'lovlari va qarz/avans qoldig'ini **faqat o'qiy oladi** — hech narsa o'zgartira olmaydi. Agent yoki haydovchi ilovasi ishlamay qolганda ham mijoz qarz/avans qoldig'ini Telegram orqali ko'ra oladi.

## 2. Asosiy talablar

1. Agent buyurtma kiritib, tasdiqlanganda → mijozga "buyurtma qabul qilindi" xabari
2. Buyurtma haydovchiga yuklanganda → "yo'lda" xabari
3. Buyurtma yetkazilganda + to'lov → "№… yetkazildi, to'langan …, qoldiq …" xabari
4. Agent mijozdan pul qabul qilganda (supervisor tasdiqlagach) → "AG-001 Akbarjon … so'm qabul qildi, qoldiq …" xabari
5. Sana oralig'ida (yil/oy/kun) buyurtmalar, summalar, to'lovlar tarixi
6. Ilova ishlamasa ham qarz/avans qoldig'i ko'rinadi (`partner.balance` — DB o'qish)

## 3. Qabul qilingan qarorlar

| Qaror | Tanlov |
|---|---|
| Ro'yxatdan o'tish tasdiqlash | Admin Telegram'da inline tugma bilan tasdiqlaydi |
| Tarix sana oralig'i UX | Tez tugmalar (Bugun/Shu hafta/Shu oy/30 kun) + qo'lda oraliq |
| Agent to'lovi xabari vaqti | Supervisor tasdiqlagach (qoldiq aniq bo'ladi) |
| Bot jarayoni | Mustaqil process (o'z tokeni, socket-lock 47893) |
| Tasdiqlanmagan foydalanuvchi | Har doim "telefon ulashing" so'raladi (hamma read gate'langan) |
| Raqam kiritish | Faqat Telegram contact tugmasi (qo'lda matn qabul qilinmaydi) |

## 4. Ma'lumotlar modeli (additive — migratsiya xavfi yo'q)

Yangi jadval `customer_bot_links` (mavjud `ChatTelegramLink` namunasida). `Partner` jadvaliga tegmaymiz.

```python
class CustomerBotLink(Base):
    __tablename__ = "customer_bot_links"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String(50), unique=True, index=True)
    telegram_username = Column(String(100), nullable=True)
    telegram_full_name = Column(String(200), nullable=True)
    phone = Column(String(20))                # ulashilgan raqam (normallashtirilgan)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=True, index=True)
    status = Column(String(20), default="pending")  # pending | approved | rejected
    requested_at = Column(DateTime, default=datetime.now)
    approved_at = Column(DateTime, nullable=True)
    approved_by = Column(String(100), nullable=True)  # admin telegram id/username
```

- Yangi jadval `Base.metadata.create_all` orqali avtomatik yaratiladi — mavjud schema'ga ta'sir yo'q.
- `partner.balance` ishonchli manba: `> 0` = qarz, `< 0` = avans. **Qayta hisoblanmaydi.**
- Bitta telegram_id = bitta link (unique). Bir partner'ga bir nechta telegram ulanishi mumkin (do'kon egasi + menejer).

## 5. Bot jarayoni (mustaqil process)

```
app/bot/customer_bot/
  config.py        — CUSTOMER_BOT_TOKEN, CUSTOMER_BOT_ADMIN_IDS, LOCK_PORT=47893
  bot.py           — Bot+Dispatcher, polling entry (aiogram 3.x, HTML, MemoryStorage)
  registration.py  — telefon match + admin tasdiq logikasi
  handlers.py      — /start, contact, menyu, hisobot, callback handlerlar
  queries.py       — faqat o'qish DB so'rovlari (buyurtma, balans, oraliq hisobot)
  notify.py        — notify_customer(partner_id, text) — web hooklar ishlatadi
scripts/customer_bot_standalone.py  — socket-lock 47893 + runner (load_dotenv)
```

- **Token:** yangi BotFather token `CUSTOMER_BOT_TOKEN` (mavjud tokenlarni qayta ishlatmaymiz — 409 konflikt).
- **Admin:** `CUSTOMER_BOT_ADMIN_IDS` (default egasi `1340383182`).
- **Socket-lock port 47893** (47891 = sheets bot, 47892 = senior botlar band).
- `start.bat`: `:start_customer_bot_if_needed` + `:kill_customer_bot` bloklari, `:do_restart`/`:do_stop` ga qo'shiladi.

## 6. Ro'yxatdan o'tish + tasdiq oqimi

1. `/start` → bot salomlashadi, **contact tugmasi** ko'rsatadi ("📱 Telefon raqamni ulashish").
2. Mijoz raqamni ulashadi → bot **normallashtiradi** → `Partner.phone` / `phone2` bilan solishtiradi (faqat `is_active`, type `customer`/`both`).
   - **1 aniq mos** → pending `CustomerBotLink` yaratiladi → adminga inline `✅ Tasdiqlash / ❌ Rad etish` tugmali xabar.
   - **Bir nechta mos** → adminga nomzod do'konlar tugma ro'yxati, admin to'g'risini tanlaydi.
   - **Mos yo'q** → mijozga "Raqamingiz topilmadi, agentingizga murojaat qiling".

### 6.1. Telefon mosligi — ANIQ qoida (kritik)

Kontragent raqamlari turli formatda saqlangan: `+998946862724`, `998910558888`, `99899 652 82 60`, nom ichida raqam, `0.....` (soxta), ikkinchi raqam `phone2` da. Telegram contact esa xalqaro formatda (`998...`) beradi.

**Yechim — oxirgi 9 raqam bo'yicha solishtirish:**
```python
def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    return digits[-9:] if len(digits) >= 9 else None  # milliy qism (9 xonali)
```
- Solishtirish: `normalize_phone(telegram_phone) == normalize_phone(partner.phone)` YOKI `== normalize_phone(partner.phone2)`.
- `+998`, `998`, bo'sh joy, `+` farqi yo'qoladi — barchasi to'g'ri mos keladi.
- 9 xonadan kam raqam (`0.....` kabi soxta) → `None` → hech qachon mos kelmaydi (link yaratilmaydi).
- **Mijoz raqami kontragent raqami bilan mos kelmasa — hech qanday ma'lumot taqdim etilmaydi** (asosiy talab).
3. Admin ✅ → `status=approved`, `partner_id` o'rnatiladi, `approved_by/at` yoziladi → mijozga "Ulandingiz!" + asosiy menyu.
4. Admin ❌ → `status=rejected` → mijozga muloyim rad xabari.
5. Qayta `/start` (allaqachon approved) → to'g'ridan-to'g'ri menyu.
6. **Gate:** tasdiqlanmagan foydalanuvchi nima yozsa ham — doim contact so'raladi. Approved bo'lmasa hech qanday shaxsiy ma'lumot ko'rinmaydi.

## 7. Mijoz menyusi (faqat o'qish)

Reply keyboard:
- 📦 **Buyurtmalarim** — oxirgi N buyurtma + holati (qabul qilindi / yo'lda / yetkazildi / bekor)
- 💰 **Qarz/Avans qoldig'i** — `partner.balance`: `>0` "Qarzingiz: X", `<0` "Avans: Y", `0` "Qarzdorlik yo'q"
- 📅 **Hisobot** — Bugun / Shu hafta / Shu oy / Oxirgi 30 kun + "Oraliq tanlash" (boshlanish–tugash sanasi) → buyurtmalar + to'lovlar + jami summa
- ℹ️ **Yordam**

Balans har doim `partner.balance` dan to'g'ridan-to'g'ri o'qiladi — agent/haydovchi ilovasidan mustaqil, **ilova ishlamasa ham ishlaydi**.

## 8. Bildirishnomalar (push hooklar)

`app/bot/customer_bot/notify.py` → `notify_customer(partner_id, text)`:
- Shu `partner_id` uchun `approved` linklarni topadi.
- `CUSTOMER_BOT_TOKEN` bilan yangi `Bot` ochib, `sendMessage` qiladi, `finally` da sessiyani yopadi.
- **Polling jarayoniga bog'liq emas** — token bilan istalgan kod xabar yubora oladi.
- **Fire-and-forget + try/except** — Telegram xatosi biznes operatsiyasini HECH QACHON buzmaydi.

| Hodisa | Hook joyi (audit) | Xabar |
|---|---|---|
| Buyurtma tasdiqlandi | `sales.py` `sales_confirm` (agent branch, ~:808) | "✅ Buyurtma №{number} qabul qilindi. Summa: {total} so'm" |
| Haydovchiga yuklandi | `sales.py` `sales_dispatch` (~:964/:1090) | "🚚 Buyurtma №{number} yo'lda" |
| Yetkazildi + to'lov | `api_driver_ops.py` `driver_delivery_status` delivered (~:351-365) | "📦 №{number} yetkazildi. To'langan: {paid}. Qoldiq: {balance}" |
| Agent to'lov qabul qildi | `delivery_routes.py` `supervisor_confirm_agent_payment` (~:1060) | "💰 {agent_code} {agent_name} {amount} so'm to'lov qabul qildi. Joriy qoldiq: {balance}" |

Barcha hooklar mutatsiyadan **keyin** `partner.balance` ni o'qiydi (aniq joriy qoldiq).

## 9. Xavfsizlik & xatolik

- Bot domain ma'lumotiga **yozmaydi** — faqat o'z `customer_bot_links` jadvaliga (ro'yxatdan o'tishda).
- Hamma read komandasi `approved` link bilan himoyalangan.
- Telefon aniq mosligi + admin tasdiq → boshqa mijoz ma'lumoti oshkor bo'lmaydi.
- Admin callbacklari `from_user.id in CUSTOMER_BOT_ADMIN_IDS` bilan tekshiriladi.
- Notify hooklar fire-and-forget — jonli tizimga **0 ta'sir**.
- SQLite vaqt: `sa_func.date(Order.date)` ishlatiladi, `'localtime'` modifikator yoki raw SQL `isoformat()` ISHLATILMAYDI (Tashkent vaqti tuzog'i).
- Telefon normallashtirish: `re.sub(r'\D', '', phone)` — POS qidiruv fix bilan bir xil yondashuv.

## 10. Deploy & test (tier)

- **Tier A:** yangi jadval (`create_all`), yangi mustaqil process, `start.bat` bloklari — mavjud logikaga tegmaydi.
- **Tier B:** 4 ta notify hook route fayllarga qo'shiladi (try/except bilan o'ralgan, fire-and-forget). Tungi oynada (00:00–04:00) deploy.
- **Token:** `CUSTOMER_BOT_TOKEN` env'ga qo'shiladi (start.bat / .env). Egasi yaratdi.

**Smoke test:**
1. Test partner (telefon bilan) yaratish
2. Bot orqali `/start` → contact ulashish → admin tasdiq → menyu
3. Balans ko'rsatish to'g'riligini tekshirish
4. Test buyurtma: yaratish → tasdiqlash → dispatch → yetkazish → har bosqichda xabar kelishini tekshirish
5. Agent to'lov → supervisor tasdiq → xabar

## 11. Komponentlar ro'yxati

- `app/models/database.py` → `CustomerBotLink` model
- `app/bot/customer_bot/{config,bot,registration,handlers,queries,notify}.py`
- `scripts/customer_bot_standalone.py`
- `start.bat` → customer bot launch/kill bloklari
- 4 hook: `sales.py` (x2), `api_driver_ops.py`, `delivery_routes.py`

## 12. Bu spec'ga KIRMAYDI (YAGNI)

- Mijoz tomonidan buyurtma berish / to'lov qilish (faqat o'qish)
- Push reklama / ommaviy xabar yuborish
- Ko'p tillilik (faqat o'zbekcha)
- Mijoz profilini tahrirlash
