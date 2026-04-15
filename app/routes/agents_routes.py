"""
Agentlar — ro'yxat, qo'shish, tafsilot.
"""
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func

from app.core import templates
from app.models.database import (
    get_db,
    Agent,
    AgentCall,
    AgentLocation,
    AgentSms,
    Order,
    User,
    Visit,
)
from app.deps import require_auth, require_admin

router = APIRouter(tags=["agents"])


@router.get("/agents", response_class=HTMLResponse)
async def agents_list(request: Request, db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    agents = db.query(Agent).all()
    today = datetime.now().date()
    agent_ids = [a.id for a in agents]

    # Oxirgi lokatsiya — har agent uchun bitta query (N+1 o'rniga)
    latest_loc_ids = (
        db.query(func.max(AgentLocation.id))
        .filter(AgentLocation.agent_id.in_(agent_ids))
        .group_by(AgentLocation.agent_id)
        .subquery()
    )
    locations = db.query(AgentLocation).filter(AgentLocation.id.in_(latest_loc_ids)).all()
    loc_map = {loc.agent_id: loc for loc in locations}

    # Bugungi vizitlar soni — bitta GROUP BY query
    visits_counts = (
        db.query(Visit.agent_id, func.count(Visit.id).label("cnt"))
        .filter(Visit.agent_id.in_(agent_ids), Visit.visit_date >= today)
        .group_by(Visit.agent_id)
        .all()
    )
    visits_map = {row.agent_id: row.cnt for row in visits_counts}

    for agent in agents:
        agent.last_location = loc_map.get(agent.id)
        agent.today_visits = visits_map.get(agent.id, 0)
    return templates.TemplateResponse("agents/list.html", {
        "request": request,
        "agents": agents,
        "current_user": current_user,
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
    current_user: User = Depends(require_admin),
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


@router.get("/agent", response_class=HTMLResponse)
async def agent_app(request: Request):
    """Mobile agent app — token auth done client-side via localStorage."""
    return templates.TemplateResponse("agents/app.html", {
        "request": request,
        "page_title": "Agent App",
    })


@router.get("/agents/{agent_id}", response_class=HTMLResponse)
async def agent_detail(
    request: Request,
    agent_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth),
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
        .options(joinedload(Visit.partner), joinedload(Visit.photos))
        .filter(Visit.agent_id == agent_id)
        .order_by(Visit.visit_date.desc())
        .limit(30)
        .all()
    )
    orders = (
        db.query(Order)
        .filter(Order.agent_id == agent_id)
        .order_by(Order.id.desc())
        .limit(50)
        .all()
    )
    calls = (
        db.query(AgentCall)
        .filter(AgentCall.agent_id == agent_id)
        .order_by(AgentCall.called_at.desc())
        .limit(50)
        .all()
    )
    sms_list = (
        db.query(AgentSms)
        .filter(AgentSms.agent_id == agent_id)
        .order_by(AgentSms.sent_at.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse("agents/detail.html", {
        "request": request,
        "agent": agent,
        "locations": locations,
        "visits": visits,
        "orders": orders,
        "calls": calls,
        "sms_list": sms_list,
        "current_user": current_user,
        "page_title": f"Agent: {agent.full_name}",
    })
