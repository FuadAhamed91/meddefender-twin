from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import correlation_id, db_session, get_services, viewer
from app.core.errors import AppError, NotFound
from app.models import TelemetryEvent
from app.models.enums import IngestChannel, TelemetryDecision
from app.schemas.api import (
    EnrollmentRequestIn,
    ErrorResponse,
    IngestResponse,
    TelemetryEventDetail,
    TelemetryEventOut,
)
from app.services.administration import submit_enrollment
from app.services.auth import Principal
from app.services.context import AppServices
from app.services.ingestion import InboundMessage

router = APIRouter(prefix="/api/v1", tags=["telemetry"])

STATUS_BY_REASON = {
    "PAYLOAD_TOO_LARGE": 413,
    "MALFORMED": 400,
    "REPLAY_DUPLICATE": 409,
    "DUPLICATE_NONCE": 409,
    "SEQUENCE_REUSED": 409,
    "OUT_OF_SEQUENCE": 409,
    "SEQUENCE_GAP": 409,
    "STALE": 409,
    "FUTURE_TIMESTAMP": 409,
    "SCHEMA_INVALID": 422,
    "OUT_OF_RANGE": 422,
    "INCONSISTENT": 422,
    "POLICY_DENIED": 403,
    "TRUST_GATE": 403,
    "MESSAGE_TYPE_NOT_PERMITTED": 403,
}


async def read_limited_body(request: Request, limit: int) -> bytes:
    """Read at most ``limit + 1`` bytes so oversized bodies are detected without buffering them."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise AppError(413, "PAYLOAD_TOO_LARGE", f"Body exceeds {limit} bytes.")
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            break
    return b"".join(chunks)[: limit + 1]


@router.post(
    "/telemetry/ingest",
    status_code=202,
    response_model=IngestResponse,
    responses={
        400: {"model": IngestResponse},
        401: {"model": IngestResponse},
        403: {"model": IngestResponse},
        409: {"model": IngestResponse},
        413: {"model": ErrorResponse},
        422: {"model": IngestResponse},
    },
)
async def ingest(
    request: Request,
    x_md_signature: str | None = Header(None, alias="X-MD-Signature"),
    services: AppServices = Depends(get_services),
) -> JSONResponse:
    """Device ingestion endpoint. Authenticated by per-device HMAC-SHA-256 over the raw body,
    not by a user session. The detailed reason is only disclosed to senders that authenticated,
    so the endpoint cannot be used to enumerate valid device IDs."""
    raw = await read_limited_body(request, services.settings.max_message_bytes)
    message = InboundMessage(
        raw=raw,
        signature_header=x_md_signature,
        channel=IngestChannel.HTTP,
        transport_source=request.client.host if request.client else None,
        correlation_id=correlation_id(request) or None,
    )
    result = await run_in_threadpool(request.app.state.pipeline.process, message)
    if result.decision is not TelemetryDecision.REJECTED:
        status = 202
    elif not result.authenticated:
        # One status for every unauthenticated rejection after parsing, so responses do not
        # reveal whether a device ID exists (no enumeration oracle).
        status = {"PAYLOAD_TOO_LARGE": 413, "MALFORMED": 400}.get(result.reason_code, 401)
    else:
        status = STATUS_BY_REASON.get(result.reason_code, 400)
    body = IngestResponse(
        decision=result.decision.value,
        event_id=result.telemetry_event_id,
        correlation_id=result.correlation_id,
        reason_code=result.reason_code if result.authenticated else None,
    )
    return JSONResponse(status_code=status, content=body.model_dump())


@router.post("/devices/enroll", status_code=202, tags=["devices"])
def enroll(
    body: EnrollmentRequestIn, request: Request, services: AppServices = Depends(get_services)
) -> dict[str, Any]:
    """Device self-enrollment request. Always recorded as PENDING; never grants trust."""
    with services.uow(correlation_id(request) or None) as uow:
        return submit_enrollment(
            uow,
            claimed_device_id=body.claimed_device_id,
            requested_type=body.requested_type,
            source_ref=request.client.host if request.client else None,
            details=dict(body.details),
        )


@router.get(
    "/telemetry/events",
    response_model=list[TelemetryEventOut],
    responses={401: {"model": ErrorResponse}},
)
def telemetry_events(
    asset_id: str | None = Query(None, max_length=64),
    decision: TelemetryDecision | None = None,
    run_id: int | None = None,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[TelemetryEvent]:
    q = select(TelemetryEvent).order_by(TelemetryEvent.id.desc()).limit(limit)
    if asset_id:
        q = q.where(
            (TelemetryEvent.asset_id == asset_id) | (TelemetryEvent.claimed_device_id == asset_id)
        )
    if decision is not None:
        q = q.where(TelemetryEvent.decision == decision)
    if run_id is not None:
        q = q.where(TelemetryEvent.simulation_run_id == run_id)
    if before_id is not None:
        q = q.where(TelemetryEvent.id < before_id)
    return list(session.scalars(q))


@router.get(
    "/telemetry/events/{event_id}",
    response_model=TelemetryEventDetail,
    responses={404: {"model": ErrorResponse}},
)
def telemetry_event(
    event_id: int, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> TelemetryEvent:
    event = session.get(TelemetryEvent, event_id)
    if event is None:
        raise NotFound("Telemetry event", event_id)
    return event
