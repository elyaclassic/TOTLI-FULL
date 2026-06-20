# Yetkazish masofasi — Design (1-bosqich: haversine)

**Sana:** 2026-06-20
**Holat:** Tasdiqlangan (brainstorming)
**Muallif:** Elyor + Claude

## Maqsad

Yetkazib berish marshruti masofasini hisoblash — uchchala maqsad uchun:
1. Haydovchi yo'l haqi / yoqilg'i hisobi (jami km)
2. Marshrut samaradorligi nazorati (ortiqcha aylanish)
3. Har yetkazish masofasi (logistika tahlili)

## Yondashuv

**1-bosqich: haversine** (havo masofasi, offline, API'siz). Keyingi bosqichda kerak bo'lsa OSRM (real yo'l masofasi) yoki koeffitsient (×1.3) qo'shiladi. Bosqichma-bosqich — avval ishlaydigan natija.

## Ma'lumot bazasi (mavjud, tasdiqlangan)

- `deliveries.latitude`, `deliveries.longitude` — yetkazilgan joy GPS. **196/196 to'ldirilgan.**
- `deliveries.delivered_at` — yetkazilgan vaqt (tartib uchun). 196/196 bor.
- `driver_locations` — haydovchi GPS treki: `driver_id`, `latitude`, `longitude`, `recorded_at`. 354 nuqta.
- Ombor koordinatasi YO'Q (warehouse'da lat/lon maydoni yo'q) — shuning uchun GPS trekdan boshlanadi.

## Umumiy mantiq

Har **(haydovchi, kun)** uchun marshrut:
```
A (GPS start) → B (1-yetkazish) → C (2-yetkazish) → ... → N
```
- **A nuqta** = o'sha haydovchining o'sha kungi birinchi GPS nuqtasi (`driver_locations`, eng erta `recorded_at`). GPS yo'q bo'lsa — birinchi yetkazishdan boshlanadi.
- **Tartib** = yetkazishlar `delivered_at` bo'yicha (haqiqiy yurish tartibi).
- **Masofa** = ketma-ket nuqtalar orasida haversine (km).

## Komponentlar

### 1. `app/utils/geo.py` — `haversine_km(lat1, lon1, lat2, lon2) -> float`
Sof funksiya. Ikki koordinata orasidagi km. Mustaqil testlanadi.
```
R = 6371 km
masofa = 2R · arcsin(√(sin²(Δlat/2) + cos(lat1)·cos(lat2)·sin²(Δlon/2)))
```

### 2. `compute_delivery_distances(db, deliveries) -> dict`
- Yetkazishlarni `(driver_id, sana)` bo'yicha guruhlaydi.
- Har guruh uchun: o'sha kun + haydovchi birinchi `driver_locations` nuqtasini topadi (GPS start).
- Guruh ichini `delivered_at` bo'yicha tartiblaydi.
- Ketma-ket haversine: har yetkazishga `segment_km` (oldingi nuqtadan), har guruhga `total_km`.
- Qaytaradi: `{delivery_id: segment_km}` va `[{driver, sana, total_km}]`.

### 3. `delivery_routes.py` (delivery_list)
`delivered_deliveries` olingach `compute_delivery_distances` chaqiriladi, natija template'ga uzatiladi (`segment_km_map`, `daily_totals`).

## UI (`delivery/list.html`)

- **Har yetkazilgan kartada:** "Oldingi nuqtadan: **X.X km**" (kulrang, geo ikoni). Kun birinchi yetkazishida "Boshlanishdan (GPS): X km" (GPS start mavjud bo'lsa), GPS yo'q bo'lsa "—" (marshrut shu nuqtadan boshlanadi).
- **Kunlik jami:** filtr panel ostida kichik jadval — "Haydovchi · kun · jami km" (faqat ko'rinayotgan sana oralig'i). Masalan "Ulug'bek · 19.06 · 47.2 km".

## Chegaraviy holatlar

- GPS start yo'q → birinchi yetkazishdan boshlanadi (jami ozroq kam chiqadi)
- Koordinata 0/NULL → segment "—", hisobga olinmaydi
- Bitta yetkazish (kun) → segment yo'q, jami 0
- Pagination: `segment_km` butun filtrlangan datasetda hisoblanadi (har yetkazish o'z guruhidagi oldingi `delivered_at` bilan), keyin sahifa kesiladi — segment qiymati pagination'dan mustaqil

## Aniqlik eslatmasi

Haversine real yo'ldan ~20-40% kam (yo'llar egri). Yo'l haqi uchun aniqlik kerak bo'lsa: koeffitsient (×1.3) yoki 2-bosqichda OSRM. Hozircha sof haversine — taqqoslash va nazorat uchun yetarli.

## Qamrov tashqarisi (YAGNI)

- Real yo'l masofasi (OSRM/Google) — 2-bosqich
- Xaritada marshrut chizish — kelajak
- Optimal marshrut tavsiyasi — kelajak
- Ombor koordinatasini sozlash UI — hozircha GPS trek yetarli
