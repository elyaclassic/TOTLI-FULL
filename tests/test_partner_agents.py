import pytest
from sqlalchemy.exc import IntegrityError

from app.models.database import Partner, Agent, PartnerAgent
from app.services.partner_agents import effective_agent_ids


def test_partner_agent_row_create(db):
    ag = Agent(code="AGX", full_name="Test Agent")
    p = Partner(code="PX", name="Test Partner", type="customer")
    db.add_all([ag, p]); db.flush()
    pa = PartnerAgent(partner_id=p.id, agent_id=ag.id,
                       visit_type="weekly", visit_days="0,2,4", position=1)
    db.add(pa); db.commit()
    rows = db.query(PartnerAgent).filter_by(partner_id=p.id).all()
    assert len(rows) == 1
    assert rows[0].agent_id == ag.id
    assert rows[0].visit_days == "0,2,4"
    assert p.partner_agents[0].agent_id == ag.id


def test_partner_agent_unique(db):
    ag = Agent(code="AGU", full_name="A"); p = Partner(code="PU", name="P", type="customer")
    db.add_all([ag, p]); db.flush()
    db.add(PartnerAgent(partner_id=p.id, agent_id=ag.id, position=1)); db.commit()
    db.add(PartnerAgent(partner_id=p.id, agent_id=ag.id, position=2))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_effective_agent_ids_union(db):
    a1 = Agent(code="A1", full_name="A1"); a2 = Agent(code="A2", full_name="A2")
    a3 = Agent(code="A3", full_name="A3")
    db.add_all([a1, a2, a3]); db.flush()
    p = Partner(code="PE", name="PE", type="customer", agent_id=a1.id)
    db.add(p); db.flush()
    db.add_all([
        PartnerAgent(partner_id=p.id, agent_id=a2.id, position=1),
        PartnerAgent(partner_id=p.id, agent_id=a3.id, position=2),
    ])
    db.commit()
    assert effective_agent_ids(p) == {a1.id, a2.id, a3.id}

    p2 = Partner(code="PE2", name="PE2", type="customer", agent_id=a1.id)
    db.add(p2); db.commit()
    assert effective_agent_ids(p2) == {a1.id}

    p3 = Partner(code="PE3", name="PE3", type="customer", agent_id=None)
    db.add(p3); db.commit()
    assert effective_agent_ids(p3) == set()
