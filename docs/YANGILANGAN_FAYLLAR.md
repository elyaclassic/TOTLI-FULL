# Yangilangan fayllar (Git yo'q — qo'lda ro'yxat)

Tizimda Git o'rnatilmagan. Quyida loyihada o'zgartirilgan/qo'shilgan fayllar.

## O'zgartirilgan fayllar

| Fayl | O'zgarish |
|------|-----------|
| `start.bat` | Python ni PATH dan va odatiy papkalardan qidirish; to'liq yo'l bilan `pip` / `uvicorn` ishlatish |
| `create_admin.py` | Emoji olib tashlandi (Windows konsol xatosi bartaraf) |

## Yangi fayllar

| Fayl | Maqsad |
|------|--------|
| `PYTHON_ORNATISH.md` | Python o'rnatish va loyihani ishga tushirish bo'yicha qo'llanma |
| `YANGILANGAN_FAYLLAR.md` | Ushbu ro'yxat |
| `restore_db_and_run.bat` | DB nusxasini qayta tiklash va serverni ishga tushirish |

## Boshqa loyiha fayllari

- `totli_holva.db` — asosiy baza (loyiha ildizida)
- `backups/` yoki `backups/daily/` — `backup_db.py` yoki `python backup_db.py` orqali yaratilgan nusxalar (`totli_holva_YYYYMMDD_HHMMSS.db`)

---

**DB nusxasidan ishga tushirish:**  
`restore_db_and_run.bat` ni ishlatishingiz yoki qo'lda: nusxa faylini `totli_holva.db` ga nusxalang, keyin `start.bat` ni ishga tushiring.
