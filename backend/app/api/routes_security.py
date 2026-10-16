from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import correlation_id, db_session, get_services, operator, security_admin, viewer
from app.core.errors import NotFound
from app.models import Asset, AuditEvent, PolicyDecision, SecurityAlert, SecurityPolicy
from app.models.enums import (
    AlertClassification,
    EnforcementMode,
    PolicyType,
    Severity,
)
from app.schemas.api import (
    AlertOut,
    AuditEventOut,
    AuditVerifyOut,
    ErrorResponse,
    PolicyDecisionOut,
    PolicyEvaluateRequest,
    PolicyEvaluationOut,
    PolicyModeUpdate,
    PolicyOut,
)
from app.services import administration, audit, queries
from app.services.auth import Principal
from app.services.context import AppServices
from app.services.policy_engine import PolicyEngine, endpoint_for_asset, trust_of

router = APIRouter(
    prefix="/api/v1",
    tags=["security"],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)


@router.get("/policies", response_model=list[PolicyOut])
def policies(
    policy_type: PolicyType | None = None,
    include_inactive: bool = False,
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[SecurityPolicy]:
    q = select(SecurityPolicy).order_by(SecurityPolicy.priority, SecurityPolicy.id)
    if policy_type is not None:
        q = q.where(SecurityPolicy.policy_type == policy_type)
    if not include_inactive:
        q = q.where(SecurityPolicy.is_active.is_(True))
    return list(session.scalars(q))


@router.post(
    "/policies/evaluate",
    response_model=PolicyEvaluationOut,
    responses={404: {"model": ErrorResponse}},
)
def evaluate_policy(
    body: PolicyEvaluateRequest,
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> dict[str, Any]:
    """Dry-run evaluation against live policy. Nothing is persisted or enforced."""
    src = session.get(Asset, body.source_asset_id)
    dst = session.get(Asset, body.destination_asset_id)
    if src is None:
        raise NotFound("Asset", body.source_asset_id)
    if dst is None:
        raise NotFound("Asset", body.destination_asset_id)
    engine = PolicyEngine.load(session)
    if body.policy_type == "DEVICE_COMMAND":
        evaluation = engine.evaluate_command(
            endpoint_for_asset(src),
            trust_of(session, src.id),
            endpoint_for_asset(dst),
            body.service_or_action,
        )
    else:
        evaluation = engine.evaluate(
            PolicyType.NETWORK_FLOW,
            endpoint_for_asset(src),
            endpoint_for_asset(dst),
            body.service_or_action,
        )
    return {
        "decision": evaluation.decision.value,
        "outcome": evaluation.outcome.value,
        "matched_policy_id": evaluation.matched_policy_id,
        "reason": evaluation.reason,
        "explanation": evaluation.explanation,
    }


@router.patch(
    "/policies/{policy_id}", response_model=PolicyOut, responses={404: {"model": ErrorResponse}}
)
def update_policy_mode(
    policy_id: str,
    body: PolicyModeUpdate,
    request: Request,
    principal: Principal = Depends(security_admin),
    services: AppServices = Depends(get_services),
) -> SecurityPolicy:
    with services.uow(correlation_id(request) or None) as uow:
        policy = administration.set_policy_mode(
            uow, principal, policy_id, EnforcementMode(body.enforcement_mode), body.reason
        )
        uow.session.flush()
        uow.session.expunge(policy)
    return policy


@router.get("/policy-decisions", response_model=list[PolicyDecisionOut])
def policy_decisions(
    asset_id: str | None = Query(None, max_length=64),
    decision: str | None = Query(None, pattern="^(ALLOW|DENY)$"),
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[PolicyDecision]:
    q = select(PolicyDecision).order_by(PolicyDecision.id.desc()).limit(limit)
    if asset_id:
        q = q.where(
            (PolicyDecision.source_asset_id == asset_id)
            | (PolicyDecision.destination_asset_id == asset_id)
        )
    if decision:
        q = q.where(PolicyDecision.decision == decision)
    if before_id is not None:
        q = q.where(PolicyDecision.id < before_id)
    return list(session.scalars(q))


@router.get("/security-events", response_model=list[AlertOut])
def security_events(
    asset_id: str | None = Query(None, max_length=64),
    severity: Severity | None = None,
    classification: AlertClassification | None = None,
    incident_id: int | None = None,
    current_epoch_only: bool = True,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[SecurityAlert]:
    """Detections (alerts) with their rule, evidence and confidence limitations."""
    q = select(SecurityAlert).order_by(SecurityAlert.id.desc()).limit(limit)
    if asset_id:
        q = q.where((SecurityAlert.asset_id == asset_id) | (SecurityAlert.subject_ref == asset_id))
    if severity is not None:
        q = q.where(SecurityAlert.severity == severity)
    if classification is not None:
        q = q.where(SecurityAlert.classification == classification)
    if incident_id is not None:
        q = q.where(SecurityAlert.incident_id == incident_id)
    if current_epoch_only:
        q = q.where(SecurityAlert.epoch == queries.current_epoch(session))
    if before_id is not None:
        q = q.where(SecurityAlert.id < before_id)
    return list(session.scalars(q))


@router.get("/detection-rules")
def detection_rules(_: Principal = Depends(viewer)) -> list[dict[str, Any]]:
    from app.services.detection import RULES

    return [
        {
            "id": r.id,
            "title": r.title,
            "classification": r.classification.value,
            "severity": r.severity.value,
            "opens_incident": r.opens_incident,
            "marks_suspicious": r.marks_suspicious,
            "description": r.description,
            "confidence_note": r.confidence_note,
        }
        for r in RULES.values()
    ]


@router.get("/audit", response_model=list[AuditEventOut])
def audit_events(
    action: str | None = Query(None, max_length=64),
    target_id: str | None = Query(None, max_length=64),
    actor_id: str | None = Query(None, max_length=64),
    correlation: str | None = Query(None, max_length=64, alias="correlation_id"),
    incident_id: int | None = None,
    before_id: int | None = None,
    limit: int = Query(50, ge=1, le=200),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
) -> list[AuditEvent]:
    """Append-only audit trail (read-only: there are no update or delete endpoints)."""
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if action:
        q = q.where(AuditEvent.action == action)
    if target_id:
        q = q.where(AuditEvent.target_id == target_id)
    if actor_id:
        q = q.where(AuditEvent.actor_id == actor_id)
    if correlation:
        q = q.where(AuditEvent.correlation_id == correlation)
    if incident_id is not None:
        q = q.where(AuditEvent.incident_id == incident_id)
    if before_id is not None:
        q = q.where(AuditEvent.id < before_id)
    return list(session.scalars(q))


@router.get("/audit/verify", response_model=AuditVerifyOut)
def verify_audit(
    _: Principal = Depends(operator), session: Session = Depends(db_session)
) -> dict[str, Any]:
    result = audit.verify_chain(session)
    return {
        "valid": result.valid,
        "checked": result.checked,
        "first_invalid_id": result.first_invalid_id,
        "problem": result.problem,
        "head_hash": result.head_hash,
        "note": "Tamper-evident, not tamper-proof: a database superuser could rewrite the whole chain. "
        "Anchoring the head hash externally would close that gap.",
    }


@router.get("/metrics/summary")
def metrics_summary(
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
    services: AppServices = Depends(get_services),
) -> dict[str, Any]:
    """Dashboard metrics, computed from persisted backend data."""
    return queries.metrics_summary(session, services.clock.now())


@router.get("/metrics/timeseries")
def metrics_timeseries(
    minutes: int = Query(30, ge=5, le=360),
    _: Principal = Depends(viewer),
    session: Session = Depends(db_session),
    services: AppServices = Depends(get_services),
) -> list[dict[str, Any]]:
    return queries.telemetry_timeseries(session, services.clock.now(), minutes)
