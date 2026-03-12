# Harakat tarixi (StockMovement) — qayerlarda ishlatiladi

Mahsulot harakati tarixi (qayerdan keldi / qayerga ketdi) quyidagi joylarda ko‘rinadi yoki ulanish orqali ochiladi.

## Allaqachon ulangan

| Joy | Qanday |
|-----|--------|
| **Qoldiqlar** | Tab «Tovar qoldiqlari» → tugma «Mahsulot harakati tarixi» → ombor + mahsulot tanlash → jadval |
| **Qoldiqlar → Tarix** | `/qoldiqlar/tarix` — ombor va mahsulot tanlash, keyin `/reports/stock/source` jadvali |
| **Hisobotlar → Qoldiq hisoboti** | Har bir qatorda ustun «Manbai» → harakatlar jadvali |
| **Ombor (Qaysi omborda nima bor)** | Har bir mahsulot qatorida tugma «Tarix» → shu ombor+mahsulot uchun harakatlar |
| **Mahsulot kartasi** | Ma'lumotnomalar → Mahsulotlar → mahsulotni ochish → «Mahsulot harakati tarixi» (mahsulot tanlangan holda tarix formasiga) |
| **Sotuv hujjati (tahrir)** | Sotuv → buyurtma → mahsulotlar jadvalida har bir qator uchun «Tarix» (shu ombor + mahsulot) |
| **Ombordan omborga** | `/warehouse/movement` sahifasida «Mahsulot harakati tarixi» havolasi |

## Qo‘shilgan (keyingi qatlam)

| Joy | Qanday |
|-----|--------|
| **Kirim hujjati (purchase)** | `/purchases/.../edit` — mahsulotlar jadvalida har bir qator uchun «Tarix» (shu ombor + mahsulot) |
| **Ishlab chiqarish — xom ashyo (materiallar)** | `/production/{id}/materials` — har bir xom ashyo qatorida «Tarix» (1-ombor + mahsulot) |
| **Ombordan omborga o‘tkazish hujjati** | Transfer form: har bir mahsulot qatorida «Tarix» (qayerdan ombor + mahsulot) |
| **Qaytish hujjati (sotuv)** | Qaytarish hujjati detali: har bir qator uchun «Tarix» (ombor + mahsulot) |
| **Mahsulotlar ro‘yxati** | `/products` — jadvalda «Tarix» ustuni, har qatorida havola `/qoldiqlar/tarix?product_id=...` |

## Qo‘shish mumkin (kelajakda)

| Joy | Taklif |
|-----|--------|
| **Dashboard (ombor / executive)** | Blok «So‘nggi harakatlar» — StockMovement dan oxirgi N ta harakat |
| **Hujjat raqami bo‘yicha qidiruv** | «Ushbu hujjat qanday qoldiqlarni o‘zgartirdi» — document_type + document_id bo‘yicha harakatlar ro‘yxati |

## Texnik

- **Harakatlar jadvali:** `GET /reports/stock/source?warehouse_id=...&product_id=...`
- **Tarix forma (ombor + mahsulot tanlash):** `GET /qoldiqlar/tarix`, ixtiyoriy `?product_id=...` (mahsulotni oldindan tanlash)
- Ma'lumot manbai: `StockMovement` (document_type, document_id, quantity_change, quantity_after, created_at va b.)
