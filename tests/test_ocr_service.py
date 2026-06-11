import pytest
from app.services.ocr_service import parse_ocr_json, OcrParseError


def test_parse_clean_json():
    raw = '{"hujjat_turi":"chek","ishonch":"yuqori","sana":"2026-06-11",' \
          '"taminotchi":null,"valyuta":"UZS","tolov_turi":"naqd",' \
          '"qatorlar":[{"nomi":"Shakar","miqdor":50,"birlik":"kg","narx":12000,"summa":600000}],' \
          '"jami_summa":600000,"ogohlantirish":null}'
    r = parse_ocr_json(raw)
    assert r["hujjat_turi"] == "chek"
    assert r["valyuta"] == "UZS"
    assert r["qatorlar"][0]["miqdor"] == 50
    assert r["jami_summa"] == 600000


def test_parse_json_with_markdown_fence():
    raw = 'Mana natija:\n```json\n{"hujjat_turi":"nomalum","ishonch":"past",' \
          '"qatorlar":[],"jami_summa":0}\n```\nUmid qilaman foydali.'
    r = parse_ocr_json(raw)
    assert r["hujjat_turi"] == "nomalum"
    assert r["qatorlar"] == []


def test_parse_fills_defaults():
    raw = '{"hujjat_turi":"chek","qatorlar":[]}'
    r = parse_ocr_json(raw)
    assert r["ishonch"] == "past"
    assert r["valyuta"] == "UZS"
    assert r["tolov_turi"] == "nomalum"
    assert r["jami_summa"] == 0


def test_parse_coerces_numbers():
    raw = '{"hujjat_turi":"chek","qatorlar":[{"nomi":"X","miqdor":"5","birlik":"kg","narx":"1000","summa":"5000"}],"jami_summa":"5000"}'
    r = parse_ocr_json(raw)
    assert r["qatorlar"][0]["miqdor"] == 5.0
    assert r["jami_summa"] == 5000.0


def test_parse_invalid_raises():
    with pytest.raises(OcrParseError):
        parse_ocr_json("bu umuman JSON emas, hech qanday qavs yo'q")
