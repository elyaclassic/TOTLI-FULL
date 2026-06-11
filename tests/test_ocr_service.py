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


from unittest.mock import patch, MagicMock


def test_extract_from_image_success(tmp_path):
    img = tmp_path / "doc.jpg"
    img.write_bytes(b"\xff\xd8\xff fake jpeg")

    fake_cli_json = '{"result": "{\\"hujjat_turi\\":\\"chek\\",\\"qatorlar\\":[],\\"jami_summa\\":0}"}'
    fake = MagicMock(returncode=0, stdout=fake_cli_json.encode(), stderr=b"")

    with patch("app.services.ocr_service._sp.run", return_value=fake):
        from app.services.ocr_service import extract_from_image
        r = extract_from_image(str(img))
    assert r["hujjat_turi"] == "chek"


def test_extract_from_image_cli_fail(tmp_path):
    img = tmp_path / "doc.jpg"
    img.write_bytes(b"fake")
    fake = MagicMock(returncode=1, stdout=b"", stderr=b"some error")
    with patch("app.services.ocr_service._sp.run", return_value=fake):
        from app.services.ocr_service import extract_from_image, OcrCliError
        with pytest.raises(OcrCliError):
            extract_from_image(str(img))
