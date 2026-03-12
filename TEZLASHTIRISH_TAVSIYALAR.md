# Ilova tezligi — sabablar va tavsiyalar

## Qilingan o'zgarishlar (allaqachon qo'shildi)

### 1. SQLite tezligi (app/models/database.py)
- **WAL rejimi** (`PRAGMA journal_mode=WAL`) — yozuvlar tezroq, o'qish va yozish bir vaqtda yaxshiroq.
- **Cache** (`PRAGMA cache_size=-64000`) — 64 MB cache, tezroq qayta o'qish.
- **synchronous=NORMAL** — xavfsiz, lekin tezroq.
- **temp_store=MEMORY** — vaqtinchalik jadvallar xotirada.

Bu o'zgarishlar **har bir bazaga ulanishda** avtomatik qo'llanadi.

---

## Sekinlashish sabablari

### 1. SQLite — bitta fayl
- Barcha so'rovlar bitta `totli_holva.db` fayliga boradi.
- Bir vaqtning o'zida ko'p foydalanuvchi bo'lsa, navbatlashadi.
- **Tavsiya:** Kunda 5–10 dan ortiq bir vaqtda ishlatmasa, hozirgi holat yetadi. Katta yuk bo'lsa — PostgreSQL yoki MySQL ga o'tish.

### 2. Bosh sahifa — ko'p so'rov
- Bosh sahifada 15+ ta alohida DB so'rovi bor (sotuv, kassa, qarz, mahsulotlar, xodimlar va h.k.).
- **Tavsiya:** Kelajakda bitta yoki bir nechta “statistika” jadvali yoki cache (masalan, 1 daqiqa) qo'shish mumkin.

### 3. Ishlab chiqarish sahifasi (production)
- Har bir retsept va har bir ishlab chiqarish uchun alohida so'rovlar (N+1 muammo).
- Retseptlar/ishlab chiqarishlar ko'p bo'lsa, sahifa sekin ochiladi.
- **Tavsiya:** Bir so'rovda `joinedload` yoki bitta katta so'rov bilan yuklash (keyingi optimizatsiya bosqichida).

### 4. main.py — katta fayl
- `main.py` 7000+ qator — ishga tushganda import biroz vaqt oladi.
- Bu faqat **dastur ishga tushganda** ta'sir qiladi, har bir so'rovga emas.

### 5. Tarmoq
- `10.243.49.144` — lokal tarmoq. Wi‑Fi yoki router sekin bo'lsa, brauzer sekin yuklaydi.
- **Tavsiya:** Bir xil kompyuterdan `http://127.0.0.1:8080` bilan tekshirib ko'ring; tezroq bo'lsa, muammo tarmoqda.

---

## Qisqacha tavsiyalar

| Sabab              | Nima qilish                          |
|--------------------|--------------------------------------|
| SQLite             | ✅ PRAGMA qo'shildi (WAL, cache)     |
| Ko'p so'rovlar     | Kelajakda cache yoki birlashtirish   |
| Tarmoq             | 127.0.0.1 bilan tekshirish           |
| Kompyuter zaif     | Boshqa dasturlarni kamroq ochish     |
| Ma'lumotlar ko'p   | Eski ma'lumotlarni arxivlash         |

---

**Xulosa:** SQLite tezlashtirish (WAL, cache) qo'llandi. Agar hali ham sekin bo'lsa, avvalo bir xil kompyuterdan `http://127.0.0.1:8080` da tekshiring; keyin qaysi sahifa sekin (bosh sahifa, foydalanuvchilar, ishlab chiqarish) ayting — shu yo'nalishda keyingi optimizatsiya qilamiz.
