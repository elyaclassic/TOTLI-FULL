"""Claude Code audit log hook.

PreToolUse / PostToolUse event'larida ishga tushadi. Har Bash, Edit, Write
chaqirig'i uchun yozuv yaratadi:
- timestamp, tool_name, parameters (sanitized)
- file_edit holatlari uchun: oldingi hash + yangi hash
- output (first 500 chars)

Saqlash joyi: claude_logs/YYYY-MM-DD/HH.jsonl

Hook chaqirilishi: settings.local.json ichida hooks bo'limi orqali.
JSON event stdin'dan keladi (Claude Code hook protokoli).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import datetime as _dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LOG_DIR = ROOT / "claude_logs"

# Maxfiy fayllarni log'da yashirish
SECRET_PATHS = {".env", "totli-release.jks", "credentials.json"}
# Juda katta parametrlar uchun cheklov
MAX_PARAM_LEN = 2000
MAX_OUTPUT_LEN = 1000


def file_hash(path: str) -> str:
    try:
        p = Path(path)
        if not p.is_file():
            return ""
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:16]
    except (OSError, PermissionError):
        return ""


def truncate(s: str, limit: int) -> str:
    if not isinstance(s, str):
        s = str(s)
    if len(s) <= limit:
        return s
    return s[:limit] + f"...[{len(s) - limit} more]"


def sanitize_path(path: str) -> str:
    if not path:
        return path
    name = Path(path).name.lower()
    if name in SECRET_PATHS or name.endswith(".key") or name.endswith(".pem"):
        return f"<SECRET: {name}>"
    return path


def log_entry(event_type: str, data: dict) -> None:
    now = _dt.datetime.now()
    day_dir = LOG_DIR / now.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    log_file = day_dir / f"{now.strftime('%H')}.jsonl"
    entry = {
        "ts": now.isoformat(),
        "event": event_type,
        **data,
    }
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def main() -> int:
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        event = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0

    hook_event = event.get("hook_event_name") or event.get("event") or "unknown"
    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {}) or {}

    data: dict = {
        "hook": hook_event,
        "tool": tool_name,
    }

    if tool_name in ("Edit", "Write", "NotebookEdit"):
        file_path = tool_input.get("file_path", "")
        data["file"] = sanitize_path(file_path)
        if hook_event == "PreToolUse":
            data["hash_before"] = file_hash(file_path)
        else:
            data["hash_after"] = file_hash(file_path)
        if tool_name == "Edit":
            data["old_string"] = truncate(tool_input.get("old_string", ""), MAX_PARAM_LEN)
            data["new_string"] = truncate(tool_input.get("new_string", ""), MAX_PARAM_LEN)
        elif tool_name == "Write":
            data["content_size"] = len(tool_input.get("content", ""))
    elif tool_name in ("Bash", "PowerShell"):
        data["command"] = truncate(tool_input.get("command", ""), MAX_PARAM_LEN)
        if hook_event == "PostToolUse":
            tool_response = event.get("tool_response", {}) or {}
            output = tool_response.get("stdout", "") or tool_response.get("output", "")
            data["output"] = truncate(output, MAX_OUTPUT_LEN)
            data["exit_code"] = tool_response.get("exit_code", 0)
    elif tool_name == "Read":
        data["file"] = sanitize_path(tool_input.get("file_path", ""))
    elif tool_name in ("Glob", "Grep"):
        data["pattern"] = truncate(tool_input.get("pattern", ""), 200)
    else:
        data["params_keys"] = list(tool_input.keys())

    log_entry(hook_event, data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
