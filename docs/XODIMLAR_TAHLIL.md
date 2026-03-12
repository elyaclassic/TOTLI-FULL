# Xodimlar bo‘limi — tahlil va holat

Tahlil qilingan: **daj** (joriy worktree), **pwp** va **hsy** (sibling worktree’lar).

---

## PWP va HSY worktree’lar — qisqa tahlil

**Yo‘llar:**  
- `C:\Users\ELYOR\.cursor\worktrees\business_system\pwp`  
- `C:\Users\ELYOR\.cursor\worktrees\business_system\hsy`

### PWP
- **database.py:** `Employee` va `Salary` modellari bor (daj bilan bir xil). **Attendance**, **AttendanceDoc**, **EmployeeAdvance** yo‘q. Passport/salary_type/photo ustunlari modelda ko‘rinmaydi.
- **main.py:** Import’da faqat `Employee`, `Salary`. `Attendance` yoki davomat route’lari yo‘q. Router’lar: auth, home, reports, info, dashboard (employees router include qilinmagan).
- **app/utils/hikvision.py:** **Fayl mavjud emas** (File not found).
- **Xulosa:** PWP da davomat (Hikvision), kunlik tabellar, avans va oylik sahifalari **yo‘q**. Faqat asosiy Employee + Salary va ehtimol main.py ichidagi /employees/add, export, import (dajdagiga o‘xshash) mavjud.

### HSY
- **database.py:** PWP bilan bir xil — `Employee`, `Salary` bor; **Attendance**, **AttendanceDoc**, **EmployeeAdvance** yo‘q.
- **main.py:** PWP bilan bir xil struktura (Attendance import/routes yo‘q).
- **app/utils/hikvision.py:** **Fayl mavjud emas**.
- **Xulosa:** HSY ham PWP kabi — davomat, Hikvision, avans, oylik sahifalari **yo‘q**.

### Daj vs PWP/HSY
| Narsa | daj | pwp | hsy |
|-------|-----|-----|-----|
| Employee, Salary | ✅ | ✅ | ✅ |
| app/utils/hikvision.py | ✅ | ❌ | ❌ |
| attendance_*.html shablonlar | ✅ | (n tekshirildi) | (n tekshirildi) |
| Attendance/AttendanceDoc model | ❌ | ❌ | ❌ |
| /employees/attendance route’lar | ❌ | ❌ | ❌ |
| Avans / oylik sahifa | ❌ | ❌ | ❌ |

**Xulosa:** Davomat (Hikvision), kunlik tabellar, avans va oylik hisoblash **uchala worktree’da ham** to‘liq ishlab chiqilmagan. Faqat **daj** da `hikvision.py` va davomat shablonlari bor; backend (model + route) daj da ham yo‘q. PWP va HSY da Hikvision util va ehtimol attendance shablonlari ham yo‘q. Shuning uchun barcha funksiyalar **daj** da boshidan yozilishi kerak (yoki boshqa manbadan nusxa olish kerak).

---

## 1. Ishga qabul qilish (Yangi xodim)

### Mavjud
- **Route:** `POST /employees/add` (main.py ~5753).
- **Forma:** "Yangi xodim" modali — Xodim turi (Oddiy / Agent / Haydovchi), F.I.O, Kodi, Oylik, Lavozim, Bo‘lim, Telefon; Agent/Haydovchi uchun qo‘shimcha maydonlar.
- **Model:** `Employee` — code, full_name, position, department, phone, salary, hire_date, hikvision_id, is_active.
- **Migratsiyalar:**  
  - `add_employee_hire_document_fields.py` — `salary_type`, `passport_series`, `passport_number`, `passport_issued_by`, `passport_issued_date`, `photo` (employees jadvaliga).  
  - `add_employee_salary_rates.py` — soatlik/bo‘lak stavka.  
  - `add_piecework_tasks.py` — bo‘lak ish vazifalari jadvali va `employee.piecework_task_id`.  
- **Ma’lumotnoma:** `info/piecework_tasks.html` — "Bo'lak" ish haqi turi uchun 1 birlik ish narxi (ishga qabulda tanlash uchun).

### Modelda yo‘q
- `Employee` da `salary_type`, `passport_*`, `photo`, `salary_hourly_rate`, `salary_piece_rate`, `piecework_task_id` **aniq kiritilmagan** — migratsiyalar bajarilgan bo‘lsa, DB da ustunlar bor, lekin SQLAlchemy modelida yo‘q. Modelni migratsiyaga moslashtirish kerak.

### Qilish kerak
- `Employee` modeliga yuqoridagi maydonlarni qo‘shish (yoki migratsiya bajarilmagan bo‘lsa, avval migratsiyalarni tekshirish).
- Ishga qabul formasida (ixtiyoriy): passport, photo, salary_type (Oylik / Soatlik / Bo‘lak) va bo‘lak turi uchun vazifa tanlash.

---

## 2. Avans berish

### Mavjud
- **Hisobot:** `/reports/debts` — "Qarzdorlik hisoboti". Bu **kontragentlar** (mijozlar/yetkazib beruvchilar) uchun: Jami qarz, Jami avans (balans bo‘yicha). Xodimlar uchun alohida avans moduli yo‘q.
- **Model:** `Salary` (salaries) — base_salary, bonus, deduction, total, paid, status. Oylik hisob-kitob uchun, lekin **avans** alohida jadval yoki maydon ko‘rinmaydi.

### Yo‘q
- Xodimga avans berish (summa, sana, izoh).
- Xodim avanslari ro‘yxati va hisoboti.
- `EmployeeAdvance` yoki shunga o‘xshash model/yozuv yo‘q.

### Qilish kerak
- Xodim avanslari uchun jadval (masalan: employee_id, amount, date, note, created_at).
- Avans berish forma/sahifa va ro‘yxat (xodim bo‘yicha yoki umumiy).
- Oylik hisoblashda avanslarni hisobga olish (total dan yoki alohida ustunda).

---

## 3. Oylik hisoblash

### Mavjud
- **Model:** `Salary` — employee_id, year, month, base_salary, bonus, deduction, total, paid, status (pending/paid).
- **Employee:** `salary` (oylik asosiy summa).
- **Loyihada:** `Salary` yozuvlarini yaratish/ yangilash/ ko‘rsatish uchun **route yoki sahifa yo‘q**. Faqat model mavjud.

### Yo‘q
- Oy tanlash va xodimlar bo‘yicha oylik hisoblash (base + bonus - deduction, avanslarni minus qilish).
- Oylik hujjati ro‘yxati, tasdiqlash, to‘lov (paid).
- Soatlik/bo‘lak ish haqi bo‘lsa, davomat va ish soatlari/ birliklari bo‘yicha hisoblash logikasi.

### Qilish kerak
- Oylik hisoblash sahifasi: oy tanlash → xodimlar ro‘yxati (base_salary yoki soat/bo‘lakdan hisoblangan) + bonus - deduction - avans = total.
- `Salary` yozuvlarini yaratish/yangilash (status: pending/paid).
- Oylik to‘langanligini belgilash (paid, sana).

---

## 4. Hikvision’dan davomat yuklash

### Mavjud
- **Util:** `app/utils/hikvision.py` — `sync_hikvision_attendance(host, port, username, password, start_date, end_date, db_session)`.  
  Hikvision’dan hodisalarni oladi, xodimlarni `employeeNo` / `hikvision_id` / `code` orqali moslashtiradi, **Attendance** jadvaliga kirish/chiqish va ish soatini yozadi, rasmni `attendance_snapshots` ga saqlaydi.
- **Shablonlar:**  
  - `attendance_form.html` — sana tanlash, "Hikvision'dan yuklash" tugmasi, shu kundagi yozuvlar jadvali, tasdiqlash.  
  - `attendance_docs_list.html` — davomat hujjatları ro‘yxati.  
  - `attendance_doc.html` — kunlik tabel hujjati ko‘rinishi.  
- **Forma:** Hikvision IP, port, login, parol; POST `/employees/attendance/sync-hikvision`.

### Yo‘q (muhim)
- **`Attendance` va `AttendanceDoc` modellari** `app/models/database.py` da **yo‘q**. `hikvision.py` `from app.models.database import Attendance, Employee` qiladi — model bo‘lmasa import xato beradi.
- **Route’lar:** `/employees/attendance`, `/employees/attendance/form`, `/employees/attendance/sync-hikvision`, `/employees/attendance/form/confirm`, `/employees/attendance/doc/<id>`, `/employees/attendance/records`, `/employees/attendance/doc/<id>/delete`, `/employees/attendance/doc/<id>/cancel-confirm` — **main.py** da (va boshqa route fayllarida) **aniq ko‘rinmadi**. Ya’ni shablonlar va Hikvision util bor, backend route va modellar yo‘q.

### Qilish kerak
- `database.py` ga **Attendance** (employee_id, date, check_in, check_out, hours_worked, status, event_snapshot_path, note) va kerak bo‘lsa **AttendanceDoc** (kunlik tasdiqlangan tabel hujjati) modellarini qo‘shish.
- Barcha `/employees/attendance/*` route’larini yozish: ro‘yxat, forma (sana + yozuvlar), sync-hikvision (utilni chaqirish), tasdiqlash, hujjat ko‘rish, records (sana oralig‘i), delete, cancel-confirm.
- Sidebar/base.html da "Davomat" yoki "Kunlik tabellar" havolasini qo‘shish (xodimlar bo‘limi ostida yoki alohida).

---

## 5. Kunlik tabellar

### Mavjud
- Shablonlar davomat hujjatini "Kunlik tabel hujjati" deb ko‘rsatadi (`attendance_doc.html`).
- Tasdiqlash orqali hujjat yaratiladi degan mantiq (form/confirm) — lekin route va `AttendanceDoc` yo‘q.

### Yo‘q
- Route’lar va modellar (yuqoridagi kabi).

### Qilish kerak
- Attendance + AttendanceDoc modellari va barcha attendance route’lari (4-banddagi kabi) — bu kunlik tabellar uchun asos bo‘ladi.

---

## Qisqa jadval

| Funksiya              | Model / Util                      | Route / sahifa              | Holat                          |
|-----------------------|-----------------------------------|-----------------------------|--------------------------------|
| Ishga qabul           | Employee (qisman), migratsiyalar  | POST /employees/add         | Bor; modelga passport/salary_type qo‘shish kerak |
| Avans berish          | Yo‘q                              | Yo‘q                        | Qilish kerak                   |
| Oylik hisoblash       | Salary bor                        | Yo‘q                        | Sahifa va logika qilish kerak  |
| Hikvision davomat     | Attendance yo‘q, util bor         | Yo‘q                        | Model + barcha route kerak     |
| Kunlik tabellar       | AttendanceDoc yo‘q                | Yo‘q                        | Model + route’lar (davomat bilan) |

---

## Eski worktree’lar (pwp, hsy) dan foydalanish

**pwp** va **hsy** tekshirildi: ularnda ham Attendance, AttendanceDoc, EmployeeAdvance va davomat/avans/oylik route’lari yo‘q. Hikvision util faqat **daj** da bor.

Agar sizda **boshqa** eski worktree yoki branch bor bo‘lsa (masalan, davomat/avans/oylik qo‘shilgan branch), u yerda quyidagilarni qidiring va kerak bo‘lsa **daj** ga nusxa qiling:

1. **`app/models/database.py`** — `Attendance`, `AttendanceDoc`, `EmployeeAdvance` (yoki avans jadvali) va Employee’dagi `salary_type`, `passport_*`, `photo`, stavka maydonlari.
2. **Route’lar** — `employees/attendance` barcha endpoint’lar, avans va oylik sahifalari (qaysi faylda ekani — main.py yoki `app/routes/employees.py` va boshqa).
3. **Migratsiyalar** — `add_emp_att_adv_sal` (davomat/avans/oylik jadvalari) va boshqa employee bilan bog‘liq migratsiyalar.

Keyin nima qilish kerakligini (qaysi fayllarni qayta yozish, qaysi qismlarni yangidan yozish) yozsangiz, aniq qadamlar bilan yozib beraman.
