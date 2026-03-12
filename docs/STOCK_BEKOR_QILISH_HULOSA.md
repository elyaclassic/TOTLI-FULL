# Hujjatlar bekor qilinganda Stock qanday ishlaydi — tekshiruv va xulosa

## Umumiy qoida (create_stock_movement va boshqa joylar)

- **Stock.quantity hech qachon manfiy saqlanmaydi.**  
  `create_stock_movement` ichida: `if stock.quantity < 0: stock.quantity = 0`  
  Demak: chiqim ko'p bo'lsa ham bazada qoldiq **0** dan pastga tushmaydi, **minus (−) ko'rsatkich saqlanmaydi**.

---

## 1. Qoldiq tuzatish (QLD) — bekor qilish

**Qanday:** `stock.quantity -= item.quantity`, keyin `if stock.quantity < 0: stock.quantity = 0`

- **Natija:** Qoldiq **kamayadi**, lekin **0 dan pastga tushmaydi** (clamp qilinadi).  
- **Muammo:** Agar keyinroq boshqa operatsiyalar (sotuv, o'tkazish) shu mahsulotdan ko'p chiqargan bo'lsa, bekor qilganda "haqiqiy" qoldiq manfiy bo'lishi mumkin, lekin tizim uni **0** qilib qo'yadi. Minus **ko'rsatilmaydi**.

---

## 2. Inventarizatsiya (INV) — bekor qilish

**Qanday:** Har bir item uchun `stock.quantity = item.previous_quantity` (tasdiqlashdan oldingi qoldiq qaytariladi).

- **Natija:** Stock **oldingi (previous_quantity) holatiga** qaytadi.  
- **Minus:** Yo'q — previous_quantity saqlangan va u manfiy emas (inventarizatsiya tasdiqlashda ham quantity 0 dan pastga tushmaydi).

---

## 3. Kirim (Purchase) — bekor qilish

**Qanday:** `stock.quantity -= item.quantity`. Agar `stock.quantity < 0` bo'lsa — **rollback**, xabar: "Ombor qoldig'i yetarli emas".

- **Natija:** Bekor qilish **faqat qoldiq yetarli bo'lsa** bajariladi. Kam bo'lsa operatsiya **rad etiladi**, stock o'zgarmaydi.  
- **0 ga tushish:** Agar kirim bekor qilinsa va boshqa chiqimlar bo'lmasa, qoldiq to'g'ri **kamayadi**; agar bir xil mahsulotdan boshqa qatorlar/kirimlar bo'lsa, faqat bitta `Stock` qatori yangilanadi (`.first()`), boshqalar hisobga olinmasa noto'g'ri bo'lishi mumkin.

---

## 4. O'mbordan omborga (Transfer) — bekor qilish

**Qanday:**  
- **Qayerga (to):** `dest.quantity -= item.quantity`, agar `< 0` bo'lsa `= 0`.  
- **Qayerdan (from):** `src.quantity += item.quantity` yoki yangi `Stock` qatori.

- **Natija:** O'tkazish teskari qilindi. **To** tomonda qoldiq kamayadi, lekin **0 dan pastga tushmaydi** (clamp). **From** tomonda qoldiq oshadi.  
- **Muammo:** Agar "qayerga" omborda mahsulot sotilgan yoki boshqa chiqim bo'lgan bo'lsa, bekor qilganda "qayerga" qoldiq manfiy bo'lishi mumkin edi, lekin tizim uni **0** qilib qo'yadi — **minus ko'rsatilmaydi**.

---

## 5. Sotuv — bekor qilish

**Qanday:** `stock.quantity += item.quantity` (qoldiq qaytariladi).

- **Natija:** Ombordagi qoldiq **oshadi**. Stock hech qanday tekshiruvsiz qo'shiladi (minusga tushish mumkin emas, chunki faqat qo'shish).  
- **0 yoki minus:** Sotuv bekor qilinsa qoldiq to'g'ri **ortadi**; minus yoki 0 ga maxsus holat yo'q.

---

## 6. Ishlab chiqarish — bekor qilish

**Qanday:**  
- **2-ombor (tayyor mahsulot):** `product_stock.quantity -= output_units`. Agar **current_qty < output_units** bo'lsa — **revert rad etiladi** (xabar: "2-omborda shu miqdorda qoldiq bo'lishi kerak").  
- **1-ombor (xom ashyo):** `stock.quantity += required` (yoki yangi Stock qatori).

- **Natija:**  
  - Tayyor mahsulot omborida qoldiq **yetarli bo'lsa** — bekor qilish bajariladi, tayyor mahsulot **kamayadi**, xom ashyo **qaytadi**.  
  - Tayyor mahsulot sotilgan/ko'chirilgan bo'lsa (qoldiq yetarli emas) — **revert qilinmaydi**, stock o'zgarmaydi.  
- **Minus:** Tayyor mahsulot qoldig'i yetarli emas bo'lsa revert **qilmaymiz**; agar qoldiq yetarli bo'lsa, faqat ayirish, **clamp yo'q** (ayirishdan keyin tekshiruv yo'q), lekin mantiqan qoldiq >= output_units bo'lgani uchun minus bo'lmasa kerak.

---

## Xulosa (savollaringizga javob)

| Savol | Javob |
|-------|--------|
| **Qoldiqlar / kirim / o'tkazish bekor qilinsa stock 0 holatga keladimi?** | **Yo'q.** Stock **0 ga faqat shu operatsiya natijasida** manfiy bo'lib qolsa clamp qilinadi (QLD revert, transfer revert "qayerga" tomonda). Umuman "barcha stock 0 bo'ladi" deb qilinmaydi. |
| **Ishlab chiqarish yoki sotuv bekor qilinsa, olingan/sotilgan miqdor stockda (−) ko'rsatiladimi?** | **Yo'q.** Tizimda **Stock.quantity hech qachon manfiy saqlanmaydi**. `create_stock_movement` va revert joylarida `< 0` bo'lsa **0** qilib qo'yiladi (yoki revert rad etiladi). **Minus ko'rsatkich** (bazada) **yo'q**. |
| **Stock 0 dan pastga tushadimi?** | **Yo'q.** Ham tasdiqlashda (`create_stock_movement`), ham revertlarda qoldiq **0 dan pastga tushmasa** qilinadi (clamp) yoki revert **rad etiladi** (purchase, production). |

---

## Tuzatish takliflari (agar xohlasangiz)

1. **Bir mahsulot/ombor uchun bir nechta Stock qatori:**  
   Revertlarda ham (purchase, transfer, production, qoldiq) bitta mahsulot/ombor uchun **barcha** Stock qatorlarini **yig'indiga** olib, keyin bitta qatorga birlashtirib ishlash — hisob va revert natijasi aniqroq bo'ladi.

2. **Manfiy qoldiqni hisobga olish (ixtiyoriy):**  
   Agar biznesda "minus qoldiq" ko'rsatilishi kerak bo'lsa, `create_stock_movement` va revertlardagi `if stock.quantity < 0: stock.quantity = 0` qismini olib tashlash kerak; bunda boshqa hisobotlar va cheklovlar ham qayta ko'rib chiqilishi kerak.

3. **Revert tartibi:**  
   Agar bir nechta hujjat ketma-ket tasdiqlangan bo'lsa, ularni bekor qilish tartibi (oxirgisi birinchi) to'g'ri bo'lishi uchun "oldingi qoldiq" yoki harakatlar tarixi asosida revert qilish mantiqini saqlab qolish ma'qul.
