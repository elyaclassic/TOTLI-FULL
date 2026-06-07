# Kadr o'zgarishi buyrug'i (Employee Change Order) — Dizayn

**Sana:** 2026-06-07
**Holat:** Loyiha — foydalanuvchi ko'rib chiqishi kutilmoqda
**Bog'liq:** EmploymentDoc (ishga qabul), DismissalDoc (bo'shatish), Salary (oylik), [[project-salary-carryover]]

---

## 1. Muammo
Xodimning ish haqi yoki lavozimi ish davomida o'zgarganda hozir ishga-qabul hujjati (`EmploymentDoc`) tahrirlanadi → **eski qiymat yo'qoladi**, "qachondan kuchga kirdi", "kim o'zgartirdi", "eski→yangi" yozilmaydi. Tarix va javobgarlik yo'q; o'tgan oylar uchun "o'sha paytda ish haqi qancha edi" deb javob berib bo'lmaydi.

## 2. Maqsad
Ish haqi / lavozim / bo'lim / ish haqi turi o'zgarishini **hujjatlashtirilgan buyruq** sifatida yozish: qaysi xodim, qachondan (effective), kim (user), eski→yangi, sabab. Oylik hisob **o'sha oyga kuchda bo'lgan** ish haqini ishlatsin.

## 3. Asosiy qarorlar (foydalanuvchi, 2026-06-07)
1. **Alohida hujjat turi** (EmploymentDoc'ni kengaytirish emas) — ishga qabul / o'zgarish / bo'shatish toza ajralib turadi.
2. **Effective-date bo'yicha oylik:** oylik hisob o'sha oyga kuchda bo'lgan stavkani oladi (o'tmish/kelajak sanaga to'g'ri).

## 4. Effective-date semantikasi (oylik hisob)
- Har oy (M) uchun **bazaviy ish haqi = o'sha oyning BIRINCHI kuniga (1-sana) kuchda bo'lgan stavka** = `effective_date ≤ oyning 1-sanasi` bo'lgan eng so'nggi tasdiqlangan hujjat (change yoki hire).
- **Oy o'rtasidagi o'zgarish KEYINGI oydan kuchga kiradi** (foydalanuvchi qarori 2026-06-07). Masalan: effective_date = 20-mart → mart uchun (1-mart ≤ 20-mart emas) eski stavka; aprel uchun (20-mart ≤ 1-aprel) yangi stavka. effective_date = 1-mart → mart shu oyning o'zida yangi stavka.
- **Proratsiya YO'Q** (butun oy bitta stavkada) — mavjud `Salary.base_salary` butun-oy tizimiga mos.
- Manba ustuvorligi: eng so'nggi effective `EmployeeChangeDoc` → bo'lmasa `EmploymentDoc` (hire) → bo'lmasa `Employee.salary` (fallback).
- Markaziy helper: `get_effective_salary(db, employee_id, as_of_date) -> (salary, salary_type)` — hire + barcha tasdiqlangan change'larni hisobga olib, `as_of_date` ga (shu sana ham kiradi: `effective_date ≤ as_of_date`) kuchda bo'lgan qiymatni qaytaradi. Oylik hisob buni **oyning 1-sanasi** bilan chaqiradi.

## 5. Ma'lumotlar modeli
Yangi jadval `employee_change_docs` (`EmployeeChangeDoc`):
| Ustun | Tur | Izoh |
|-------|-----|------|
| id | Integer PK | |
| number | String unique | KO-YYYYMMDD-NNN (kadr o'zgarishi) |
| employee_id | FK employees | qaysi xodim |
| doc_date | Date | buyruq sanasi (imzolangan) |
| effective_date | Date | **qachondan kuchga kiradi** |
| change_salary | Boolean | ish haqi o'zgaradimi |
| old_salary / new_salary | Float | eski→yangi (change_salary bo'lsa) |
| change_salary_type | Boolean | |
| old_salary_type / new_salary_type | String | |
| change_position | Boolean | lavozim o'zgaradimi |
| old_position / new_position | String | eski→yangi |
| change_department | Boolean | |
| old_department / new_department | String | |
| reason | String(500) | sabab/izoh |
| user_id | FK users | **kim yaratdi/tasdiqladi** |
| status | String | draft / confirmed / cancelled |
| confirmed_at | DateTime | |
| created_at | DateTime | |

**Eski qiymatlar** hujjat YARATILGANDA xodimning joriy effective qiymatlaridan avtomatik olinadi (`get_effective_salary` + emp.position/department).

`ensure_*` migratsiya: `CREATE TABLE IF NOT EXISTS employee_change_docs (...)` + ustun-qo'shish patterni (mavjud kod uslubi).

## 6. Oqim (lifecycle)
1. **Yaratish** (admin/manager/rahbar): xodim tanlanadi → forma qaysi maydon(lar) o'zgarishini ko'rsatadi (ish haqi/lavozim/bo'lim/tur). Har biri uchun eski qiymat read-only ko'rsatiladi, yangi qiymat kiritiladi. `effective_date` + sabab. Holat=draft.
2. **Tasdiqlash:** validatsiya (kamida 1 maydon o'zgargan, effective_date bor). Holat=confirmed, confirmed_at. Agar `effective_date ≤ bugun` → `Employee` joriy qiymatlari (salary/position/...) yangilanadi (display kesh). Kelajak sanali bo'lsa Employee hozir o'zgarmaydi (effective bo'lганда oylik hisob baribir to'g'ri oladi).
3. **Bekor qilish (admin):** confirmed→cancelled; Employee joriy qiymati eng so'nggi effective holatdan qayta hisoblanadi.
4. **Tarix:** xodim sahifasida barcha change buyruqlari ro'yxati (sana, effective, eski→yangi, kim).

## 7. Komponentlar (fayllar)
| Fayl | Mas'uliyat |
|------|-----------|
| `app/models/database.py` | `EmployeeChangeDoc` model + `ensure_employee_change_docs()` migratsiya |
| `app/services/employee_salary_service.py` (YANGI) | `get_effective_salary(db, emp_id, as_of_date)` markaziy helper |
| `app/routes/employees_changes.py` (YANGI) | list / new / create / confirm / cancel / print route'lar |
| `app/routes/employees_salary.py` (MODIFY) | `latest_doc_salary` → `get_effective_salary` (oy oxiri bilan) |
| `app/templates/employees/changes_*.html` (YANGI) | ro'yxat + forma + chop etish |
| `app/templates/employees/detail.html` (MODIFY) | "Kadr o'zgarishlari" bo'limi + tugma |
| `tests/test_employee_change_order.py` (YANGI) | model, get_effective_salary, confirm, payroll integratsiya |

## 8. Ruxsat
Yaratish/tasdiq/bekor: admin / manager / rahbar (mavjud `user_can_override` yoki rol tekshiruvi naqshi). Sotuvchi ko'ra olmaydi.

## 9. Edge case'lar
- Bir buyruqda bir nechta maydon (masalan lavozim oshishi = position + salary birga) — har biri ixtiyoriy, faqat belgilangani yoziladi.
- Kelajak sanali buyruq: Employee hozir o'zgarmaydi; oylik hisob effective oyda oladi. Employee.salary display keshi effective bo'lganda yangilanadi (tasdiq vaqtida `effective_date ≤ bugun` tekshiruvi; kelajak uchun — kesh keyingi tegishli hisob/ochishda yangilanadi yoki lazy `get_effective_salary` ishlatiladi).
- Oy 1-sanasiga kuchda bo'lgan stavka olinadi; oy ichida kiritilgan o'zgarish(lar) keyingi oydan kuchga kiradi (4-bo'lim qoidasi).
- O'tmishdagi (back-dated) buyruq: o'sha oydan keyingi tasdiqlanmagan oyliklar qayta hisoblanishi mumkin (tasdiqlangan/to'langan oyliklarga tegmaymiz — ogohlantirish).

## 10. Test
- `get_effective_salary`: hire only / hire+1 change / hire+2 change / kelajak sana / as_of o'rtada.
- Confirm: Employee yangilanishi (effective≤bugun) / kelajak (yangilanmaydi).
- Payroll: change'dan keyingi oy yangi stavka, oldingi oy eski.
- Cancel: Employee qayta hisoblanadi.

## 11. Risk
- Oylik hisob lookup o'zgaradi (`latest_doc_salary`) — mavjud xulqni saqlash (hire-only xodimlar uchun bir xil natija). Test bilan qoplangan.
- Tasdiqlangan/to'langan oyliklarga retroaktiv tegmaslik (himoya).
- DB migratsiya (yangi jadval) — backup oldin.
