"""
Agentlar — ro'yxat, qo'shish, tafsilot.
"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, Agent, AgentLocation, Visit

router = APIRouter(tags=["agents"])


@router.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request, db: Session = Depends(get_db)):
    agents = db.query(Agent).all()
    today = datetime.now().date()
    for agent in agents:
        agent.last_location = (
            db.query(AgentLocation)
            .filter(AgentLocation.agent_id == agent.id)
            .order_by(AgentLocation.recorded_at.desc())
            .first()
        )
        agent.today_visits = (
            db.query(Visit).filter(Visit.agent_id == agent.id, Visit.visit_date >= today).count()
        )
    return templates.TemplateResponse("agents/list.html", {
        "request": request,
        "agents": agents,
        "page_title": "Agentlar",
    })


@router.post("/agents/add")
async def agent_add(
    request: Request,
    full_name: str = Form(...),
    phone: str = Form(""),
    region: str = Form(""),
    telegram_id: str = Form(""),
    db: Session = Depends(get_db),
):
    last_agent = db.query(Agent).order_by(Agent.id.desc()).first()
    code = f"AG{str((last_agent.id if last_agent else 0) + 1).zfill(3)}"
    agent = Agent(
        code=code,
        full_name=full_name,
        phone=phone,
        region=region,
        telegram_id=telegram_id,
        is_active=True,
    )
    db.add(agent)
    db.commit()
    return RedirectResponse(url="/agents", status_code=303)


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
async def agent_detail(
    request: Request,
    agent_id: int,
    db: Session = Depends(get_db),
):
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent topilmadi")
    locations = (
        db.query(AgentLocation)
        .filter(AgentLocation.agent_id == agent_id)
        .order_by(AgentLocation.recorded_at.desc())
        .limit(50)
        .all()
    )
    visits = (
        db.query(Visit)
        .filter(Visit.agent_id == agent_id)
        .order_by(Visit.visit_date.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse("agents/detail.html", {
        "request": request,
        "agent": agent,
        "locations": locations,
        "visits": visits,
        "page_title": f"Agent: {agent.full_name}",
    })
