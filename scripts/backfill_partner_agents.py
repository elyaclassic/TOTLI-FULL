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
