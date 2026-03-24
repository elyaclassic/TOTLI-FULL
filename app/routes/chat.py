import json
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func

from app.core import templates
from app.deps import get_current_user, require_auth
from app.models.database import get_db, User, ChatThread, ChatParticipant, ChatMessage, ChatTelegramLink
from app.utils.auth import get_user_from_token

router = APIRouter(prefix="/chat", tags=["chat"])


def _norm_pair(a: int, b: int):
    return (a, b) if a < b else (b, a)


def _require_user(current_user: Optional[User]) -> User:
    if not current_user:
        raise HTTPException(status_code=401, detail="Login talab qilindi")
    return current_user


def _thread_title(db: Session, t: ChatThread, me_id: int) -> str:
    if t.type == "support":
        su = t.support_user
        if su:
            return f"Support: {su.full_name or su.username}"
        return "Support"
    if t.type == "group":
        return t.name or "Guruh"
    # direct
    other_id = t.user2_id if t.user1_id == me_id else t.user1_id
    other = db.query(User).filter(User.id == other_id).first() if other_id else None
    return other.full_name or other.username if other else "Chat"


def _get_or_create_direct_thread(db: Session, me: User, other_id: int) -> ChatThread:
    a, b = _norm_pair(me.id, other_id)
    t = (
        db.query(ChatThread)
        .filter(ChatThread.type == "direct", ChatThread.user1_id == a, ChatThread.user2_id == b)
        .first()
    )
    if t:
        return t
    t = ChatThread(type="direct", user1_id=a, user2_id=b, created_by_id=me.id)
    db.add(t)
    db.commit()
    db.refresh(t)
    db.add(ChatParticipant(thread_id=t.id, user_id=a, role="member", last_read_at=datetime.now(), unread_count=0))
    db.add(ChatParticipant(thread_id=t.id, user_id=b, role="member", last_read_at=None, unread_count=0))
    db.commit()
    return t


def _get_or_create_support_thread(db: Session, user_id: int, created_by_id: Optional[int] = None) -> ChatThread:
    t = db.query(ChatThread).filter(ChatThread.type == "support", ChatThread.support_user_id == user_id).first()
    if t:
        return t
    t = ChatThread(type="support", support_user_id=user_id, created_by_id=created_by_id)
    db.add(t)
    db.commit()
    db.refresh(t)
    # user participant
    db.add(ChatParticipant(thread_id=t.id, user_id=user_id, role="member", last_read_at=datetime.now(), unread_count=0))
    # adminlar participant: barcha adminlar ko'rishi uchun
    admins = db.query(User).filter(User.role == "admin", User.is_active == True).all()
    for a in admins:
        db.add(ChatParticipant(thread_id=t.id, user_id=a.id, role="admin", last_read_at=None, unread_count=0))
    db.commit()
    return t


def _is_participant(db: Session, thread_id: int, user_id: int) -> bool:
    return (
        db.query(ChatParticipant)
        .filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == user_id)
        .first()
        is not None
    )


def _bump_unread_for_others(db: Session, thread_id: int, sender_id: int):
    parts = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id).all()
    for p in parts:
        if p.user_id == sender_id:
            continue
        p.unread_count = int(p.unread_count or 0) + 1
    db.commit()


def _mark_thread_read(db: Session, thread_id: int, user_id: int):
    p = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == user_id).first()
    if not p:
        return
    p.unread_count = 0
    p.last_read_at = datetime.now()
    db.commit()


def _total_unread(db: Session, user_id: int) -> int:
    rows = db.query(ChatParticipant).filter(ChatParticipant.user_id == user_id).all()
    return int(sum(int(r.unread_count or 0) for r in rows))


class _ConnHub:
    def __init__(self):
        self.by_thread = {}  # thread_id -> set(ws)

    async def connect(self, thread_id: int, ws: WebSocket):
        await ws.accept()
        self.by_thread.setdefault(thread_id, set()).add(ws)

    def disconnect(self, thread_id: int, ws: WebSocket):
        try:
            self.by_thread.get(thread_id, set()).discard(ws)
        except Exception:
            pass

    async def broadcast(self, thread_id: int, payload: dict):
        dead = []
        for ws in list(self.by_thread.get(thread_id, set())):
            try:
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(thread_id, ws)


hub = _ConnHub()


@router.get("", response_class=HTMLResponse)
async def chat_home(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    parts = (
        db.query(ChatParticipant)
        .filter(ChatParticipant.user_id == me.id)
        .order_by(ChatParticipant.id.desc())
        .all()
    )
    thread_ids = [p.thread_id for p in parts]
    threads = db.query(ChatThread).filter(ChatThread.id.in_(thread_ids)).all() if thread_ids else []
    # index uchun title/unread/last message
    items = []
    for p in parts:
        t = next((x for x in threads if x.id == p.thread_id), None)
        if not t:
            continue
        last = (
            db.query(ChatMessage)
            .filter(ChatMessage.thread_id == t.id)
            .order_by(ChatMessage.created_at.desc())
            .first()
        )
        items.append({
            "thread": t,
            "title": _thread_title(db, t, me.id),
            "unread": int(p.unread_count or 0),
            "last": last,
        })
    # user list for creating direct chats
    users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()
    return templates.TemplateResponse("chat/index.html", {
        "request": request,
        "current_user": me,
        "page_title": "Chat",
        "items": items,
        "users": users,
        "unread_total": _total_unread(db, me.id),
    })


@router.post("/direct")
async def chat_create_direct(
    other_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    if int(other_id) == me.id:
        return RedirectResponse(url="/chat", status_code=303)
    other = db.query(User).filter(User.id == int(other_id), User.is_active == True).first()
    if not other:
        return RedirectResponse(url="/chat", status_code=303)
    t = _get_or_create_direct_thread(db, me, other.id)
    return RedirectResponse(url=f"/chat/thread/{t.id}", status_code=303)


@router.get("/support", response_class=HTMLResponse)
async def chat_support_entry(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    if (me.role or "").lower() == "admin":
        # admin: support threadlar ro'yxati
        threads = db.query(ChatThread).filter(ChatThread.type == "support").order_by(ChatThread.id.desc()).all()
        items = []
        for t in threads:
            p = db.query(ChatParticipant).filter(ChatParticipant.thread_id == t.id, ChatParticipant.user_id == me.id).first()
            last = db.query(ChatMessage).filter(ChatMessage.thread_id == t.id).order_by(ChatMessage.created_at.desc()).first()
            items.append({
                "thread": t,
                "title": _thread_title(db, t, me.id),
                "unread": int((p.unread_count if p else 0) or 0),
                "last": last,
            })
        return templates.TemplateResponse("chat/support_admin.html", {
            "request": request,
            "current_user": me,
            "page_title": "Support chat",
            "items": items,
            "unread_total": _total_unread(db, me.id),
        })
    # user: o'z support threadiga kiradi
    t = _get_or_create_support_thread(db, me.id, created_by_id=me.id)
    return RedirectResponse(url=f"/chat/thread/{t.id}", status_code=303)


@router.get("/thread/{thread_id}", response_class=HTMLResponse)
async def chat_thread_page(
    thread_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    if not _is_participant(db, thread_id, me.id):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    t = db.query(ChatThread).filter(ChatThread.id == thread_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Topilmadi")
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
        .limit(200)
        .all()
    )
    _mark_thread_read(db, thread_id, me.id)
    return templates.TemplateResponse("chat/thread.html", {
        "request": request,
        "current_user": me,
        "page_title": "Chat",
        "thread": t,
        "title": _thread_title(db, t, me.id),
        "messages": msgs,
        "unread_total": _total_unread(db, me.id),
    })


@router.get("/api/unread-count")
async def chat_unread_count(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    return {"unread": _total_unread(db, me.id)}


@router.post("/api/read")
async def chat_mark_read(
    thread_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    if not _is_participant(db, int(thread_id), me.id):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    _mark_thread_read(db, int(thread_id), me.id)
    return {"ok": True, "unread": _total_unread(db, me.id)}


@router.post("/api/send")
async def chat_send_message(
    thread_id: int = Form(...),
    body: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    tid = int(thread_id)
    if not _is_participant(db, tid, me.id):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    text = (body or "").strip()
    if not text:
        return {"ok": False}
    msg = ChatMessage(thread_id=tid, sender_id=me.id, body=text, created_at=datetime.now())
    db.add(msg)
    db.commit()
    db.refresh(msg)
    _bump_unread_for_others(db, tid, me.id)
    sender = db.query(User).filter(User.id == msg.sender_id).first()
    await hub.broadcast(tid, {
        "type": "message",
        "thread_id": tid,
        "message": {
            "id": msg.id,
            "sender_id": msg.sender_id,
            "sender_name": (sender.full_name or sender.username) if sender else "",
            "body": msg.body,
            "created_at": msg.created_at.isoformat(),
        },
    })
    # Telegram ga relay
    try:
        from app.utils.telegram_bot import relay_to_telegram
        sender_name = (sender.full_name or sender.username) if sender else "Noma'lum"
        await relay_to_telegram(tid, sender_name, text)
    except Exception:
        pass
    return {"ok": True}


@router.post("/group/create")
async def chat_create_group(
    request: Request,
    group_name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    name = (group_name or "").strip()
    if not name:
        return RedirectResponse(url="/chat", status_code=303)

    # form dan member_ids olish
    form = await request.form()
    member_ids = form.getlist("member_ids")
    member_ids = [int(x) for x in member_ids if str(x).isdigit() and int(x) != me.id]

    if not member_ids:
        return RedirectResponse(url="/chat", status_code=303)

    t = ChatThread(type="group", name=name, created_by_id=me.id)
    db.add(t)
    db.commit()
    db.refresh(t)

    # yaratuvchini admin sifatida qo'shish
    db.add(ChatParticipant(thread_id=t.id, user_id=me.id, role="admin", last_read_at=datetime.now(), unread_count=0))
    # a'zolarni qo'shish
    for uid in member_ids:
        u = db.query(User).filter(User.id == uid, User.is_active == True).first()
        if u:
            db.add(ChatParticipant(thread_id=t.id, user_id=u.id, role="member", last_read_at=None, unread_count=0))
    db.commit()
    return RedirectResponse(url=f"/chat/thread/{t.id}", status_code=303)


@router.get("/group/{thread_id}/info", response_class=HTMLResponse)
async def chat_group_info(
    thread_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    t = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.type == "group").first()
    if not t:
        raise HTTPException(status_code=404, detail="Guruh topilmadi")
    if not _is_participant(db, thread_id, me.id):
        raise HTTPException(status_code=403, detail="Ruxsat yo'q")
    participants = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id).all()
    members = []
    for p in participants:
        u = db.query(User).filter(User.id == p.user_id).first()
        if u:
            members.append({"user": u, "role": p.role})
    my_role = next((p.role for p in participants if p.user_id == me.id), "member")
    all_users = db.query(User).filter(User.is_active == True).order_by(User.full_name).all()
    tg_links = db.query(ChatTelegramLink).filter(
        ChatTelegramLink.thread_id == thread_id,
        ChatTelegramLink.is_active == True,
    ).all()
    return templates.TemplateResponse("chat/group_info.html", {
        "request": request,
        "current_user": me,
        "page_title": t.name or "Guruh",
        "thread": t,
        "members": members,
        "my_role": my_role,
        "all_users": all_users,
        "tg_links": tg_links,
        "unread_total": _total_unread(db, me.id),
    })


@router.post("/group/{thread_id}/add-member")
async def chat_group_add_member(
    thread_id: int,
    user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    t = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.type == "group").first()
    if not t:
        raise HTTPException(status_code=404)
    my_part = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == me.id).first()
    if not my_part or my_part.role != "admin":
        raise HTTPException(status_code=403, detail="Faqat admin a'zo qo'sha oladi")
    if not _is_participant(db, thread_id, int(user_id)):
        u = db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
        if u:
            db.add(ChatParticipant(thread_id=thread_id, user_id=u.id, role="member", last_read_at=None, unread_count=0))
            db.commit()
    return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)


@router.post("/group/{thread_id}/remove-member")
async def chat_group_remove_member(
    thread_id: int,
    user_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    t = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.type == "group").first()
    if not t:
        raise HTTPException(status_code=404)
    my_part = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == me.id).first()
    if not my_part or my_part.role != "admin":
        raise HTTPException(status_code=403, detail="Faqat admin a'zoni o'chira oladi")
    if int(user_id) == me.id:
        return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)
    p = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == int(user_id)).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)


@router.post("/group/{thread_id}/rename")
async def chat_group_rename(
    thread_id: int,
    group_name: str = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    t = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.type == "group").first()
    if not t:
        raise HTTPException(status_code=404)
    my_part = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == me.id).first()
    if not my_part or my_part.role != "admin":
        raise HTTPException(status_code=403, detail="Faqat admin nomini o'zgartira oladi")
    name = (group_name or "").strip()
    if name:
        t.name = name
        db.commit()
    return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)


@router.post("/group/{thread_id}/add-telegram")
async def chat_group_add_telegram(
    thread_id: int,
    telegram_id: str = Form(...),
    telegram_name: str = Form(""),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    t = db.query(ChatThread).filter(ChatThread.id == thread_id, ChatThread.type == "group").first()
    if not t:
        raise HTTPException(status_code=404)
    my_part = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == me.id).first()
    if not my_part or my_part.role != "admin":
        raise HTTPException(status_code=403, detail="Faqat admin Telegram foydalanuvchi qo'sha oladi")

    tg_id = (telegram_id or "").strip()
    if not tg_id:
        return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)

    # Mavjud linkni tekshirish
    existing = db.query(ChatTelegramLink).filter(
        ChatTelegramLink.thread_id == thread_id,
        ChatTelegramLink.telegram_chat_id == tg_id,
    ).first()
    if existing:
        existing.is_active = True
        if telegram_name.strip():
            existing.telegram_full_name = telegram_name.strip()
        db.commit()
    else:
        link = ChatTelegramLink(
            thread_id=thread_id,
            telegram_chat_id=tg_id,
            telegram_full_name=telegram_name.strip() or None,
            is_active=True,
        )
        db.add(link)
        db.commit()

    # Telegram foydalanuvchiga xabar yuborish
    try:
        from app.utils.telegram_bot import send_telegram_message
        await send_telegram_message(tg_id,
            f"Siz <b>{t.name or 'Guruh'}</b> chatiga qo'shildingiz!\n"
            "Endi shu yerda xabar yozsangiz, chatga tushadi."
        )
    except Exception:
        pass

    return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)


@router.post("/group/{thread_id}/remove-telegram")
async def chat_group_remove_telegram(
    thread_id: int,
    link_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    me = _require_user(current_user)
    my_part = db.query(ChatParticipant).filter(ChatParticipant.thread_id == thread_id, ChatParticipant.user_id == me.id).first()
    if not my_part or my_part.role != "admin":
        raise HTTPException(status_code=403)
    link = db.query(ChatTelegramLink).filter(ChatTelegramLink.id == int(link_id), ChatTelegramLink.thread_id == thread_id).first()
    if link:
        db.delete(link)
        db.commit()
    return RedirectResponse(url=f"/chat/group/{thread_id}/info", status_code=303)


@router.websocket("/ws/{thread_id}")
async def chat_ws(thread_id: int, websocket: WebSocket):
    # cookie'dan auth
    token = websocket.cookies.get("session_token")
    if not token:
        await websocket.close(code=4401)
        return
    data = get_user_from_token(token)
    if not data or not data.get("user_id"):
        await websocket.close(code=4401)
        return
    user_id = int(data["user_id"])

    # db session (websocket uchun qo'lda)
    db = next(get_db())
    try:
        if not _is_participant(db, int(thread_id), user_id):
            await websocket.close(code=4403)
            return
        await hub.connect(int(thread_id), websocket)
        await websocket.send_text(json.dumps({"type": "hello", "thread_id": int(thread_id)}, ensure_ascii=False))
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {}
            if payload.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
                continue
            if payload.get("type") == "send":
                body = (payload.get("body") or "").strip()
                if not body:
                    continue
                msg = ChatMessage(thread_id=int(thread_id), sender_id=user_id, body=body, created_at=datetime.now())
                db.add(msg)
                db.commit()
                db.refresh(msg)
                _bump_unread_for_others(db, int(thread_id), user_id)
                ws_sender = db.query(User).filter(User.id == user_id).first()
                await hub.broadcast(int(thread_id), {
                    "type": "message",
                    "thread_id": int(thread_id),
                    "message": {
                        "id": msg.id,
                        "sender_id": msg.sender_id,
                        "sender_name": (ws_sender.full_name or ws_sender.username) if ws_sender else "",
                        "body": msg.body,
                        "created_at": msg.created_at.isoformat(),
                    },
                })
                # Telegram ga relay
                try:
                    from app.utils.telegram_bot import relay_to_telegram
                    sn = (ws_sender.full_name or ws_sender.username) if ws_sender else "Noma'lum"
                    await relay_to_telegram(int(thread_id), sn, body)
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(int(thread_id), websocket)
        try:
            db.close()
        except Exception:
            pass

# reload trigger
