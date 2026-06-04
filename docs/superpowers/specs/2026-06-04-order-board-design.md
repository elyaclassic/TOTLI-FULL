# Spec: Buyurtma holati katta-ekran board (real-vaqt)

**Sana:** 2026-06-04
**Status:** Dizayn tasdiqlangan — implementatsiya rejasi kutilmoqda
**Maqsad:** Ishlab chiqarish/ombor xodimlari uchun agent-yetkazish buyurtmalarini katta ekranda real-vaqt kuzatish.

## Maqsad va kontekst

Menejer kompyuteriga ulangan katta ekranda agent/yetkazish buyurtmalari kanban uslubida ko'rsatiladi. Buyurtma yaratilganda paydo bo'ladi, holati har o'zgarganda kartochka tegishli ustunga ko'chadi — sahifani yangilamasdan (real-vaqt).

**Kim ishlatadi:** ishlab chiqarish/ombor (nimani tayyorlash, qadoqlash, jo'natish kerakligini ko'radi).
**Qayerda:** menejer kompyuterining brauzerida (mavjud admin/menejer sessiyasi), F11 bilan to'liq ekran. Alohida kiosk/login KERAK EMAS.

## Ko'lam (YAGNI)

**Kiradi:** agent/yetkazish buyurtmalari (`type='sale'`, `source='agent'`), aktiv bosqichlarda + bugun yetkazilganlar.
**Kirmaydi:** POS (darhol sotuv), web buyurtmalar, return_sale. Ovozli signal YO'Q.

## Ustunlar (4 ta kanban)

| Ustun | Order status | Izoh |
|-------|--------------|------|
| **TASDIQLANGAN** | `confirmed` | Tasdiqlangan, dispatch kutilmoqda (tayyorlash/qadoqlash) |
| **ISHLAB CHIQARILMOQDA** | `waiting_production` | Stock yetmagan, ishlab chiqarish kutilmoqda |
| **YO'LDA** | `out_for_delivery` | Haydovchi olib ketgan |
| **YETKAZILDI** | `delivered` (faqat **bugun**) | Bugun yetkazilganlar (eskisi ko'rsatilmaydi) |

- Aktiv ustunlar (Tasdiqlangan / I.chiqarilmoqda / Yo'lda) — **sanadan qat'i nazar** (hali bajarilmagani uchun). Yetkazildi — faqat bugun.

## Kartochka mazmuni

- **Mijoz nomi** (yirik shrift — uzoqdan o'qish uchun)
- AGT-raqam · summa
- mahsulot soni · bosqichda turgan vaqt (masalan "12 daqiqa")
- Yo'lda bo'lsa: 🚚 haydovchi ismi
- I.chiqarilmoqda bo'lsa: qaysi mahsulot kutilmoqda (mavjud bo'lsa)

**Kechikkan belgilash (qizil):** aktiv (yetkazilmagan) buyurtma `delivery_date <= bugun` bo'lsa — kartochka qizil ramka/fon bilan ajratiladi (rejalashtirilgan kunida hali yetkazilmagan).

## Arxitektura

### ♻️ Qayta ishlatiladi
- **WebSocket bus** (`app/services/realtime_bus.py`, `ConnectionManager`, `publish_event`).
- **WS endpoint** `/ws/dashboard/v2` (`dashboard_v2.py:601`) — board shunga ulanadi (yoki kerak bo'lsa parallel `/ws/board` — qaror implementatsiyada; default: mavjudini qayta ishlatish).

### ➕ Quriladi (3 komponent)

1. **Board sahifasi** — `GET /sales/board` (admin/menejer). To'liq-ekran HTML+JS, qora fon, yirik shrift, 4 ustun CSS grid. JS: snapshot yuklaydi → WS ulanadi → event'da DOM kartochkani ko'chiradi/qo'shadi/o'chiradi. Login chrome yo'q (sof board).
2. **Snapshot API** — `GET /sales/board/data` → JSON: aktiv agent buyurtmalari bosqich bo'yicha guruhlangan + bugun yetkazilganlar. Boshlang'ich yuklash va WS-reconnect qayta-sinxron uchun. Har order: id, number, partner_name, total, items_count, status, delivery_date, dispatched_at, driver_name, overdue (bool), stage_since (vaqt).
3. **Status-change event'lari** — mavjud order-transition joylariga bitta GENERIK signal `publish_event("order_board")` qo'shiladi (payload ixtiyoriy/minimal). Joylar:
   - Agent buyurtma yaratildi (api_agent_ops)
   - Supervisor tasdiqladi → `confirmed` (delivery_routes)
   - Dispatch → `out_for_delivery` / `waiting_production` (agent_order_service / delivery dispatch)
   - Haydovchi yetkazdi → `delivered` (api_driver_ops)
   - Bekor → `cancelled`
   - Mavjud `sale_created` ham qayta ishlatiladi (board uni ham "refresh signal" deb qabul qiladi).

**MUHIM (soddalik):** event — bu faqat "**refresh signal**". Board DOM-diffing qilmaydi; har signal kelganda `/sales/board/data` snapshot'ini **qayta yuklaydi** (debounced ~500ms) va 4 ustunni qayta chizadi. Sabab: board'da o'nlab buyurtma — to'liq qayta-render arzon, kod sodda va o'tkazib yuborilgan event'larga chidamli (snapshot doim haqiqat manbai).

### Ma'lumot oqimi
```
Board sahifa ochiladi
   → GET /sales/board/data (snapshot) → 4 ustunni chizadi
   → WS /ws/dashboard/v2 ga ulanadi
   → har qanday order event (refresh signal) keladi
       → /sales/board/data ni qayta yuklaydi (debounced 500ms) → 4 ustunni qayta chizadi
   → WS uzilsa: avtomatik reconnect + har ~30 sek snapshot bilan qayta-sinxron (zaxira poll)
```

## Xatolarga chidamlilik
- `publish_event` allaqachon silent-fail (asosiy operatsiyaga ta'sir qilmaydi). Event qo'shish xavfsiz.
- WS uzilsa board snapshot-poll bilan ishlashda davom etadi (graceful degradation).
- Snapshot API faqat o'qish (read-only) — hech narsani o'zgartirmaydi.

## Test
- Snapshot API: agent buyurtmalar to'g'ri bosqichga guruhlanadi; bugun yetkazilgan filtri; overdue flag (delivery_date<=bugun + aktiv).
- Event publish: har transition'da to'g'ri event_type+payload chiqadi (unit/integration).
- Board JS: minimal (qo'lda smoke — menejer kompyuterida ochib, test buyurtma yaratish→tasdiqlash→yetkazish, kartochka ko'chishini ko'rish).

## Kirish/xavfsizlik
- `/sales/board` va `/sales/board/data` — admin/menejer (require_auth + rol). Menejer kompyuteri allaqachon login.
- WS `/ws/dashboard/v2` — mavjud (admin dashboard uchun).

## Bog'liq
- `app/services/realtime_bus.py` · `app/routes/dashboard_v2.py` (WS) · `app/routes/delivery_routes.py`, `api_driver_ops.py`, `api_agent_ops.py` (status transitions) · `compute_partner_balance` gating (agent delivered) bilan izchil.
