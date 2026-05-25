"""Har bir ekspertdan loyiha auditi so'rash.

Ishlatish:
    python scripts/expert_audit.py
    python scripts/expert_audit.py --experts Rustam Anvar Nosir
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess as _sp
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.bot.senior_bot.experts import EXPERTS, PROJECT_CONTEXT

AUDIT_PROMPT = """Siz {name} ({role}) sifatida TOTLI BI loyihasini audit qilyapsiz.

Fokus: {focus}

Quyidagi savolga javob bering:
"TOTLI BI loyihasida {role} nuqtai nazaridan qanday muammolar, xatarlar va yaxshilanish imkoniyatlari bor?"

Javob formati:
## KRITIK (zudlik bilan tuzatish kerak)
- muammo: izoh

## MUHIM (keyingi sprint)
- muammo: izoh

## YAXSHILANISH (keyinroq)
- muammo: izoh

## YAXSHI TOMONLAR
- nima to'g'ri qilingan

Qisqa va aniq. Faqat o'z domeningizga oid narsalarni yozing."""

DEFAULT_EXPERTS = ["Nosir", "Rustam", "Diyor", "Anvar", "Nodira", "Jahongir", "Alisher", "Dilshoda"]


def _resolve_claude() -> str:
    found = shutil.which("claude")
    if found:
        return found
    if sys.platform == "win32":
        for c in (
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            os.path.expandvars(r"%APPDATA%\npm\claude.bat"),
        ):
            if os.path.exists(c):
                return c
    return "claude"


async def ask_expert(expert: dict) -> tuple[str, str]:
    name = expert["name"]
    prompt = (
        PROJECT_CONTEXT + "\n\n" +
        AUDIT_PROMPT.format(
            name=name,
            role=expert["role"],
            focus=expert["focus"],
        )
    )

    claude_bin = _resolve_claude()
    args = [claude_bin, "--print", "--output-format", "json",
            "--model", "claude-sonnet-4-6",
            "--dangerously-skip-permissions", prompt]

    if sys.platform == "win32" and claude_bin.lower().endswith((".cmd", ".bat")):
        args = ["cmd.exe", "/c"] + args

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)

    def _run():
        return _sp.run(
            args, cwd=str(ROOT),
            stdout=_sp.PIPE, stderr=_sp.PIPE,
            stdin=_sp.DEVNULL, timeout=180, env=env,
        )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run)
        out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        if result.returncode != 0:
            err = (result.stderr or b"").decode("utf-8", errors="replace")
            return name, f"XATO (code={result.returncode}): {err[:200]}"
        try:
            data = json.loads(out)
            text = data.get("result") or data.get("content") or out
            if isinstance(text, list):
                text = "\n".join(str(x) for x in text)
            return name, str(text).strip()
        except json.JSONDecodeError:
            return name, out
    except _sp.TimeoutExpired:
        return name, "XATO: timeout (120s)"
    except Exception as e:
        return name, f"XATO: {e}"


async def main(expert_names: list[str]):
    experts = [e for e in EXPERTS if e["name"] in expert_names]
    if not experts:
        print("Ekspert topilmadi")
        return

    print(f"[{datetime.now().strftime('%H:%M:%S')}] {len(experts)} ta ekspertdan audit so'ralmoqda...\n")

    # Ketma-ket — parallel CLI timeout muammosini oldini oladi
    results = []
    for e in experts:
        print(f"  >> {e['name']} so'ralmoqda...", flush=True)
        r = await ask_expert(e)
        results.append(r)

    out_dir = ROOT / "data" / "expert_audits"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

    lines = [f"# Expert Audit — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"]
    for name, answer in results:
        safe = answer.encode("cp1251", errors="replace").decode("cp1251")
        print(f"\n{'='*60}")
        print(f"## {name}")
        print(f"{'='*60}")
        print(safe)
        lines.append(f"\n## {name}\n\n{answer}\n")

    out_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n\nNatija saqlandi: {out_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--experts", nargs="+", default=DEFAULT_EXPERTS)
    args = parser.parse_args()
    asyncio.run(main(args.experts))
