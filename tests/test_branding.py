"""Universal logo (branding) testlari."""
import os


def test_resolve_branding_defaults_when_empty(db):
    """AppSetting bo'sh -> standart logo yo'llari qaytadi."""
    from app.services.branding_service import resolve_branding, DEFAULTS

    result = resolve_branding(db)

    assert result["logo_main"] == DEFAULTS["logo_main"]
    assert result["logo_circle"] == DEFAULTS["logo_circle"]


def test_resolve_branding_ignores_missing_file(db):
    """AppSetting'da yozuv bor, lekin fayl jismonan yo'q -> standartga qaytadi."""
    from app.models.database import AppSetting
    from app.services.branding_service import resolve_branding, DEFAULTS

    db.add(AppSetting(key="logo_main", value="nonexistent_file_xyz.png"))
    db.commit()

    result = resolve_branding(db)

    assert result["logo_main"] == DEFAULTS["logo_main"]


def test_resolve_branding_uses_existing_file(db, tmp_path, monkeypatch):
    """AppSetting'da yozuv bor va fayl mavjud -> yangi yo'l qaytadi."""
    from app.models.database import AppSetting
    from app.services import branding_service

    fake_dir = tmp_path / "branding"
    fake_dir.mkdir()
    (fake_dir / "logo_main_123.png").write_bytes(b"PNGDATA")
    monkeypatch.setattr(branding_service, "BRANDING_DIR", str(fake_dir))

    db.add(AppSetting(key="logo_main", value="logo_main_123.png"))
    db.commit()

    result = branding_service.resolve_branding(db)

    assert result["logo_main"] == "/static/images/branding/logo_main_123.png"


def test_cache_invalidation(monkeypatch):
    """Cache to'ldiriladi, invalidate'dan keyin qayta yuklanadi."""
    from app.services import branding_service

    calls = {"n": 0}

    def fake_load():
        calls["n"] += 1
        return {"logo_main": f"/x{calls['n']}.png", "logo_circle": "/c.png"}

    monkeypatch.setattr(branding_service, "_load_branding", fake_load)
    branding_service.invalidate_branding_cache()

    first = branding_service.get_branding_cached()
    second = branding_service.get_branding_cached()
    assert first == second           # cache — qayta yuklanmaydi
    assert calls["n"] == 1

    branding_service.invalidate_branding_cache()
    third = branding_service.get_branding_cached()
    assert calls["n"] == 2           # invalidate'dan keyin qayta yuklandi
    assert third != first


def test_save_branding_image(tmp_path, monkeypatch):
    """save_branding_image faylni timestamp nomi bilan saqlaydi."""
    from app.services import branding_service

    fake_dir = tmp_path / "branding"
    monkeypatch.setattr(branding_service, "BRANDING_DIR", str(fake_dir))

    fname = branding_service.save_branding_image("logo_main", b"PNGDATA", "png")

    assert fname.startswith("logo_main_")
    assert fname.endswith(".png")
    assert (fake_dir / fname).is_file()


def test_upload_requires_admin(client, db, agent_user):
    """Admin bo'lmagan foydalanuvchi yuklay olmaydi."""
    from app.deps import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: agent_user
    try:
        resp = client.post(
            "/admin/branding/upload",
            data={"slot": "logo_main"},
            files={"image": ("x.png", b"x", "image/png")},
            follow_redirects=False,
        )
        assert resp.status_code in (302, 303, 401, 403)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
