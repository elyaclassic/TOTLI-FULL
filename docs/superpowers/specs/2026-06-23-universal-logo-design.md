# Universal Logo (Brending sozlamalari) — Dizayn hujjati

**Sana:** 2026-06-23
**Muallif:** Elyor + Claude
**Holat:** Tasdiqlangan (implementatsiya kutilmoqda)

## Maqsad

Admin panelidan oddiy rasm yuklash orqali tizim logosini almashtirish imkonini berish.
Hozir logo kodda qattiq (hardcoded) yozilgan; uni dinamik, sozlanadigan qilamiz.

## Hozirgi holat

Logo 4 joyda qattiq yozilgan:
- `app/templates/base.html:8` — favicon (`/static/images/logo.png`)
- `app/templates/base.html:892` — sidebar logosi (`/static/images/logo_circle.png`, 240x240)
- `app/templates/base.html:1801` — bildirishnoma ikonkasi (`/static/images/logo.png`)
- `app/templates/login.html:167` — kirish sahifasi (`/static/images/logo_circle.png`)

Ikki xil logo ishlatiladi:
- **Asosiy logo** (`logo.png`) — favicon + bildirishnoma (to'rtburchak)
- **Dumaloq logo** (`logo_circle.png`) — sidebar + login sahifasi

Loyihada umumiy sozlamalar jadvali (`Settings`/`Config`) **mavjud emas**.

## Qaror qilingan yondashuv

| Savol | Qaror |
|-------|-------|
| Saqlash usuli | Yangi `AppSetting` key-value jadvali (moslashuvchan, kelajakka mo'ljallangan) |
| Logo turlari | Ikkita alohida slot: asosiy + dumaloq |
| Route joyi | Yangi `app/routes/branding.py` fayli |
| Templatega yetkazish | Jinja global funksiya (`csrf_token_from_request` bilan bir xil mexanizm) |

## Arxitektura

### 1. Ma'lumotlar saqlash — `AppSetting` jadvali

Universal key-value sozlamalar jadvali:

```
AppSetting:
  key        TEXT PRIMARY KEY      -- "logo_main", "logo_circle"
  value      TEXT                  -- saqlangan fayl nomi, masalan "logo_main_1750000000.png"
  updated_at DATETIME
```

**Nega key-value?** Kelajakda kompaniya nomi, telefon, rang kabi sozlamalar
yangi ustun/migratsiyasiz qator sifatida qo'shiladi. Bu loyihadagi ORM-DB
schema-drift xavfini chetlab o'tadi (ustun qo'shilmaydi, faqat qator).

**Yuklangan fayllar joyi:** `app/static/images/branding/`
Eski `logo.png` / `logo_circle.png` ga tegmaymiz — fallback (zaxira) sifatida qoladi.
Fayl nomiga timestamp qo'shiladi (`logo_main_<ts>.png`) → brauzer cache muammosi yo'qoladi.

### 2. Backend — `app/routes/branding.py`

```
GET  /admin/branding          -> sozlamalar sahifasi (hozirgi logolar + yuklash formasi)
POST /admin/branding/upload   -> rasmni qabul/tekshirish/saqlash, AppSetting yangilash
POST /admin/branding/reset    -> standart logoga qaytarish
```

**Upload logikasi** (mavjud `products.py::_validate_and_save_product_image` uslubida):
1. Faylni o'qish, Pillow (PIL) bilan ochib haqiqiy rasm ekanligini tekshirish
2. Format tekshiruvi: PNG / JPG / WEBP
3. Hajm limiti: 2 MB
4. `app/static/images/branding/<key>_<timestamp>.<ext>` nomi bilan saqlash
5. Tegishli `AppSetting.key` ni yangilash (upsert)
6. Eski yuklangan faylni o'chirish (papka shishmasligi uchun)

**Ruxsat:** faqat **admin** roli. Sotuvchi/agent/haydovchi kira olmaydi.

### 3. Servis qatlami — `app/services/branding_service.py`

```python
DEFAULTS = {
    "logo_main":   "/static/images/logo.png",
    "logo_circle": "/static/images/logo_circle.png",
}

def get_branding(db) -> dict:
    """AppSetting'dan logo yo'llarini o'qiydi; bo'lmasa standartni qaytaradi.
    Fayl jismonan mavjudligini ham tekshiradi (yo'q bo'lsa -> standart)."""
    ...
```

### 4. Templatega yetkazish — Jinja global funksiya

Mavjud `csrf_token_from_request` bilan bir xil mexanizm orqali `branding()`
funksiyasi barcha templatelarga avtomatik ulanadi. Shunda **100+ mavjud route'ga
tegmaymiz**.

O'zgaradigan template joylari (4 ta):
- `base.html:8`  → `<link rel="icon" href="{{ branding().logo_main }}">`
- `base.html:892` → `<img src="{{ branding().logo_circle }}">`
- `base.html:1801` → bildirishnoma `icon: '{{ branding().logo_main }}'`
- `login.html:167` → `<img src="{{ branding().logo_circle }}">`

### 5. Sidebar menyusi

`base.html` sidebar menyusiga "Brending" / "Logo sozlamalari" havolasi qo'shiladi
(faqat admin ko'radi, mavjud rol-shartli menyu pattern bilan).

## Xatolarni boshqarish (fallback)

- Admin hali logo yuklamagan → standart `logo.png`/`logo_circle.png`
- AppSetting'da yozuv bor, lekin fayl jismonan yo'q → standartga qaytadi
- Noto'g'ri format/hajm yuklansa → forma xato xabari, fayl saqlanmaydi
- Hech qachon "buzilgan rasm" (broken image) ko'rsatilmaydi

## Test rejasi

- AppSetting jadvali yaratilishi (ensure-table)
- Upload: to'g'ri PNG/JPG/WEBP qabul qilinadi
- Upload: noto'g'ri fayl (matn, juda katta hajm) rad etiladi
- get_branding: yozuv yo'q → standart; yozuv bor → yangi yo'l
- get_branding: fayl o'chirilgan → standartga qaytadi
- Ruxsat: admin bo'lmagan foydalanuvchi 403/redirect oladi
- Template render: logo dinamik ko'rinadi (favicon, sidebar, login)
- Reset: standartga qaytaradi

## Qamrov tashqarisida (YAGNI)

- Kompaniya nomi / telefon / rang sozlamalari — keyingi bosqich (jadval tayyor bo'ladi)
- Logo o'lcham/crop tahriri brauzerda — kerak emas, oddiy yuklash yetarli
- PWA ikonkalari (`static/pwa/`) — hozircha qamrovda emas, alohida ish
