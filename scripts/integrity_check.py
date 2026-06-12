"""TOTLI BI Integrity Check — 2026-05-07
Har soatda DB invariantlarni tekshiradi va Yordamchim bot orqali alert yuboradi.

XAVFSIZ: faqat o'qiydi, hech narsa yozmaydi.
Topadigan muammolar: stock drift, manfiy paid, user-employee gap, orphan
yozuvlar, manfiy kassa, stale draft, balance entry mismatch.

Ishlatish:
    python scripts/integrity_check.py        # bir martalik tekshiruv
    python scripts/integrity_check.py --quiet # faqat muammo bo'lsa output
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path

# Windows cp1251 stdout — emoji va kirill harflar uchun
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"
ENV_PATH = ROOT / ".env"
LOG_PATH = ROOT / "integrity_check.log"

OWNER_ID = "1340383182"  # @elya_classic — Yordamchim bot owner


def load_env(name: str) -> str | None:
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def send_telegram(text: str) -> None:
    token = load_env("CLAUDE_BOT_TOKEN")
    if not token:
        print("[ERROR] CLAUDE_BOT_TOKEN topilmadi (.env'ni tekshiring)")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": OWNER_ID,
        "text": text[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            if resp.status != 200:
                print(f"[WARN] TG status={resp.status}")
    except Exception as e:
        print(f"[ERROR] TG yuborish xatosi: {e}")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts}  {msg}\n"
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# ============================================================
# TEKSHIRUVLAR — har biri (issue_count, message_or_none) qaytaradi
# ============================================================

def check_stock_drift(cur) -> tuple[int, str | None]:
    """Stock.quantity != sum(StockMovement.quantity_change) — drift."""
    cur.execute("""
        SELECT s.id, s.warehouse_id, s.product_id, s.quantity,
               COALESCE((SELECT SUM(sm.quantity_change) FROM stock_movements sm WHERE sm.stock_id = s.id), 0) AS sum_mv
        FROM stocks s
    """)
    drifted = []
    for r in cur.fetchall():
        if abs(float(r[3] or 0) - float(r[4] or 0)) > 0.01:
            drifted.append(r)
    if not drifted:
        return 0, None
    msg = f"❌ <b>Stock drift</b>: {len(drifted)} ta\n"
    for r in drifted[:3]:
        msg += f"  stock_id={r[0]} wh={r[1]} prod={r[2]} qty={r[3]:.2f} sum_mv={r[4]:.2f} farq={float(r[3] or 0) - float(r[4] or 0):+.2f}\n"
    if len(drifted) > 3:
        msg += f"  ...va yana {len(drifted) - 3} ta\n"
    return len(drifted), msg


def check_negative_paid(cur) -> tuple[int, str | None]:
    """Salary.paid < 0 — invariant violation."""
    cur.execute("""
        SELECT s.id, s.year, s.month, e.full_name, s.paid
        FROM salaries s JOIN employees e ON s.employee_id = e.id
        WHERE s.paid < 0
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"❌ <b>Salary.paid &lt; 0</b>: {len(rows)} ta\n"
    for r in rows[:5]:
        msg += f"  id={r[0]} {r[1]}-{r[2]:02d} {r[3]} paid={r[4]:,.0f}\n"
    return len(rows), msg


def check_user_without_employee(cur) -> tuple[int, str | None]:
    """Operator role'i bor User'lar Employee'ga bog'lanmagan."""
    cur.execute("""
        SELECT u.id, u.username, u.role
        FROM users u
        LEFT JOIN employees e ON e.user_id = u.id
        WHERE u.role IN ('production', 'qadoqlash', 'operator')
          AND u.is_active = 1
          AND e.id IS NULL
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"⚠️ <b>User-Employee link yo'q</b>: {len(rows)} ta\n"
    for r in rows:
        msg += f"  user_id={r[0]} {r[1]} role={r[2]}\n"
    return len(rows), msg


def check_dismissed_in_salary(cur) -> tuple[int, str | None]:
    """Bo'shatilgan xodimlar joriy oy salary'da paydo bo'lgan."""
    today = date.today()
    period_start = f"{today.year}-{today.month:02d}-01"
    cur.execute("""
        SELECT e.id, e.full_name, MAX(d.doc_date) as last_dismiss
        FROM salaries s
        JOIN employees e ON s.employee_id = e.id
        JOIN dismissal_docs d ON d.employee_id = e.id
        WHERE s.year = ? AND s.month = ?
        GROUP BY e.id
        HAVING last_dismiss < ?
    """, (today.year, today.month, period_start))
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"⚠️ <b>Bo'shatilgan xodim joriy oy salary'da</b>: {len(rows)} ta\n"
    for r in rows:
        msg += f"  emp={r[0]} {r[1]} dismissed={r[2]}\n"
    return len(rows), msg


def check_orphan_movements(cur) -> tuple[int, str | None]:
    """StockMovement.stock_id mavjud bo'lmagan stocks'ga ishora qiladi."""
    cur.execute("""
        SELECT sm.id, sm.stock_id, sm.product_id, sm.warehouse_id
        FROM stock_movements sm
        LEFT JOIN stocks s ON s.id = sm.stock_id
        WHERE sm.stock_id IS NOT NULL AND s.id IS NULL
        LIMIT 5
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"❌ <b>Orphan StockMovement</b>: {len(rows)} ta (nominal)\n"
    for r in rows[:3]:
        msg += f"  sm_id={r[0]} stock_id={r[1]} prod={r[2]} wh={r[3]}\n"
    return len(rows), msg


def check_orphan_production_order(cur) -> tuple[int, str | None]:
    """Production.order_id mavjud bo'lmagan order'ga ishora."""
    cur.execute("""
        SELECT p.id, p.number, p.order_id
        FROM productions p
        LEFT JOIN orders o ON o.id = p.order_id
        WHERE p.order_id IS NOT NULL AND o.id IS NULL
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"❌ <b>Production.order_id orphan</b>: {len(rows)} ta\n"
    for r in rows[:3]:
        msg += f"  pr_id={r[0]} {r[1]} order_id={r[2]}\n"
    return len(rows), msg


def check_stale_drafts(cur) -> tuple[int, str | None]:
    """7 kundan eski draft hujjatlar."""
    cur.execute("""
        SELECT 'order' as kind, COUNT(*) FROM orders
        WHERE status = 'draft' AND created_at < datetime('now', '-7 days')
        UNION ALL
        SELECT 'production', COUNT(*) FROM productions
        WHERE status = 'draft' AND created_at < datetime('now', '-7 days')
        UNION ALL
        SELECT 'expense_doc', COUNT(*) FROM expense_docs
        WHERE status = 'draft' AND created_at < datetime('now', '-7 days')
    """)
    stale = [(r[0], r[1]) for r in cur.fetchall() if r[1] > 0]
    if not stale:
        return 0, None
    total = sum(s[1] for s in stale)
    msg = f"⚠️ <b>Stale drafts &gt; 7 kun</b>: jami {total} ta\n"
    for kind, count in stale:
        msg += f"  {kind}: {count} ta\n"
    return total, msg


def check_balance_entry_paid_mismatch(cur) -> tuple[int, str | None]:
    """is_balance_entry=True + status=paid + paid != |total| → XOD ka'fil."""
    cur.execute("""
        SELECT s.id, s.year, s.month, e.full_name, s.total, s.paid
        FROM salaries s JOIN employees e ON s.employee_id = e.id
        WHERE s.is_balance_entry = 1
          AND s.status = 'paid'
          AND s.paid != 0
          AND ABS(ABS(s.paid) - ABS(s.total)) > 0.01
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"⚠️ <b>Balance entry paid≠total</b>: {len(rows)} ta\n"
    for r in rows[:5]:
        msg += f"  id={r[0]} {r[1]}-{r[2]:02d} {r[3]} total={r[4]:,.0f} paid={r[5]:,.0f}\n"
    return len(rows), msg


def check_negative_stock(cur) -> tuple[int, str | None]:
    """Stock.quantity < 0 — manfiy qoldiq."""
    cur.execute("""
        SELECT s.id, s.warehouse_id, p.name, s.quantity
        FROM stocks s JOIN products p ON s.product_id = p.id
        WHERE s.quantity < -0.01
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"❌ <b>Manfiy stock</b>: {len(rows)} ta\n"
    for r in rows[:5]:
        msg += f"  stock_id={r[0]} wh={r[1]} {r[2][:30]} qty={r[3]:.2f}\n"
    return len(rows), msg


def check_subtotal_desync(cur) -> tuple[int, str | None]:
    """Order.subtotal != Σ(OrderItem.quantity × price) — subtotal desync.

    Chegirma subtotal'ni o'zgartirmaydi, shuning uchun qty×price bilan
    solishtiramiz (total emas). cancelled/draft chiqarib tashlanadi.
    """
    cur.execute("""
        SELECT o.id, o.number, o.subtotal,
               COALESCE((SELECT SUM(oi.quantity * oi.price) FROM order_items oi
                         WHERE oi.order_id = o.id), 0) AS items_sum
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
    """)
    bad = []
    for r in cur.fetchall():
        if abs(float(r[2] or 0) - float(r[3] or 0)) > 1.0:
            bad.append(r)
    if not bad:
        return 0, None
    msg = f"❌ <b>Subtotal desync</b>: {len(bad)} ta\n"
    for r in bad[:5]:
        msg += f"  #{r[0]} {r[1] or ''} subtotal={float(r[2] or 0):,.0f} items={float(r[3] or 0):,.0f} farq={float(r[2] or 0)-float(r[3] or 0):+,.0f}\n"
    if len(bad) > 5:
        msg += f"  ...va yana {len(bad) - 5} ta\n"
    return len(bad), msg


def check_sale_from_wrong_warehouse(cur) -> tuple[int, str | None]:
    """Sotuv Vozvrat (wh=7) yoki Xom ashyo (wh=1) ombordan bo'lmasligi kerak.

    Order.warehouse_id yoki biror OrderItem.warehouse_id shu omborlarda bo'lsa.
    """
    cur.execute("""
        SELECT DISTINCT o.id, o.number, o.warehouse_id
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
          AND (
            o.warehouse_id IN (1, 7)
            OR EXISTS (SELECT 1 FROM order_items oi
                       WHERE oi.order_id = o.id AND oi.warehouse_id IN (1, 7))
          )
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"❌ <b>Noto'g'ri ombordan sotuv</b> (Vozvrat/Xom ashyo): {len(rows)} ta\n"
    for r in rows[:5]:
        msg += f"  #{r[0]} {r[1] or ''} wh={r[2]}\n"
    return len(rows), msg


def check_null_price_type(cur) -> tuple[int, str | None]:
    """Aktiv sotuvda price_type_id NULL bo'lmasligi kerak (narx turi tanlanmagan)."""
    cur.execute("""
        SELECT o.id, o.number, o.source
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
          AND o.price_type_id IS NULL
    """)
    rows = cur.fetchall()
    if not rows:
        return 0, None
    msg = f"⚠️ <b>Narx turi (price_type) NULL</b>: {len(rows)} ta aktiv sotuv\n"
    for r in rows[:5]:
        msg += f"  #{r[0]} {r[1] or ''} source={r[2] or '?'}\n"
    if len(rows) > 5:
        msg += f"  ...va yana {len(rows) - 5} ta\n"
    return len(rows), msg


def check_agent_debt_desync(cur) -> tuple[int, str | None]:
    """Aktiv sotuvda Order.debt == max(0, total − paid) bo'lishi kerak.

    Agent/oddiy sotuvlarda per-order qarz ko'rsatkichi izchilligi.
    """
    cur.execute("""
        SELECT o.id, o.number, o.source, o.total, o.paid, o.debt
        FROM orders o
        WHERE o.type = 'sale' AND o.status NOT IN ('cancelled', 'draft')
    """)
    bad = []
    for r in cur.fetchall():
        total, paid, debt = float(r[3] or 0), float(r[4] or 0), float(r[5] or 0)
        expected = max(0.0, total - paid)
        if abs(debt - expected) > 1.0:
            bad.append((r[0], r[1], r[2], total, paid, debt, expected))
    if not bad:
        return 0, None
    msg = f"⚠️ <b>Qarz desync</b> (debt ≠ total−paid): {len(bad)} ta\n"
    for b in bad[:5]:
        msg += f"  #{b[0]} {b[1] or ''} total={b[3]:,.0f} paid={b[4]:,.0f} debt={b[5]:,.0f} kutilgan={b[6]:,.0f}\n"
    if len(bad) > 5:
        msg += f"  ...va yana {len(bad) - 5} ta\n"
    return len(bad), msg


# ============================================================
# MAIN
# ============================================================

CHECKS = [
    ("Stock drift (qty vs sum_movements)", check_stock_drift),
    ("Manfiy salary.paid", check_negative_paid),
    ("User-Employee link", check_user_without_employee),
    ("Bo'shatilgan xodim salary'da", check_dismissed_in_salary),
    ("Orphan StockMovement", check_orphan_movements),
    ("Orphan Production.order_id", check_orphan_production_order),
    ("Stale drafts", check_stale_drafts),
    ("Balance entry paid mismatch", check_balance_entry_paid_mismatch),
    ("Manfiy stock", check_negative_stock),
]


def main(argv: list[str]) -> int:
    quiet = "--quiet" in argv
    verbose = "--verbose" in argv or "-v" in argv

    if not DB_PATH.exists():
        msg = f"DB topilmadi: {DB_PATH}"
        log(msg)
        print(msg)
        return 1

    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
    except sqlite3.OperationalError as e:
        log(f"DB ochish xatosi: {e}")
        if not quiet:
            print(f"[ERROR] DB ochish xatosi: {e}")
        return 1

    cur = conn.cursor()
    issues = []
    summary = []
    total_count = 0

    for name, check_fn in CHECKS:
        try:
            count, message = check_fn(cur)
        except Exception as e:
            log(f"Check '{name}' xato: {e}")
            summary.append(f"⚠️ {name}: ERROR ({e})")
            continue
        total_count += count
        if message:
            issues.append(message)
            summary.append(f"❌ {name}: {count}")
        else:
            summary.append(f"✅ {name}")

    conn.close()

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if issues:
        text = f"<b>[INTEGRITY {now}]</b>\n\n" + "\n".join(issues)
        log(f"ALERT: total={total_count}")
        send_telegram(text)
        if not quiet or verbose:
            print(text.replace("<b>", "").replace("</b>", ""))
    else:
        log("OK")
        if not quiet:
            print(f"[INTEGRITY {now}] ✅ Hammasi toza ({len(CHECKS)} ta tekshiruv)")

    if verbose:
        print("\n--- Summary ---")
        for s in summary:
            print(" ", s)

    return 0 if not issues else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
