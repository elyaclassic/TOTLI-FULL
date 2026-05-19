# Multi-agent P1 (model + helper + backfill) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `partner_agents` jadvali + `PartnerAgent` ORM model + `effective_agent_ids` helper + mavjud `partner.agent_id` dan backfill — XULQ O'ZGARMAYDI (P1 poydevor).

**Architecture:** Yondashuv A (spec `3496481`): join jadval + `Partner.agent_id` anchor. `Base.metadata.create_all` (init_db, main.py:304) yangi modelni avto-yaratadi — alembic skript shart emas. Backfill = bir martalik dry-run skript (`fix_*` namunasi). P1 da helper hozircha `{agent_id}` bilan bir xil to'plam qaytaradi (regression yo'q).

**Tech Stack:** SQLAlchemy (declarative_base, database.py:9), pytest (`tests/conftest.py` `db` in-memory fixture), SQLite.

---

## File Structure

- **Modify** `app/models/database.py`: `PartnerAgent` model class (Partner klassidan keyin, ~874-qator atrofida relationship) + `Partner.partner_agents` relationship.
- **Create** `app/services/partner_agents.py`: `effective_agent_ids(partner) -> set[int]` helper (yagona manba).
- **Create** `scripts/backfill_partner_agents.py`: dry-run/apply backfill (`scripts/fix_obmen_6669_cancel.py` uslubi).
- **Create** `tests/test_partner_agents.py`: model, helper, backfill testlari (`db` fixture).

---

### Task 1: PartnerAgent model + Partner relationship

**Files:**
- Modify: `app/models/database.py` (Partner klassidan keyin, `class AgentPayment` (1058) dan oldin)
- Test: `tests/test_partner_agents.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_partner_agents.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_partner_agents.py::test_partner_agent_row_create -v`
Expected: FAIL — `ImportError: cannot import name 'PartnerAgent'`

- [ ] **Step 3: Write minimal implementation**

`app/models/database.py` — `class Partner` dan keyin, `class AgentPayment` (~1058) dan oldin qo'shing:

```python
class PartnerAgent(Base):
    """Kontragentga biriktirilgan agentlar (N:N + per-agent tashrif).

    Spec: docs/superpowers/specs/2026-05-19-multi-agent-partner-design.md
    visit_days = CSV kun raqamlari "0,2,4" (Du=0..Yak=6, Partner.visit_day bilan izchil).
    """
    __tablename__ = "partner_agents"

    id = Column(Integer, primary_key=True, index=True)
    partner_id = Column(Integer, ForeignKey("partners.id"), nullable=False, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    visit_type = Column(String(20), nullable=True)
    visit_days = Column(String(50), nullable=True)
    position = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("partner_id", "agent_id", name="uq_partner_agent"),
    )
```

`class Partner` ichida, `orders = relationship(...)` (875) yonига qo'shing:

```python
    partner_agents = relationship(
        "PartnerAgent",
        backref="partner",
        cascade="all, delete-orphan",
        order_by="PartnerAgent.position",
    )
```

Fayl boshида `UniqueConstraint` import borligini tekshiring; yo'q bo'lsa `from sqlalchemy import ... UniqueConstraint` qatoriga qo'shing (`Column` import qilingan qator).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_partner_agents.py::test_partner_agent_row_create -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/database.py tests/test_partner_agents.py
git commit -m "feat(multi-agent P1): PartnerAgent model + Partner.partner_agents relationship"
```

---

### Task 2: UNIQUE(partner_id, agent_id) cheklov testi

**Files:**
- Test: `tests/test_partner_agents.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest
from sqlalchemy.exc import IntegrityError


def test_partner_agent_unique(db):
    ag = Agent(code="AGU", full_name="A"); p = Partner(code="PU", name="P", type="customer")
    db.add_all([ag, p]); db.flush()
    db.add(PartnerAgent(partner_id=p.id, agent_id=ag.id, position=1)); db.commit()
    db.add(PartnerAgent(partner_id=p.id, agent_id=ag.id, position=2))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
```

- [ ] **Step 2: Run test to verify it fails/passes**

Run: `python -m pytest tests/test_partner_agents.py::test_partner_agent_unique -v`
Expected: PASS (Task 1 da UniqueConstraint qo'shilgan — bu test uni TASDIQLAYDI). Agar FAIL bo'lsa — `__table_args__` UniqueConstraint yo'q, Task 1 Step 3 ni tekshiring.

- [ ] **Step 3: Commit**

```bash
git add tests/test_partner_agents.py
git commit -m "test(multi-agent P1): partner_agents UNIQUE constraint"
```

---

### Task 3: effective_agent_ids helper

**Files:**
- Create: `app/services/partner_agents.py`
- Test: `tests/test_partner_agents.py`

- [ ] **Step 1: Write the failing test**

```python
from app.services.partner_agents import effective_agent_ids


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
    assert effective_agent_ids(p2) == {a1.id}          # faqat anchor

    p3 = Partner(code="PE3", name="PE3", type="customer", agent_id=None)
    db.add(p3); db.commit()
    assert effective_agent_ids(p3) == set()             # bo'sh
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_partner_agents.py::test_effective_agent_ids_union -v`
Expected: FAIL — `ModuleNotFoundError: app.services.partner_agents`

- [ ] **Step 3: Write minimal implementation**

```python
# app/services/partner_agents.py
"""Kontragent effektiv agentlari — YAGONA manba.

Spec: docs/superpowers/specs/2026-05-19-multi-agent-partner-design.md
Agent ko'rinishi/huquqi qaror qilinadigan HAR joyda shu helper
ishlatiladi (tarqoq `partner.agent_id == x` taqqoslash o'rniga).
"""
from __future__ import annotations


def effective_agent_ids(partner) -> set[int]:
    """partner.agent_id (anchor) ∪ partner_agents.agent_id."""
    ids: set[int] = set()
    if getattr(partner, "agent_id", None):
        ids.add(partner.agent_id)
    for pa in (getattr(partner, "partner_agents", None) or []):
        if pa.agent_id:
            ids.add(pa.agent_id)
    return ids
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_partner_agents.py::test_effective_agent_ids_union -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/partner_agents.py tests/test_partner_agents.py
git commit -m "feat(multi-agent P1): effective_agent_ids helper (yagona manba)"
```

---

### Task 4: Backfill skript (partner.agent_id -> partner_agents)

**Files:**
- Create: `scripts/backfill_partner_agents.py`
- Test: `tests/test_partner_agents.py`

- [ ] **Step 1: Write the failing test**

```python
from scripts.backfill_partner_agents import backfill


def test_backfill_creates_position1_rows(db):
    a1 = Agent(code="B1", full_name="B1")
    db.add(a1); db.flush()
    p_with = Partner(code="PB1", name="PB1", type="customer",
                      agent_id=a1.id, visit_day=2)
    p_none = Partner(code="PB2", name="PB2", type="customer", agent_id=None)
    db.add_all([p_with, p_none]); db.commit()

    n = backfill(db, apply=True)
    assert n == 1                                        # faqat agent_id'li
    rows = db.query(PartnerAgent).filter_by(partner_id=p_with.id).all()
    assert len(rows) == 1
    assert rows[0].agent_id == a1.id
    assert rows[0].position == 1
    assert rows[0].visit_days == "2"                     # int visit_day -> CSV
    assert db.query(PartnerAgent).filter_by(partner_id=p_none.id).count() == 0

    # idempotent: ikkinchi marta 0 qo'shadi
    assert backfill(db, apply=True) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_partner_agents.py::test_backfill_creates_position1_rows -v`
Expected: FAIL — `ModuleNotFoundError: scripts.backfill_partner_agents`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/backfill_partner_agents.py
"""partner.agent_id -> partner_agents position-1 backfill.

Spec: docs/superpowers/specs/2026-05-19-multi-agent-partner-design.md
Idempotent: (partner_id, agent_id) allaqachon bor bo'lsa o'tkazadi.
Default DRY-RUN. --apply bilan. Backup avtomatik (apply'da DB nusxa).

Ishlatish (D:\\TOTLI BI dan):
    python scripts/backfill_partner_agents.py [--apply]
"""
import sys
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def backfill(db, *, apply: bool) -> int:
    """Qaytaradi: qo'shilgan (yoki dry-run'da qo'shiladigan) qator soni."""
    from app.models.database import Partner, PartnerAgent
    n = 0
    partners = db.query(Partner).filter(Partner.agent_id.isnot(None)).all()
    for p in partners:
        exists = db.query(PartnerAgent.id).filter_by(
            partner_id=p.id, agent_id=p.agent_id).first()
        if exists:
            continue
        n += 1
        if apply:
            db.add(PartnerAgent(
                partner_id=p.id,
                agent_id=p.agent_id,
                visit_type=None,
                visit_days=(str(p.visit_day)
                            if p.visit_day is not None else None),
                position=1,
            ))
    if apply:
        db.commit()
    return n


def main() -> None:
    apply = "--apply" in sys.argv[1:]
    db_path = ROOT / "totli_holva.db"
    if not db_path.exists():
        print(f"XATO: DB topilmadi: {db_path}")
        sys.exit(1)
    if apply:
        bak = db_path.parent / (
            db_path.name + f".pre-pabackfill.{datetime.now():%Y%m%d_%H%M%S}.bak"
        )
        shutil.copy2(db_path, bak)
        print(f"Backup: {bak.name}")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    eng = create_engine("sqlite:///" + str(db_path))
    db = sessionmaker(bind=eng)()
    try:
        n = backfill(db, apply=apply)
        print(f"{'QO_LLANDI' if apply else 'DRY-RUN'}: {n} ta partner_agents "
              f"qatori {'qo_shildi' if apply else 'qo_shiladi'}")
        if not apply:
            print("--apply bilan qo'llang.")
    finally:
        db.close()
        eng.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_partner_agents.py::test_backfill_creates_position1_rows -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_partner_agents.py tests/test_partner_agents.py
git commit -m "feat(multi-agent P1): backfill skript (agent_id -> partner_agents)"
```

---

### Task 5: Regression — P1 xulqni O'ZGARTIRMAGANINI tasdiqlash

**Files:**
- Test: `tests/test_partner_agents.py`

- [ ] **Step 1: Write the failing test**

```python
def test_p1_no_behavior_change(db):
    """P1: agent_id hali authoritative. effective set HAR DOIM agent_id ni
    o'z ichiga oladi -> agent_id == x o'qiydigan eski kod buzilmaydi."""
    a1 = Agent(code="R1", full_name="R1")
    db.add(a1); db.flush()
    p = Partner(code="PR", name="PR", type="customer", agent_id=a1.id)
    db.add(p); db.commit()
    eff = effective_agent_ids(p)
    assert a1.id in eff                                  # anchor doim ichida
    assert p.agent_id == a1.id                           # anchor o'zgarmagan
```

- [ ] **Step 2: Run test to verify it passes**

Run: `python -m pytest tests/test_partner_agents.py -v`
Expected: PASS (barcha 5 test). Bu Task 1-3 ni tasdiqlaydi.

- [ ] **Step 3: Commit**

```bash
git add tests/test_partner_agents.py
git commit -m "test(multi-agent P1): regression — xulq o'zgarmaganini tasdiq"
```

---

## Deploy (P1 — Tier C, tungi/nazoratli)

1. Kod merge (model + helper + skript + testlar)
2. Server restart → `init_db()` `Base.metadata.create_all` `partner_agents` jadvalini avto-yaratadi
3. `python scripts/backfill_partner_agents.py` (DRY-RUN) — nechta qator qo'shilishini ko'rsatish
4. Tasdiqdan keyin `python scripts/backfill_partner_agents.py --apply` (backup avtomatik)
5. Tekshir: `SELECT COUNT(*) FROM partner_agents` == `SELECT COUNT(*) FROM partners WHERE agent_id IS NOT NULL`
6. Smoke: agent app + kontragent ro'yxat O'ZGARMAGANINI tasdiqlash (P1 = xulq o'zgarmaydi)

**Rollback:** model/helper/skript commitlarini revert + `DROP TABLE partner_agents` (bo'sh, side-effectsiz — backfill faqat additive qatorlar).

---

## Self-Review

**Spec coverage:** Spec §3 (model partner_agents) → Task 1; UNIQUE → Task 2; §4 helper → Task 3; §3 backfill (visit_day→CSV) → Task 4; §7 P1 "xulq o'zgarmaydi" → Task 5; §9 test (backfill, helper, regression) → Task 1-5. §5/§6/§8 (ko'rinish, UI) → P2/P3 (bu reja qamrovida emas — bosqichli). Gap yo'q.

**Placeholder scan:** Har stepда to'liq kod/komanda bor; "TBD/TODO" yo'q.

**Type consistency:** `PartnerAgent` maydonlari (partner_id, agent_id, visit_type, visit_days, position) Task 1/3/4 da bir xil; `effective_agent_ids(partner)->set[int]` Task 3/5 da bir xil; `backfill(db,*,apply)->int` Task 4 da bir xil ishlatilgan.
