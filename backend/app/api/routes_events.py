"""Live events over HTTP polling, for hosts without WebSocket support (serverless).

``GET /api/v1/events?since=<id>`` returns the persisted events after ``since`` (exactly the
messages the WebSocket sends) or ``resync_required`` when the gap is too large, in which case
the client reloads ``/api/v1/twin/state``. On a serverless host there is no background loop,
so a poll also advances the simulation when a generator tick is due.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_services, viewer
from app.api.ws import _backlog
from app.services.auth import Principal
from app.services.context import AppServices

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["live"])


@router.get("/events")
def poll_events(
    request: Request,
    since: int = Query(0, ge=0),
    _: Principal = Depends(viewer),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    runtime = getattr(request.app.state, "runtime", None)
    if services.settings.serverless and runtime is not None:
        try:
            runtime.tick_if_due()
        except Exception:  # the poll must still answer even if the simulation step fails
            logger.exception("Simulation tick during poll failed")
    events, overflow, latest, epoch = _backlog(
        services, since, services.settings.event_backlog_limit
    )
    return {
        "latest_event_id": latest,
        "epoch": epoch,
        "resync_required": overflow,
        "events": [] if overflow else events,
    }
