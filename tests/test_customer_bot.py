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


def _mk_partner(db, name, phone, phone2=None, active=True):
    from app.models.database import Partner
    p = Partner(name=name, phone=phone, phone2=phone2, is_active=active, balance=0)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def test_find_matching_partner_diff_formats(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Gellet Market", "+998902924002")
    _mk_partner(db, "olmos market", "998910558888")
    # Telegram '998902924002' yuboradi -> +998902924002 ga mos
    res = find_matching_partners(db, "998902924002")
    assert len(res) == 1
    assert res[0].name == "Gellet Market"


def test_find_matching_partner_phone2(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Benazir", "+998938000458", phone2="+998331777727")
    res = find_matching_partners(db, "998331777727")
    assert len(res) == 1
    assert res[0].name == "Benazir"


def test_find_matching_partner_none(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Gellet Market", "+998902924002")
    assert find_matching_partners(db, "998000000000") == []
    assert find_matching_partners(db, "0.....") == []


def test_find_matching_partner_skips_inactive(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Eski", "+998905565959", active=False)
    assert find_matching_partners(db, "998905565959") == []


def test_find_matching_partner_multiple(db):
    from app.bot.customer_bot.registration import find_matching_partners
    _mk_partner(db, "Do'kon A", "+998905565959")
    _mk_partner(db, "Do'kon B", "905565959")
    res = find_matching_partners(db, "998905565959")
    assert len(res) == 2


def test_link_lifecycle(db):
    from app.bot.customer_bot import registration as reg
    p = _mk_partner(db, "Gellet", "+998902924002")

    # mavjud emas
    assert reg.get_link_by_telegram(db, "555") is None

    # pending yaratish
    link = reg.create_pending_link(db, "555", "akbar", "Akbarjon", "902924002")
    assert link.status == "pending"
    assert reg.get_link_by_telegram(db, "555").id == link.id

    # tasdiqlash
    approved = reg.approve_link(db, link.id, p.id, "admin1340")
    assert approved.status == "approved"
    assert approved.partner_id == p.id
    assert approved.approved_at is not None
    assert approved.approved_by == "admin1340"


def test_link_reject(db):
    from app.bot.customer_bot import registration as reg
    link = reg.create_pending_link(db, "777", None, "Test", "900000000")
    rejected = reg.reject_link(db, link.id, "admin1340")
    assert rejected.status == "rejected"


def test_approved_link_lookup_by_partner(db):
    from app.bot.customer_bot import registration as reg
    p = _mk_partner(db, "Gellet", "+998902924002")
    link = reg.create_pending_link(db, "555", "a", "A", "902924002")
    reg.approve_link(db, link.id, p.id, "admin")
    ids = reg.approved_telegram_ids_for_partner(db, p.id)
    assert ids == ["555"]
