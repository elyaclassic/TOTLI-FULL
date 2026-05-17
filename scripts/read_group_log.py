"""Guruh log fayllarini o'qib chiqadi.

Ishlatish:
    python scripts/read_group_log.py              # bugungi
    python scripts/read_group_log.py --date 2026-05-17
    python scripts/read_group_log.py --last 50    # oxirgi N ta xabar
"""
import argparse
import json
from datetime import date
from pathlib import Path

CWD = Path(__file__).parent.parent
LOG_DIR = CWD / "data" / "group_logs"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--last", type=int, default=0)
    args = parser.parse_args()

    files = sorted(LOG_DIR.glob(f"{args.date}_*.jsonl"))
    if not files:
        print(f"Log topilmadi: {args.date}")
        return

    entries = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                pass

    entries.sort(key=lambda x: x.get("ts", ""))
    if args.last:
        entries = entries[-args.last:]

    for e in entries:
        name = e.get("full_name") or e.get("username") or str(e.get("user_id"))
        uname = f"@{e['username']}" if e.get("username") else ""
        reply = f"  [reply→{e['reply_to']}]" if e.get("reply_to") else ""
        print(f"[{e['ts'][11:16]}] {name}{' ' + uname if uname else ''}{reply}")
        print(f"  {e['text']}")
        print()


if __name__ == "__main__":
    main()
