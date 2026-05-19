from app.models.database import Partner, Agent, PartnerAgent


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
