"""Bir martalik skript — bot orqali gruppa chat ID'ni topish.

Foydalanish:
  python scripts/capture_chat_id.py

Yo'l ko'rsatma:
  1. Botni gruppaga qo'shing (allaqachon qo'shgan bo'lsangiz, OK)
  2. Skript ishga tushgach 30 sek ichida gruppada xabar yozing
  3. Skript chat.id'ni ekranga yozadi
  4. Skript tugagach eski bot avto-restart bilan tiklanadi
"""
from __future__ import annotations

import json
import os
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ.get("CLAUDE_BOT_TOKEN", "")
if not TOKEN:
    print("CLAUDE_BOT_TOKEN .env'da yo'q")
    sys.exit(1)

API = f"https://api.telegram.org/bot{TOKEN}"


def drain():
    """Eski xabarlarni tashlab yuborish (faqat yangilar uchun kutamiz)."""
    r = requests.get(f"{API}/getUpdates", params={"limit": 100, "timeout": 0}, timeout=10)
    data = r.json()
    if not data.get("ok"):
        print(f"getUpdates xato: {data}")
        sys.exit(1)
    results = data.get("result", [])
    if results:
        last_id = max(u["update_id"] for u in results)
        # Confirm bilan tozalash
        requests.get(f"{API}/getUpdates", params={"offset": last_id + 1, "limit": 1, "timeout": 0}, timeout=10)
        print(f"Eski {len(results)} ta xabar tozalandi (oxirgi offset: {last_id + 1})")
        return last_id + 1
    return 0


def listen(offset: int, deadline: float):
    print(f"\nKuyuyapman... Gruppada XABAR YOZING (max {int(deadline - time.time())} sek)\n")
    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        try:
            r = requests.get(
                f"{API}/getUpdates",
                params={"offset": offset, "limit": 10, "timeout": min(10, remaining)},
                timeout=remaining + 5,
            )
            data = r.json()
        except Exception as e:
            print(f"Xato: {e}")
            time.sleep(2)
            continue
        if not data.get("ok"):
            print(f"API xato: {data.get('description', data)}")
            return None
        for upd in data.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member")
            if not msg:
                continue
            chat = msg.get("chat", {})
            ctype = chat.get("type", "?")
            cid = chat.get("id", "?")
            title = chat.get("title", "")
            from_user = msg.get("from", {})
            uname = from_user.get("username") or from_user.get("first_name") or "?"
            print(f"[update {upd['update_id']}] chat_type={ctype} chat_id={cid} title={title!r} from={uname}")
            if ctype in ("group", "supergroup"):
                print(f"\nTOPILDI: chat_id = {cid}")
                print(f"Sarlavha: {title}")
                print(f"Turi: {ctype}")
                return cid
    return None


def main():
    print("=== Gruppa chat ID topish ===")
    print(f"Bot token: {TOKEN[:10]}...{TOKEN[-4:]}")
    me = requests.get(f"{API}/getMe", timeout=10).json()
    if not me.get("ok"):
        print(f"getMe xato: {me}")
        sys.exit(1)
    print(f"Bot: @{me['result']['username']}")

    offset = drain()
    deadline = time.time() + 60  # 60 sek kutamiz
    cid = listen(offset, deadline)
    if cid:
        print(f"\nBuni .env'ga qo'shing:")
        print(f"  SENIOR_BOT_GROUP_IDS={cid}")
    else:
        print("\nVaqt tugadi — chat ID topilmadi. Bot gruppaga qo'shilganmi?")
        sys.exit(2)


if __name__ == "__main__":
    main()
