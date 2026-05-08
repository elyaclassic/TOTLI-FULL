"""TOTLI BI — Stale draft auto-cleanup
H4 audit fix: 7 kundan eski draft hujjatlar avtomat 'cancelled' ga o'tadi.

Har kuni 04:00 da Task Scheduler chaqiradi (TOTLI Stale Cleanup).

Quyidagilar tekshiriladi:
- Order (sotuv) draft >7 kun
- Production draft >7 kun
- ExpenseDoc draft >7 kun
- Purchase draft >7 kun

Telegramga digest yuboriladi. Read-only mode uchun --dry-run.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "totli_holva.db"
LOG_PATH = ROOT / "stale_cleanup.log"
ENV_PATH = ROOT / ".env"
OWNER_ID = "1340383182"

# 7 kundan eski draftlar tozalanadi
STALE_DAYS = 7


def load_env(name: str) -> str:
    val = os.environ.get(name)
    if val:
        return val
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    print(line, end="")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def send_telegram(text: str) -> None:
    token = load_env("CLAUDE_BOT_TOKEN")
    if not token:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": OWNER_ID,
        "text": text[:3500],
        "parse_mode": "HTML",
    }).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
    except Exception:
        pass


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    if not DB_PATH.exists():
        log(f"DB topilmadi: {DB_PATH}")
        return 1

    cutoff = (datetime.now() - timedelta(days=STALE_DAYS)).isoformat(sep=" ")
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    targets = [
        ("orders", "Order"),
        ("productions", "Production"),
        ("expense_docs", "ExpenseDoc"),
        ("purchases", "Purchase"),
    ]

    summary = []
    total_cancelled = 0
    samples = []

    for table, label in targets:
        try:
            cur.execute(
                f"SELECT id, number, created_at FROM {table} "
                f"WHERE status = 'draft' AND created_at < ? ORDER BY created_at LIMIT 100",
                (cutoff,),
            )
            stale = cur.fetchall()
        except sqlite3.OperationalError:
            continue

        if not stale:
            summary.append(f"✅ {label}: 0")
            continue

        cnt = len(stale)
        total_cancelled += cnt
        summary.append(f"⚠️ {label}: {cnt}")
        for r in stale[:3]:
            samples.append(f"  - {label} #{r[1] or r[0]} ({r[2][:10]})")

        if not dry_run:
            ids = [r[0] for r in stale]
            placeholders = ",".join("?" * len(ids))
            cur.execute(
                f"UPDATE {table} SET status = 'cancelled' WHERE id IN ({placeholders})",
                ids,
            )

    if not dry_run:
        conn.commit()

    log(f"{'DRY-RUN' if dry_run else 'APPLIED'}: {total_cancelled} ta stale draft "
        f"(>{STALE_DAYS} kun, kesma: {cutoff[:10]})")

    if total_cancelled > 0:
        prefix = "🔧 [DRY-RUN]" if dry_run else "🧹"
        text = (
            f"{prefix} <b>Stale draft cleanup</b>\n\n"
            f"{chr(10).join(summary)}\n\n"
            f"Jami: <b>{total_cancelled} ta</b> {'tozalanardi' if dry_run else 'tozalandi'}\n"
            f"Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        if samples:
            text += "\n\nMisollar:\n" + "\n".join(samples[:6])
        if not dry_run:
            send_telegram(text)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
