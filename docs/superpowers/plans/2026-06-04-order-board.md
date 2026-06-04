# Buyurtma holati katta-ekran board — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent/yetkazish buyurtmalarini katta ekranda real-vaqt kanban board'da ko'rsatish (4 ustun), buyurtma yaratilganda/holati o'zgarganda jonli yangilanadi.

**Architecture:** Read-only snapshot API joriy agent buyurtmalarini bosqich bo'yicha guruhlaydi. To'liq-ekran sahifa snapshot'ni yuklaydi, mavjud WebSocket bus (`/ws/dashboard/v2`) ga ulanadi, har "refresh signal" event'da snapshot'ni qayta yuklaydi (debounced) + zaxira poll (30 sek). Status-transition joylariga `publish_event` qo'shiladi.

**Tech Stack:** FastAPI, SQLAlchemy, Jinja2, vanilla JS (WebSocket + fetch), mavjud `realtime_bus`.

**Spec:** `docs/superpowers/specs/2026-06-04-order-board-design.md`

---

## Fayl tuzilishi

- **Create:** `app/services/board_service.py` — `build_board_snapshot(db)` (testlanadigan, sof read-only).
- **Create:** `app/routes/board.py` — `GET /sales/board` (sahifa) + `GET /sales/board/data` (JSON snapshot). Yangi router.
- **Create:** `app/templates/board/order_board.html` — to'liq-ekran board + JS.
- **Create:** `tests/test_board_snapshot.py` — snapshot testlari.
- **Modify:** `main.py` — yangi `board` routerni `include_router`.
- **Modify:** `app/routes/delivery_routes.py`, `app/routes/api_driver_ops.py`, `app/routes/api_agent_ops.py`, `app/services/agent_order_service.py` — status-transition'larga `publish_event("order_board")`.

---

### Task 1: `build_board_snapshot` service (snapshot logikasi)

**Files:**
- Create: `app/services/board_service.py`
- Test: `tests/test_board_snapshot.py`

- [ ] **Step 1: Failing test yozish**

```python
# tests/test_board_snapshot.py
from datetime import datetime, date, timedelta


def test_board_snapshot_groups_by_status(db):
    from app.models.database import Order, OrderItem, Partner, Product
    from app.services.board_service import build_board_snapshot

    p = Partner(name="Elshod Market", balance=0, code="P_B1")
    pr = Product(name="BARGELIK 400gr", is_active=True, sale_price=30000)
    db.add_all([p, pr]); db.flush()
    # Har bosqichdan bittadan agent buyurtma
    for st in ["confirmed", "waiting_production", "out_for_delivery"]:
        o = Order(number=f"AGT-{st}", date=datetime.now(), type="sale", source="agent",
                  partner_id=p.id, total=490000, paid=0, debt=490000, status=st,
                  delivery_date=date.today() + timedelta(days=1))
        db.add(o); db.flush()
        db.add(OrderItem(order_id=o.id, product_id=pr.id, quantity=5, price=30000, total=150000))
    db.commit()

    snap = build_board_snapshot(db)
    assert len(snap["confirmed"]) == 1
    assert len(snap["waiting_production"]) == 1
    assert len(snap["out_for_delivery"]) == 1
    assert snap["confirmed"][0]["partner"] == "Elshod Market"
    assert snap["confirmed"][0]["items_count"] == 1
    assert snap["confirmed"][0]["overdue"] is False  # delivery_date kelajakda


def test_board_snapshot_overdue_flag(db):
    from app.models.database import Order, Partner
    from app.services.board_service import build_board_snapshot
    from datetime import date, timedelta
    p = Partner(name="Kech Market", balance=0, code="P_B2")
    db.add(p); db.flush()
    o = Order(number="AGT-OVD", date=datetime.now(), type="sale", source="agent",
              partner_id=p.id, total=100000, paid=0, debt=100000, status="confirmed",
              delivery_date=date.today() - timedelta(days=1))  # kecha — kechikkan
    db.add(o); db.commit()
    snap = build_board_snapshot(db)
    assert snap["confirmed"][0]["overdue"] is True


def test_board_snapshot_excludes_pos_and_old_delivered(db):
    from app.models.database import Order, Partner
    from app.services.board_service import build_board_snapshot
    p = Partner(name="P", balance=0, code="P_B3")
    db.add(p); db.flush()
    # POS sotuv (source != agent) -> kirmaydi
    db.add(Order(number="S-POS", date=datetime.now(), type="sale", source="web",
                 partner_id=p.id, total=50000, paid=50000, debt=0, status="completed"))
    db.commit()
    snap = build_board_snapshot(db)
    total = sum(len(v) for v in snap.values())
    assert total == 0, "POS/web va eski buyurtmalar board'ga kirmasligi kerak"
```

- [ ] **Step 2: Testni ishga tushirib FAIL ko'rish**

Run: `python -m pytest tests/test_board_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: app.services.board_service`

- [ ] **Step 3: `build_board_snapshot` yozish**

```python
# app/services/board_service.py
"""Buyurtma board snapshot — agent yetkazish buyurtmalarini bosqich bo'yicha guruhlaydi.
Sof read-only. Spec: docs/superpowers/specs/2026-06-04-order-board-design.md"""
from datetime import date, datetime
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session, joinedload

from app.models.database import Order, Delivery, Driver

ACTIVE_STATUSES = ("confirmed", "waiting_production", "out_for_delivery")
COLUMNS = ("confirmed", "waiting_production", "out_for_delivery", "delivered")


def _stage_since(o):
    """Bosqichda turgan boshlanish vaqti (dispatch bo'lsa dispatched_at, aks holda order date)."""
    if o.status == "out_for_delivery" and getattr(o, "dispatched_at", None):
        return o.dispatched_at
    return o.date


def build_board_snapshot(db: Session) -> dict:
    today = date.today()
    # Aktiv agent buyurtmalar (sanadan qat'i nazar) + BUGUN yetkazilganlar
    orders = (
        db.query(Order)
        .options(joinedload(Order.partner), joinedload(Order.items))
        .filter(
            Order.source == "agent",
            Order.type == "sale",
            or_(
                Order.status.in_(ACTIVE_STATUSES),
                and_(
                    Order.status == "delivered",
                    func.date(Order.delivery_date) == today,
                ),
            ),
        )
        .order_by(Order.delivery_date.asc(), Order.id.asc())
        .all()
    )
    # Yo'lda buyurtmalar uchun haydovchi ismi (Delivery -> Driver)
    driver_by_order = {}
    oids = [o.id for o in orders if o.status == "out_for_delivery"]
    if oids:
        for d in (
            db.query(Delivery).options(joinedload(Delivery.driver))
            .filter(Delivery.order_id.in_(oids)).all()
        ):
            if d.driver:
                driver_by_order[d.order_id] = d.driver.full_name or d.driver.code or ""

    cols = {c: [] for c in COLUMNS}
    for o in orders:
        dd = o.delivery_date
        overdue = bool(o.status in ACTIVE_STATUSES and dd and dd <= today)
        card = {
            "id": o.id,
            "number": o.number or "",
            "partner": (o.partner.name if o.partner else "—"),
            "total": float(o.total or 0),
            "items_count": len(o.items or []),
            "status": o.status,
            "delivery_date": dd.isoformat() if dd else None,
            "driver": driver_by_order.get(o.id, ""),
            "overdue": overdue,
            "stage_since": (_stage_since(o).isoformat() if _stage_since(o) else None),
        }
        if o.status in cols:
            cols[o.status].append(card)
    return cols
```

- [ ] **Step 4: Testni ishga tushirib PASS ko'rish**

Run: `python -m pytest tests/test_board_snapshot.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/services/board_service.py tests/test_board_snapshot.py
git commit -m "feat(board): build_board_snapshot service + testlar"
```

---

### Task 2: Board route + snapshot API

**Files:**
- Create: `app/routes/board.py`
- Modify: `main.py` (router include)
- Test: `tests/test_board_snapshot.py` (snapshot API endpoint smoke qo'shiladi)

- [ ] **Step 1: `board.py` route yozish**

```python
# app/routes/board.py
"""Buyurtma holati katta-ekran board — sahifa + snapshot API (admin/menejer)."""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core import templates
from app.models.database import get_db, User
from app.deps import require_auth
from app.services.board_service import build_board_snapshot

router = APIRouter(prefix="/sales", tags=["board"])


@router.get("/board", response_class=HTMLResponse)
async def order_board_page(request: Request, current_user: User = Depends(require_auth)):
    """To'liq-ekran buyurtma board sahifasi."""
    return templates.TemplateResponse("board/order_board.html", {
        "request": request,
        "current_user": current_user,
        "page_title": "Buyurtma board",
    })


@router.get("/board/data", response_class=JSONResponse)
async def order_board_data(db: Session = Depends(get_db), current_user: User = Depends(require_auth)):
    """Joriy snapshot (JSON) — boshlang'ich yuklash + qayta-sinxron uchun."""
    return build_board_snapshot(db)
```

- [ ] **Step 2: `main.py` ga routerni qo'shish**

`main.py` da boshqa `from app.routes import ...` qatorlari yonida (masalan `from app.routes import sales_deliveries as sales_deliveries_routes` dan keyin):

```python
from app.routes import board as board_routes
```

va `app.include_router(...)` bloki ichida (masalan `app.include_router(sales_deliveries_routes.router)` dan keyin):

```python
app.include_router(board_routes.router)
```

- [ ] **Step 3: Route ro'yxatga olinganini test qilish**

```python
# tests/test_board_snapshot.py ga qo'shish
def test_board_routes_registered(db):
    from app.routes.board import router
    paths = [getattr(r, "path", None) for r in router.routes]
    assert "/sales/board" in paths
    assert "/sales/board/data" in paths
```

Run: `python -m pytest tests/test_board_snapshot.py::test_board_routes_registered -v`
Expected: PASS

- [ ] **Step 4: AST + import smoke**

Run: `python -c "import ast; ast.parse(open('app/routes/board.py',encoding='utf-8').read()); ast.parse(open('main.py',encoding='utf-8').read()); print('OK')"`
Expected: OK

- [ ] **Step 5: Commit**

```bash
git add app/routes/board.py main.py tests/test_board_snapshot.py
git commit -m "feat(board): /sales/board sahifa + /sales/board/data API"
```

---

### Task 3: Board sahifa template (HTML + JS)

**Files:**
- Create: `app/templates/board/order_board.html`

- [ ] **Step 1: Template yozish**

To'liq-ekran, qora fon, 4 ustun grid. JS: snapshot yuklaydi → WS `/ws/dashboard/v2` ga ulanadi → har event'da debounced qayta-yuklaydi → 30 sek zaxira poll.

```html
{# app/templates/board/order_board.html #}
<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Buyurtma board — TOTLI HOLVA</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background:#0f1115; color:#e8eaed; font-family: system-ui, sans-serif; height:100vh; overflow:hidden; }
  .board { display:grid; grid-template-columns: repeat(4, 1fr); gap:10px; height:100vh; padding:10px; }
  .col { background:#171a21; border-radius:10px; display:flex; flex-direction:column; overflow:hidden; }
  .col-head { padding:12px; font-size:20px; font-weight:800; text-align:center; border-bottom:2px solid #2a2f3a; letter-spacing:.5px; }
  .col-body { flex:1; overflow-y:auto; padding:8px; }
  .c-confirmed .col-head { color:#4da3ff; }
  .c-waiting_production .col-head { color:#ffb74d; }
  .c-out_for_delivery .col-head { color:#9c8bff; }
  .c-delivered .col-head { color:#5ed16a; }
  .card { background:#1f242e; border-radius:8px; padding:12px; margin-bottom:8px; border-left:5px solid #3a4150; }
  .card.overdue { border-left-color:#ff4d4f; background:#2a1a1c; }
  .card .name { font-size:22px; font-weight:800; line-height:1.1; }
  .card .meta { font-size:14px; color:#9aa0ab; margin-top:4px; }
  .card .amt { font-size:16px; font-weight:700; color:#cfd3da; }
  .card .drv { font-size:14px; color:#9c8bff; margin-top:2px; }
  .empty { color:#5a606b; text-align:center; padding:20px; font-size:14px; }
  .conn { position:fixed; bottom:6px; right:10px; font-size:11px; color:#5a606b; }
</style>
</head>
<body>
<div class="board" id="board"></div>
<div class="conn" id="conn">…</div>
<script>
const COLS = [
  ["confirmed", "TASDIQLANGAN"],
  ["waiting_production", "ISHLAB CHIQARILMOQDA"],
  ["out_for_delivery", "YO'LDA"],
  ["delivered", "YETKAZILDI (bugun)"],
];
const STAGE_LABEL = {confirmed:"", waiting_production:"⏳ ishlab chiqarish", out_for_delivery:"", delivered:"✓"};

function fmt(n){ return (n||0).toLocaleString('ru-RU'); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function sinceMin(iso){ if(!iso) return ""; const d=new Date(iso); const m=Math.floor((Date.now()-d.getTime())/60000); if(m<1) return "hozir"; if(m<60) return m+" daq"; return Math.floor(m/60)+" soat"; }

function render(data){
  const board = document.getElementById('board');
  board.innerHTML = "";
  for(const [key, title] of COLS){
    const items = data[key] || [];
    const col = document.createElement('div');
    col.className = "col c-"+key;
    let html = `<div class="col-head">${title} (${items.length})</div><div class="col-body">`;
    if(!items.length){ html += `<div class="empty">—</div>`; }
    for(const o of items){
      // XSS himoyasi: mijoz nomi/raqam/haydovchi DB'dan kelgan matn — esc() bilan escape
      const drv = o.driver ? `<div class="drv">🚚 ${esc(o.driver)}</div>` : "";
      const extra = STAGE_LABEL[o.status] || "";
      html += `<div class="card ${o.overdue?'overdue':''}">
        <div class="name">${esc(o.partner)}</div>
        <div class="amt">${esc(o.number)} · ${fmt(o.total)} so'm</div>
        <div class="meta">${(o.items_count||0)} mahsulot${extra?(' · '+extra):''} · ${sinceMin(o.stage_since)}</div>
        ${drv}
      </div>`;
    }
    html += `</div>`;
    col.innerHTML = html;
    board.appendChild(col);
  }
}

let reloadTimer = null;
async function reload(){
  try{
    const r = await fetch('/sales/board/data', {credentials:'same-origin'});
    if(r.ok){ render(await r.json()); }
  }catch(e){}
}
function scheduleReload(){ clearTimeout(reloadTimer); reloadTimer = setTimeout(reload, 500); }

// Boshlang'ich + 30 sek zaxira poll
reload();
setInterval(reload, 30000);

// WebSocket — har event "refresh signal"
function connectWS(){
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws/dashboard/v2`);
  const conn = document.getElementById('conn');
  ws.onopen = ()=>{ conn.textContent = "● jonli"; };
  ws.onmessage = ()=>{ scheduleReload(); };
  ws.onclose = ()=>{ conn.textContent = "○ qayta ulanmoqda…"; setTimeout(connectWS, 3000); };
  ws.onerror = ()=>{ try{ws.close();}catch(e){} };
  // keep-alive ping
  setInterval(()=>{ try{ if(ws.readyState===1) ws.send('ping'); }catch(e){} }, 25000);
}
connectWS();
</script>
</body>
</html>
```

- [ ] **Step 2: Jinja parse smoke**

Run:
```bash
python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('board/order_board.html'); print('Jinja OK')"
```
Expected: Jinja OK

- [ ] **Step 3: Commit**

```bash
git add app/templates/board/order_board.html
git commit -m "feat(board): to'liq-ekran order board template (WS + poll)"
```

---

### Task 4: Status-transition event'lari (`publish_event`)

**Files:**
- Modify: `app/routes/delivery_routes.py` (agent confirm — `~536`, `~554`)
- Modify: `app/routes/api_driver_ops.py` (delivered — `~446`; failed/cancelled — `~374`)
- Modify: `app/services/agent_order_service.py` (waiting → out_for_delivery: `try_confirm_waiting_orders`)
- Modify: `app/routes/api_agent_ops.py` (agent buyurtma yaratish)

Maqsad: har status o'zgarish `db.commit()` dan KEYIN board'ga "refresh signal" yuborish. `publish_event` allaqachon silent-fail, shuning uchun xavfsiz.

- [ ] **Step 1: Helper — har commit'dan keyin chaqiriladigan signal**

Hech qanday yangi modul kerak emas. Har joyga shu naqsh qo'shiladi (commit'dan keyin):

```python
    try:
        from app.services.realtime_bus import publish_event
        publish_event("order_board")
    except Exception:
        pass
```

- [ ] **Step 2: `delivery_routes.py` agent confirm'dan keyin qo'shish**

`supervisor_confirm_*` funksiyalarida `db.commit()` dan KEYIN (`~536` va `~554` atrofidagi confirm endpointlar) yuqoridagi snippet'ni qo'shish.

- [ ] **Step 3: `api_driver_ops.py` delivered + failed'dan keyin qo'shish**

`driver_delivery_status` da yagona yakuniy `db.commit()` (`~452`) dan KEYIN snippet'ni qo'shish (delivered/failed/cancelled — hammasi shu commit orqali o'tadi, bitta joy yetarli).

- [ ] **Step 4: `agent_order_service.try_confirm_waiting_orders` oxirida qo'shish**

waiting_production → out_for_delivery o'tkazilganda (funksiya order(lar)ni qaytaradi); funksiya commit qiladigan/qaytadigan joyda snippet'ni qo'shish (agar `result` bo'sh bo'lmasa).

- [ ] **Step 5: `api_agent_ops.py` agent buyurtma yaratishdan keyin qo'shish**

Agent buyurtma yaratuvchi endpoint(lar)da `db.commit()` dan keyin snippet'ni qo'shish.

- [ ] **Step 6: AST smoke (har o'zgartirilgan fayl)**

Run:
```bash
for f in app/routes/delivery_routes.py app/routes/api_driver_ops.py app/services/agent_order_service.py app/routes/api_agent_ops.py; do python -c "import ast; ast.parse(open('$f',encoding='utf-8').read()); print('OK $f')"; done
```
Expected: hammasi OK

- [ ] **Step 7: Commit**

```bash
git add app/routes/delivery_routes.py app/routes/api_driver_ops.py app/services/agent_order_service.py app/routes/api_agent_ops.py
git commit -m "feat(board): status-transition'larga order_board refresh signal"
```

---

### Task 5: To'liq regressiya + qo'lda smoke

- [ ] **Step 1: To'liq test paketi**

Run: `python -m pytest tests/ -q`
Expected: yangi board testlari pass; mavjud testlar buzilmagan (faqat oldindan ma'lum `test_login_get_returns_200` jinja flake).

- [ ] **Step 2: Qo'lda smoke (deploy + restart'dan keyin)**

Menejer kompyuterida `/sales/board` ni F11 bilan oching. Boshqa oynada test agent buyurtma yarating → supervisor tasdiqlang → dispatch → haydovchi yetkazsin. Har bosqichda kartochka tegishli ustunga ko'chishi va `delivery_date` o'tgan buyurtma qizil bo'lishini tekshiring. WS uzilsa (serverni restart) 30 sek ichida o'zi tiklanishini ko'ring.

- [ ] **Step 3: Deploy** (tungi oyna yoki past-trafik) — route o'zgarishi, restart kerak. Backup → merge/push → foreground restart (taskkill + `tasklist /S` kill-tasdiq + schtasks /run + /login 200 + yangi PID).

---

## Self-review eslatmalari
- Snapshot read-only — hech narsani o'zgartirmaydi (xavfsiz).
- Event'lar silent-fail — asosiy operatsiyaga ta'sir yo'q.
- WS auth admin/menejer (mavjud) — board ham require_auth.
- Zaxira poll (30 sek) — biror transition event qo'shilmay qolsa ham board yangilanadi (chidamlilik).
- YETKAZILDI ustuni `delivery_date == bugun` bilan cheklangan (delivered_at o'rniga delivery_date — model'da ishonchli maydon; agar kelajakda aniqroq kerak bo'lsa Delivery.delivered_at ga o'tish mumkin).
