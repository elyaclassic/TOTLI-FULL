# Tier C1 — employees.py bo'lish rejasi

**Manba:** `app/routes/employees.py` — 2934 qator, 129 KB
**Maqsad:** 6 ta modulga bo'lish
**Sana:** 2026-04-11 tayyorlandi
**Strategiya:** Incremental split bilan feature flag, eski fayl ishlashda davom etadi

---

## 📦 Modul taqsimoti

### 1. `employees.py` (core CRUD + import/export)
**Taxminiy hajm:** ~550 qator

| Qator | Funksiya | Endpoint |
|---|---|---|
| 37 | `employees_list` | GET / |
| 73 | `employee_add` | POST /add |
| 120 | `employee_edit_page` | GET /edit/{id} |
| 141 | `employee_update` | POST /update/{id} |
| 191 | `employee_delete` | POST /delete/{id} |
| 1096 | `export_employees` | GET /export |
| 1110 | `template_employees` | GET /template |
| 1122 | `import_employees` | POST /import |
| 1152 | `employees_import_from_hikvision_preview` | POST /import/hikvision-preview |
| 1196 | `employees_import_from_hikvision_preview_get` | GET /import/hikvision-preview |
| 1205 | `employees_import_from_hikvision` | POST /import/hikvision |

### 2. `employees_dismissals.py` (ishdan bo'shatish)
**Taxminiy hajm:** ~155 qator

| Qator | Funksiya | Endpoint |
|---|---|---|
| 228 | `dismissal_create_page` | GET /dismissal/new |
| 252 | `dismissal_create_submit` | POST /dismissal/create |
| 291 | `dismissal_doc_view` | GET /dismissal/{id} |
| 314 | `_build_dismissal_docx` | helper |
| 356 | `dismissal_doc_export_word` | GET /dismissal/{id}/word |

### 3. `employees_employment.py` (ishlash shartnomalari)
**Taxminiy hajm:** ~711 qator

| Qator | Funksiya | Endpoint |
|---|---|---|
| 384 | `employment_docs_list` | GET /employment |
| 405 | `employment_doc_create_page` | GET /employment/new |
| 441 | `employment_doc_create` | POST /employment/create |
| 547 | `employment_doc_view` | GET /employment/{id} |
| 596 | `employment_doc_contract` | GET /employment/{id}/contract |
| 669 | `_build_labor_contract_docx` | helper |
| 787 | `employment_doc_contract_export_word` | GET /employment/{id}/contract/word |
| 848 | `employment_docs_bulk_confirm` | POST /employment/bulk-confirm |
| 874 | `employment_docs_bulk_cancel_confirm` | POST /employment/bulk-cancel |
| 900 | `employment_doc_confirm` | POST /employment/{id}/confirm |
| 915 | `employment_doc_cancel_confirm` | POST /employment/{id}/cancel |
| 930 | `employment_doc_delete` | POST /employment/{id}/delete |
| 951 | `employment_doc_edit_page` | GET /employment/{id}/edit |
| 996 | `employment_doc_edit_save` | POST /employment/{id}/edit |

### 4. `employees_attendance.py` (davomat, tabel)
**Taxminiy hajm:** ~652 qator

| Qator | Funksiya | Endpoint |
|---|---|---|
| 1248 | `attendance_docs_list` | GET /attendance |
| 1300 | `attendance_form` | GET /attendance/{id}/form |
| 1350 | `attendance_sync_hikvision` | POST /attendance/sync-hikvision |
| 1395 | `_parse_time` | helper |
| 1411 | `attendance_form_bulk_time` | POST /attendance/form/bulk-time |
| 1470 | `attendance_form_save` | POST /attendance/form/save |
| 1545 | `attendance_form_confirm` | POST /attendance/form/confirm |
| 1576 | `attendance_doc_view` | GET /attendance/{id} |
| 1597 | `attendance_records` | GET /attendance/records |
| 1627 | `attendance_doc_delete` | POST /attendance/{id}/delete |
| 1642 | `attendance_doc_cancel_confirm` | POST /attendance/{id}/cancel |
| 1657 | `attendance_record_add` | POST /attendance/record/add |
| 1702 | `attendance_record_edit_page` | GET /attendance/record/{id}/edit |
| 1725 | `attendance_record_edit_save` | POST /attendance/record/{id}/edit |
| 1777 | `attendance_records_bulk_time` | POST /attendance/records/bulk-time |
| 1812 | `attendance_records_bulk_time_all` | POST /attendance/records/bulk-time-all |
| 1853 | `attendance_record_delete` | POST /attendance/record/{id}/delete |
| 1869 | `attendance_records_bulk_delete` | POST /attendance/records/bulk-delete |

### 5. `employees_advances.py` (avans hujjatlari)
**Taxminiy hajm:** ~493 qator

| Qator | Funksiya | Endpoint |
|---|---|---|
| 1901 | `_advances_list_redirect_params` | helper |
| 1917 | `employee_advances_list` | GET /advances |
| 1961 | `employee_advance_docs_list` | GET /advances/docs |
| 2014 | `employee_advance_add` | POST /advance/add |
| 2099 | `employee_advance_view_page` | GET /advance/{id} |
| 2132 | `employee_advance_edit_page` | GET /advance/{id}/edit |
| 2169 | `employee_advance_edit_save` | POST /advance/{id}/edit |
| 2228 | `employee_advance_confirm` | POST /advance/{id}/confirm |
| 2243 | `employee_advance_unconfirm` | POST /advance/{id}/unconfirm |
| 2258 | `employee_advance_delete` | POST /advance/{id}/delete |
| 2278 | `employee_advances_bulk_edit` | POST /advances/bulk-edit |
| 2313 | `employee_advances_bulk_unconfirm` | POST /advances/bulk-unconfirm |
| 2337 | `employee_advances_bulk_confirm` | POST /advances/bulk-confirm |
| 2362 | `employee_advances_bulk_delete` | POST /advances/bulk-delete |

### 6. `employees_salary.py` (ish haqi)
**Taxminiy hajm:** ~539 qator

| Qator | Funksiya | Endpoint |
|---|---|---|
| 2395 | `employee_salary_page` | GET /salary |
| 2786 | `employee_salary_save` | POST /salary/save |
| 2911 | `employee_salary_mark_paid` | POST /salary/mark-paid |

---

## 🧮 Hajm xulosasi

| Modul | Qator | Foiz |
|---|---|---|
| employees.py (core) | ~550 | 19% |
| employment | ~711 | 24% |
| attendance | ~652 | 22% |
| salary | ~539 | 18% |
| advances | ~493 | 17% |
| dismissals | ~155 | 5% |
| **JAMI** | **~3100** | 100% |

(Biroz oshirilgan chunki helper'lar qayta yoziladi)

---

## 🎯 Execution strategiyasi

### Variant 1 — **Incremental, eski fayl ishlayveradi** (TAVSIYA)

1. **1-bosqich:** Yangi `employees_dismissals.py` yaratish (eng kichik, 155 qator)
2. 5 ta dismissal funksiyasini **ko'chirish** (nusxa, eski joyida qoldirish)
3. Yangi router yaratish: `dismissals_router = APIRouter(prefix="/employees", tags=["employees-dismissals"])`
4. Endpoint path'lar to'liq mos: masalan `/employees/dismissal/new`
5. `main.py` ga yangi router qo'shish **include_router bilan** — eski router oldin, yangi keyin → yangi endpointlar ustunlik qiladi
6. Smoke test — dismissal sahifalari ishlayaptimi
7. Muvaffaqiyatli bo'lsa — eski funksiyalarni o'chirish
8. Commit

9. **2-bosqich:** `employees_advances.py` (493 qator)
10. **3-bosqich:** `employees_attendance.py` (652 qator) 
11. **4-bosqich:** `employees_salary.py` (539 qator)
12. **5-bosqich:** `employees_employment.py` (711 qator)
13. **6-bosqich:** `employees.py` tozalanadi (faqat core + import qoladi)

Har bosqich mustaqil commit. Agar bir bosqich buzilsa — shu commit rollback.

### Variant 2 — **Big bang** (RAD ETILGAN)

Barcha fayllar bir vaqtda yaratiladi, eski fayl o'chiriladi. **Xavfli** — bitta xato hammasini buzadi.

---

## ⚠️ Xavflar va ehtiyot choralari

1. **Import'lar** — har modulda alohida import list. `employees.py` dagi 30+ import'ni ehtiyotkorlik bilan tarqatish.
2. **Shared helpers** — `_build_dismissal_docx`, `_build_labor_contract_docx`, `_parse_time`, `_advances_list_redirect_params` — har biri o'z modulida qoladi.
3. **Router prefix** — barcha yangi routerlar `/employees` prefix bilan, eski endpoint path'lariga mos.
4. **Shablon havolalari** — `app/templates/employees/*` — o'zgarmaydi, yangi modullar xuddi shu shablonlarga havola qiladi.
5. **main.py** — har bosqichda yangi `include_router` qo'shiladi. Tartib muhim: yangi router oldin bo'lsa, u eski route'ni override qiladi.
6. **Smoke test** — har bosqichdan keyin **manual** tekshirish: kelib-ketish sahifalari, avanslar, ish haqi, ishdan bo'shatish, ishga qabul.

---

## 🕐 Vaqt tahmin

| Bosqich | Vaqt | Umumiy |
|---|---|---|
| 1 — dismissals (155 qator) | 30 daq | 30 daq |
| 2 — advances (493 qator) | 1.5 soat | 2 soat |
| 3 — attendance (652 qator) | 2 soat | 4 soat |
| 4 — salary (539 qator) | 1.5 soat | 5.5 soat |
| 5 — employment (711 qator) | 2 soat | 7.5 soat |
| 6 — cleanup (core tozalash) | 30 daq | 8 soat |

**Real:** 1 kun (6-8 soat), tanaffuslarsiz.

**Tavsiya:** 1-bosqich (dismissals) bugun — eng kichik, eng xavfsiz. Qolganini yakshanbaga rejalashtirish.
