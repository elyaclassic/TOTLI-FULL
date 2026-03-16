# Hozirgi loyiha vs totli_full / GitHub — farq

## Repolar

| Repo | URL | Tavsif |
|------|-----|--------|
| **totli_full** | https://github.com/elyaclassic/totli_full | "TOTLI HOLVA biznes tizimi", ~23 MB, Python, yangi (2026-03-10) |
| **totli-business-system** | https://github.com/elyaclassic/totli-business-system | Asosiy loyiha, ~31 MB, HTML (front ko‘p) |

**Hozirgi loyiha (d:\TOTLI BI)** — totli-business-system dan klonlangan + mahalliy o‘zgarishlar.

---

## totli_full vs totli-business-system (farq)

### totli_full da bor, totli-business-system da yo‘q
| Fayl / papka | Izoh |
|--------------|------|
| `.env.example` | Muhit o‘zgaruvchilari namuna |
| `.venv` | Virtual muhit (odatda repoga kiritilmaydi) |
| `KAMCHILIKLAR_TAHLILI_2026-02-03.md` | Tahlil (sana bilan) |
| `debug_home.log` | Log fayl |
| `main.py.backup` | main.py zaxira nusxasi |
| `temp_purchase.txt` | Vaqtinchalik fayl |
| `totli_holva.db` | **Baza fayli repoda** (totli-business-system da odatda yo‘q) |

### totli-business-system da bor, totli_full da yo‘q
| Fayl / papka | Izoh |
|--------------|------|
| `.cursor` | Cursor sozlamalari |
| `BUYURTMA_ISHLAB_CHIQARISH.md` | Ishlab chiqarish buyurtmasi qo‘llanmasi |
| `DATABASE_SETUP.md` | Baza sozlash |
| `KONTRAGENT_PUL_OQIMLARI.md` | Kontragent pul oqimlari |
| `LOYIHA_HISOBOTI.md` | Loyiha hisoboti |
| `ORNATISH_QOLLANMA.md` | O‘rnatish qo‘llanmasi |
| `TEZLASHTIRISH_TAVSIYALAR.md` | Tezlashtirish tavsiyalari |
| `add_cash_register_payment_type_column.py` | Migratsiya |
| `add_order_payment_type.py` | Migratsiya |
| `add_payment_status_column.py` | Migratsiya |
| `add_user_cash_register.py` | Migratsiya |
| `add_user_department_warehouse.py` | Migratsiya |
| `add_user_many_tables.py` | Migratsiya |
| `backup_db.py` | Baza nusxasi skripti |
| `baza_nusxasi_saqlash.bat` | Baza nusxasi .bat |
| `docs` | Hujjatlar papkasi |
| `fix_purchases_total_expenses.py` | Xarajatlar tuzatish |
| `server_started.txt` | Server holati |
| `test_smoke.py` | Smoke test |
| `tests` | Testlar papkasi |

### Xulosa (totli_full vs totli-business-system)
- **totli_full** — loyihaning boshqa nusxasi: baza (totli_holva.db), .venv, .env.example, ba’zi log/backup fayllar bor; migratsiya skriptlari va qo‘llanmalar kamroq.
- **totli-business-system** — to‘liqroq: backup_db.py, baza_nusxasi_saqlash.bat, ko‘proq migratsiyalar, docs, tests. Baza fayli odatda repoda yo‘q.

---

## Hozirgi loyiha (d:\TOTLI BI) — qo‘shilgan/o‘zgartirilgan

### 1. Ishga tushirish va avtostart
| Fayl | Farq |
|------|------|
| `start.bat` | Python PATH + odatiy papkalardan qidiriladi; `PORT=8081` (yoki 8080), to‘liq yo‘l bilan `pip`/`uvicorn`. |
| `start_server_fon.bat` | Orqa fonda server (oynasiz). |
| `totli_avtostart.vbs` | Kompyuter yonganida serverni yashirin ishga tushiradi. |
| `Avtostart_o_rnatish.bat` | Vazifalar rejasi orqali avtostart o‘rnatadi. |
| `baza_nusxasi_saqlash.bat` | Repodan qo‘shilgan; baza nusxasini tez saqlash. |
| `restore_db_and_run.bat` | DB nusxasini tiklash, keyin start.bat. |

### 2. Python va qo‘llanma
| Fayl | Farq |
|------|------|
| `create_admin.py` | Emoji olib tashlangan (Windows cp1251 xatosi). |
| `PYTHON_ORNATISH.md` | Python o‘rnatish va ishga tushirish. |
| `YANGILANGAN_FAYLLAR.md` | O‘zgartirilgan fayllar ro‘yxati. |
| `GITHUB_TEKSHIRUV.md` | GitHub repodan tekshiruv. |

### 3. Backend (main.py, app/)
| Joy | O‘zgarish |
|-----|-----------|
| `app/models/database.py` | `text` import qo‘shildi (ensure_piecework_tasks_table va boshqalar xatosiz ishlashi uchun). |
| `main.py` — avans | `/employees/advances/add`: CSRF formada; bitta commit (startup da _ensure_payments_status_column); redirect filtrsiz; commit xatosi foydalanuvchiga ko‘rsatiladi. |
| `main.py` — avans ro‘yxati | `joinedload(EmployeeAdvance.employee)`; xabar matni. |
| `main.py` — ishlab chiqarish qoldiq | Xom ashyo yetarli emas: raqamlar yaxlitlash, xabar aniqroq. |
| `main.py` — inventarizatsiya | Tasdiqlash va qoralama saqlashda **bo‘sh «haqiqiy qoldiq»** = o‘zgartirmaslik (oldingi qiymat); bo‘sh maydon endi 0 ga aylantirilmaydi. |
| `main.py` — startup | `_ensure_payments_status_column(db)` startup da chaqiriladi. |
| `app/templates/employees/advances_list.html` | Formada `csrf_token`; «Qo‘shildi» xabarida qisqa yo‘riqnoma. |

### 4. Hisobot fayllari
| Fayl | Maqsad |
|------|--------|
| `FARQ_TOTLI_FULL.md` | Ushbu farq hisoboti. |

---

## Qisqacha

| Narsa | Holat |
|-------|--------|
| **totli_full** | Mavjud: https://github.com/elyaclassic/totli_full — baza, .venv, .env.example bor; migratsiyalar va testlar kamroq. |
| **totli-business-system** | Asosiy repo: ko‘proq skriptlar, backup_db, baza_nusxasi_saqlash.bat, tests, docs. |
| **Sizning loyihangiz (d:\TOTLI BI)** | totli-business-system asosida + yuqoridagi mahalliy o‘zgarishlar (start.bat, avans/inventarizatsiya tuzatishlari va b.). |

Agar Git o‘rnatilsa, `git clone https://github.com/elyaclassic/totli_full.git` bilan totli_full ni yuklab, fayllarni qo‘lda solishtirishingiz mumkin.
