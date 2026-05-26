"""Realtime event bus — Dashboard v2 WebSocket broadcast.

Sotuv/Production/CashTransfer kabi event'lar shu erga publish qilinadi va
subscribed WebSocket clients (admin/manager dashboardlar)ga broadcast yuboriladi.

publish_sync() — sync kontekstda chaqirish uchun (transaction commit'dan keyin).
publish() — async kontekstda.

Fail-safe: agar broadcast xato bersa, asosiy operatsiya tegmasligi uchun
try/except bilan o'rab chaqirish kerak (event hook tomonidan).
"""
import asyncio
import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ConnectionManager:
    """WebSocket clients ro'yxatini boshqaradi va broadcast yuboradi."""

    def __init__(self) -> None:
        self._clients: set = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Asosiy event loop ni saqlash — sync chaqiruvlar uchun."""
        self._loop = loop

    async def connect(self, websocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)
        logger.info(f"[realtime] +1 client (jami: {len(self._clients)})")

    def disconnect(self, websocket) -> None:
        self._clients.discard(websocket)
        logger.info(f"[realtime] -1 client (jami: {len(self._clients)})")

    async def broadcast(self, message: dict) -> None:
        """Barcha subscribed clientlarga yuborish."""
        if not self._clients:
            return
        data = json.dumps(message, default=str)
        dead = []
        for ws in list(self._clients):
            try:
                await ws.send_text(data)
            except Exception as e:
                logger.warning(f"[realtime] send fail, removing client: {e}")
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    def publish_sync(self, event_type: str, payload: Optional[dict] = None) -> None:
        """Sync kontekstdan chaqirish — transaction commit'dan keyin.

        Loop o'rnatilgan bo'lsa, broadcast'ni schedule qiladi. Bo'lmasa silent skip.
        Asosiy operatsiya tegmasin uchun hech qanday exception qaytarmaydi.
        """
        try:
            if not self._loop or not self._clients:
                return
            message = {"type": event_type, "payload": payload or {}}
            asyncio.run_coroutine_threadsafe(self.broadcast(message), self._loop)
        except Exception as e:
            logger.warning(f"[realtime] publish_sync fail (silent): {e}")

    async def publish(self, event_type: str, payload: Optional[dict] = None) -> None:
        """Async kontekstdan chaqirish."""
        try:
            await self.broadcast({"type": event_type, "payload": payload or {}})
        except Exception as e:
            logger.warning(f"[realtime] publish fail (silent): {e}")

    @property
    def client_count(self) -> int:
        return len(self._clients)


# Singleton
bus = ConnectionManager()


def publish_event(event_type: str, payload: Optional[dict] = None) -> None:
    """Tashqi modullar uchun qulay helper. Silent fail."""
    try:
        bus.publish_sync(event_type, payload)
    except Exception:
        pass
