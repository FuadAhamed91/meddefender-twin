"""WebSocket event stream with resynchronisation.

Protocol
* Connect to ``/ws/events?since=<last_event_id>`` with the session cookie. The Origin header
  must be an allowed origin (prevents cross-site WebSocket hijacking).
* Server sends ``{"type": "hello", "latest_event_id", "epoch"}``, then any missed events
  with id > since (from the persisted event_log), then live events.
* If the gap is too large or too old, the server sends ``{"type": "resync_required"}``; the
  client should fetch ``GET /api/v1/twin/state`` and reconnect with the returned id.
* The session is re-validated periodically; revoked or expired sessions are disconnected.
* No secrets are ever sent.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select

from app.api.deps import SESSION_COOKIE
from app.models import EventLogEntry
from app.services.auth import resolve_session
from app.services.context import AppServices
from app.services.events import event_message
from app.services.queries import current_epoch

router = APIRouter()
HEARTBEAT_SECONDS = 20


def _backlog(
    services: AppServices, since: int, limit: int
) -> tuple[list[dict[str, Any]], bool, int, int]:
    with services.session_factory() as session:
        latest = session.scalar(select(func.max(EventLogEntry.id))) or 0
        oldest = session.scalar(select(func.min(EventLogEntry.id))) or 0
        epoch = current_epoch(session)
        if since >= latest:
            return [], False, latest, epoch
        if oldest and since < oldest - 1:
            return [], True, latest, epoch  # events were pruned: client must resync
        rows = session.scalars(
            select(EventLogEntry)
            .where(EventLogEntry.id > since)
            .order_by(EventLogEntry.id)
            .limit(limit + 1)
        ).all()
        if len(rows) > limit:
            return [], True, latest, epoch
        return [event_message(r) for r in rows], False, latest, epoch


@router.websocket("/ws/events")
async def events(websocket: WebSocket, since: int | None = None) -> None:
    services: AppServices = websocket.app.state.services
    origin = websocket.headers.get("origin")
    if origin is None or origin not in services.settings.allowed_origins:
        await websocket.close(code=4403, reason="origin not allowed")
        return
    token = websocket.cookies.get(SESSION_COOKIE)
    principal = await run_in_threadpool(resolve_session, services, token)
    if principal is None:
        await websocket.close(code=4401, reason="authentication required")
        return
    await websocket.accept()
    queue = services.bus.subscribe()
    last_sent = since or 0
    try:
        backlog, overflow, latest, epoch = await run_in_threadpool(
            _backlog,
            services,
            since if since is not None else 10**18,
            services.settings.event_backlog_limit,
        )
        await websocket.send_json(
            {"type": "hello", "latest_event_id": latest, "epoch": epoch, "user": principal.username}
        )
        if since is not None:
            if overflow:
                await websocket.send_json(
                    {
                        "type": "resync_required",
                        "reason": "backlog unavailable",
                        "latest_event_id": latest,
                    }
                )
                last_sent = latest
            for message in backlog:
                await websocket.send_json(message)
                last_sent = message["id"]
        else:
            last_sent = latest

        receiver = asyncio.create_task(_drain_client(websocket))
        try:
            while not receiver.done():
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    still_valid = await run_in_threadpool(resolve_session, services, token)
                    if still_valid is None:
                        await websocket.close(code=4401, reason="session ended")
                        return
                    await websocket.send_json({"type": "heartbeat", "latest_event_id": last_sent})
                    continue
                message_id = message.get("id")
                if isinstance(message_id, int):
                    if message_id <= last_sent:
                        continue
                    last_sent = message_id
                await websocket.send_json(message)
        finally:
            receiver.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await receiver
    except WebSocketDisconnect:
        pass
    finally:
        services.bus.unsubscribe(queue)


async def _drain_client(websocket: WebSocket) -> None:
    """Consume client frames (pings) so a disconnect is noticed promptly."""
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        while True:
            await websocket.receive_text()
