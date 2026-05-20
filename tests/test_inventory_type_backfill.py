"""Backfill classify() funksiyasi unit testlari."""
import importlib.util, pathlib

# Skriptni modul sifatida yuklash
_path = pathlib.Path(__file__).parent.parent / "scripts" / "backfill_inventory_type.py"
spec = importlib.util.spec_from_file_location("backfill_inventory_type", _path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
classify = mod.classify


def test_stock_entry_from_note():
    assert classify(["Tovar qoldiqlari: INV-X"], "INV-X") == "stock_entry"


def test_qoldiq_kiritish_from_note():
    assert classify(["Qoldiq kiritish: QLD-X"], "QLD-X") == "stock_entry"


def test_inventory_from_note():
    assert classify(["Inventarizatsiya: INV-X"], "INV-X") == "inventory"


def test_qld_prefix_when_no_notes():
    assert classify([], "QLD-20260507-0001") == "stock_entry"


def test_default_inventory():
    assert classify([], "INV-PENDING-99") == "inventory"
    assert classify([], None) == "inventory"


def test_none_in_notes_handled():
    assert classify([None, "Inventarizatsiya: X"], "X") == "inventory"
