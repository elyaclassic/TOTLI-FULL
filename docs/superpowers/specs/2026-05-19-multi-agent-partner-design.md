# Multi-agent kontragent (N:N + per-agent tashrif) — dizayn spetsifikatsiyasi

**Sana:** 2026-05-19
**Holat:** Tasdiqlangan dizayn (implementatsiya kutilmoqda)
**Tier:** C (ko'ndalang: schema + agent ko'rinishi + UI)

## 1. Muammo / Maqsad

Hozir `Partner.agent_id` — bitta agent FK (database.py:870, "qaysi agent qo'shgan").
Bir kontragentni bir necha agent xizmat qiladi (real holat). Maqsad: bitta
kontragentga **cheksiz N agent** biriktirish, **teng** semantika (har
biriktirilgan agent mijozni ko'radi, buyurtma yaratadi), va Sales Doctor
namunasidagidek **har agentga alohida tashrif jadvali** (tashrif turi +
kunlari). `order.agent_id` per-order o'zgarmaydi (kim yaratsa — o'shanga).

**Maqsad EMAS (bu spec qamrovida):** auditor multi (namunada bor, alohida);
agent komissiya bo'linishi; partner.agent_id ni butunlay olib tashlash.

## 2. Yondashuv (tasdiqlangan: A)

Join jadval + `Partner.agent_id` anchor/legacy saqlanadi. Additive,
eski kod buzilmaydi, "effektiv agent" helper orqali bosqichli N:N.
(B = to'liq almashtirish — rad: jonli prodda yuqori xavf. C = is_primary —
rad: "teng" tanlandi, YAGNI.)

## 3. Ma'lumot modeli

Yangi jadval **`partner_agents`**:
| ustun | tur | izoh |
|---|---|---|
| id | PK | |
| partner_id | FK partners, index | |
| agent_id | FK agents, index | |
| visit_type | str/nullable | tashrif turi (mavjud TOTLI qiymatlari) |
| visit_days | str/nullable | tashrif kunlari (mavjud format — CSV) |
| position | int | Agent 1/2/3 tartibi |
| created_at | datetime | |

`UNIQUE(partner_id, agent_id)` — bir agent bir partnerга ikki marta emas.
`Partner.agent_id` QOLADI (anchor/legacy/qo'shuvchi). Partner'ning mavjud
tashrif maydonlari (`Tashrif kuni` va h.k.) saqlanadi (back-compat).

**MUHIM (reallik bilan tuzatildi):** Kod tekshiruvi ko'rsatdi —
`Partner.visit_day` = `Column(Integer)` BITTA kun (0-6), `visit_type`
Partner'da YO'Q. Sales Doctor multi-day talabi uchun bu yetarli emas →
`partner_agents` YANGI format ishlatadi:
- `visit_days` = `String`, CSV kun raqamlari "0,2,4" (Du=0..Yak=6 —
  Partner.visit_day bilan AYNAN bir xil kodlash, izchil)
- `visit_type` = `String` nullable (masalan 'weekly'/'biweekly'/'monthly';
  aniq qiymatlar UI bilan P3'da)
Backfill: `Partner.visit_day` (int) → position-1 qatorida
`visit_days = str(visit_day)` (bitta kun CSV sifatida).

**Migratsiya (additive, CLAUDE.md: faqat additive):** `partner_agents`
yaratiladi; har `agent_id IS NOT NULL` partner uchun bitta qator backfill
(position=1, partner'ning mavjud visit_type/visit_days ko'chiriladi).
Downgrade: jadval drop. Nullable, default — xavfsiz.

## 4. "Effektiv agentlar" helper

Yagona funksiya (masalan `app/services/partner_agents.py`):
`effective_agent_ids(partner) -> set[int]` =
`{partner.agent_id} (agar bor) ∪ {pa.agent_id for pa in partner.partner_agents}`.
Agent ko'rinishi/huquqi qaror qilinadigan HAR joyda SHU helper ishlatiladi
(izchillik kafolati — tarqoq `==agent_id` taqqoslashlar o'rniga).

## 5. Xulq o'zgarishlari (ko'ndalang — sanab o'tilgan)

| Joy | Hozir | Keyin |
|---|---|---|
| Agent ilova "mening mijozlarim" | `Partner.agent_id == agent` | `agent ∈ effective_agent_ids` |
| Buyurtma yaratish huquqi | agent_id mos | agent effektiv agentlar ichida |
| `order.agent_id` (per-order) | yaratuvchi | **O'ZGARMAYDI** (yaratuvchi) |
| Hisobot/reja `order.agent_id` bo'yicha | — | **O'ZGARMAYDI** (per-order atribut saqlanadi) |
| "Agent mijozlari soni" hisobi | agent_id | effektiv agentlar bo'yicha |

Aniq kod joylari (qaysi fayl:qator `partner.agent_id` ko'rinish uchun
o'qiydi) — implementatsiya rejasida sanab chiqiladi va helperга o'tkaziladi.

## 6. UI

Kontragent qo'shish/tahrir modali (`partners` — templates):
bitta "Agent" select o'rniga takrorlanuvchi **"Agent N" bloki**:
`[agent select] [tashrif turi select] [tashrif kunlari checkboxlar]`
+ **＋** (Agent 2, 3... qo'shish) / **−** (o'chirish). Sales Doctor
namunasiga mos. Saqlashda `partners.py` `/add` + `/edit` (allaqachon
`require_admin_or_manager`) takroriy agent qatorlarini parse qilib
`partner_agents` upsert (o'chirilganni delete, yangini insert, o'zgarganni
update). 1-qator (position=1) backward-compat uchun `partner.agent_id` ga
ham yoziladi (anchor sinxron).

## 7. Rollout (bosqichli, Tier C, tungi oyna)

- **P1:** jadval + model + migratsiya + backfill + helper. Xulq
  O'ZGARMAYDI (agent_id hali authoritative; helper bir xil to'plam).
  Deploy + test (backfill to'g'riligi).
- **P2:** ko'rinish/huquq o'qishlarini helperга o'tkazish (agent app,
  buyurtma). Deploy + test (agent endi ko'p mijoz ko'radi).
- **P3:** UI multi-agent bloki + save logikasi. Deploy + test (round-trip).

Har bosqich alohida deploy + rollback (additive; P1 downgrade=drop;
P2 rollback=helper o'rniga eski `==agent_id`; P3 rollback=UI revert).

## 8. Chekka / xato holatlar

- Dublikat agent bitta partnerда → UNIQUE constraint + save'da dedupe
- Agent biriktirishdan olib tashlansa: tarixiy `order.agent_id` SAQLANADI
  (tarix/hisobot buzilmaydi); faqat kelajak ko'rinishi o'zgaradi
- Back-compat: `partner.agent_id` o'qiydigan kod P2 gacha ishlayveradi
  (anchor saqlangan); P2 da helperга ko'chiriladi
- partner.agent_id NULL (agentsiz partner) → effektiv to'plam faqat
  partner_agents'дан (yoki bo'sh)
- Auditor multi — QAMROVDA EMAS (alohida spec, kerak bo'lsa)

## 9. Test

- Migratsiya: har `agent_id`li partner → partner_agents position=1 qatori,
  visit maydonlari to'g'ri ko'chgan; agentsiz partner → qator yo'q
- Helper: union to'g'ri (agent_id + jadval; bo'sh; faqat jadval)
- Agent app: agent partner_agents'даги (agent_id emas) mijozni ko'radi
- Buyurtma: effektiv agent buyurtma yarata oladi; `order.agent_id`=yaratuvchi
- UI: Agent qo'shish/o'chirish/saqlash round-trip; dublikat rad
- Regression: P1'дан keyin mavjud agent app/hisobot O'ZGARMAGANINI tasdiqlash

## 10. Ochiq savollar

Yo'q (yondashuv A, N:N cheksiz, teng semantika, per-agent visit,
bosqichli P1-P3, auditor tashqarida — hammasi tasdiqlangan).
