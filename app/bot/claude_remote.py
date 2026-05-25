"""Claude Code Remote Bot — Telegram orqali Claude CLI bilan suhbat.
v1.3 — 2026-04-30 (inbox MCP integratsiyasi)
"""
import asyncio
import json
import logging
import os
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.bot import inbox as _inbox

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("CLAUDE_BOT_TOKEN", "")
PIN = os.environ.get("CLAUDE_BOT_PIN", "")
try:
    OWNER_ID = int(os.environ.get("CLAUDE_OWNER_ID", "1340383182"))
except (ValueError, TypeError):
    OWNER_ID = 1340383182

CWD = os.environ.get("CLAUDE_BOT_CWD") or os.getcwd()
try:
    TIMEOUT = int(os.environ.get("CLAUDE_BOT_TIMEOUT", "300"))
except (ValueError, TypeError):
    TIMEOUT = 300

AUTH_TTL_SECONDS = 12 * 3600
TG_MSG_MAX = 4000

LOG_DIR = Path(CWD) / "app" / "bot" / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
PHOTO_DIR = LOG_DIR / "photos"
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG = LOG_DIR / "claude_remote_audit.log"
SESSIONS_FILE = LOG_DIR / "claude_remote_sessions.json"

_state: dict = {}
_bot: Optional[Bot] = None
_dp: Optional[Dispatcher] = None
_task: Optional[asyncio.Task] = None
_bot_username: str = "claudeyordamchi_bot"


def _audit(user_id: int, kind: str, payload: str = "") -> None:
    try:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}\t{user_id}\t{kind}\t{payload[:200]}\n"
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _load_sessions() -> dict:
    try:
        if SESSIONS_FILE.exists():
            return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_sessions(data: dict) -> None:
    try:
        SESSIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_authed(user_id: int) -> bool:
    s = _state.get(user_id)
    if s and s.get("auth_until", 0) > time.time():
        return True
    # Persistent fallback — session file dan auth_until o'qish (bot restart dan keyin)
    saved = _load_sessions().get(str(user_id), {})
    auth_until = saved.get("auth_until", 0)
    if auth_until and auth_until > time.time():
        _state.setdefault(user_id, {})["auth_until"] = auth_until
        return True
    return False


def _set_authed(user_id: int) -> None:
    auth_until = int(time.time()) + AUTH_TTL_SECONDS
    _state.setdefault(user_id, {})["auth_until"] = auth_until
    # Persistent — bot restart dan keyin ham auth saqlanishi uchun
    saved = _load_sessions()
    saved.setdefault(str(user_id), {})["auth_until"] = auth_until
    _save_sessions(saved)


def _is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID


async def _send_long(message: Message, text: str) -> None:
    if not text:
        await message.reply("(bo'sh javob)")
        return
    while text:
        chunk = text[:TG_MSG_MAX]
        text = text[TG_MSG_MAX:]
        try:
            await message.answer(chunk)
        except Exception as e:
            logger.error(f"send_long: {e}")
            break


async def _autodelete(msg, delay: int = 6) -> None:
    """Botning o'z xabarini delay soniyadan keyin o'chiradi (admin huquqsiz)."""
    try:
        await asyncio.sleep(delay)
        await msg.delete()
    except Exception:
        pass


def subprocess_quote_windows(args) -> str:
    """Windows cmd.exe uchun argumentlarni xavfsiz quotelash."""
    out = []
    for a in args:
        s = str(a)
        if not s or any(c in s for c in ' \t\n"^&|<>()'):
            s = '"' + s.replace('"', '\\"') + '"'
        out.append(s)
    return " ".join(out)


def _resolve_claude_path() -> str:
    """Windows uchun `claude.cmd` to'liq yo'lini topadi (shell ishlatmasdan ishga tushirish uchun)."""
    found = shutil.which("claude")
    if found:
        return found
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%APPDATA%\npm\claude.cmd"),
            os.path.expandvars(r"%APPDATA%\npm\claude.bat"),
            os.path.expandvars(r"%LOCALAPPDATA%\npm\claude.cmd"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return "claude"


async def _run_claude(user_id: int, prompt: str):
    saved = _load_sessions()
    user_sess = saved.get(str(user_id), {})
    sid = user_sess.get("claude_session_id")

    claude_bin = _resolve_claude_path()
    # Model qat'iy — har doim Opus 4.7 (1M context). Aks holda CLI default
    # boshqa modelni tanlashi mumkin (bug: 2026-05-05 da Opus 4.6 ishlagan edi).
    model = os.environ.get("CLAUDE_BOT_MODEL", "claude-opus-4-7[1m]")
    args = [claude_bin, "--print", "--output-format", "json", "--model", model]
    if sid:
        args += ["--resume", sid]
    args += ["--dangerously-skip-permissions", prompt]

    _audit(user_id, "claude_call", " ".join(shlex.quote(c) for c in args))

    # Windows'da .cmd fayllarni ishga tushirish uchun cmd.exe orqali list-form
    if sys.platform == "win32" and claude_bin.lower().endswith((".cmd", ".bat")):
        exec_args = ["cmd.exe", "/c"] + args
    else:
        exec_args = args

    # Uvicorn Windows'da SelectorEventLoop ishlatadi — asyncio subprocess ishlamaydi.
    # Yechim: thread executor'da blocking subprocess.run chaqirish.
    import subprocess as _sp

    def _blocking_run():
        return _sp.run(
            exec_args,
            cwd=CWD,
            stdout=_sp.PIPE,
            stderr=_sp.PIPE,
            stdin=_sp.DEVNULL,
            timeout=TIMEOUT,
        )

    s = _state.setdefault(user_id, {})
    s["running"] = True
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _blocking_run)
    except _sp.TimeoutExpired:
        return (f"⏱ Vaqt tugadi ({TIMEOUT}s).", sid)
    except FileNotFoundError:
        return ("❌ `claude` CLI topilmadi.", sid)
    except Exception as e:
        return (f"❌ Xato: {type(e).__name__}: {e}", sid)
    finally:
        s.pop("running", None)

    out = (result.stdout or b"").decode("utf-8", errors="replace").strip()
    err = (result.stderr or b"").decode("utf-8", errors="replace").strip()

    if result.returncode != 0:
        return (f"❌ Claude xatosi (code={result.returncode}):\n{err or out}", sid)

    try:
        data = json.loads(out)
        new_sid = data.get("session_id") or sid
        result_text = data.get("result") or data.get("content") or out
        if isinstance(result_text, list):
            result_text = "\n".join(str(x) for x in result_text)
        return (str(result_text).strip() or "(bo'sh javob)", new_sid)
    except json.JSONDecodeError:
        return (out or "(bo'sh javob)", sid)


def _save_session_id(user_id: int, sid):
    if not sid:
        return
    saved = _load_sessions()
    saved.setdefault(str(user_id), {})["claude_session_id"] = sid
    _save_sessions(saved)


def _create_bot_and_dp():
    global _bot, _dp
    _bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=None))
    _dp = Dispatcher(storage=MemoryStorage())
    _register_handlers(_dp)
    return _bot, _dp


def _register_handlers(dp: Dispatcher) -> None:

    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        uid = message.from_user.id
        if not _is_owner(uid):
            _audit(uid, "denied_start")
            await message.answer(f"Ruxsat yo'q. Sizning ID: {uid}")
            return
        _audit(uid, "start")
        if _is_authed(uid):
            await message.answer("Salom! Avtorizatsiya bor. Savol yozing yoki /help.")
        else:
            await message.answer(
                "Salom! Bu Claude Code remote bot.\n"
                f"Server katalog: {CWD}\n\n"
                "PIN kiriting (faqat raqam):"
            )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        if not _is_owner(message.from_user.id):
            return
        await message.answer(
            "Buyruqlar:\n"
            "/start — boshlash\n"
            "/reset — yangi Claude sessiya (kontekst tozalanadi)\n"
            "/cancel — joriy ishni to'xtatish\n"
            "/status — holat\n"
            "/help — yordam\n\n"
            "Oddiy matn yozsangiz — Claude'ga yuboriladi."
        )

    @dp.message(Command("status"))
    async def cmd_status(message: Message):
        uid = message.from_user.id
        if not _is_owner(uid):
            return
        s = _state.get(uid, {})
        authed = _is_authed(uid)
        left = max(0, int(s.get("auth_until", 0) - time.time()))
        sid = (_load_sessions().get(str(uid)) or {}).get("claude_session_id")
        await message.answer(
            f"Holat:\n"
            f"  Auth: {'OK' if authed else 'YO`Q'} (qoldi: {left//60} daq)\n"
            f"  Sessiya: {sid or 'yangi'}\n"
            f"  Ishlamoqda: {'ha' if s.get('running') else 'yo`q'}\n"
            f"  Katalog: {CWD}"
        )

    @dp.message(Command("reset"))
    async def cmd_reset(message: Message):
        uid = message.from_user.id
        if not _is_owner(uid) or not _is_authed(uid):
            return
        saved = _load_sessions()
        if str(uid) in saved:
            saved[str(uid)].pop("claude_session_id", None)
            _save_sessions(saved)
        _audit(uid, "reset")
        await message.answer("Yangi sessiya boshlandi. Kontekst tozalandi.")

    @dp.message(Command("cancel"))
    async def cmd_cancel(message: Message):
        uid = message.from_user.id
        if not _is_owner(uid) or not _is_authed(uid):
            return
        s = _state.get(uid, {})
        if s.get("running"):
            _audit(uid, "cancel_request")
            await message.answer(
                "To'xtatish so'rovi yuborildi (subprocess.run executor'da — "
                "joriy ish tugaguncha kutiladi yoki TIMEOUT yetadi)."
            )
        else:
            await message.answer("Hozir ishlayotgan jarayon yo'q.")

    @dp.message(F.photo)
    async def on_photo(message: Message):
        uid = message.from_user.id
        if not _is_owner(uid):
            _audit(uid, "denied_photo")
            return
        if not _is_authed(uid):
            if message.chat.type != "private":
                try:
                    await message.delete()
                except Exception:
                    pass
                try:
                    await message.bot.send_message(uid, "Avval PIN kiriting (faqat raqam):")
                except Exception:
                    pass
                notice = await message.answer(f"👉 PIN'ni shaxsiy chatda kiriting: @{_bot_username}")
                asyncio.create_task(_autodelete(notice, 6))
                return
            await message.answer("Avval PIN kiriting (matn xabar bilan).")
            return

        caption = (message.caption or "").strip()
        if not caption:
            caption = "Quyidagi rasmga qarab tushuntir yoki tegishli kod o'zgartirishlarini taklif qil."

        # Rasmning eng katta o'lchamini olish
        photo = message.photo[-1]
        ts = int(time.time())
        local_name = f"tg_{uid}_{ts}_{photo.file_unique_id}.jpg"
        local_path = PHOTO_DIR / local_name

        try:
            await message.bot.download(photo, destination=str(local_path))
        except Exception as e:
            await message.answer(f"❌ Rasmni yuklab olishda xato: {e}")
            return

        _audit(uid, "photo", f"{local_name} caption={caption[:80]}")

        try:
            _inbox.append_message(uid, "photo", caption, str(local_path))
        except Exception as e:
            logger.error(f"inbox append (photo): {e}")

        # Promptga rasm yo'lini va caption ni qo'shamiz — Claude `Read` orqali rasmni ko'radi
        rel_path = str(local_path).replace("\\", "/")
        prompt = (
            f"{caption}\n\n"
            f"Foydalanuvchi telefondan rasm yubordi. Rasmni Read tool bilan oching va kontekst sifatida ishlating:\n"
            f"{rel_path}"
        )

        try:
            await message.bot.send_chat_action(message.chat.id, "typing")
        except Exception:
            pass

        result, new_sid = await _run_claude(uid, prompt)
        if new_sid:
            _save_session_id(uid, new_sid)
        await _send_long(message, result)

    @dp.message(F.text)
    async def on_text(message: Message):
        uid = message.from_user.id
        if not _is_owner(uid):
            _audit(uid, "denied_text")
            return
        text = (message.text or "").strip()
        if not text:
            return

        if not _is_authed(uid):
            if not PIN:
                await message.answer("PIN konfigda yo'q. .env da CLAUDE_BOT_PIN o'rnating.")
                return
            if message.chat.type != "private":
                # PIN guruhga tushmasin — qabul qilmaymiz, DM ga yo'naltiramiz
                try:
                    await message.delete()  # bot guruh admini bo'lsa PIN xabari o'chadi
                except Exception:
                    pass
                try:
                    await message.bot.send_message(uid, "PIN kiriting (faqat raqam):")
                except Exception:
                    pass
                notice = await message.answer(f"👉 PIN'ni shaxsiy chatda kiriting: @{_bot_username}")
                asyncio.create_task(_autodelete(notice, 6))
                return
            if text == PIN:
                _set_authed(uid)
                _audit(uid, "auth_ok")
                try:
                    await message.delete()
                except Exception:
                    pass
                ok = await message.answer("✓ PIN qabul qilindi. Endi savol yozing.\n12 soat ichida qayta PIN so'ralmaydi.")
                asyncio.create_task(_autodelete(ok, 6))
            else:
                _audit(uid, "auth_fail")
                try:
                    await message.delete()
                except Exception:
                    pass
                bad = await message.answer("PIN noto'g'ri. Qayta urinib ko'ring.")
                asyncio.create_task(_autodelete(bad, 6))
            return

        try:
            _inbox.append_message(uid, "text", text)
        except Exception as e:
            logger.error(f"inbox append (text): {e}")

        # Bot Claude CLI auto-reply o'chirilgan — faqat inbox'ga saqlash.
        # Asosiy Claude (Code IDE da) MCP inbox orqali o'qib bu yerga
        # javob beradi va Stop hook orqali Telegramga push qiladi.
        # Auto-reply'ni qaytarish uchun CLAUDE_BOT_AUTOREPLY=1 env qo'ying.
        if os.environ.get("CLAUDE_BOT_AUTOREPLY", "").strip() == "1":
            try:
                await message.bot.send_chat_action(message.chat.id, "typing")
            except Exception:
                pass
            result, new_sid = await _run_claude(uid, text)
            if new_sid:
                _save_session_id(uid, new_sid)
            await _send_long(message, result)
        else:
            try:
                await message.answer("✓ Xabar qabul qilindi (kompyuterdagi Claude javob beradi).")
            except Exception:
                pass


def notify_owner(text: str) -> bool:
    """Outbound — Claude (yoki boshqa kod) owner ga Telegram orqali xabar yuborish.
    Sync wrapper — uvicorn loop ichida coroutine_threadsafe ishlatadi.
    Qaytaradi: True yuborilgan, False bot ishlamayapti.
    """
    if not _bot or not OWNER_ID:
        return False
    try:
        loop = asyncio.get_event_loop()
        if loop and loop.is_running():
            chunks = [text[i:i + TG_MSG_MAX] for i in range(0, len(text), TG_MSG_MAX)] or [""]
            for chunk in chunks:
                asyncio.run_coroutine_threadsafe(_bot.send_message(OWNER_ID, chunk), loop)
            _audit(OWNER_ID, "notify_out", text[:200])
            return True
    except Exception as e:
        logger.error(f"notify_owner: {e}")
    return False


async def start_claude_bot():
    global _task
    if not TOKEN or len(TOKEN) < 20:
        print("[Claude Bot] CLAUDE_BOT_TOKEN yo'q — bot ishga tushmadi")
        return
    if not PIN:
        print("[Claude Bot] CLAUDE_BOT_PIN yo'q — bot ishga tushmadi")
        return
    try:
        bot, dp = _create_bot_and_dp()
        await bot.delete_webhook(drop_pending_updates=True)
        _task = asyncio.create_task(_run_polling(dp, bot))
        me = await bot.get_me()
        global _bot_username
        if me.username:
            _bot_username = me.username
        print(f"[Claude Bot] @{me.username} ishga tushdi (owner={OWNER_ID}, cwd={CWD})")
    except Exception as e:
        print(f"[Claude Bot] Ishga tushirishda xato: {e}")


async def _run_polling(dp: Dispatcher, bot: Bot):
    try:
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[Claude Bot] Polling xatosi: {e}")


async def stop_claude_bot():
    global _task, _bot
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
    if _bot:
        await _bot.session.close()
        _bot = None
    print("[Claude Bot] To'xtatildi")
