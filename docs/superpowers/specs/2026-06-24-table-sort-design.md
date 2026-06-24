# Jadval ustun saralash (client-side) — Dizayn hujjati

**Sana:** 2026-06-24
**Muallif:** Elyor + Claude
**Holat:** Tasdiqlangan (implementatsiya kutilmoqda)

## Maqsad

Foydalanuvchi ko'radigan barcha ma'lumot ro'yxati jadvallariga ustun sarlavhasini
bosib saralash (client-side) qo'shish — server restart va faylma-fayl tahrirsiz.

## Hozirgi holat

- `app/templates/` ostida 123 faylda `<thead>` bor, lekin ko'pi forma/modal/detail/dashboard.
- Haqiqiy saralanadigan ro'yxat: ~60 (17 list + 19 hisobot + ~15 ma'lumotnoma + boshqalar).
- Mavjud **server-side** sort: `app/templates/components/_sortable_th.html` macro +
  `app/utils/sort_helpers.py` (parse_sort/apply_sort) — faqat 4 ro'yxat: partners,
  products, employees, advances_list (`?sort=` linkli th).
- Ko'p ro'yxat `class="card data-table"` strukturasini ishlatadi (lekin ba'zi forma/detail
  ham — masalan harajat_hujjat_form, kassa_detail).

## Qaror qilingan yondashuv

**Client-side universal JS** (foydalanuvchi tanlovi) — bitta skript barcha mos jadvalga
avtomatik tarqaladi.

| Savol | Qaror |
|-------|-------|
| Sort turi | Client-side (JS, DOM qatorlarini saralaydi) |
| Ulanish | Avtomatik: `.data-table table`, forma/mavjud-sort skip |
| Mavjud server-side sort | Tegilmaydi (JS uni skip qiladi) |
| Pagination'li 3 hisobot | Faqat joriy sahifa saralanadi (kutilgan) |

## Arxitektura

### 1. Yangi fayl: `app/static/js/table-sort.js`

`DOMContentLoaded` da ishga tushadi. Har bir `.data-table table` (yoki `table.table`
`.data-table` ichida) uchun:

**Sortable qilish SHARTLARI (hammasi bajarilishi kerak):**
- `thead th` mavjud va `tbody` da kamida 1 ma'lumot qatori bor.
- `tbody` da `<input>`/`<select>`/`<textarea>` YO'Q (forma jadvali emas).
- `th` larda `<a href*="sort=">` YO'Q (server-side sort emas).
- Jadvalda `data-no-sort` atributi YO'Q.

**Sortable th xulqi:**
- `th` ga `cursor:pointer`, hover effekti, neytral `⇅` ko'rsatkich.
- Bosilganda: o'sish → kamayish → (boshqa ustun) qayta. Saralangan th da `▲`/`▼`.
- Ustun ma'lumot turini avtomatik aniqlash (har ustun bo'yicha katak qiymatlaridan):
  - **Raqam:** vergul/bo'shliq/birlik (`kg`, `/ta`, `so'm`) tozalanib `parseFloat`.
  - **Sana:** `DD.MM.YYYY [HH:MM]` → `YYYY-MM-DD...` taqqoslash.
  - **Matn:** `localeCompare` (o'zbekcha).
- Katakdan asosiy qiymat olinadi: `td` ning birinchi matn tuguni / `data-sort-value`
  bo'lsa undan (kelajak uchun), aks holda `textContent` ning birinchi qatori.
- `<tfoot>` va `tr.total` / `tr.sum-row` qatorlari saralashda joyida qoladi (aralashmaydi).

### 2. Tahrir: `app/templates/base.html`

`</body>` dan oldin (yoki boshqa global skriptlar yonida):
```html
<script src="/static/js/table-sort.js" defer></script>
```

### 3. Ixtiyoriy: `data-no-sort`

Test paytida noto'g'ri qamralган jadval chiqsa, o'sha `<table>` ga `data-no-sort`
atributi qo'shiladi (kod o'zgarmaydi).

## Xatolarni boshqarish

- Bo'sh jadval / 1 qator → sortable qilinmaydi (ma'no yo'q).
- Parse xatosi (noto'g'ri raqam/sana) → matn sifatida saralaydi (fallback).
- Forma yoki mavjud-sort jadval → avtomatik skip, hech narsa buzilmaydi.
- JS xatosi sahifani buzmasligi uchun `try/catch` har jadval bo'yicha izolyatsiya.

## Test rejasi

- Parse funksiyalari (raqam/sana/matn) — namunaviy qiymatlarda to'g'ri tartib.
- Aniqlash mantiqi: forma jadvali (input bor) skip, server-sort (th link) skip,
  data-no-sort skip.
- Qo'lda smoke (5-6 ro'yxat): production, sales/list, reports/stock, reports/debts,
  info/users, agents/list — raqam/sana/matn ustunlari to'g'ri saralanadi.
- Forma sahifa regressiyasi: harajat_hujjat_form, qoldiqlar hujjat formalari buzilmagan.
- Server-side regressiya: partners/products/employees/advances avvalgidek `?sort=` ishlaydi.

## Qamrov tashqarisida (YAGNI)

- Server-side sort 64 route'ga kengaytirish — kerak emas (client-side yetarli).
- Pagination'li hisobotlarda to'liq (sahifalararo) saralash — keyingi bosqich, kerak bo'lsa.
- Filtr/qidiruv — alohida (production.html'da retsept filtri allaqachon bor).
- Saralash holatini saqlash (URL/localStorage) — kerak emas.

## Ta'sir

- **1 yangi fayl:** app/static/js/table-sort.js
- **1 tahrir:** base.html (1 qator script)
- **0–N kichik tuzatish:** muammoli jadvalga data-no-sort (test paytida)
- Server restart KERAK EMAS (statik JS + template — Ctrl+F5).
