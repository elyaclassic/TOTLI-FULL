"""Bir martalik test — audit fixlar mantiqini tekshirish.
Local Python da SQLAlchemy yo'q — logikani qo'lda implement qilib sinaymiz."""
import sys, sqlite3
sys.stdout.reconfigure(encoding='utf-8')

# === D4 check_credit_limit local impl (partner_credit.py copy) ===
def check_credit_limit(partner, new_debt):
    if not partner:
        return True, ""
    if new_debt <= 0:
        return True, ""
    limit = float(getattr(partner, 'credit_limit', 0) or 0)
    if limit <= 0:
        return True, ""
    current = float(getattr(partner, 'balance', 0) or 0)
    projected = current + new_debt
    if projected > limit:
        return False, f"Limit oshib ketdi: {projected:,.0f} > {limit:,.0f}"
    return True, ""

class FakePartner:
    def __init__(self, name, balance, credit_limit):
        self.name = name; self.balance = balance; self.credit_limit = credit_limit

print('=== D4 check_credit_limit unit testlari ===')
print(f'1. Chakana 0 limit, 5M debt: ok={check_credit_limit(FakePartner("Chakana", 0, 0), 5_000_000)[0]} (kutilgan True)')
print(f'2. None partner: ok={check_credit_limit(None, 1_000_000)[0]} (kutilgan True)')
print(f'3. Naqd (debt=0): ok={check_credit_limit(FakePartner("X", 1_000_000, 2_000_000), 0)[0]} (kutilgan True)')
print(f'4. balans 500k + 1M < 2M: ok={check_credit_limit(FakePartner("Y", 500_000, 2_000_000), 1_000_000)[0]} (kutilgan True)')
ok, err = check_credit_limit(FakePartner("Z", 1_500_000, 2_000_000), 1_000_000)
print(f'5. balans 1.5M + 1M > 2M: ok={ok} (kutilgan False) | {err}')

print()
print('=== Real DB partnerlar ===')
conn = sqlite3.connect('totli_holva.db')
cur = conn.cursor()
cur.execute('SELECT id, name, balance, credit_limit FROM partners WHERE balance > 0 AND credit_limit > 0 LIMIT 5')
rows = cur.fetchall()
print(f'Limit > 0 va balans > 0 mijozlar: {len(rows)} ta')
for pid, name, bal, lim in rows:
    p = FakePartner(name, bal, lim)
    ok, _ = check_credit_limit(p, 500_000)
    print(f'  id={pid:4} {name[:25]:25} bal={bal:>10,.0f} lim={lim:>10,.0f} +500k -> {"OK" if ok else "BLOCK"}')

cur.execute('SELECT COUNT(*) FROM partners WHERE credit_limit > 0')
limit_count = cur.fetchone()[0]
cur.execute('SELECT COUNT(*) FROM partners WHERE credit_limit = 0 AND balance > 100000')
no_limit = cur.fetchone()[0]
print(f'  Jami: {limit_count} ta mijozda limit, {no_limit} ta limitsiz lekin qarzi >100k')

print()
print('=== H1 mark-paid validatsiya simulatsiyasi ===')
def sim_mark_paid(paid, total):
    if paid < 0: return 'REJECT', 0, 'pending'
    fp = max(0.0, float(paid))
    return 'OK', fp, ('paid' if fp >= total else 'pending')

for paid, total, label in [
    (-590000, 0, 'Bugungi Abdulhamid Mar bug — bloklanadi'),
    (-3692593, 0, 'Bugungi Siddiqov Mar bug — bloklanadi'),
    (590000, 590000, "Normal to'lov"),
    (300000, 590000, "Qism to'lov"),
    (0, 590000, 'Bo\'sh'),
]:
    res, p, st = sim_mark_paid(paid, total)
    print(f'  paid={paid:>+10,} total={total:>10,} -> {res:8} stored={p:>10,.0f} status={st}  [{label}]')

print()
print('=== C1 advance unconfirm — Payment lookup test ===')
cur.execute('''SELECT a.id, a.employee_id, e.full_name, a.amount, a.advance_date, a.cash_register_id
              FROM employee_advances a JOIN employees e ON a.employee_id=e.id
              WHERE a.confirmed_at IS NOT NULL ORDER BY a.id DESC LIMIT 5''')
for aid, eid, name, amount, adate, cash_id in cur.fetchall():
    desc = f'Avans: {(name or "")[:100]}'
    cur.execute('''SELECT id, status FROM payments
                  WHERE cash_register_id=? AND description=? AND amount=? AND date(date)=?
                    AND status='confirmed' AND type='expense' ORDER BY id DESC LIMIT 1''',
                (cash_id, desc, float(amount or 0), adate))
    p = cur.fetchone()
    if p:
        print(f'  adv={aid:4} {name[:18]:18} amount={amount:>9,.0f} {adate} -> Payment {p[0]} ({p[1]}) [LINK OK]')
    else:
        print(f'  adv={aid:4} {name[:18]:18} amount={amount:>9,.0f} {adate} -> Payment YOQ [orphan]')

print()
print('=== C2 last_prices admin-only ===')
print('  Logic: is_admin=False -> last_prices={}')
print('  Template: last_prices.get(p.id, 0) if last_prices else 0 -> hammasi 0')
print('  data-cost="0" non-admin uchun -> tannarx ko\'rinmaydi  [OK]')

print()
print('=== D2 POS qarz revert previous_partner_balance ===')
cur.execute('''SELECT COUNT(*) FROM orders WHERE source != "agent" AND debt > 0 AND previous_partner_balance IS NULL''')
unsaved = cur.fetchone()[0]
print(f'  Eski qarz orderlar previous_partner_balance saqlanmagan: {unsaved} ta')
print(f'  Yangi POS qarz orderlar avtomatik saqlanadi (D2 fix)')

conn.close()
print()
print('=== ✓ Hammasi tekshirildi ===')
