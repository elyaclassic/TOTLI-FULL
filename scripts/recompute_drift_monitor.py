"""TOTLI BI Recompute Drift Monitor — 2026-06-02

Kunlik: partner balans, stock kesh va kassa balansini KANONIK formula bilan solishtiradi.
Drift bo'lsa Yordamchim bot (CLAUDE_BOT_TOKEN) orqali egasiga alert yuboradi.

XAVFSIZ: faqat o'qiydi, hech narsa yozmaydi.
- Partner drift: compute_partner_balance(db, pid) vs stored (faol, pid!=1)
- Stock drift:   compute_stock_quantity(db, wh, pid) vs stored (move_count>0)
- Cash drift:    cash_balance_formula(db, cid)[0] vs stored (barcha kassalar)

Ishlatish:
    python scripts/recompute_drift_monitor.py            # tekshir + drift bo'lsa alert
    python scripts/recompute_drift_monitor.py --quiet    # faqat drift bo'lsa output
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

os.environ.setdefault("TOTLI_DB_FILE", "totli_holva.db")
os.environ.setdefault("SECRET_KEY", "x")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ENV_PATH = ROOT / ".env"
LOG_PATH = ROOT / "recompute_drift_monitor.log"
OWNER_ID = "1340383182"  # @elya_classic — Yordamchim bot owner
PARTNER_THRESHOLD = 1.0
STOCK_THRESHOLD = 0.01
QUIET = "--quiet" in sys.argv


def load_env(name: str):
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
        print("[ERROR] CLAUDE_BOT_TOKEN topilmadi (.env)")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": OWNER_ID, "text": text[:4000],
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data=data, timeout=10) as resp:
            if resp.status != 200:
                print(f"[WARN] TG status={resp.status}")
    except Exception as e:
        print(f"[ERROR] TG yuborish xatosi: {e}")


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts}  {msg}\n")
    except Exception:
        pass


def main():
    from app.models.database import SessionLocal, Partner, Stock, StockMovement, CashRegister
    from app.services.partner_balance_service import compute_partner_balance
    from app.services.stock_service import compute_stock_quantity
    from app.services.finance_service import cash_balance_formula

    db = SessionLocal()
    p_drift = []
    s_drift = []
    c_drift = []
    try:
        for p in db.query(Partner).filter(Partner.is_active == True):  # noqa: E712
            if p.id == 1:
                continue
            stored = float(p.balance or 0)
            computed = compute_partner_balance(db, p.id)
            if abs(stored - computed) > PARTNER_THRESHOLD:
                p_drift.append((p.id, p.name, stored, computed, computed - stored))
        for s in db.query(Stock).all():
            mc = db.query(StockMovement).filter(
                StockMovement.warehouse_id == s.warehouse_id,
                StockMovement.product_id == s.product_id).count()
            if mc == 0:
                continue
            stored = float(s.quantity or 0)
            computed = compute_stock_quantity(db, s.warehouse_id, s.product_id)
            if abs(stored - computed) > STOCK_THRESHOLD:
                s_drift.append((s.warehouse_id, s.product_id, stored, computed, computed - stored))
        for c in db.query(CashRegister).all():
            stored = float(c.balance or 0)
            computed, _, _ = cash_balance_formula(db, c.id)
            if abs(stored - computed) > PARTNER_THRESHOLD:
                c_drift.append((c.id, c.name, stored, computed, computed - stored))
    finally:
        db.close()

    p_drift.sort(key=lambda x: abs(x[4]), reverse=True)
    s_drift.sort(key=lambda x: abs(x[4]), reverse=True)
    c_drift.sort(key=lambda x: abs(x[4]), reverse=True)
    total = len(p_drift) + len(s_drift) + len(c_drift)

    if total == 0:
        msg = "Recompute drift YO'Q (partner + stock + kassa toza)."
        log(msg)
        if not QUIET:
            print(msg)
        return

    lines = [f"⚠️ <b>Recompute drift</b>: partner {len(p_drift)}, stock {len(s_drift)}, kassa {len(c_drift)}"]
    if p_drift:
        lines.append("\n<b>Partner balans:</b>")
        for pid, name, st, co, d in p_drift[:8]:
            lines.append(f"  #{pid} {str(name)[:20]}: {st:,.0f} vs {co:,.0f} ({d:+,.0f})")
    if s_drift:
        lines.append("\n<b>Stock:</b>")
        for wh, pid, st, co, d in s_drift[:8]:
            lines.append(f"  wh{wh}/p{pid}: {st:.1f} vs {co:.1f} ({d:+.1f})")
    if c_drift:
        lines.append("\n<b>Kassa balans:</b>")
        for cid, name, st, co, d in c_drift[:8]:
            lines.append(f"  #{cid} {str(name)[:20]}: {st:,.0f} vs {co:,.0f} ({d:+,.0f})")
    msg = "\n".join(lines)
    print(msg)
    log(f"DRIFT partner={len(p_drift)} stock={len(s_drift)} kassa={len(c_drift)}")
    send_telegram(msg)


if __name__ == "__main__":
    main()
