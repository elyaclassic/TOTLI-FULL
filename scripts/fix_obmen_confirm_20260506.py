"""4 ta obmen pari (return_sale parent + sale child) ni to'g'ri tasdiqlash.

To'g'ridan-to'g'ri sqlite3 — sqlalchemy talab qilmaydi.
Stock va stock_movements bitta transaction ichida yangilanadi.

Algoritm har obmen pari uchun:
1. Parent (return_sale, WH=Vozvrat=7): status=confirmed, har item uchun
   stock_movements +qty (kirim Vozvrat) va Stock.quantity += qty
2. Child (sale, WH=Tayyor=3): Stock yetarli bo'lsa status=confirmed +
   stock_movements -qty + Stock.quantity -= qty + Delivery (Ulug'bek);
   yetmasa waiting_production
"""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "totli_holva.db"
NOW = datetime.now()
ADMIN_USER_ID = 1
ULUGBEK_DRIVER_ID = 1


def log(msg: str) -> None:
    print(msg, flush=True)


def get_or_create_stock(cur, warehouse_id: int, product_id: int) -> tuple[int, float]:
    cur.execute(
        "SELECT id, quantity FROM stocks WHERE warehouse_id=? AND product_id=?",
        (warehouse_id, product_id),
    )
    row = cur.fetchone()
    if row:
        return row[0], float(row[1] or 0)
    cur.execute(
        "INSERT INTO stocks (warehouse_id, product_id, quantity, cost_price) VALUES (?, ?, 0, 0)",
        (warehouse_id, product_id),
    )
    return cur.lastrowid, 0.0


def add_stock_movement(
    cur, *, warehouse_id, product_id, change, op_type, doc_id, doc_number, note, user_id, when
):
    stock_id, current = get_or_create_stock(cur, warehouse_id, product_id)
    new_qty = current + change
    cur.execute(
        """
        INSERT INTO stock_movements
            (stock_id, warehouse_id, product_id, operation_type, document_type, document_id,
             document_number, quantity_change, quantity_after, user_id, note, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stock_id, warehouse_id, product_id, op_type, "Sale", doc_id,
            doc_number, change, new_qty, user_id, note, when,
        ),
    )
    cur.execute("UPDATE stocks SET quantity=? WHERE id=?", (new_qty, stock_id))
    return new_qty


def confirm_return_part(cur, parent: dict) -> int:
    """Parent return_sale → Vozvrat omborga kirim. items soni qaytaradi."""
    cur.execute(
        "SELECT id, product_id, quantity, warehouse_id FROM order_items WHERE order_id=?",
        (parent["id"],),
    )
    items = cur.fetchall()
    note = f"Obmen qaytarish (Vozvrat kirim): {parent['number']}"
    when = parent["date"] or NOW.strftime("%Y-%m-%d %H:%M:%S")
    for _, pid, qty, item_wh in items:
        if not pid or (qty or 0) <= 0:
            continue
        wh = item_wh or parent["warehouse_id"]
        if not wh:
            continue
        add_stock_movement(
            cur,
            warehouse_id=wh,
            product_id=pid,
            change=+float(qty),
            op_type="return_sale",
            doc_id=parent["id"],
            doc_number=parent["number"],
            note=note,
            user_id=ADMIN_USER_ID,
            when=when,
        )
    cur.execute(
        "UPDATE orders SET status='confirmed', user_id=? WHERE id=?",
        (ADMIN_USER_ID, parent["id"]),
    )
    return len(items)


def confirm_sale_part(cur, child: dict) -> tuple[str, list[str]]:
    """Child sale → Stock yetsa Tayyor chiqim + confirmed; aks holda waiting."""
    cur.execute(
        "SELECT id, product_id, quantity, warehouse_id FROM order_items WHERE order_id=?",
        (child["id"],),
    )
    items = cur.fetchall()
    shortage = []
    for _, pid, qty, item_wh in items:
        if not pid or (qty or 0) <= 0:
            continue
        wh = item_wh or child["warehouse_id"]
        cur.execute(
            "SELECT quantity FROM stocks WHERE warehouse_id=? AND product_id=?",
            (wh, pid),
        )
        row = cur.fetchone()
        have = float(row[0] or 0) if row else 0
        if have + 1e-6 < float(qty):
            cur.execute("SELECT name FROM products WHERE id=?", (pid,))
            name_row = cur.fetchone()
            name = name_row[0] if name_row else f"#{pid}"
            shortage.append(f"{name} (kerak: {qty}, bor: {have})")

    if shortage:
        new_note = (child["note"] or "") + "\n[Production kutilmoqda] " + ", ".join(shortage)
        cur.execute(
            "UPDATE orders SET status='waiting_production', pending_driver_id=?, note=? WHERE id=?",
            (ULUGBEK_DRIVER_ID, new_note, child["id"]),
        )
        return "waiting", shortage

    note = f"Obmen yangi tovar (Tayyor chiqim): {child['number']}"
    when = child["date"] or NOW.strftime("%Y-%m-%d %H:%M:%S")
    for _, pid, qty, item_wh in items:
        if not pid or (qty or 0) <= 0:
            continue
        wh = item_wh or child["warehouse_id"]
        add_stock_movement(
            cur,
            warehouse_id=wh,
            product_id=pid,
            change=-float(qty),
            op_type="sale",
            doc_id=child["id"],
            doc_number=child["number"],
            note=note,
            user_id=ADMIN_USER_ID,
            when=when,
        )
    cur.execute(
        "UPDATE orders SET status='confirmed', user_id=? WHERE id=?",
        (ADMIN_USER_ID, child["id"]),
    )
    return "confirmed", []


def create_delivery(cur, child: dict, parent_number: str) -> str:
    today = NOW.strftime("%Y%m%d")
    prefix = f"DLV-{today}"
    cur.execute(
        "SELECT number FROM deliveries WHERE number LIKE ? ORDER BY id DESC LIMIT 1",
        (f"{prefix}-%",),
    )
    last = cur.fetchone()
    try:
        seq = int(last[0].split("-")[-1]) + 1 if last else 1
    except (ValueError, IndexError):
        seq = 1
    number = f"{prefix}-{seq:04d}"

    cur.execute(
        "SELECT name, address, latitude, longitude, phone FROM partners WHERE id=?",
        (child["partner_id"],),
    )
    p = cur.fetchone() or ("?", "", None, None, "")

    cur.execute(
        """
        INSERT INTO deliveries
            (number, driver_id, order_id, order_number, delivery_address, latitude, longitude,
             planned_date, notes, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'in_progress', ?)
        """,
        (
            number, ULUGBEK_DRIVER_ID, child["id"], child["number"], p[1] or "",
            p[2], p[3], NOW, f"Mijoz: {p[0]}, Obmen pari: {parent_number}",
            NOW,
        ),
    )
    return number


def main() -> int:
    if not DB.exists():
        log(f"DB topilmadi: {DB}")
        return 1
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, number, type, status, partner_id, total, parent_order_id,
               warehouse_id, date, note
        FROM orders
        WHERE agent_id=1 AND type='return_sale' AND status='waiting_production'
          AND created_at >= '2026-05-06'
        ORDER BY id ASC
        """
    )
    parents = [dict(r) for r in cur.fetchall()]
    if not parents:
        log("Tasdiqlanishi kerak bo'lgan obmen pari yo'q")
        return 0

    log(f"Topildi: {len(parents)} ta obmen pari")
    log("")

    try:
        for parent in parents:
            cur.execute(
                """
                SELECT id, number, type, partner_id, total, warehouse_id, date, note
                FROM orders WHERE parent_order_id=? AND type='sale' LIMIT 1
                """,
                (parent["id"],),
            )
            child_row = cur.fetchone()
            child = dict(child_row) if child_row else None

            cur.execute("SELECT name FROM partners WHERE id=?", (parent["partner_id"],))
            pname_row = cur.fetchone()
            pname = pname_row[0] if pname_row else f"#{parent['partner_id']}"

            log(f"\n→ {parent['number']} ↔ {child['number'] if child else 'YO`Q'} | {pname}")

            n_ret = confirm_return_part(cur, parent)
            log(f"  ✓ {parent['number']} (return_sale) → confirmed, Vozvratga kirim {n_ret} item")

            if child:
                status, short = confirm_sale_part(cur, child)
                if status == "confirmed":
                    log(f"  ✓ {child['number']} (sale) → confirmed, Tayyor chiqim")
                    dlv = create_delivery(cur, child, parent["number"])
                    log(f"  ✓ {dlv} → driver=Ulug'bek")
                else:
                    log(f"  ⚠ {child['number']} (sale) → waiting_production: {', '.join(short)}")

                diff = float(child["total"] or 0) - float(parent["total"] or 0)
                log(f"  i Balans farqi: {diff:+.0f} (mijoz balansi avtomat hisoblanadi)")

        conn.commit()
        log("\n✅ Hammasi muvaffaqiyatli tasdiqlandi")
        return 0
    except Exception as e:
        conn.rollback()
        log(f"\nXATO: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
