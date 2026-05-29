import os

BOT_TOKEN = os.environ.get("CUSTOMER_BOT_TOKEN", "")
LOCK_PORT = int(os.environ.get("CUSTOMER_BOT_LOCK_PORT", "47893"))


def admin_ids():
    raw = os.environ.get("CUSTOMER_BOT_ADMIN_IDS", "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.strip().isdigit()}
