"""Senior Bot — Telegram entrypoint.

aiogram 3.x. Gruppa + DM rejimida ishlaydi. Anthropic Claude API orqali
javob beradi (Claude CLI emas).

Auth:
- DM (private chat): faqat OWNER_IDS dagi user
- Gruppa: chat.id ALLOWED_GROUP_IDS da bo'lishi + foydalanuvchi PIN bilan auth

Buyruqlar:
- /start, /help, /status, /whoami
- /ask <savol>  yoki shunchaki matn yozish (DM'da)
- /expert <nom> — bitta ekspert nuqtai nazaridan
- /team — 11 ekspert ro'yxati
- /memory — MEMORY.md mazmuni
- /audit — so'nggi audit log
- /reset — bugungi suhbat tarixini arxivlash
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.bot.senior_bot import claude_client
from app.bot.senior_bot import conversation_store as conv
from app.bot.senior_bot import experts

logger = logging.getLogger(__name__)

TOKEN = os.environ.get("CLAUDE_BOT_TOKEN", "")
PIN = os.environ.get("CLAUDE_BOT_PIN", "")

# Bir nechta owner — vergul bilan
OWNER_IDS: set[int] = set()
for raw in (os.environ.get("CLAUDE_OWNER_ID", "1340383182") or "").split(","):
    raw = raw.strip()
    if raw.isdigit():
        OWNER_IDS.add(int(raw))

# Ruxsat berilgan gruppalar
ALLOWED_GROUP_IDS: set[int] = set()
for raw in (os.environ.get("SENIOR_BOT_GROUP_IDS", "") or "").split(","):
    raw = raw.strip()
    try:
        if raw:
            ALLOWED_GROUP_IDS.add(int(raw))
    except ValueError:
        pass

CWD = os.environ.get("CLAUDE_BOT_CWD") or os.getcwd()
AUTH_TTL_SECONDS = 12 * 3600
TG_MSG_MAX = 4000

# Gruppada har oddiy matnga javob berish (maxsus bot gruppasi uchun).
# 0 qilinса — faqat @mention yoki reply'ga javob beradi (aralash gruppa uchun).
RESPOND_ALL = (os.environ.get("SENIOR_BOT_GROUP_RESPOND_ALL", "1") or "1").strip() not in ("0", "false", "no", "")

LOG_DIR = Path(CWD) / "app" / "bot" / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
AUDIT_LOG = LOG_DIR / "senior_bot_audit.log"

_auth_state: dict[int, dict] = {}  # uid → {"auth_until": ts, "expert": Optional[str]}
_bot: Optional[Bot] = None
_dp: Optional[Dispatcher] = None
_task: Optional[asyncio.Task] = None
_in_flight: set[int] = set()  # uid lock — bir kishi bir vaqtda 1 ta savol


def _audit(chat_id: int, uid: int, kind: str, payload: str = "") -> None:
    try:
        line = (
            f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tchat={chat_id}\tuid={uid}\t"
            f"{kind}\t{payload[:300]}\n"
        )
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _is_owner(uid: int) -> bool:
    return uid in OWNER_IDS


def _is_authed(uid: int) -> bool:
    s = _auth_state.get(uid)
    if not s:
        return False
    return s.get("auth_until", 0) > time.time()


def _set_authed(uid: int) -> None:
    s = _auth_state.setdefault(uid, {})
    s["auth_until"] = int(time.time() + AUTH_TTL_SECONDS)


async def _delete_pin_message(message: Message) -> None:
    # Gruppada PIN sirini ochiq qoldirmaslik uchun foydalanuvchi xabarini
    # o'chiramiz. Faqat asosiy Yordamchim o'chiradi; ekspert botlar tegmaydi
    # (12 bot bir xabarni o'chirsa 11 tasi xato beradi). Ruxsat yo'q / xabar
    # eskirgan / allaqachon o'chirilgan — yutiladi.
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    try:
        await message.delete()
    except Exception:
        pass


def _chat_allowed(message: Message) -> bool:
    """Chat (DM yoki gruppa) ruxsat berilganmi?"""
    ctype = message.chat.type
    cid = message.chat.id
    uid = message.from_user.id if message.from_user else 0
    if ctype == ChatType.PRIVATE:
        return _is_owner(uid)
    if ctype in (ChatType.GROUP, ChatType.SUPERGROUP):
        return cid in ALLOWED_GROUP_IDS
    return False


def _user_allowed(message: Message) -> bool:
    """Foydalanuvchi (chat + PIN) muvofiqmi?"""
    if not _chat_allowed(message):
        return False
    uid = message.from_user.id if message.from_user else 0
    # DM'da OWNER avtomatik auth (PIN'siz)
    if message.chat.type == ChatType.PRIVATE and _is_owner(uid):
        return True
    # Gruppada — har user alohida PIN bilan
    return _is_authed(uid)


async def _send_long(message: Message, text: str) -> None:
    """Uzun javobni qismlarga bo'lib yuborish."""
    while text:
        chunk = text[:TG_MSG_MAX]
        text = text[TG_MSG_MAX:]
        try:
            await message.answer(chunk, parse_mode=None)
        except Exception as e:
            logger.error(f"send fail: {e}")
            break


def _register_handlers(dp: Dispatcher) -> None:
    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        if not _chat_allowed(message):
            _audit(message.chat.id, message.from_user.id, "denied_start")
            return
        if _user_allowed(message):
            await message.answer(
                "Salom! Senior Assistant tayyor.\n"
                "Savol bering yoki /help."
            )
        else:
            await message.answer(
                "Salom! TOTLI BI Senior Assistant.\n"
                "Avval auth: /pin <raqam>\n"
                "Masalan: /pin 2712"
            )

    @dp.message(Command("help"))
    async def cmd_help(message: Message):
        if not _chat_allowed(message):
            return
        await message.answer(
            "Buyruqlar:\n"
            "/pin <raqam> — gruppada PIN bilan auth\n"
            "/ask <savol> — 11 ekspert bilan kengashib javob\n"
            "/expert <nom> — bitta ekspert nuqtai nazari\n"
            "/team — 11 ekspert ro'yxati\n"
            "/memory — MEMORY.md\n"
            "/status — auth, sessiya, ekspert\n"
            "/whoami — chat ID (gruppa qo'shish uchun)\n"
            "/reset — bugungi suhbat tarixini arxivlash\n"
            "/audit — so'nggi audit log\n\n"
            "DM'da oddiy matn ham yuborilsa, savol sifatida qabul qilinadi.",
            parse_mode=None,
        )

    @dp.message(Command("whoami"))
    async def cmd_whoami(message: Message):
        # Bu buyruq har kim uchun ochiq — gruppani sozlashda kerak
        uid = message.from_user.id if message.from_user else 0
        cid = message.chat.id
        ctype = message.chat.type
        cname = message.chat.title or message.chat.full_name or "?"
        await message.answer(
            f"Chat ma'lumotlari:\n"
            f"- Chat ID: `{cid}`\n"
            f"- Turi: {ctype}\n"
            f"- Nomi: {cname}\n"
            f"- Sizning User ID: `{uid}`\n"
            f"- Ruxsat: {'HA' if _chat_allowed(message) else 'Yo`q'}\n",
            parse_mode=None,
        )

    @dp.message(Command("status"))
    async def cmd_status(message: Message):
        if not _chat_allowed(message):
            return
        uid = message.from_user.id
        s = _auth_state.get(uid, {})
        left = max(0, int(s.get("auth_until", 0) - time.time()))
        ex = s.get("expert") or "11 ekspert"
        await message.answer(
            f"Holat:\n"
            f"- Auth: {'OK' if _user_allowed(message) else 'Yo`q'} "
            f"(qoldi: {left // 60} daq)\n"
            f"- Ekspert: {ex}\n"
            f"- Model: `{claude_client.DEFAULT_MODEL}`\n"
            f"- Chat: `{message.chat.id}`",
            parse_mode=None,
        )

    @dp.message(Command("team"))
    async def cmd_team(message: Message):
        if not _chat_allowed(message):
            return
        if not _user_allowed(message):
            await message.answer("Avval /pin <raqam> bilan auth qiling.")
            return
        await _send_long(message, experts.list_experts())

    @dp.message(Command("expert"))
    async def cmd_expert(message: Message, command: CommandObject):
        if not _user_allowed(message):
            return
        arg = (command.args or "").strip()
        if not arg:
            cur = _auth_state.get(message.from_user.id, {}).get("expert") or "11 ekspert"
            await message.answer(
                f"Joriy ekspert: {cur}\n"
                "O'zgartirish: `/expert Anvar` yoki `/expert all` (11 ekspert)",
                parse_mode=None,
            )
            return
        s = _auth_state.setdefault(message.from_user.id, {"auth_until": 0})
        if arg.lower() == "all":
            s["expert"] = None
            await message.answer("Yoqildi: 11 ekspert bilan kengashish.")
            return
        ex = next((e for e in experts.EXPERTS if e["name"].lower() == arg.lower()), None)
        if not ex:
            await message.answer(f"Ekspert topilmadi: {arg}. /team — ro'yxat.")
            return
        s["expert"] = ex["name"]
        _audit(message.chat.id, message.from_user.id, "expert_switch", ex["name"])
        await message.answer(f"Yoqildi: {ex['name']} ({ex['role']}).")

    @dp.message(Command("memory"))
    async def cmd_memory(message: Message):
        if not _user_allowed(message):
            return
        # MEMORY.md'ni o'qib, eng yangi 30 qatorni ko'rsatish
        mem_path = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~")) / ".claude" / "projects" / "--server2220-d-TOTLI-BI" / "memory" / "MEMORY.md"
        if not mem_path.exists():
            await message.answer("MEMORY.md topilmadi.")
            return
        try:
            lines = mem_path.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            await message.answer(f"O'qish xato: {e}")
            return
        last = lines[-25:]
        await _send_long(message, "Memory (so'nggi 25 qator):\n```\n" + "\n".join(last) + "\n```")

    @dp.message(Command("audit"))
    async def cmd_audit(message: Message):
        if not _user_allowed(message):
            return
        if not AUDIT_LOG.exists():
            await message.answer("Audit log hali bo'sh.")
            return
        try:
            lines = AUDIT_LOG.read_text(encoding="utf-8").splitlines()[-15:]
        except OSError as e:
            await message.answer(f"O'qish xato: {e}")
            return
        await _send_long(message, "So'nggi audit:\n```\n" + "\n".join(lines) + "\n```")

    @dp.message(Command("reset"))
    async def cmd_reset(message: Message):
        if not _user_allowed(message):
            return
        conv.reset(message.chat.id)
        claude_client.reset_session(message.chat.id)
        _audit(message.chat.id, message.from_user.id, "reset")
        await message.answer("Suhbat tozalandi. Yangi kontekst boshlandi.")

    @dp.message(Command("pin"))
    async def cmd_pin(message: Message, command: CommandObject):
        if not _chat_allowed(message):
            return
        uid = message.from_user.id
        arg = (command.args or "").strip()
        if not arg:
            await message.answer("Foydalanish: /pin <raqam>")
            return
        if PIN and arg == PIN:
            _set_authed(uid)
            _audit(message.chat.id, uid, "auth_success_pin")
            await message.answer("PIN to'g'ri. 12 soat avtorizatsiya.")
        else:
            _audit(message.chat.id, uid, "auth_failed_pin")
            await message.answer("PIN noto'g'ri.")
        await _delete_pin_message(message)

    @dp.message(Command("ask"))
    async def cmd_ask(message: Message, command: CommandObject):
        if not _chat_allowed(message):
            return
        if not _user_allowed(message):
            await message.answer("Avval /pin <raqam> bilan auth qiling.")
            return
        question = (command.args or "").strip()
        if not question:
            await message.answer("Foydalanish: /ask <savol>")
            return
        await _handle_question(message, question)

    @dp.message(F.text & ~F.text.startswith("/"))
    async def on_text(message: Message):
        uid = message.from_user.id if message.from_user else 0
        cid = message.chat.id
        text = (message.text or "").strip()

        # PIN auth?
        if _chat_allowed(message) and not _user_allowed(message):
            if text.isdigit() and text == PIN:
                _set_authed(uid)
                _audit(cid, uid, "auth_success")
                await message.answer("PIN to'g'ri. 12 soat avtorizatsiya.")
                await _delete_pin_message(message)
                return
            elif text.isdigit():
                _audit(cid, uid, "auth_failed")
                await message.answer("PIN noto'g'ri.")
                await _delete_pin_message(message)
                return
            else:
                await message.answer("Avval PIN kiriting.")
                return

        if not _user_allowed(message):
            return

        # Gruppada: SENIOR_BOT_GROUP_RESPOND_ALL=1 (default) bo'lsa har oddiy matnga
        # javob beradi (maxsus bot gruppasi uchun). 0 bo'lsa — faqat @mention/reply.
        if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            bot_username = (await message.bot.me()).username or ""
            raw_text = message.text or ""
            is_mention = bool(bot_username) and f"@{bot_username}" in raw_text
            is_reply_to_bot = (
                message.reply_to_message is not None
                and message.reply_to_message.from_user is not None
                and message.reply_to_message.from_user.id == message.bot.id
            )
            # Boshqa bot @mention qilingan (masalan @Kamila_UX_bot) — bu ekspert
            # botga yo'naltirilgan, asosiy Yordamchim aralashmasin (ikki javob bo'lmasin).
            import re as _re
            other_bot_mentioned = False
            for m in _re.findall(r"@(\w+)", raw_text):
                if m.lower() != bot_username.lower() and m.lower().endswith("bot"):
                    other_bot_mentioned = True
                    break
            if other_bot_mentioned and not is_mention:
                return
            # @mention bor bo'lsa har doim olib tashlaymiz
            if bot_username:
                text = text.replace(f"@{bot_username}", "").strip()
            if not RESPOND_ALL:
                if not (is_mention or is_reply_to_bot):
                    return
            # Juda qisqa "ok", emoji kabi shovqinni o'tkazib yuborish
            if len(text) < 3:
                return

        await _handle_question(message, text)


async def _handle_question(message: Message, question: str) -> None:
    cid = message.chat.id
    uid = message.from_user.id if message.from_user else 0
    user_name = (message.from_user.full_name or message.from_user.username or "?") if message.from_user else "?"

    if uid in _in_flight:
        await message.answer("Avvalgi savol hali ishlanmoqda. Kuting yoki /reset.")
        return
    _in_flight.add(uid)
    try:
        _audit(cid, uid, "ask", question[:200])
        conv.append_user(cid, user_name, uid, question)

        try:
            await message.bot.send_chat_action(cid, "typing")
        except Exception:
            pass

        focus = (_auth_state.get(uid, {}) or {}).get("expert")
        system_prompt = experts.build_system_prompt(focus_expert=focus)
        # CLI subprocess kontekstni --resume orqali Claude tomonida saqlaydi —
        # history yuborish shart emas. conversation_store faqat shaffoflik uchun.

        try:
            answer, meta = await claude_client.ask(cid, question, system_prompt)
        except Exception as e:
            logger.exception("Claude CLI fail")
            _audit(cid, uid, "cli_error", str(e)[:200])
            await message.answer(f"Xato: {e}")
            return

        conv.append_assistant(cid, answer, meta)
        _audit(cid, uid, "answer", f"in={meta.get('input_tokens')} out={meta.get('output_tokens')}")
        await _send_long(message, answer)
    finally:
        _in_flight.discard(uid)


async def start_senior_bot() -> None:
    """Main entrypoint — uvicorn startup'dan chaqiriladi."""
    global _bot, _dp, _task
    if not TOKEN:
        logger.warning("[Senior Bot] CLAUDE_BOT_TOKEN .env'da yo'q — bot yuklanmaydi")
        return
    # CLI subprocess rejimi — ANTHROPIC_API_KEY shart emas, mavjud `claude` CLI (Max obuna) ishlatiladi
    if _task is not None and not _task.done():
        logger.info("[Senior Bot] allaqachon ishlamoqda")
        return

    _bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=None))
    _dp = Dispatcher(storage=MemoryStorage())
    _register_handlers(_dp)
    try:
        me = await _bot.get_me()
        logger.info(f"[Senior Bot] @{me.username} ishga tushdi (model={claude_client.DEFAULT_MODEL})")
    except Exception as e:
        logger.error(f"[Senior Bot] get_me fail: {e}")
        return
    _task = asyncio.create_task(_dp.start_polling(_bot, handle_signals=False))


async def stop_senior_bot() -> None:
    global _bot, _dp, _task
    if _dp:
        try:
            await _dp.stop_polling()
        except Exception:
            pass
    if _bot:
        try:
            await _bot.session.close()
        except Exception:
            pass
    if _task and not _task.done():
        _task.cancel()
    _bot = _dp = _task = None
