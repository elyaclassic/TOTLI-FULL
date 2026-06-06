# POS "Band ustidan o'tish" checkbox — Dizayn

**Sana:** 2026-06-07
**Holat:** Tasdiqlangan → bajarish
**Bog'liq:** [[project-stock-reservation-deployed-20260606]] (Faza 2-B follow-up)

---

## 1. Muammo
Faza 2-B backend `/pos/complete` `force` form-fieldini qabul qiladi (band'ni admin/manager chetlab o'tishi), lekin POS'da uni yuborish UI yo'q — POS override ishlatib bo'lmaydi.

## 2. Maqsad
POS to'lov panelida admin/manager uchun "⚠️ Band ustidan o'tish" checkbox — belgilansa sotuv `force=1` bilan yuboriladi.

**Qaror (foydalanuvchi 2026-06-07):** oldindan belgilash (checkbox), reaktiv AJAX emas (POS form-POST arxitekturasiga mos, savat yo'qolmaydi).

## 3. Yondashuv
Faqat `app/templates/sales/_pos_cart.html` (posForm ichida include qilinadi) o'zgaradi. Backend tayyor (Faza 2-B `/pos/complete` `form.get("force")`). pos.js sotuvni `form.submit()` bilan yuboradi (pos.js:615/695) → posForm ichidagi har qanday input avtomatik yuboriladi, demak checkbox pos.js o'zgartirilmasdan ishlaydi. Checkbox "Sotuv" tugmasi yonida (admin/manager-only), `onchange` da JS confirm.

## 4. Komponent
`app/templates/sales/pos.html`:
- `posForm` ichida, to'lov/Sotish tugmasi yaqinida:
  ```html
  {% if current_user and current_user.role in ['admin','manager','menejer'] %}
  <label class="pos-force-label" title="Waiting buyurtmalarga band qilingan mahsulotni baribir sotish">
    <input type="checkbox" name="force" value="1" id="posForceReserve"> ⚠️ Band ustidan o'tish
  </label>
  {% endif %}
  ```
- Submit confirm: posForm submit'da `#posForceReserve` belgilangan bo'lsa `confirm("Band ustidan o'tib sotmoqchimisiz? Audit logga yoziladi.")` — false bo'lsa to'xtatadi.

## 5. Edge case
- Sotuvchi (sotuvchi roli) → checkbox ko'rinmaydi (faqat admin/manager). Agar sotuvchi qandaydir force=1 yuborsa ham, backend `reservation_override` role tekshiradi → band saqlanadi (Faza 2-B himoyasi).
- Belgilanmasa → oddiy sotuv (band saqlanadi).
- Har sotuvdan keyin sahifa qayta yuklanadi → checkbox tozalanadi.

## 6. Test
Template-only; Jinja sintaksis tekshiruvi. Backend force mantig'i Faza 2-B'da test qilingan (reservation_override). Manual: admin POS'da band mahsulotni checkbox bilan sotadi.

## 7. Risk
- Ma'lumotga ta'sir: yo'q (UI). Backend o'zgarmaydi.
- Xulq: admin/manager band ustidan POS'da sota oladi (maqsadli, audit bilan). Deploy: restart.
