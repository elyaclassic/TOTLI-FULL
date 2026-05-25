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
