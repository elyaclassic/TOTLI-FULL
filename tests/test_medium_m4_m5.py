"""MEDIUM M4 + M5 fix testlari.

M4: obmen (almashtirish) return qty parent xaridiga clamp qilinadi (xaridan ko'p
    qaytarib bo'lmaydi); parent'da yo'q mahsulot tashlanadi.
M5: bir xil sanada bir xil (ombor,mahsulot)ni qamragan ikkinchi inventarizatsiya
    hujjati baseline'ni buzmasin — overlap aniqlansin.
"""
from datetime import datetime


# ============ M4 ============

class _OI:
    def __init__(self, product_id, quantity, price):
        self.product_id = product_id
        self.quantity = quantity
        self.price = price


class _Parent:
    def __init__(self, items):
        self.items = items


def test_m4_return_qty_clamped_to_parent():
    from app.routes.api_agent_ops import _build_return_lines
    parent = _Parent([_OI(10, 5, 2000), _OI(20, 3, 1500)])

    # 10 ta so'ralgan, lekin parent'da 5 -> 5 ga clamp
    lines = _build_return_lines([{"product_id": 10, "qty": 10}], parent)
    assert lines == [(10, 5, 2000)], f"clamp 5 ga bo'lishi kerak: {lines}"

    # xarid ichida (3 <= 3) -> o'zgarmaydi
    lines2 = _build_return_lines([{"product_id": 20, "qty": 3}], parent)
    assert lines2 == [(20, 3, 1500)]


def test_m4_skips_product_not_in_parent():
    from app.routes.api_agent_ops import _build_return_lines
    parent = _Parent([_OI(10, 5, 2000)])
    # 99 parent'da yo'q -> tashlanadi
    lines = _build_return_lines([{"product_id": 99, "qty": 1}, {"product_id": 10, "qty": 2}], parent)
    assert lines == [(10, 2, 2000)], f"parentsiz mahsulot tashlanishi kerak: {lines}"


def test_m4_invalid_and_zero_skipped():
    from app.routes.api_agent_ops import _build_return_lines
    parent = _Parent([_OI(10, 5, 2000)])
    lines = _build_return_lines([
        {"product_id": 10, "qty": 0},      # 0 -> skip
        {"product_id": 0, "qty": 3},        # pid 0 -> skip
        {"product_id": "x", "qty": 1},      # invalid -> skip
        {"product_id": 10, "quantity": 4},  # 'quantity' kaliti ham qabul qilinadi
    ], parent)
    assert lines == [(10, 4, 2000)]


# ============ M5 ============

def _mk_inv_doc(db, number, date, pairs, status="confirmed"):
    """pairs: [(warehouse_id, product_id, qty), ...]"""
    from app.models.database import StockAdjustmentDoc, StockAdjustmentDocItem
    doc = StockAdjustmentDoc(number=number, date=date, status=status, type="inventory")
    db.add(doc); db.flush()
    for wh, pid, qty in pairs:
        db.add(StockAdjustmentDocItem(doc_id=doc.id, warehouse_id=wh, product_id=pid, quantity=qty))
    db.flush()
    return doc


def test_m5_same_day_overlap_detected(db):
    from app.routes.warehouse import _inventory_same_day_overlap
    d = datetime(2026, 6, 4, 10, 0, 0)
    _mk_inv_doc(db, "INV-A", d, [(1, 100, 50)])           # tasdiqlangan, wh1/prod100
    doc_b = _mk_inv_doc(db, "INV-B", d.replace(hour=15), [(1, 100, 60)], status="confirmed")
    # B ham wh1/prod100 ni qamragan, bir xil kun -> overlap
    assert _inventory_same_day_overlap(db, doc_b) == "INV-A"


def test_m5_different_product_no_overlap(db):
    from app.routes.warehouse import _inventory_same_day_overlap
    d = datetime(2026, 6, 4, 10, 0, 0)
    _mk_inv_doc(db, "INV-A", d, [(1, 100, 50)])
    doc_b = _mk_inv_doc(db, "INV-B", d.replace(hour=15), [(1, 200, 60)])  # boshqa mahsulot
    assert _inventory_same_day_overlap(db, doc_b) is None


def test_m5_different_day_no_overlap(db):
    from app.routes.warehouse import _inventory_same_day_overlap
    _mk_inv_doc(db, "INV-A", datetime(2026, 6, 3, 10, 0, 0), [(1, 100, 50)])
    doc_b = _mk_inv_doc(db, "INV-B", datetime(2026, 6, 4, 10, 0, 0), [(1, 100, 60)])  # ertasi
    assert _inventory_same_day_overlap(db, doc_b) is None


def test_m5_draft_sibling_ignored(db):
    from app.routes.warehouse import _inventory_same_day_overlap
    d = datetime(2026, 6, 4, 10, 0, 0)
    _mk_inv_doc(db, "INV-A", d, [(1, 100, 50)], status="draft")  # draft -> e'tiborga olinmaydi
    doc_b = _mk_inv_doc(db, "INV-B", d.replace(hour=15), [(1, 100, 60)])
    assert _inventory_same_day_overlap(db, doc_b) is None
