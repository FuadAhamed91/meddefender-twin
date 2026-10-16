from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import correlation_id, db_session, get_services, operator, security_admin, viewer
from app.core.errors import NotFound
from app.models import EnrollmentRequest, SimulationRun, SimulationState
from app.schemas.api import (
    DecisionRequest,
    ErrorResponse,
    GeneratorToggle,
    ResetRequest,
    ScenarioRunRequest,
    SimulationRunOut,
    SimulationStatusOut,
)
from app.services import administration
from app.services.auth import Principal
from app.services.context import AppServices
from app.simulator.scenarios import check_preconditions, run_scenario, scenario_catalog

router = APIRouter(
    prefix="/api/v1",
    tags=["simulation"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


@router.get("/scenarios")
def scenarios(
    _: Principal = Depends(viewer), services: AppServices = Depends(get_services)
) -> list[dict[str, Any]]:
    return [
        s | {"precondition_checks": check_preconditions(services, s["id"])}
        for s in scenario_catalog()
    ]


@router.post(
    "/scenarios/{scenario_id}/run",
    response_model=SimulationRunOut,
    responses={404: {"model": ErrorResponse}},
)
async def run(
    scenario_id: str,
    request: Request,
    body: ScenarioRunRequest | None = None,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> SimulationRun:
    """Execute a scenario through the real security pipeline and evaluate its expectations
    against persisted state."""
    app = request.app
    return await run_in_threadpool(
        run_scenario,
        services,
        app.state.pipeline,
        getattr(app.state, "runtime", None),
        scenario_id.upper(),
        principal,
        (body.seed if body else 7),
    )


@router.get("/simulation/runs", response_model=list[SimulationRunOut])
def runs(
    limit: int = Query(20, ge=1, le=100),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[SimulationRun]:
    return list(
        session.scalars(select(SimulationRun).order_by(SimulationRun.id.desc()).limit(limit))
    )


@router.get(
    "/simulation/runs/{run_id}",
    response_model=SimulationRunOut,
    responses={404: {"model": ErrorResponse}},
)
def run_detail(
    run_id: int, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> SimulationRun:
    item = session.get(SimulationRun, run_id)
    if item is None:
        raise NotFound("Simulation run", run_id)
    return item


@router.get("/simulation/status", response_model=SimulationStatusOut)
def status(
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    state = session.get(SimulationState, 1)
    if state is None:
        raise NotFound("Simulation state", 1)
    return {
        "epoch": state.epoch,
        "generator_enabled": state.generator_enabled,
        "tick_count": state.tick_count,
        "last_tick_at": state.last_tick_at,
        "last_reset_at": state.last_reset_at,
        "interval_seconds": services.settings.generator_interval_seconds,
    }


@router.post("/simulation/generator", response_model=SimulationStatusOut)
def toggle_generator(
    body: GeneratorToggle,
    request: Request,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    with services.uow(correlation_id(request) or None) as uow:
        state = administration.set_generator(uow, principal, body.enabled)
        result = {
            "epoch": state.epoch,
            "generator_enabled": state.generator_enabled,
            "tick_count": state.tick_count,
            "last_tick_at": state.last_tick_at,
            "last_reset_at": state.last_reset_at,
            "interval_seconds": services.settings.generator_interval_seconds,
        }
    return result


@router.post("/simulation/reset")
def reset(
    body: ResetRequest,
    request: Request,
    principal: Principal = Depends(security_admin),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    """Restore the known baseline in a new epoch. Audit history, incidents and evidence are kept."""
    runtime = getattr(request.app.state, "runtime", None)
    lock = runtime.scenario_lock if runtime is not None else None
    if lock is not None:
        lock.acquire()
    try:
        with services.uow(correlation_id(request) or None) as uow:
            return administration.reset_simulation(uow, principal, body.reason)
    finally:
        if lock is not None:
            lock.release()


# ---- device identity administration ------------------------------------------------------


@router.get("/devices/enrollments", tags=["devices"])
def enrollments(
    _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(EnrollmentRequest).order_by(EnrollmentRequest.id.desc()).limit(100)
    )
    return [
        {
            "id": r.id,
            "claimed_device_id": r.claimed_device_id,
            "asset_id": r.asset_id,
            "requested_type": r.requested_type,
            "source_ref": r.source_ref,
            "status": r.status.value,
            "created_at": r.created_at,
            "decided_at": r.decided_at,
            "decision_reason": r.decision_reason,
            "epoch": r.epoch,
        }
        for r in rows
    ]


@router.post(
    "/devices/enrollments/{request_id}/{decision}",
    tags=["devices"],
    responses={404: {"model": ErrorResponse}},
)
def decide(
    request_id: int,
    decision: str,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(security_admin),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    if decision not in ("approve", "reject"):
        raise NotFound("Decision", decision)
    with services.uow(correlation_id(request) or None) as uow:
        return administration.decide_enrollment(
            uow, principal, request_id, decision == "approve", body.reason
        )


@router.post(
    "/devices/{asset_id}/revoke", tags=["devices"], responses={404: {"model": ErrorResponse}}
)
def revoke(
    asset_id: str,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(security_admin),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    with services.uow(correlation_id(request) or None) as uow:
        return administration.revoke_device(uow, principal, asset_id, body.reason)


@router.post(
    "/devices/{asset_id}/rotate-key", tags=["devices"], responses={404: {"model": ErrorResponse}}
)
def rotate(
    asset_id: str,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(security_admin),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    with services.uow(correlation_id(request) or None) as uow:
        return administration.rotate_device_key(uow, principal, asset_id, body.reason)


@router.post(
    "/devices/{asset_id}/clear-suspicion",
    tags=["devices"],
    responses={404: {"model": ErrorResponse}},
)
def clear(
    asset_id: str,
    body: DecisionRequest,
    request: Request,
    principal: Principal = Depends(security_admin),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    with services.uow(correlation_id(request) or None) as uow:
        return administration.clear_suspicion(uow, principal, asset_id, body.reason)
