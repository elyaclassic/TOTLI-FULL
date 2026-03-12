-- Kassalar jadvaliga payment_type ustunini qo'shish (POS to'lov turi: naqd, plastik, click, terminal)
-- SQLite:
ALTER TABLE cash_registers ADD COLUMN payment_type VARCHAR(20);

-- Agar ustun allaqachon mavjud bo'lsa, xato chiqadi — boshqa migratsiya bajarilgan bo'lishi mumkin.
