from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import correlation_id, db_session, get_services, operator, viewer
from app.core.errors import NotFound
from app.models import (
    ContainmentPlan,
    Incident,
    IncidentAsset,
    IncidentEvent,
    PolicyDecision,
    SecurityAlert,
)
from app.models.enums import ActorType, AuditDecision, IncidentStatus, Severity
from app.schemas.api import (
    ApplyPlanRequest,
    ContainmentPlanOut,
    ErrorResponse,
    IncidentDetailOut,
    IncidentNoteRequest,
    IncidentSummaryOut,
    IncidentTransitionRequest,
    RecoveryRequest,
)
from app.services import containment, incidents, queries
from app.services.auth import Principal
from app.services.context import AppServices
from app.services.replay import incident_replay

router = APIRouter(
    prefix="/api/v1",
    tags=["incidents"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


@router.get("/incidents", response_model=list[IncidentSummaryOut])
def list_incidents(
    status: IncidentStatus | None = None,
    severity: Severity | None = None,
    include_previous_epochs: bool = False,
    open_only: bool = False,
    limit: int = Query(100, ge=1, le=200),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[Incident]:
    q = select(Incident).order_by(Incident.id.desc()).limit(limit)
    if not include_previous_epochs:
        q = q.where(Incident.epoch == queries.current_epoch(session))
    if status is not None:
        q = q.where(Incident.status == status)
    if severity is not None:
        q = q.where(Incident.severity == severity)
    if open_only:
        q = q.where(Incident.status != IncidentStatus.RESOLVED)
    return list(session.scalars(q))


def _detail(session: Session, incident: Incident) -> dict[str, Any]:
    alerts = session.scalars(
        select(SecurityAlert)
        .where(SecurityAlert.incident_id == incident.id)
        .order_by(SecurityAlert.id)
    ).all()
    decision_ids = {a.policy_decision_id for a in alerts if a.policy_decision_id}
    events = session.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.id)
    ).all()
    decision_ids |= {e.policy_decision_id for e in events if e.policy_decision_id}
    decisions = (
        session.scalars(
            select(PolicyDecision)
            .where(PolicyDecision.id.in_(decision_ids))
            .order_by(PolicyDecision.id)
        ).all()
        if decision_ids
        else []
    )
    epoch = queries.current_epoch(session)
    return {
        **{c: getattr(incident, c) for c in IncidentSummaryOut.model_fields},
        "resolution_note": incident.resolution_note,
        "events": events,
        "assets": session.scalars(
            select(IncidentAsset)
            .where(IncidentAsset.incident_id == incident.id)
            .order_by(IncidentAsset.added_at)
        ).all(),
        "alerts": alerts,
        "policy_decisions": decisions,
        "containment_plans": session.scalars(
            select(ContainmentPlan)
            .where(ContainmentPlan.incident_id == incident.id)
            .order_by(ContainmentPlan.id)
        ).all(),
        "allowed_transitions": []
        if incident.epoch != epoch
        else sorted(s.value for s in incidents.TRANSITIONS[incident.status]),
        "read_only": incident.epoch != epoch,
    }


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetailOut,
    responses={404: {"model": ErrorResponse}},
)
def get_incident(
    incident_id: int, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise NotFound("Incident", incident_id)
    return _detail(session, incident)


def _locked_incident(uow: Any, incident_id: int) -> Incident:
    incident = uow.session.get(Incident, incident_id, with_for_update=True)
    if incident is None:
        raise NotFound("Incident", incident_id)
    return incident


@router.post(
    "/incidents/{incident_id}/transition",
    response_model=IncidentSummaryOut,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def transition(
    incident_id: int,
    body: IncidentTransitionRequest,
    request: Request,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> Incident:
    """Move an incident through the enforced state machine."""
    with services.uow(correlation_id(request) or None) as uow:
        incident = _locked_incident(uow, incident_id)
        incidents.transition_incident(
            uow,
            incident,
            IncidentStatus(body.target_status),
            actor_id=principal.username,
            note=body.note,
            resolution=body.resolution,
        )
        uow.session.flush()
        uow.session.expunge(incident)
    return incident


@router.post(
    "/incidents/{incident_id}/notes", status_code=201, responses={404: {"model": ErrorResponse}}
)
def add_note(
    incident_id: int,
    body: IncidentNoteRequest,
    request: Request,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    with services.uow(correlation_id(request) or None) as uow:
        incident = _locked_incident(uow, incident_id)
        event = incidents.add_incident_event(
            uow,
            incident,
            "NOTE_ADDED",
            body.note,
            actor_type=ActorType.USER,
            actor_id=principal.username,
        )
        uow.audit(
            actor_type=ActorType.USER,
            actor_id=principal.username,
            action="INCIDENT_NOTE_ADDED",
            target_type="incident",
            target_id=incident.reference or str(incident.id),
            decision=AuditDecision.SUCCESS,
            reason=body.note[:200],
            incident_id=incident.id,
        )
        uow.emit("incident.updated", incidents.incident_summary(incident))
        uow.session.flush()
        return {"event_id": event.id}


@router.get("/incidents/{incident_id}/replay", responses={404: {"model": ErrorResponse}})
def replay(
    incident_id: int, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> dict[str, Any]:
    """Ordered reconstruction of the incident from persisted evidence."""
    return incident_replay(session, incident_id)


@router.get("/incidents/{incident_id}/containment/plans", response_model=list[ContainmentPlanOut])
def list_plans(
    incident_id: int, _: Principal = Depends(viewer), session: Session = Depends(db_session)
) -> list[ContainmentPlan]:
    return list(
        session.scalars(
            select(ContainmentPlan)
            .where(ContainmentPlan.incident_id == incident_id)
            .order_by(ContainmentPlan.id)
        )
    )


@router.post(
    "/incidents/{incident_id}/containment/plans",
    response_model=list[ContainmentPlanOut],
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def generate_plans(
    incident_id: int,
    request: Request,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> list[ContainmentPlan]:
    """Generate and compare containment options. Changes no live policy."""
    with services.uow(correlation_id(request) or None) as uow:
        incident = _locked_incident(uow, incident_id)
        plans = containment.generate_plans(
            uow, incident, principal.username, user_id=principal.user_id
        )
        uow.session.flush()
        for plan in plans:
            uow.session.expunge(plan)
    return plans


@router.post(
    "/containment/plans/{plan_id}/apply",
    response_model=ContainmentPlanOut,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def apply_plan(
    plan_id: int,
    body: ApplyPlanRequest,
    request: Request,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> ContainmentPlan:
    """Apply a proposed plan (requires explicit confirmation and justification; high-impact
    plans additionally require SECURITY_ADMIN)."""
    with services.uow(correlation_id(request) or None) as uow:
        plan = containment.apply_plan(uow, plan_id, principal, body.justification)
        uow.session.flush()
        uow.session.expunge(plan)
    return plan


@router.post(
    "/incidents/{incident_id}/recovery",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def recovery(
    incident_id: int,
    body: RecoveryRequest,
    request: Request,
    principal: Principal = Depends(operator),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    """Execute recovery actions. Evidence is preserved: nothing is deleted."""
    with services.uow(correlation_id(request) or None) as uow:
        incident = _locked_incident(uow, incident_id)
        return containment.execute_recovery(
            uow,
            incident,
            principal,
            rotate_credentials=body.rotate_credentials,
            release_containment=body.release_containment,
            restore_trusted_state=body.restore_trusted_state,
            note=body.note,
        )
