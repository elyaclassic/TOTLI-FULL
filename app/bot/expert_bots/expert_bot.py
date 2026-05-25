"""ExpertBot — har bir virtual ekspert uchun alohida Telegram bot.

Gruppa: faqat @mention yoki reply bo'lganda javob beradi.
DM: owner uchun to'g'ridan-to'g'ri.
Xotira: data/expert_memories/<name>.md faylida saqlanadi.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

from app.bot.senior_bot import claude_client, experts
from app.bot.expert_bots import group_logger

logger = logging.getLogger(__name__)

CWD = Path(os.environ.get("CLAUDE_BOT_CWD") or os.getcwd())
DATA_DIR = CWD / "app" / "bot" / "data"
MEMORY_DIR = DATA_DIR / "expert_memories"
CONV_DIR = CWD / "conversations" / "experts"
AUTH_TTL_SECONDS = 12 * 3600
TG_MSG_MAX = 4000
PIN = os.environ.get("CLAUDE_BOT_PIN", "")
TYPING_INTERVAL = 4  # sekund — typing action qayta yuborish

OWNER_IDS: set[int] = set()
for _raw in (os.environ.get("CLAUDE_OWNER_ID", "") or "").split(","):
    _raw = _raw.strip()
    if _raw.isdigit():
        OWNER_IDS.add(int(_raw))

ALLOWED_GROUP_IDS: set[int] = set()
for _raw in (os.environ.get("SENIOR_BOT_GROUP_IDS", "") or "").split(","):
    _raw = _raw.strip()
    try:
        if _raw:
            ALLOWED_GROUP_IDS.add(int(_raw))
    except ValueError:
        pass


class ExpertBot:
    """Bitta ekspert uchun Telegram bot."""

    def __init__(self, expert_name: str, token: str) -> None:
        ex = next(
            (e for e in experts.EXPERTS if e["name"].lower() == expert_name.lower()),
            None,
        )
        if not ex:
            raise ValueError(f"Ekspert topilmadi: {expert_name}")
        self.expert = ex
        self.token = token
        self._bot: Optional[Bot] = None
        self._dp: Optional[Dispatcher] = None
        self._task: Optional[asyncio.Task] = None
        self._auth_state: dict[int, float] = {}  # uid → auth_until timestamp
        self._in_flight: set[int] = set()
        self._bot_username: str = ""  # cache — bot.me() bir marta chaqiriladi

        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        CONV_DIR.mkdir(parents=True, exist_ok=True)
        self._memory_file = MEMORY_DIR / f"{self.name.lower()}.md"

    @property
    def name(self) -> str:
        return self.expert["name"]

    # ── Auth ──────────────────────────────────────────────────────────────

    def _is_authed(self, uid: int) -> bool:
        return self._auth_state.get(uid, 0) > time.time()

    def _set_authed(self, uid: int) -> None:
        self._auth_state[uid] = time.time() + AUTH_TTL_SECONDS

    def _chat_allowed(self, message: Message) -> bool:
        ctype = message.chat.type
        uid = message.from_user.id if message.from_user else 0
        if ctype == ChatType.PRIVATE:
            return uid in OWNER_IDS
        if ctype in (ChatType.GROUP, ChatType.SUPERGROUP):
            return not ALLOWED_GROUP_IDS or message.chat.id in ALLOWED_GROUP_IDS
        return False

    def _user_allowed(self, message: Message) -> bool:
        if not self._chat_allowed(message):
            return False
        uid = message.from_user.id if message.from_user else 0
        if message.chat.type == ChatType.PRIVATE and uid in OWNER_IDS:
            return True
        return self._is_authed(uid)

    # ── Conversation log ──────────────────────────────────────────────────

    def _conv_path(self, chat_id: int) -> Path:
        return CONV_DIR / f"{date.today().isoformat()}_{self.name.lower()}_{chat_id}.md"

    def _conv_append(self, chat_id: int, role: str, author: str, text: str) -> None:
        p = self._conv_path(chat_id)
        ts = datetime.now().strftime("%H:%M")
        if role == "user":
            block = f"\n## {ts} — {author}\n{text.strip()}\n"
        else:
            block = f"\n### {ts} — {self.name}\n{text.strip()}\n"
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(block)
        except OSError as e:
            logger.error(f"[{self.name}] conv write fail: {e}")

    # ── Memory ────────────────────────────────────────────────────────────

    def _read_memory(self) -> str:
        try:
            if self._memory_file.exists():
                return self._memory_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
        return ""

    def _append_memory(self, text: str) -> None:
        try:
            with self._memory_file.open("a", encoding="utf-8") as f:
                f.write(f"\n{text}")
        except OSError as e:
            logger.error(f"[{self.name}] memory write fail: {e}")

    def _build_system_prompt(self) -> str:
        base = experts.build_system_prompt(focus_expert=self.name)
        mem = self._read_memory()
        if mem:
            base += f"\n\n## Mening xotiram (oldingi suhbatlardan):\n{mem}"
        return base

    # ── Helpers ───────────────────────────────────────────────────────────

    def _is_cmd_for_me(self, message: Message, command: CommandObject) -> bool:
        """Gruppada buyruq faqat shu botga yo'naltirilganmi?"""
        if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            return True
        if command.mention:
            return command.mention.lower() == self._bot_username.lower()
        # mention yo'q → faqat /pin hammaga ruxsat (auth uchun)
        return command.command.lower() == "pin"

    async def _send_long(self, message: Message, text: str) -> None:
        while text:
            chunk, text = text[:TG_MSG_MAX], text[TG_MSG_MAX:]
            try:
                await message.answer(chunk, parse_mode=None)
            except Exception as e:
                logger.error(f"[{self.name}] send fail: {e}")
                break

    def _session_key(self, chat_id: int) -> str:
        return f"{self.name.lower()}_{chat_id}"

    async def _keep_typing(self, chat_id: int, stop_event: asyncio.Event) -> None:
        """Claude ishlab turganida typing action yuborib turadi."""
        while not stop_event.is_set():
            try:
                await self._bot.send_chat_action(chat_id, "typing")
            except Exception:
                pass
            try:
                await asyncio.wait_for(
                    asyncio.shield(stop_event.wait()), timeout=TYPING_INTERVAL
                )
            except asyncio.TimeoutError:
                pass

    async def _handle_question(self, message: Message, question: str) -> None:
        uid = message.from_user.id if message.from_user else 0
        cid = message.chat.id

        if uid in self._in_flight:
            await message.answer(
                "Javob tayyorlanmoqda, biroz kuting... (~30-60 sek)"
            )
            return

        user_name = (message.from_user.full_name or message.from_user.username or "?") if message.from_user else "?"
        self._conv_append(cid, "user", user_name, question)

        self._in_flight.add(uid)
        stop_typing = asyncio.Event()
        typing_task = asyncio.create_task(self._keep_typing(cid, stop_typing))
        try:
            answer, _ = await claude_client.ask(
                self._session_key(cid),
                question,
                self._build_system_prompt(),
            )
            self._conv_append(cid, "assistant", self.name, answer)
            await self._send_long(message, answer)
            asyncio.create_task(self._auto_memorize(question, answer))
        except Exception as e:
            logger.exception(f"[{self.name}] Claude xato")
            await message.answer(f"Xato: {e}")
        finally:
            stop_typing.set()
            typing_task.cancel()
            self._in_flight.discard(uid)

    async def _auto_memorize(self, question: str, answer: str) -> None:
        """Suhbatdan muhim ma'lumotni ajratib xotiraga yozadi."""
        extract_prompt = (
            f"Quyidagi suhbatdan '{self.name}' ekspert sifatida kelajakda foydali bo'ladigan "
            f"aniq faktlarni ajrat (masalan: foydalanuvchi tanlagan yechim, muhim qaror, "
            f"loyiha haqida yangi ma'lumot). "
            f"Agar muhim narsa yo'q bo'lsa faqat 'yo'q' de. "
            f"Aks holda qisqa bullet list (har biri 1 qator).\n\n"
            f"Savol: {question[:300]}\n"
            f"Javob: {answer[:500]}"
        )
        try:
            mem_key = f"{self.name.lower()}_memory_extract"
            result, _ = await claude_client.ask(mem_key, extract_prompt, "")
            result = result.strip()
            if result and result.lower() not in ("yo'q", "yoq", "no", "none", ""):
                timestamp = __import__("datetime").date.today().isoformat()
                self._append_memory(f"\n### {timestamp}\n{result}")
        except Exception as e:
            logger.warning(f"[{self.name}] auto_memorize fail: {e}")

    # ── Handlers ──────────────────────────────────────────────────────────

    def _register_handlers(self, dp: Dispatcher) -> None:

        @dp.message(Command("start"))
        async def cmd_start(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            if not self._chat_allowed(message):
                return
            if self._user_allowed(message):
                await message.answer(
                    f"Salom! Men — {self.name} ({self.expert['role']}).\n"
                    f"Savol bering yoki /help.",
                    parse_mode=None,
                )
            else:
                await message.answer(
                    f"Salom! Men — {self.name}.\nAvval auth: /pin <raqam>",
                    parse_mode=None,
                )

        @dp.message(Command("help"))
        async def cmd_help(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            if not self._chat_allowed(message):
                return
            await message.answer(
                f"Men — {self.name} ({self.expert['role']})\n"
                f"Fokus: {self.expert['focus']}\n\n"
                "Buyruqlar:\n"
                "/pin <raqam> — auth (guruhda)\n"
                "/ask <savol> — savol berish\n"
                "/memory — xotiramni ko'rish\n"
                "/remember <matn> — xotiraga yozish (faqat owner)\n"
                "/reset — suhbatni tozalash\n"
                "/whoami — chat va user ID\n\n"
                "Guruhda: @mention yoki reply orqali ham savollarni yuborishingiz mumkin.",
                parse_mode=None,
            )

        @dp.message(Command("whoami"))
        async def cmd_whoami(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            uid = message.from_user.id if message.from_user else 0
            await message.answer(
                f"Chat ID: {message.chat.id}\nUser ID: {uid}\nBot: {self.name}",
                parse_mode=None,
            )

        @dp.message(Command("pin"))
        async def cmd_pin(message: Message, command: CommandObject):
            if not self._chat_allowed(message):
                return
            uid = message.from_user.id if message.from_user else 0
            arg = (command.args or "").strip()
            # Gruppada keng /pin (bu botga aniq @mention qilinmagan) → JIM auth.
            # Faqat asosiy Yordamchim "PIN to'g'ri" deydi; ekspert botlar
            # jim avtorizatsiya qiladi (6 ta dublikat tasdiq spam'ini oldini olish).
            is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
            targeted = bool(command.mention) and command.mention.lower() == self._bot_username.lower()
            silent = is_group and not targeted
            if PIN and arg == PIN:
                self._set_authed(uid)
                if not silent:
                    await message.answer("PIN to'g'ri. 12 soat avtorizatsiya.")
            elif not silent:
                await message.answer("PIN noto'g'ri.")

        @dp.message(Command("ask"))
        async def cmd_ask(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            if not self._chat_allowed(message):
                return
            if not self._user_allowed(message):
                await message.answer("Avval /pin <raqam> bilan auth qiling.")
                return
            question = (command.args or "").strip()
            if not question:
                await message.answer("Foydalanish: /ask <savol>")
                return
            await self._handle_question(message, question)

        @dp.message(Command("memory"))
        async def cmd_memory(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            if not self._user_allowed(message):
                return
            mem = self._read_memory()
            await self._send_long(message, f"Xotiram:\n{mem or '(bo`sh)'}")

        @dp.message(Command("remember"))
        async def cmd_remember(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            if not self._user_allowed(message):
                return
            uid = message.from_user.id if message.from_user else 0
            if uid not in OWNER_IDS:
                return
            note = (command.args or "").strip()
            if not note:
                await message.answer("Foydalanish: /remember <matn>")
                return
            self._append_memory(f"- {note}")
            await message.answer("Xotiraga yozildi.")

        @dp.message(Command("reset"))
        async def cmd_reset(message: Message, command: CommandObject):
            if not self._is_cmd_for_me(message, command):
                return
            if not self._user_allowed(message):
                return
            claude_client.reset_session(self._session_key(message.chat.id))
            await message.answer("Suhbat tozalandi.")

        @dp.message(F.text)
        async def on_text(message: Message):
            # Barcha guruh xabarlarini log qilamiz (dedup — faqat bir marta yoziladi)
            if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                group_logger.log_message(message)

            if (message.text or "").startswith("/"):
                return

            uid = message.from_user.id if message.from_user else 0
            text = (message.text or "").strip()

            if self._chat_allowed(message) and not self._user_allowed(message):
                # Gruppada ekspert botlar jim — faqat asosiy Yordamchim javob beradi.
                _is_group = message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP)
                if text.isdigit() and PIN and text == PIN:
                    self._set_authed(uid)
                    if not _is_group:
                        await message.answer("PIN to'g'ri. 12 soat avtorizatsiya.")
                elif not _is_group:
                    if text.isdigit():
                        await message.answer("PIN noto'g'ri.")
                    else:
                        await message.answer("Avval /pin <raqam> bilan auth qiling.")
                return

            if not self._user_allowed(message):
                return

            # Gruppada: faqat @mention yoki reply
            if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                uname = self._bot_username
                is_mention = bool(uname) and f"@{uname}" in (message.text or "")
                is_reply = (
                    message.reply_to_message is not None
                    and message.reply_to_message.from_user is not None
                    and message.reply_to_message.from_user.id == self._bot.id
                )
                if not (is_mention or is_reply):
                    return
                if uname:
                    text = text.replace(f"@{uname}", "").strip()

            if len(text) < 3:
                return

            await self._handle_question(message, text)

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        if not self.token:
            logger.warning(f"[{self.name}] token yo'q — yuklanmaydi")
            return
        if self._task and not self._task.done():
            return

        self._bot = Bot(token=self.token, default=DefaultBotProperties(parse_mode=None))
        self._dp = Dispatcher(storage=MemoryStorage())
        self._register_handlers(self._dp)

        try:
            me = await self._bot.get_me()
            self._bot_username = me.username or ""  # cache
            logger.info(f"[ExpertBot] {self.name} → @{me.username} ishga tushdi")
        except Exception as e:
            logger.error(f"[ExpertBot] {self.name} get_me fail: {e}")
            return

        self._task = asyncio.create_task(
            self._dp.start_polling(self._bot, handle_signals=False)
        )

    async def stop(self) -> None:
        if self._dp:
            try:
                await self._dp.stop_polling()
            except Exception:
                pass
        if self._bot:
            try:
                await self._bot.session.close()
            except Exception:
                pass
        if self._task and not self._task.done():
            self._task.cancel()
        self._bot = self._dp = self._task = None
