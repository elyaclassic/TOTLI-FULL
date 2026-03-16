# Loyihani Git'ga saqlash va boshqa kompyuterga o'rnatish

## 1. Loyihani Git'ga saqlash (hozirgi kompyuterdan)

Loyihani GitHub/GitLab yoki boshqa Git serverga yuborish uchun:

```bash
cd "loyiha papkangiz yo'li"   # masalan: cd C:\Users\...\daj
git add -A
git commit -m "Loyiha yangilandi"
git push origin main
```

Agar remote (origin) hali ulangan bo'lmasa:

```bash
git remote add origin https://github.com/Foydalanuvchi/loyiha_nomi.git
git push -u origin main
```

---

## 2. Boshqa kompyuterga o'rnatish

### Kerak bo'ladigan dasturlar

| Dastur | Nima uchun | Qayerdan o'rnatish |
|--------|-------------|---------------------|
| **Python 3.8 yoki undan yangi** | Loyiha Python da yozilgan | https://www.python.org/downloads/ — o'rnatishda "Add Python to PATH" ni belgilang |
| **Git** | Loyihani klonlash uchun | https://git-scm.com/download/win |

Boshqa ilovalar (masalan, C++, Visual Studio) **kerak emas** — faqat Python va Git yetadi.

### Qadamlar

**2.1. Loyihani yuklab olish (klonlash)**

```bash
git clone https://github.com/Foydalanuvchi/loyiha_nomi.git
cd loyiha_nomi
```

Yoki ZIP orqali yuborilgan bo'lsa — arxivni oching va shu papkaga o'ting.

**2.2. Python kutubxonalarini o'rnatish**

```bash
pip install -r requirements.txt
```

Agar `requirements.txt` boshqa papkada bo'lsa (masalan, bir daraja yuqorida):

```bash
pip install -r ../requirements.txt
```

**2.3. Serverni ishga tushirish**

- **Variant A:** `start.bat` faylini ikki marta bosib ishga tushiring (avval IP ni 3-bobda o'zgartiring).
- **Variant B:** Qo'lda:
  ```bash
  python main.py
  ```
  yoki:
  ```bash
  python -m uvicorn main:app --host 0.0.0.0 --port 8080
  ```

**2.4. Brauzerda ochish**

- Shu kompyuterdan: **http://localhost:8080**
- Tarmoqdagi boshqa kompyuterdan: **http://BU_KOMPYUTER_IP:8080** (masalan: http://192.168.1.100:8080)

---

## 3. IP manzilni o'zgartirish (http://10.243.49.144:8080 → boshqa kompyuter)

Hozirgi manzil: **http://10.243.49.144:8080** — bu biror kompyuterning tarmoqdagi IP si va 8080 port.

### Sodda yo'l (tavsiya etiladi)

`start.bat` faylining **eng yuqorisida** bitta o'zgaruvchi bor — shuni o'zgartiring:

1. Loyiha papkasida **`start.bat`** faylini oching (Notepad yoki boshqa matn muharriri bilan).
2. **Eng yuqoridagi** blokni toping:
   ```bat
   set BIND_HOST=0.0.0.0
   ```
3. **O'zgartiring:**
   - **Barcha kompyuterlar ulansin** (sodda variant): `set BIND_HOST=0.0.0.0` qoldiring — brauzerda **http://localhost:8080** yoki **http://bu_kompyuter_IP:8080** ochasiz.
   - **Faqat ma'lum bir IP dan kirish** bo'lsa: `0.0.0.0` o'rniga **o'sha kompyuterning IP manzilini** yozing (masalan: `set BIND_HOST=192.168.1.50`).
4. Faylni saqlang va `start.bat` ni qayta ishga tushiring.

### Portni o'zgartirish (8080 o'rniga boshqa port)

Agar 8080 band bo'lsa, **`main.py`** faylining **eng oxirgi qatorini** o'zgartiring:

```python
uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=False)
```

Masalan, 9000 port uchun: `port=9000` qiling. Keyin brauzerda: **http://IP:9000**.

---

## 4. Qisqacha xulosa

| Nima qilmoqchi | Qilish |
|----------------|--------|
| Loyihani saqlab boshqa kompyuterga olib o'tish | Git: `git add -A` → `git commit -m "..."` → `git push` |
| Boshqa kompyuterga o'rnatish | Git yoki ZIP orqali loyihani olib, **Python** va **Git** o'rnatib, `pip install -r requirements.txt`, keyin `start.bat` yoki `python main.py` |
| IP ni o'zgartirish (10.243.49.144 → yangi) | `start.bat` da `--host 10.243.49.144` ni yangi IP ga almashtiring yoki `0.0.0.0` qiling |
| Portni o'zgartirish | `main.py` oxirida `port=8080` ni o'zgartiring |

Barcha kompyuterda brauzerda ochish: **http://[shu kompyuter IP]:8080** yoki **http://localhost:8080** (agar server shu kompyuterdan ishlab turgan bo'lsa).
