"""Faza 2-B: admin/manager override helper testlari."""


class _U:
    def __init__(self, role, username="u"):
        self.role = role
        self.username = username


def test_override_admin_with_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("admin"), 1) is True


def test_override_manager_with_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("manager"), 1) is True


def test_override_rahbar_with_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("rahbar"), 1) is True
    assert reservation_override(_U("raxbar"), 1) is True


def test_override_seller_denied():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("sotuvchi"), 1) is False


def test_override_no_force():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(_U("admin"), 0) is False


def test_override_none_user():
    from app.services.stock_reservation import reservation_override
    assert reservation_override(None, 1) is False
