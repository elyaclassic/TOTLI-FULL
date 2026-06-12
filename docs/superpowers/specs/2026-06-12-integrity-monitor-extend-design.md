# DB Integrity Monitor — 5 yangi tekshiruv (kengaytirish)

**Sana:** 2026-06-12
**Holat:** Dizayn tasdiqlandi, implementatsiya kutilmoqda

## Maqsad

Mavjud `scripts/integrity_check.py` (9 tekshiruv, read-only, Telegram alert) ga
bugungi sessiyada topilgan 3 bug turi + 2 moliyaviy invariant uchun **5 yangi
tekshiruv** qo'shish. Maqsad: shu kabi buglar kelajakda avtomatik (kunlik)
ushlanib, Yordamchim bot orqali xabar berilsin.

## Mavjud holat (o'zgarmaydi)

`integrity_check.py` arxitekturasi:
- Standalone `sqlite3` (ORM emas — tez, bog'liqliksiz), faqat `totli_holva.db` o'qiydi
- Har tekshiruv funksiyasi: `(issue_count: int, message: str | None)` qaytaradi
- `CHECKS` ro'yxati → har biri ishga tushadi → muammo bo'lsa Telegram (`OWNER_ID`,
  `CLAUDE_BOT_TOKEN`) ga HTML alert; toza bo'lsa jim (`--quiet`)
- Runner: `scripts/_integrity_runner.ps1` (kirill python yo'lini topadi) →
  Task Scheduler chaqiradi

**Yangi tekshiruvlar shu pattern'ga to'liq mos** — har biri bitta funksiya +
`CHECKS` ro'yxatiga bitta qator. Arxitektura, Telegram, runner o'zgarmaydi.

## 5 yangi tekshiruv

### 1. `check_subtotal_desync`
**Invariant:** `Order.subtotal == Σ(OrderItem.quantity × OrderItem.price)`
(chegirma `subtotal`'ni o'zgartirmaydi — shuning uchun `total` emas, `subtotal`).
**SQL:** `orders` (type='sale', status NOT IN cancelled/draft) ↔ `order_items`
yig'indisi; `ABS(subtotal − Σ(qty×price)) > 1` bo'lganlar.
**Bugungi misol:** #1554 (880k vs 1160k), #1685 (718k vs 812k).

### 2. `check_sale_from_wrong_warehouse`
**Invariant:** Sotuv (`type='sale'`) Vozvrat (wh=7) yoki Xom ashyo (wh=1)
ombordan bo'lmasligi kerak. `Order.warehouse_id` yoki `OrderItem.warehouse_id`
shu omborlarda + status NOT IN cancelled/draft.
**Bugungi misol:** #1752 (Vozvrat ombordan agent buyurtma).

### 3. `check_null_price_type`
**Invariant:** Aktiv sotuvda (`type='sale'`, status NOT IN cancelled/draft)
`price_type_id IS NOT NULL`.
**Bugungi misol:** 26 order (agent + POS).

### 4. `check_partner_balance_drift`
**Invariant:** `Partner.balance == hujjatlardan hisoblangan balans`.
**Formula (raw SQL'da takrorlash):** partner balansi = realizatsiya qilingan
sotuvlar qarzi − tasdiqlangan kirim to'lovlar ± boshqa hujjatlar. Aniq formula
`app/services/partner_balance_service.py::compute_partner_balance` dan olinadi va
raw SQL'ga ko'chiriladi (implementatsiya bosqichida o'qib aniqlanadi). Har partner
uchun `ABS(Partner.balance − hisoblangan) > 1` → drift.
**Tolerantlik:** kichik (>1 so'm) farqlar e'tiborga olinadi; yumaloqlash xatosi emas.
**Bugungi misol:** 06-01 partner drift (recompute bilan tuzatilgan).

### 5. `check_agent_debt_desync`
**Invariant:** Agent manbali (`source='agent'`) orderlar `debt` yig'indisi ↔
partner balansidagi agent hissasi izchil. Aniqrog'i: agent order faqat
`delivered/completed` bo'lsa qarzga kiradi (memory: agent debt on delivery).
Per-order `debt` yig'indisi shu partner uchun kutilgan qarzdan farq qilmasligi
kerak.
**Formula:** `app/services/partner_balance_service.py::recompute_partner_order_debts`
mantig'idan (FIFO to'lov taqsimlash) — raw SQL'da soddalashtirilgan tekshiruv:
agent order'lar `debt` summasi vs (total − paid) summasi izchilligi.
**Bugungi misol:** 06-03 agent qarz Order.debt→Partner.balance.

## Arxitektura

```
Task Scheduler (kunlik/soatlik)
   → _integrity_runner.ps1 (python topadi)
      → integrity_check.py --quiet
         → CHECKS = [9 mavjud + 5 yangi]
            → har biri sqlite3 SELECT (read-only)
            → muammo bo'lsa → send_telegram(OWNER_ID)
```

**Read-only kafolat:** barcha yangi tekshiruvlar faqat `SELECT` — hech narsa
yozmaydi (mavjud pattern). Bu monitorning asosiy xavfsizlik invarianti.

## Task Scheduler tekshiruvi

Implementatsiya yakunida: server2220'da integrity task (`_integrity_runner.ps1`)
mavjudligi va kunlik/soatlik ishlashini tekshirish. To'xtagan/yo'q bo'lsa —
qayta yaratish (ONSTART yoki kunlik trigger, `Администратор` user — python yo'li
uchun, [[project-datasette-20260612]] python-PATH darsi).

## Sinov rejasi

- Har yangi tekshiruvni **ma'lum buggi yozuvda** sinash: bugungi data fix'dan
  OLDINGI holatni reproduce qilib bo'lmaydi (tuzatilgan), shuning uchun
  sun'iy/edge holat yoki mavjud toza DB'da `0 muammo` (false positive yo'q)
  tasdiqlanadi.
- `--verbose` bilan barcha 14 tekshiruv summary'sini ko'rish.
- Toza DB'da: 5 yangi tekshiruv `0` qaytarishi (bugungi buglar tuzatilgan).

## Qamrov tashqarisi

- Mavjud 9 tekshiruvni o'zgartirish — yo'q (faqat qo'shamiz).
- Avtomatik tuzatish (recompute) — YO'Q. Monitor faqat **xabar beradi**, inson
  qaror qiladi (read-only invariant).
- Yangi Telegram bot/chat — yo'q (mavjud `OWNER_ID` Yordamchim).
