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


def test_extract_uses_safe_tools_not_dangerous(tmp_path):
    """XAVFSIZLIK regressiya: prompt injection himoyasi buzilmasligi kerak.

    - `--dangerously-skip-permissions` ISHLATILMAYDI (confused-deputy).
    - `--allowedTools Read` bor, Bash/Write/Edit disallow.
    - Prompt args'da EMAS, stdin (input=) orqali — variadic flag yutmasligi
      uchun, va prompt matni argument sifatida oqib chiqmasligi uchun.
    """
    img = tmp_path / "doc.jpg"
    img.write_bytes(b"fake")
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs
        return MagicMock(
            returncode=0,
            stdout=b'{"hujjat_turi":"chek","qatorlar":[],"jami_summa":0}',
            stderr=b"",
        )

    with patch("app.services.ocr_service._sp.run", side_effect=fake_run):
        from app.services.ocr_service import extract_from_image
        extract_from_image(str(img))

    args = captured["args"]
    assert "--dangerously-skip-permissions" not in args
    assert "--allowedTools" in args
    assert "Read" in args
    assert "Bash" in args  # disallowedTools ichida
    # Prompt argument sifatida uzatilmaydi — stdin orqali keladi
    assert "input" in captured["kwargs"]
    assert b"Read tool" in captured["kwargs"]["input"]
    # Prompt matni (masalan "moliyaviy") hech bir argda bo'lmasligi kerak
    assert not any("moliyaviy" in str(a) for a in args)
