# Python o'rnatish va loyihani ishga tushirish

## 1. Python o'rnatish (bir marta)

1. **Yuklab oling:** https://www.python.org/downloads/  
   — "Download Python 3.x" tugmasini bosing.

2. **O'rnatishda muhim:**  
   Birinchi oynaida **"Add python.exe to PATH"** qutisini **belgilang**, keyin "Install Now" bosing.

   ![Add to PATH](https://docs.python.org/3/_images/win_installer.png)

3. O'rnatish tugagach, **PowerShell yoki CMD ni yoping va qayta oching** (yoki Cursor ni qayta ishga tushiring) — PATH yangilanadi.

---

## 2. Loyihani ishga tushirish

**Variant A — `start.bat` (oson)**  
`d:\TOTLI BI` papkasida `start.bat` faylini ikki marta bosing.  
U avval kutubxonalarni o‘rnatadi, keyin serverni ishga tushiradi.

**Variant B — qo'lda (PowerShell yoki CMD):**

```powershell
cd "d:\TOTLI BI"
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

Brauzerda: **http://localhost:8080**

---

## 3. Agar `python` yoki `pip` ishlamasa

- Terminalni **yoping va qayta oching** (Python yangi o‘rnatilgan bo‘lsa).
- O‘rnatishda **"Add to PATH"** belgilanganligini tekshiring.  
  Qayta o‘rnatish kerak bo‘lsa: Windows → "Add or remove programs" → Python → Change → "Add to PATH" ni belgilang.
- Cursor ishlatayotgan bo‘lsangiz, Cursor ni **qayta ishga tushiring** (PATH yangilanishi uchun).
