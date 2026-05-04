"""
Click va Terminal kassalarni birlashtirish skripti.

Maqsad:
- Do'kon 1/2 da alohida click/terminal kassalar bor (4 ta)
- Real ish: bitta bank schyot
- Yangi 2 ta Asosiy kassa yaratiladi (click, terminal)
- Eski balanslar transfer qilinadi
- Eski 4 kassa is_active=False
- Sotuvchilar Asosiy kassalarga biriktiriladi

Ishga tushirish:
    python scripts/merge_click_terminal_cash.py --dry-run   # avval
    python scripts/merge_click_terminal_cash.py --execute   # tasdiqlandi
"""
import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB_PATH = Path("totli_holva.db")
BACKUP_DIR = Path("backups")
DEPT_ASOSIY = 1  # Ishlab chiqarish bo'limi
OLD_CASH_IDS = [6, 7, 8, 9]
OLD_CASH_LABELS = {
    6: "Do'kon 1 kassa Click",
    7: "Do'kon 2 kassa Click",
    8: "Do'kon 1 kassa Terminal",
    9: "Do'kon 2 kassa Terminal",
}
SOTUVCHILAR = [6, 13]  # Salohiddin (Do'kon 1), Abduvohid (Do'kon 2)
# Eslatma: Zikrilloh (#14) ishlab chiqarish operatori, sotuv qilmaydi.
# Eski kassalarning user_cash_registers yozuvlari (Zikrilloh ham) DELETE bilan tozalanadi.


def cash_balance(cur: sqlite3.Cursor, cid: int) -> float:
    cash = cur.execute("SELECT opening_balance FROM cash_registers WHERE id=?", (cid,)).fetchone()
    if not cash:
        return 0.0
    inc = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE cash_register_id=? AND type='income' AND (status='confirmed' OR status IS NULL)",
        (cid,),
    ).fetchone()[0]
    exp = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM payments WHERE cash_register_id=? AND type='expense' AND (status='confirmed' OR status IS NULL)",
        (cid,),
    ).fetchone()[0]
    t_out = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM cash_transfers WHERE from_cash_id=? AND status IN ('in_transit','completed')",
        (cid,),
    ).fetchone()[0]
    t_in = cur.execute(
        "SELECT COALESCE(SUM(amount),0) FROM cash_transfers WHERE to_cash_id=? AND status='completed'",
        (cid,),
    ).fetchone()[0]
    return float(cash[0] or 0) + float(inc) - float(exp) - float(t_out) + float(t_in)


def next_transfer_number(cur: sqlite3.Cursor) -> str:
    today = datetime.now().strftime("%Y%m%d")
    last = cur.execute(
        "SELECT number FROM cash_transfers WHERE number LIKE ? ORDER BY id DESC LIMIT 1",
        (f"TR-{today}-%",),
    ).fetchone()
    if not last:
        return f"TR-{today}-001"
    try:
        seq = int(last[0].split("-")[-1]) + 1
        return f"TR-{today}-{seq:03d}"
    except Exception:
        return f"TR-{today}-{datetime.now().strftime('%H%M%S')}"


def main(execute: bool):
    if not DB_PATH.exists():
        print(f"XATO: {DB_PATH} topilmadi")
        sys.exit(1)

    # Backup
    if execute:
        BACKUP_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"totli_holva_pre_merge_{ts}.db"
        shutil.copy2(DB_PATH, backup_path)
        print(f"Backup: {backup_path}")

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("\n" + "=" * 70)
    print(f"REJIM: {'IJRO' if execute else 'DRY-RUN (sinov)'}")
    print("=" * 70)

    cur.execute("BEGIN")
    try:
        # 1. Yangi 2 ta kassa
        now_iso = datetime.now().isoformat()
        cur.execute(
            "INSERT INTO cash_registers (name, payment_type, department_id, opening_balance, balance, is_active) VALUES (?, 'click', ?, 0, 0, 1)",
            ("Asosiy kassa Click", DEPT_ASOSIY),
        )
        asosiy_click = cur.lastrowid
        cur.execute(
            "INSERT INTO cash_registers (name, payment_type, department_id, opening_balance, balance, is_active) VALUES (?, 'terminal', ?, 0, 0, 1)",
            ("Asosiy kassa Terminal", DEPT_ASOSIY),
        )
        asosiy_terminal = cur.lastrowid
        print(f"\n[1] Yangi kassa yaratildi:")
        print(f"    #{asosiy_click}  Asosiy kassa Click")
        print(f"    #{asosiy_terminal}  Asosiy kassa Terminal")

        # 2. Balanslarni transfer qilish
        print(f"\n[2] CashTransfer (status=completed) yaratiladi:")
        total_transferred = 0.0
        for old_id in OLD_CASH_IDS:
            bal = cash_balance(cur, old_id)
            if bal <= 0:
                print(f"    SKIP: cash#{old_id} balansi 0 ({OLD_CASH_LABELS[old_id]})")
                continue
            old_cash = cur.execute("SELECT payment_type FROM cash_registers WHERE id=?", (old_id,)).fetchone()
            target_id = asosiy_click if old_cash["payment_type"] == "click" else asosiy_terminal
            tnum = next_transfer_number(cur)
            cur.execute(
                """INSERT INTO cash_transfers (number, date, from_cash_id, to_cash_id, amount, status, user_id, sent_at, approved_at, note, created_at)
                   VALUES (?, ?, ?, ?, ?, 'completed', NULL, ?, ?, ?, ?)""",
                (tnum, now_iso, old_id, target_id, bal, now_iso, now_iso, f"Avtomatik birlashtirish: {OLD_CASH_LABELS[old_id]} --&gt; Asosiy", now_iso),
            )
            print(f"    {tnum}  {OLD_CASH_LABELS[old_id]} ({bal:>13,.0f}) --&gt; cash#{target_id}")
            total_transferred += bal
        print(f"    JAMI: {total_transferred:,.0f}")

        # 3. Eski kassalarni o'chirish
        cur.execute(
            f"UPDATE cash_registers SET is_active=0 WHERE id IN ({','.join('?' * len(OLD_CASH_IDS))})",
            OLD_CASH_IDS,
        )
        print(f"\n[3] {len(OLD_CASH_IDS)} ta eski kassa is_active=0")

        # 4. Sotuvchi kassa biriktirishlari
        cur.execute(
            f"DELETE FROM user_cash_registers WHERE cash_register_id IN ({','.join('?' * len(OLD_CASH_IDS))})",
            OLD_CASH_IDS,
        )
        for uid in SOTUVCHILAR:
            cur.execute(
                "INSERT INTO user_cash_registers (user_id, cash_register_id) VALUES (?, ?)",
                (uid, asosiy_click),
            )
            cur.execute(
                "INSERT INTO user_cash_registers (user_id, cash_register_id) VALUES (?, ?)",
                (uid, asosiy_terminal),
            )
        print(f"\n[4] {len(SOTUVCHILAR)} ta sotuvchi qayta biriktirildi (eski --&gt; yangi)")

        # 5. Cached balance ustunlarini sinxronlashtirish
        cur.execute("UPDATE cash_registers SET balance = ? WHERE id = ?", (
            cash_balance(cur, asosiy_click), asosiy_click))
        cur.execute("UPDATE cash_registers SET balance = ? WHERE id = ?", (
            cash_balance(cur, asosiy_terminal), asosiy_terminal))
        for old_id in OLD_CASH_IDS:
            cur.execute("UPDATE cash_registers SET balance = ? WHERE id = ?", (
                cash_balance(cur, old_id), old_id))
        print(f"\n[5] Cached balance ustunlari sinxronlashtirildi")

        # 6. Tekshiruv
        print(f"\n[6] Yakuniy tekshiruv:")
        for cid, label in [(asosiy_click, "Asosiy Click"), (asosiy_terminal, "Asosiy Terminal")]:
            print(f"    cash#{cid:3} {label:25} balans = {cash_balance(cur, cid):>13,.0f}")
        for cid in OLD_CASH_IDS:
            print(f"    cash#{cid:3} {OLD_CASH_LABELS[cid]:25} balans = {cash_balance(cur, cid):>13,.0f}  (deactive)")

        if execute:
            con.commit()
            print("\n[OK] JARAYON YAKUNLANDI - DB ga yozildi")
        else:
            con.rollback()
            print("\n[DRY-RUN] hech narsa o'zgarmadi (--execute bilan ishga tushiring)")
    except Exception as e:
        con.rollback()
        print(f"\n[XATO] {e}")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    args = p.parse_args()
    main(execute=args.execute)
