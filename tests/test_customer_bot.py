from datetime import datetime


def test_customer_bot_link_create(db):
    from app.models.database import CustomerBotLink
    link = CustomerBotLink(
        telegram_id="111222333",
        telegram_username="akbar",
        telegram_full_name="Akbarjon",
        phone="905565959",
        status="pending",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    assert link.id is not None
    assert link.status == "pending"
    assert link.partner_id is None
    assert link.requested_at is not None


def test_normalize_phone_formats():
    from app.bot.customer_bot.phone import normalize_phone
    # turli format — barchasi oxirgi 9 raqamga keladi
    assert normalize_phone("+998905565959") == "905565959"
    assert normalize_phone("998905565959") == "905565959"
    assert normalize_phone("99899 652 82 60") == "996528260"  # oxirgi 9
    assert normalize_phone("+998 90 556 59 59") == "905565959"


def test_normalize_phone_invalid():
    from app.bot.customer_bot.phone import normalize_phone
    assert normalize_phone("0.....") is None     # 9 raqamdan kam
    assert normalize_phone("") is None
    assert normalize_phone(None) is None
    assert normalize_phone("12345") is None       # 5 raqam
