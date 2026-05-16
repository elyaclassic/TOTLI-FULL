"""Double-count audit tuzatish — 2 ta jabrlangan agent buyurtma.

AGT-20260502-012 (id 3711) va AGT-20260508-006 (id 4824): har order_item uchun
AYNAN 2 ta bir xil `sale` StockMovement (double-confirm dublikati, bir
soniyada, sale_revert yo'q, wh=3). Stock satr-miqdori bo'yicha ortiqcha
chegirilgan. Tuzatish: har (product, warehouse) uchun BITTA musbat
kompensatsiya StockMovement qo'shamiz (= +ortiqcha), dublikat satrlar
O'CHIRILMAYDI (audit trail saqlanadi — CLAUDE.md: revert teskari movement orqali).

Ishlatish:
    python scripts/fix_double_count_20260516.py [db_path] [--apply]

Default DRY-RUN — hech narsa yozilmaydi. --apply bilan qo'llang.
FAQAT D:\\TOTLI BI dan (.env / SECRET_KEY kerak) ishga tushiring.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from datetime import datetime

try:
    from app.services.stock_service import create_stock_movement
    from app.models.database import Order, OrderItem, Stock, StockMovement, Product
except Exception as e:  # SECRET_KEY/.env yo'q bo'lsa import zanjiri sinadi
    print(
        "XATO: app modullarini import qilib bo'lmadi.\n"
        "SECRET_KEY/.env kerak — D:\\TOTLI BI dan ishga tushiring.\n"
        f"Sabab: {e}"
    )
    sys.exit(1)


TARGET_ORDERS = ["AGT-20260502-012", "AGT-20260508-006"]
DBLFIX_MARKER = "DBLFIX-20260516"
DBLFIX_NOTE = "DBLFIX-20260516: takroriy sale chegirim qaytarildi (double-count audit)"


def run(db, *, apply: bool) -> list:
    """Har target order uchun clean-double (2x) holatni aniqlab kompensatsiya
    qo'shadi. Report: list of dict.

    Qaytaradi: [{order, product_id, product_name, warehouse_id,
                 expected_net, actual_net, compensation, status}, ...]
    """
    report = []
    for number in TARGET_ORDERS:
        order = db.query(Order).filter(Order.number == number).first()
        if not order:
            report.append({
                "order": number, "product_id": None, "product_name": "—",
                "warehouse_id": None, "expected_net": 0.0, "actual_net": 0.0,
                "compensation": 0.0, "status": "MISSING(order topilmadi)",
            })
            continue

        # Order'ning Sale movementlaridagi unikal (product, warehouse) juftliklar
        pairs = db.query(
            StockMovement.product_id, StockMovement.warehouse_id
        ).filter(
            StockMovement.document_type == "Sale",
            StockMovement.document_id == order.id,
        ).distinct().all()

        for pid, wh in pairs:
            prod = db.query(Product).filter(Product.id == pid).first()
            pname = prod.name if prod else "—"

            qty_sum = db.query(OrderItem.quantity).filter(
                OrderItem.order_id == order.id,
                OrderItem.product_id == pid,
            ).all()
            expected_net = -1.0 * sum(float(q[0] or 0) for q in qty_sum)

            actual_net = db.query(StockMovement.quantity_change).filter(
                StockMovement.document_type == "Sale",
                StockMovement.document_id == order.id,
                StockMovement.product_id == pid,
                StockMovement.warehouse_id == wh,
            ).all()
            actual_net = sum(float(c[0] or 0) for c in actual_net)

            # Idempotency: DBLFIX marker allaqachon qo'yilganmi
            already = db.query(StockMovement.id).filter(
                StockMovement.document_type == "Sale",
                StockMovement.document_id == order.id,
                StockMovement.product_id == pid,
                StockMovement.warehouse_id == wh,
                StockMovement.operation_type == "sale_revert",
                StockMovement.note.like(f"%{DBLFIX_MARKER}%"),
            ).first()
            if already:
                report.append({
                    "order": order.number, "product_id": pid,
                    "product_name": pname, "warehouse_id": wh,
                    "expected_net": expected_net, "actual_net": actual_net,
                    "compensation": 0.0, "status": "ALREADY_FIXED",
                })
                continue

            # Sanity: faqat AYNAN 2x (toza double) holatini tuzatamiz
            if not (expected_net < 0 and abs(actual_net - 2 * expected_net) < 1e-6):
                report.append({
                    "order": order.number, "product_id": pid,
                    "product_name": pname, "warehouse_id": wh,
                    "expected_net": expected_net, "actual_net": actual_net,
                    "compensation": 0.0,
                    "status": f"SKIP(pattern≠2x: net={actual_net:g})",
                })
                continue

            compensation = expected_net - actual_net  # musbat = +ortiqcha
            status = "WILL_FIX"
            if apply:
                create_stock_movement(
                    db,
                    warehouse_id=wh,
                    product_id=pid,
                    quantity_change=compensation,
                    operation_type="sale_revert",
                    document_type="Sale",
                    document_id=order.id,
                    document_number=order.number,
                    user_id=None,
                    note=DBLFIX_NOTE,
                    created_at=datetime.now(),
                )
                status = "FIXED"

            report.append({
                "order": order.number, "product_id": pid,
                "product_name": pname, "warehouse_id": wh,
                "expected_net": expected_net, "actual_net": actual_net,
                "compensation": compensation, "status": status,
            })

    if apply:
        db.commit()
    return report


def main():
    args = [a for a in sys.argv[1:]]
    apply = "--apply" in args
    args = [a for a in args if a != "--apply"]
    db_path = args[0] if args else str(
        Path(__file__).resolve().parent.parent / "totli_holva.db"
    )

    if not Path(db_path).exists():
        print(f"XATO: DB topilmadi: {db_path}")
        sys.exit(1)

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///" + db_path)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        report = run(db, apply=apply)

        print(f"\nDB: {db_path}   rejim: {'APPLY' if apply else 'DRY-RUN'}\n")
        hdr = (f"{'order':<18} {'prod':<28} {'wh':>3} "
               f"{'expected':>10} {'actual':>10} {'+komp':>9} {'status':<26} "
               f"{'stock hozir':>12} {'stock keyin':>12}")
        print(hdr)
        print("-" * len(hdr))

        n_fix = 0
        total_returned = 0.0
        n_already = 0
        n_skip = 0
        for r in report:
            st = r["status"]
            if st in ("WILL_FIX", "FIXED"):
                n_fix += 1
                total_returned += r["compensation"]
            elif st == "ALREADY_FIXED":
                n_already += 1
            elif st.startswith("SKIP") or st.startswith("MISSING"):
                n_skip += 1

            cur = "—"
            proj = "—"
            if r["product_id"] is not None and r["warehouse_id"] is not None:
                srow = db.query(Stock.quantity).filter(
                    Stock.warehouse_id == r["warehouse_id"],
                    Stock.product_id == r["product_id"],
                ).first()
                cur_q = float(srow[0] or 0) if srow else 0.0
                cur = f"{cur_q:g}"
                # apply bo'lsa Stock allaqachon yangilangan; DRY bo'lsa proyeksiya
                if st == "WILL_FIX":
                    proj = f"{cur_q + r['compensation']:g}"
                else:
                    proj = f"{cur_q:g}"

            pname = (r["product_name"] or "—")[:26]
            pcell = f"{r['product_id']}:{pname}" if r["product_id"] else "—"
            print(
                f"{r['order']:<18} {pcell:<28} "
                f"{(r['warehouse_id'] if r['warehouse_id'] is not None else '—'):>3} "
                f"{r['expected_net']:>10g} {r['actual_net']:>10g} "
                f"{r['compensation']:>9g} {st:<26} {cur:>12} {proj:>12}"
            )

        print(
            f"\nTuzatiladigan: {n_fix} harakat | "
            f"jami qaytariladigan dona: {total_returned:g} | "
            f"ALREADY_FIXED: {n_already} | SKIP: {n_skip}"
        )
        if not apply:
            print("DRY-RUN — yozilmadi. --apply bilan qo'llang.")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    main()
