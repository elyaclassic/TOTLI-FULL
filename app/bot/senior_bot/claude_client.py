"""Claude CLI subprocess wrapper (Anthropic API o'rniga).

Anthropic API kredit yo'q — mavjud Max obuna orqali `claude` CLI ishlatamiz.
Har chat uchun alohida CLI sessiya (`--resume <sid>`) — kontekst Claude
tomonida saqlanadi, biz faqat yangi savolni yuboramiz.

`ask()` interfeysi senior_bot/bot.py bilan mos (signature o'zgardi:
endi chat_id qabul qiladi).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess as _sp
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Max obuna model — Opus 4.7 (1M context). CLI default boshqa tanlamasin.
DEFAULT_MODEL = os.environ.get("SENIOR_BOT_MODEL", "claude-opus-4-7[1m]")
TIMEOUT = int(os.environ.get("SENIOR_BOT_CLI_TIMEOUT", "300"))

CWD = os.environ.get("CLAUDE_BOT_CWD") or os.getcwd()
_SESS_FILE = Path(CWD) / "app" / "bot" / "data" / "senior_bot_sessions.json"


def _resolve_claude_path() -> str:
    found = shutil.which("claude")
    if found:
        return found
    if sys.platform == "win32":
        for c in (
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            os.path.expandvars(r"%APPDATA%\npm\claude.bat"),
            os.path.expandvars(r"%LOCALAPPDATA%\npm\claude.cmd"),
        ):
            if os.path.exists(c):
                return c
    return "claude"


def _load_sessions() -> dict:
    try:
        if _SESS_FILE.exists():
            return json.loads(_SESS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save_session(chat_id: int, sid: str) -> None:
    if not sid:
        return
    data = _load_sessions()
    data[str(chat_id)] = {"claude_session_id": sid}
    try:
        _SESS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        logger.error(f"session save fail: {e}")


def reset_session(chat_id: int) -> None:
    data = _load_sessions()
    if str(chat_id) in data:
        data.pop(str(chat_id), None)
        try:
            _SESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass


async def ask(chat_id: int, question: str, system_prompt: str) -> tuple[str, dict]:
    """Claude CLI orqali savol-javob.

    Birinchi xabar (sessiya yo'q): system_prompt + savol birga yuboriladi.
    Keyingilar: faqat savol (kontekst --resume orqali Claude tomonida).

    Returns:
        (javob_matni, meta) — meta'da session_id, model, mode
    """
    sessions = _load_sessions()
    sid = (sessions.get(str(chat_id)) or {}).get("claude_session_id")

    if sid:
        prompt = question
    else:
        prompt = (
            f"{system_prompt}\n\n"
            f"---\n\n"
            f"Yuqoridagi ko'rsatmaga rioya qil. Foydalanuvchi savoli:\n\n{question}"
        )

    claude_bin = _resolve_claude_path()
    args = [claude_bin, "--print", "--output-format", "json", "--model", DEFAULT_MODEL]
    if sid:
        args += ["--resume", sid]
    args += ["--dangerously-skip-permissions", prompt]

    if sys.platform == "win32" and claude_bin.lower().endswith((".cmd", ".bat")):
        exec_args = ["cmd.exe", "/c"] + args
    else:
        exec_args = args

    # MUHIM: ANTHROPIC_API_KEY ni subprocess env'dan olib tashlaymiz.
    # Aks holda `claude` CLI Max obuna OAuth o'rniga API key billing'ni
    # ishlatadi (API plan balansi $0 → "Credit balance is too low").
    _env = os.environ.copy()
    _env.pop("ANTHROPIC_API_KEY", None)

    def _blocking_run():
        return _sp.run(
            exec_args,
            cwd=CWD,
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            stdin=_sp.DEVNULL,
            timeout=TIMEOUT,
            env=_env,
        )

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _blocking_run)
    except _sp.TimeoutExpired:
        return (f"Vaqt tugadi ({TIMEOUT}s). Savolni qisqartiring yoki /reset.", {"error": "timeout"})
    except FileNotFoundError:
        return ("`claude` CLI topilmadi (server'da o'rnatilmagan).", {"error": "no_cli"})
    except Exception as e:
        return (f"Xato: {type(e).__name__}: {e}", {"error": str(e)})

    out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (result.stderr or b"").decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        logger.error(f"[senior_bot CLI] code={result.returncode} err={err[:300]}")
        return (f"Claude xatosi (code={result.returncode}):\n{(err or out)[:500]}", {"error": "cli_fail"})

    try:
        data = json.loads(out)
        new_sid = data.get("session_id") or sid
        if new_sid and new_sid != sid:
            _save_session(chat_id, new_sid)
        text = data.get("result") or data.get("content") or out
        if isinstance(text, list):
            text = "\n".join(str(x) for x in text)
        usage = data.get("usage") or {}
        meta = {
            "model": DEFAULT_MODEL,
            "mode": "cli",
            "session_id": new_sid,
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }
        logger.info(f"[senior_bot] CLI ok chat={chat_id} sid={new_sid}")
        return (str(text).strip() or "(bo'sh javob)", meta)
    except json.JSONDecodeError:
        return (out or "(bo'sh javob)", {"mode": "cli", "parse": "raw"})
