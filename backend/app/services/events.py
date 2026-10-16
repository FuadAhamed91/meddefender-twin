"""Real-time event bus.

Events are persisted to ``event_log`` inside the producing transaction and published to
WebSocket subscribers only after that transaction commits, so clients never see state that
was rolled back. Publishing is thread-safe: domain code runs in worker threads, subscribers
live on the asyncio loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import EventLogEntry

logger = logging.getLogger(__name__)


def event_message(entry: EventLogEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "type": entry.event_type,
        "created_at": entry.created_at.isoformat(),
        "payload": entry.payload,
    }


class EventBus:
    def __init__(self, queue_size: int = 1000) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._queue_size = queue_size

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, messages: list[dict[str, Any]]) -> None:
        if not messages or self._loop is None or self._loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._fan_out(messages)
        else:
            self._loop.call_soon_threadsafe(self._fan_out, messages)

    def _fan_out(self, messages: list[dict[str, Any]]) -> None:
        for queue in list(self._subscribers):
            for message in messages:
                try:
                    queue.put_nowait(message)
                except asyncio.QueueFull:
                    # Slow consumer: tell it to resynchronise rather than block producers.
                    logger.warning("WebSocket subscriber queue full; forcing resync")
                    with contextlib.suppress(asyncio.QueueEmpty):
                        while True:
                            queue.get_nowait()
                    queue.put_nowait({"type": "resync_required", "reason": "client too slow"})
                    break


def record_event(
    session: Session, created_at: datetime, event_type: str, payload: dict[str, Any]
) -> EventLogEntry:
    entry = EventLogEntry(created_at=created_at, event_type=event_type, payload=payload)
    session.add(entry)
    return entry
