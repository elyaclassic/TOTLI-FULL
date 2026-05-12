# Deploy runbook — Yetkazish kuni feature

**Vaqt:** Yakshanba kechasi (2026-05-17), **00:00–04:00**
**Tier:** C (eng ehtiyotkor)
**Branch:** `xreport-improvements` → `main` ga merge bo'ladi
**DB:** `totli_holva.db` (live)

## Ko'rsatma turi

Bu **biror narsani buzmasligi kerak** — `delivery_date` va `dispatched_at` ustunlar additive. Status migratsiya 5238 ta `completed → delivered` o'zgartiradi, lekin foydalanuvchi ko'zi bilan farq yo'q (UI ham "Yetkazildi" deb ko'rsatadi).

---

## Pre-deploy (yakshanba kunduzi)

- [ ] Local'da to'liq pytest pass:
  ```
  python -m pytest tests/test_dispatch_flow.py tests/test_atomic_confirm.py tests/test_revert_balance.py -v
  ```
  Kutilgan: **20+ test pass, 0 fail**

- [ ] Migration skript dry-run:
  ```
  python scripts/migrate_orders_to_new_status_20260510.py
  ```
  Kutilgan: `5238 completed → delivered`, `8 confirmed (Delivery yo'q)` — bu 8 tani admin'ga ko'rsatish

- [ ] Hozirgi 8 ta `confirmed` orderni qo'lda tekshirish (`/sales?status=confirmed`) — kerak bo'lsa qo'lda `cancelled` qilish yoki tegmaslik

- [ ] `xreport-improvements` → `main` merge (PR yoki to'g'ridan-to'g'ri)

- [ ] Git tag:
  ```
  git tag pre-delivery-scheduling-2026-05-17
  git push --tags
  ```

---

## Tungi deploy (00:00–01:00)

### 1. Backup (00:00)

- [ ] DB online backup (har 5 daq script allaqachon ishlaydi, lekin qo'lda ham):
  ```
  python backup_db.py
  ```
  Hosil bo'ladi: `totli_holva_backup_2026-05-17_00-00-XX.db` (kamida 4-5 MB)

- [ ] Backup'ni alohida joyga nusxa:
  ```
  copy totli_holva.db "D:\TOTLI BI\backups\pre-deploy-2026-05-17.db"
  ```

### 2. Migration (00:10)

- [ ] Forward migration --apply:
  ```
  python scripts/migrate_orders_to_new_status_20260510.py --apply
  ```
  Kutilgan: ~5238 UPDATE qator. Skript o'zi backup yaratadi (`backups/pre_status_migrate_*.db`)

- [ ] Status taqsimot tekshirish:
  ```
  python -c "import sqlite3; c=sqlite3.connect('totli_holva.db'); [print(r) for r in c.cursor().execute('SELECT status, COUNT(*) FROM orders GROUP BY status').fetchall()]"
  ```
  Kutilgan: `delivered` taxminan 5238, `completed` 0 ga yaqin (faqat eski qaytarib bo'lmagan order'lar)

### 3. Server restart (00:20)

- [ ] Process'ni o'ldirish:
  ```
  taskkill /IM python.exe /F
  ```

- [ ] Yangi kod ishga tushirish:
  ```
  cd "D:\TOTLI BI"
  start.bat
  ```

- [ ] 1 daqiqa kutib log ko'rish (`server.log` oxiri):
  ```
  type server.log | findstr /C:"Uvicorn running"
  ```
  Kutilgan: `Uvicorn running on http://0.0.0.0:8080`

- [ ] Watchdog tekshirish (alohida task):
  ```
  schtasks /Query /TN "TOTLI Watchdog"
  ```

---

## Smoke test (00:30–01:00)

Brauzerda `http://server2220:8080`:

1. [ ] **Login** — admin sifatida kiring
2. [ ] **/sales** — sahifa ochiladi, **"Yuklash sanasi" ustun ko'rinadi**
3. [ ] **Yangi test order yarating** (agent sifatida yoki admin orqali) — status: **Yangi**
4. [ ] **Supervisor sifatida tasdiqlang** → status: **Tayyor**
5. [ ] **"Yuklash" tugmasi** ko'rinadi → bosing → **modal ochiladi**
6. [ ] Modal: **Sana (bugun)** + **Haydovchi tanlang** → "Yo'lga chiqarish" bosing
7. [ ] Status → **Yo'lda**, `dispatched_at` to'lgan
8. [ ] **Stock** kamayganini tekshiring (`/qoldiqlar`)
9. [ ] **Partner balansi** o'zgarmaganini tekshiring (ya'ni `previous_partner_balance` hali NULL)
10. [ ] **Driver mobil ilovasi** orqali "Yetkazdim" tugmasini bosing → status **Yetkazildi** + partner balansi **+= debt** yozildi

Boshqa tezkor tekshiruvlar:

- [ ] `/sales/deliveries` — **4 tab** ko'rinadi (Bugun / Ertaga / Kechikkanlar / Production)
- [ ] Mobil ilova → drayver kelajak kunlik delivery'larni **ko'rmaydi** (faqat bugun + kechikkan)
- [ ] POS, /home, /finance — eski sahifalar ishlayapti (regression yo'qligi)

---

## Agar muammo bo'lsa (Rollback)

### Soft rollback (status'ni qaytarish)

- [ ] ```
  python scripts/rollback_status_20260510.py --apply
  ```
  Bu `delivered → completed` va `out_for_delivery → confirmed` qaytaradi. `delivery_date` saqlanadi (additive).

- [ ] Server restart:
  ```
  taskkill /IM python.exe /F
  start.bat
  ```

### Hard rollback (kod va DB ham qaytarish)

- [ ] DB tiklash:
  ```
  copy /Y "D:\TOTLI BI\backups\pre-deploy-2026-05-17.db" totli_holva.db
  ```

- [ ] Git tag'ga qaytish:
  ```
  git checkout main
  git reset --hard pre-delivery-scheduling-2026-05-17
  ```
  ⚠ **`git reset --hard`** — local commit'lar yo'qoladi. Avval `git status` tekshiring.

- [ ] Server restart.

---

## Post-deploy (01:00+)

- [ ] **Telegram'ga xabar** — Yordamchim bot orqali:
  > Deploy tugadi: yetkazish kuni feature (Tier C). Smoke test OK. Watchdog ishlamoqda.

- [ ] **Sentry/log'larda** xato yo'qmi:
  ```
  type server.log | findstr /C:"ERROR" /C:"Traceback"
  ```

- [ ] **Watchdog 2 daqiqada** server javob bermayotganini sezsa, qayta ishga tushiradi

- [ ] **Kunduzi (dushanba 08:00)** birinchi haqiqiy buyurtmani kuzating — agent yarata olsinmi, supervisor tasdiqlasinmi, driver yetkaza olsinmi

---

## Foydalanuvchi instruktajli xabar (deploy oldidan)

Yakshanba kunduzi xodimlarga (admin/manager/agent/driver) Telegramda:

```
Bugun 00:00 dan boshlab buyurtma flow biroz o'zgaradi:

ESKI:
  - Buyurtma yaratdik → tasdiqladik → tugadi

YANGI:
  - Buyurtma yaratdik (Yangi)
  - Supervisor tasdiqladi (Tayyor)
  - Supervisor "Yuklash" tugmasi orqali sana va haydovchini tanladi (Yo'lda)
  - Haydovchi yetkazib "Yetkazdim" bosdi (Yetkazildi)

YANGI imkoniyat: /sales/deliveries — qaysi mahsulotlar bugun, ertaga, kechikdi
YANGI: Mijoz balansi faqat YETKAZIB BERILGANDAN keyin yangilanadi (oldin tasdiqlash paytida edi)
```

---

## Test fayllari (deploy verification)

```
python -m pytest tests/test_dispatch_flow.py -v
python -m pytest tests/test_atomic_confirm.py -v
python -m pytest tests/test_revert_balance.py -v
```

Kutilgan: hammasi pass (yaqindagi local run: 22/22 ✓)

---

## Aloqa

Deploy paytida muammo bo'lsa: **@elya_classic**

Watchdog botning ogohlantirishlari: Yordamchim bot → owner chat

---

**Yakuniy tekshiruv:** Pre-deploy → Tungi deploy → Smoke test → Post-deploy. Har bosqich tugagach checkbox belgilang. Agar smoke test'ning birorta qadami **OK emas** bo'lsa — rollback'ga o'ting, surishtirmang.
