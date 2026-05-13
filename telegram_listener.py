"""Telethon userbot that listens for XAUUSD signals in specified groups."""
import logging
from typing import Awaitable, Callable, List, Optional

from telethon import TelegramClient, events
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str], Awaitable[None]]


def _coerce_group_id(g: str):
    """Group IDs may be numeric (e.g. -1001234567890) or usernames (@foo)."""
    g = g.strip()
    if g.lstrip("-").isdigit():
        return int(g)
    return g


class TelegramListener:
    def __init__(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        group_ids: List[str],
        session_string: Optional[str] = None,
    ):
        self.phone = phone
        self.group_ids = [_coerce_group_id(g) for g in group_ids]
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        self.client = TelegramClient(
            StringSession(session_string) if session_string else StringSession(),
            api_id,
            api_hash,
            loop=loop,
        )
        self.on_message: Optional[MessageHandler] = None
        self.on_ready: Optional[Callable[[], Awaitable[None]]] = None
        self._handler_registered = False

    def _register_handler(self):
        """Register the NewMessage handler exactly once."""
        if self._handler_registered:
            return

        @self.client.on(events.NewMessage(chats=self.group_ids))
        async def _handler(event):
            text = event.message.text or ""
            if not text:
                return
            logger.info(f"Message from {event.chat_id}: {text[:200]!r}")
            if self.on_message:
                try:
                    await self.on_message(text)
                except Exception:
                    logger.exception("on_message handler raised")

        self._handler_registered = True

    async def start(self):
        await self.client.start(phone=lambda: self.phone)
        me = await self.client.get_me()
        logger.info(
            f"Telegram listener connected as {me.username or me.first_name} "
            f"({me.id}). Monitoring groups: {self.group_ids}"
        )
        self._register_handler()
        logger.info("Listening for signals...")
        if self.on_ready:
            try:
                await self.on_ready()
            except Exception:
                logger.exception("on_ready handler raised")
        await self.client.run_until_disconnected()
