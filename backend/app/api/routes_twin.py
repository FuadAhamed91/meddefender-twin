from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import db_session, get_services, viewer
from app.core.errors import NotFound
from app.models import ContainmentPlan, HospitalZone, Room
from app.schemas.api import (
    AssetSummary,
    AttackPathRequest,
    ErrorResponse,
    RoomOut,
    TwinSnapshot,
    ZoneOut,
)
from app.services import queries
from app.services.auth import Principal
from app.services.containment import plan_policy_view
from app.services.context import AppServices
from app.services.graph import GraphContext, attack_paths, dependency_graph, network_graph

router = APIRouter(
    prefix="/api/v1",
    tags=["twin"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


@router.get("/zones", response_model=list[ZoneOut])
def zones(
    _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> list[HospitalZone]:
    return list(session.scalars(select(HospitalZone).order_by(HospitalZone.id)))


@router.get("/rooms", response_model=list[RoomOut])
def rooms(_: Principal = Depends(viewer), session: Session = Depends(db_session)) -> list[Room]:
    return list(session.scalars(select(Room).order_by(Room.id)))


@router.get("/assets", response_model=list[AssetSummary])
def assets(
    _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> list[dict[str, Any]]:
    return queries.asset_summaries(session)


@router.get("/assets/{asset_id}", responses={404: {"model": ErrorResponse}})
def asset_detail(
    asset_id: str, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> dict[str, Any]:
    """Everything the inspector shows, read from backend state (never from the 3D scene)."""
    return queries.asset_detail(session, asset_id)


@router.get("/twin/state", response_model=TwinSnapshot)
def twin_state(
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    """Full snapshot plus the latest event id, used to (re)synchronise the live twin."""
    return queries.twin_snapshot(session, services.clock.now())


@router.get("/graph/network")
def graph_network(
    _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> dict[str, Any]:
    """Modeled relationships with their *current* policy status (computed, not stored)."""
    return network_graph(session)


@router.get("/graph/dependencies")
def graph_dependencies(
    _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> dict[str, Any]:
    """Operational dependencies: what relies on what. Separate from network connectivity."""
    return dependency_graph(session)


@router.post("/graph/attack-paths", responses={404: {"model": ErrorResponse}})
def graph_attack_paths(
    body: AttackPathRequest, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> dict[str, Any]:
    """Policy-aware attack paths from an entry asset. With ``containment_plan_id`` the plan's
    hypothetical policies are evaluated on top of live policy (nothing is written)."""
    extra = []
    if body.containment_plan_id is not None:
        plan = session.get(ContainmentPlan, body.containment_plan_id)
        if plan is None:
            raise NotFound("Containment plan", body.containment_plan_id)
        extra = [plan_policy_view(spec) for spec in plan.policy_changes]
    ctx = GraphContext.load(session, extra_policies=extra)
    if body.entry_asset_id not in ctx.assets:
        raise NotFound("Asset", body.entry_asset_id)
    return attack_paths(
        session, ctx, body.entry_asset_id, body.max_depth, queries.current_epoch(session)
    )
