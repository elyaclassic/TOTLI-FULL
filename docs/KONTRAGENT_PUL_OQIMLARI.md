# Kontragentlar bilan Pul Oqimlari — Qanday Hisoblanadi?

## Umumiy Tushuncha

Kontragentlar (ta'sischilar) bilan pul oqimlari **`Partner.balance`** maydoni orqali kuzatiladi:
- **Musbat balans** (+): Kontragent bizga qarzdor (bizdan olgan, to'lamagan)
- **Manfiy balans** (-): Biz kontragentga qarzdormiz (kontragentdan olgan, to'lamagan)

---

## 1. Tovar Kirimi (Purchase) — Chiqim

**Qachon:** Tovar kirimi tasdiqlanganda (`status = "confirmed"`)

**Hisoblash:**
```python
total_with_expenses = purchase.total + (purchase.total_expenses or 0)
partner.balance -= total_with_expenses  # Qarz qo'shiladi (manfiy)
```

**Misol:**
- Kirim summasi: 1,000,000 so'm
- Xarajatlar: 50,000 so'm
- **Jami:** 1,050,000 so'm
- **Kontragent balansi:** `balance = balance - 1,050,000` (bizga qarz qo'shiladi)

**Tasdiqni bekor qilish (revert):**
```python
partner.balance += total_with_expenses  # Qarz qaytariladi
```

---

## 2. Sotuv (Sale/Order) — Kirim

**Qachon:** Sotuv tasdiqlanganda (`status = "completed"`)

**Hisoblash:**
Hozirgi kodda sotuv tasdiqlashida kontragent balansi **to'g'ridan-to'g'ri o'zgartirilmaydi**. 
Sotuvdan kelgan pul **Payment** (to'lov) orqali kiritiladi.

**Agar sotuvda kontragent bo'lsa va qarz bo'lsa:**
- Sotuv summasi kontragentga qarz sifatida qo'shilishi mumkin
- Lekin hozirgi kodda bu avtomatik emas — Payment orqali qo'lda kiritiladi

---

## 3. To'lovlar (Payment) — Kirim/Chiqim

**Payment modeli:**
- `type`: `"income"` (kirim) yoki `"expense"` (chiqim)
- `partner_id`: Qaysi kontragentga tegishli
- `amount`: Summa

**Kirim (income):**
- Kontragentdan pul keldi (to'lov qildi)
- **Hisoblash:** `partner.balance += amount` (qarz kamayadi)

**Chiqim (expense):**
- Kontragentga pul ketdi (to'lov qildik)
- **Hisoblash:** `partner.balance -= amount` (qarz oshadi)

**Misol:**
- Kontragent balansi: -500,000 so'm (bizga qarzdor)
- Payment: `type="income"`, `amount=200,000`
- **Yangi balans:** `-500,000 + 200,000 = -300,000` (qarz kamaydi)

---

## 4. Kontragent Balans Hujjati (PartnerBalanceDoc)

**Qachon:** Qo'lda balans kiritilganda (Qoldiqlar → Kontragent → Yaratish)

**Hisoblash:**
```python
# Tasdiqlashda:
item.previous_balance = partner.balance  # Eski balans saqlanadi
partner.balance = item.balance  # Yangi balans o'rnatiladi

# Revertda:
partner.balance = item.previous_balance  # Eski balans qaytariladi
```

**Misol:**
- Eski balans: -300,000 so'm
- Hujjatda yangi balans: 0 so'm
- **Natija:** `balance = 0` (qarz to'landi deb belgilanadi)

---

## 5. Umumiy Formula

**Kontragent balansi quyidagicha hisoblanadi:**

```
Yangi balans = Eski balans
            - Tovar kirimlari (tasdiqlangan)
            + To'lovlar (income)
            - To'lovlar (expense)
            + Balans hujjati o'zgarishlari
```

**Yoki:**

```
partner.balance = 
    - Σ(Purchase.total + Purchase.total_expenses) [tasdiqlangan]
    + Σ(Payment.amount WHERE type='income')
    - Σ(Payment.amount WHERE type='expense')
    + PartnerBalanceDoc o'zgarishlari
```

---

## 6. Kodda Qayerda Ishlatiladi?

### Purchase (Kirim) tasdiqlash:
- **Fayl:** `app/routes/purchases.py`, `main.py`
- **Funksiya:** `purchase_confirm()`
- **Qator:** `partner.balance -= total_with_expenses`

### Purchase revert:
- **Funksiya:** `purchase_revert()`
- **Qator:** `partner.balance += total_with_expenses`

### PartnerBalanceDoc tasdiqlash:
- **Fayl:** `app/routes/qoldiqlar.py`, `main.py`
- **Funksiya:** `qoldiqlar_kontragent_hujjat_tasdiqlash()`
- **Qator:** `partner.balance = item.balance`

### Payment yaratish:
- Payment yaratilganda kontragent balansi **avtomatik o'zgartirilmaydi**
- Payment faqat tarix sifatida saqlanadi
- Agar Payment orqali balansni o'zgartirish kerak bo'lsa, qo'lda qo'shish kerak

---

## 7. Hisobotlar

**Kontragent qoldiqlari sahifasida:**
- `Partner.balance` maydoni ko'rsatiladi
- Musbat: kontragent bizga qarzdor
- Manfiy: biz kontragentga qarzdormiz

**To'lovlar ro'yxatida:**
- `Payment.type == "income"`: Kontragentdan pul keldi (+)
- `Payment.type == "expense"`: Kontragentga pul ketdi (-)

---

## 8. Eslatmalar

1. **Purchase tasdiqlash:** Avtomatik qarz qo'shiladi (kontragentdan olgan tovarlar uchun)
2. **Sale tasdiqlash:** Hozirgi kodda kontragent balansi o'zgartirilmaydi — Payment orqali qo'lda kiritiladi
3. **Payment:** Tarix sifatida saqlanadi, lekin balansga avtomatik ta'sir qilmaydi (agar kerak bo'lsa, kodga qo'shish mumkin)
4. **PartnerBalanceDoc:** Qo'lda balans o'rnatish (masalan, qarzni to'liq to'langan deb belgilash)

---

## 9. Kelajakda Yaxshilash

Agar sotuvda ham kontragent balansini avtomatik o'zgartirish kerak bo'lsa:

```python
# sales_confirm() funksiyasiga qo'shish:
if order.partner_id:
    partner = db.query(Partner).filter(Partner.id == order.partner_id).first()
    if partner:
        partner.balance += order.total  # Qarz qo'shiladi (kontragent bizga qarzdor bo'ladi)
```

Yoki Payment yaratilganda avtomatik balansni o'zgartirish:

```python
# Payment yaratilganda:
if payment.partner_id:
    partner = db.query(Partner).filter(Partner.id == payment.partner_id).first()
    if partner:
        if payment.type == "income":
            partner.balance += payment.amount  # Qarz kamayadi
        elif payment.type == "expense":
            partner.balance -= payment.amount  # Qarz oshadi
```
