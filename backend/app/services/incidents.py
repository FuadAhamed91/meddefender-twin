"""Alerts, incident correlation and the incident state machine.

Correlation rule: alerts are grouped into one open incident per *subject* (the asset or
claimed identity the alert is about) within the current simulation epoch. Rules flagged
``opens_incident`` create an incident when none is open; low-signal rules only attach to an
existing one. Incident timeline entries are append-only (enforced by a DB trigger).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict
from app.models import ContainmentPlan, Incident, IncidentAsset, IncidentEvent, SecurityAlert
from app.models.enums import (
    SEVERITY_RANK,
    ActorType,
    AuditDecision,
    IncidentStatus,
    PlanStatus,
    Severity,
)
from app.services.context import UnitOfWork
from app.services.detection import rule as get_rule

IS = IncidentStatus

TRANSITIONS: dict[IncidentStatus, frozenset[IncidentStatus]] = {
    IS.DETECTED: frozenset({IS.INVESTIGATING}),
    IS.INVESTIGATING: frozenset({IS.CONTAINMENT_PROPOSED, IS.RESOLVED}),
    IS.CONTAINMENT_PROPOSED: frozenset({IS.CONTAINED, IS.INVESTIGATING}),
    IS.CONTAINED: frozenset({IS.RECOVERY}),
    IS.RECOVERY: frozenset({IS.RESOLVED, IS.CONTAINED}),
    IS.RESOLVED: frozenset(),
}

EARLY_RESOLUTIONS = frozenset({"FALSE_POSITIVE", "BENIGN", "NO_ACTION_REQUIRED", "ACCEPTED_RISK"})

# Rules that would otherwise fire on every message are de-duplicated per subject.
DEDUPE_SECONDS: dict[str, int] = {
    "MD-AUTH-002": 60,
    "MD-RATE-001": 60,
    "MD-ID-001": 60,
    "MD-ID-003": 300,
    "MD-CMD-003": 120,
}

ROLE_STRENGTH = {
    "PRIMARY": 4,
    "TARGET": 3,
    "IMPERSONATED": 3,
    "AFFECTED": 2,
    "POTENTIALLY_REACHABLE": 1,
}


@dataclass
class AlertOutcome:
    alert: SecurityAlert | None
    incident: Incident | None
    incident_created: bool
    suppressed: bool = False


def _correlation_key(subject_ref: str) -> str:
    return f"SUBJECT:{subject_ref}"


def raise_alert(
    uow: UnitOfWork,
    rule_id: str,
    *,
    subject_ref: str,
    asset_id: str | None,
    evidence: dict[str, Any],
    telemetry_event_id: int | None = None,
    policy_decision_id: int | None = None,
    related_assets: list[tuple[str, str]] | None = None,
    simulation_run_id: int | None = None,
    severity: Severity | None = None,
) -> AlertOutcome:
    rule = get_rule(rule_id)
    session = uow.session
    window = DEDUPE_SECONDS.get(rule_id)
    if window:
        recent = session.scalar(
            select(func.count(SecurityAlert.id)).where(
                SecurityAlert.rule_id == rule_id,
                SecurityAlert.subject_ref == subject_ref,
                SecurityAlert.created_at >= uow.now - timedelta(seconds=window),
            )
        )
        if recent:
            return AlertOutcome(None, None, False, suppressed=True)

    alert = SecurityAlert(
        created_at=uow.now,
        rule_id=rule.id,
        title=rule.title,
        classification=rule.classification,
        severity=severity or rule.severity,
        asset_id=asset_id,
        subject_ref=subject_ref,
        evidence=evidence,
        confidence_note=rule.confidence_note,
        telemetry_event_id=telemetry_event_id,
        policy_decision_id=policy_decision_id,
        simulation_run_id=simulation_run_id,
        correlation_id=uow.correlation_id,
        epoch=uow.epoch,
    )
    session.add(alert)
    session.flush()

    incident, created = _correlate(
        uow, alert, rule.opens_incident, subject_ref, asset_id, simulation_run_id
    )
    if incident is not None:
        alert.incident_id = incident.id
        _link_asset(session, incident, asset_id, "PRIMARY", uow)
        for related_id, role in related_assets or []:
            _link_asset(session, incident, related_id, role, uow)
        add_incident_event(
            uow,
            incident,
            "ALERT_ATTACHED",
            f"{rule.id} {rule.title}",
            actor_type=ActorType.SYSTEM,
            actor_id="detection-engine",
            details={
                "rule_id": rule.id,
                "classification": rule.classification.value,
                "severity": alert.severity.value,
                "evidence": evidence,
            },
            alert_id=alert.id,
            policy_decision_id=policy_decision_id,
            telemetry_event_id=telemetry_event_id,
        )
    uow.emit(
        "alert.created",
        {
            "alert_id": alert.id,
            "rule_id": rule.id,
            "title": rule.title,
            "classification": rule.classification.value,
            "severity": alert.severity.value,
            "subject_ref": subject_ref,
            "asset_id": asset_id,
            "incident_id": incident.id if incident else None,
            "incident_reference": incident.reference if incident else None,
        },
    )
    return AlertOutcome(alert, incident, created)


def _correlate(
    uow: UnitOfWork,
    alert: SecurityAlert,
    may_open: bool,
    subject_ref: str,
    asset_id: str | None,
    simulation_run_id: int | None,
) -> tuple[Incident | None, bool]:
    session = uow.session
    key = _correlation_key(subject_ref)

    def find_open() -> Incident | None:
        return session.scalars(
            select(Incident)
            .where(
                Incident.correlation_key == key,
                Incident.epoch == uow.epoch,
                Incident.status != IncidentStatus.RESOLVED,
            )
            .with_for_update()
        ).first()

    incident = find_open()
    created = False
    if incident is None:
        if not may_open:
            return None, False
        rule = get_rule(alert.rule_id)
        stmt = (
            pg_insert(Incident)
            .values(
                title=f"{rule.title}: {subject_ref}",
                summary=rule.description,
                category=rule.category,
                status=IncidentStatus.DETECTED,
                severity=alert.severity,
                primary_asset_id=asset_id,
                primary_subject_ref=subject_ref,
                detection_rule_id=rule.id,
                correlation_key=key,
                alert_count=0,
                recovery_completed=False,
                created_at=uow.now,
                updated_at=uow.now,
                simulation_run_id=simulation_run_id,
                epoch=uow.epoch,
            )
            .on_conflict_do_nothing(
                index_elements=["correlation_key", "epoch"],
                index_where=text("status <> 'RESOLVED'"),
            )
            .returning(Incident.id)
        )
        new_id = session.execute(stmt).scalar()
        if new_id is not None:
            incident = session.get(Incident, new_id, populate_existing=True)
            assert incident is not None
            incident.reference = f"INC-{new_id:04d}"
            created = True
            add_incident_event(
                uow,
                incident,
                "CREATED",
                f"Incident opened by {rule.id}",
                actor_type=ActorType.SYSTEM,
                actor_id="detection-engine",
                details={"rule_id": rule.id, "subject": subject_ref},
                alert_id=alert.id,
            )
            uow.audit(
                actor_type=ActorType.SYSTEM,
                actor_id="detection-engine",
                action="INCIDENT_CREATED",
                target_type="incident",
                target_id=incident.reference or str(new_id),
                decision=AuditDecision.INFO,
                reason=f"{rule.id} {rule.title} for {subject_ref}",
                incident_id=new_id,
                simulation_run_id=simulation_run_id,
            )
        else:  # a concurrent transaction opened it first
            incident = find_open()
            if incident is None:  # pragma: no cover - defensive
                return None, False

    incident.alert_count += 1
    if SEVERITY_RANK[alert.severity] > SEVERITY_RANK[incident.severity]:
        incident.severity = alert.severity
    incident.updated_at = uow.now
    uow.emit(
        "incident.created" if created else "incident.updated",
        incident_summary(incident),
    )
    return incident, created


def _link_asset(
    session: Session, incident: Incident, asset_id: str | None, role: str, uow: UnitOfWork
) -> None:
    if not asset_id:
        return
    link = session.get(IncidentAsset, (incident.id, asset_id))
    if link is None:
        session.add(
            IncidentAsset(incident_id=incident.id, asset_id=asset_id, role=role, added_at=uow.now)
        )
    elif ROLE_STRENGTH.get(role, 0) > ROLE_STRENGTH.get(link.role, 0):
        link.role = role


def link_assets(uow: UnitOfWork, incident: Incident, links: list[tuple[str, str]]) -> None:
    for asset_id, role in links:
        _link_asset(uow.session, incident, asset_id, role, uow)


def add_incident_event(
    uow: UnitOfWork,
    incident: Incident,
    event_type: str,
    summary: str,
    *,
    actor_type: ActorType,
    actor_id: str,
    details: dict[str, Any] | None = None,
    alert_id: int | None = None,
    policy_decision_id: int | None = None,
    telemetry_event_id: int | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        incident_id=incident.id,
        occurred_at=uow.now,
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        summary=summary,
        details=details or {},
        alert_id=alert_id,
        policy_decision_id=policy_decision_id,
        telemetry_event_id=telemetry_event_id,
        correlation_id=uow.correlation_id,
    )
    uow.session.add(event)
    return event


def incident_summary(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": incident.id,
        "reference": incident.reference,
        "title": incident.title,
        "status": incident.status.value,
        "severity": incident.severity.value,
        "category": incident.category,
        "primary_asset_id": incident.primary_asset_id,
        "primary_subject_ref": incident.primary_subject_ref,
        "alert_count": incident.alert_count,
        "epoch": incident.epoch,
    }


# ---- state machine --------------------------------------------------------------------


def transition_incident(
    uow: UnitOfWork,
    incident: Incident,
    target: IncidentStatus,
    *,
    actor_id: str,
    note: str,
    resolution: str | None = None,
    system: bool = False,
) -> None:
    """Validate and apply an incident status change. ``system`` transitions come from the
    containment and recovery services, which enforce their own preconditions."""
    if incident.epoch != uow.epoch:
        raise Conflict(
            "INCIDENT_FROM_PREVIOUS_BASELINE",
            "This incident belongs to a previous simulation baseline and is read-only.",
        )
    current = incident.status
    if target not in TRANSITIONS[current]:
        raise Conflict(
            "INVALID_TRANSITION",
            f"Cannot move incident from {current.value} to {target.value}.",
            {"allowed": sorted(s.value for s in TRANSITIONS[current])},
        )
    if not system:
        _check_manual_guards(uow.session, incident, target, resolution)

    incident.status = target
    incident.updated_at = uow.now
    if target is IncidentStatus.RESOLVED:
        incident.resolved_at = uow.now
        incident.resolution = resolution or "CONTAINED_AND_RECOVERED"
        incident.resolution_note = note
    add_incident_event(
        uow,
        incident,
        "STATUS_CHANGED",
        f"{current.value} -> {target.value}",
        actor_type=ActorType.SYSTEM if system else ActorType.USER,
        actor_id=actor_id,
        details={"from": current.value, "to": target.value, "note": note, "resolution": resolution},
    )
    uow.audit(
        actor_type=ActorType.SYSTEM if system else ActorType.USER,
        actor_id=actor_id,
        action="INCIDENT_STATUS_CHANGED",
        target_type="incident",
        target_id=incident.reference or str(incident.id),
        decision=AuditDecision.SUCCESS,
        reason=note or f"{current.value} -> {target.value}",
        details={"from": current.value, "to": target.value, "resolution": resolution},
        incident_id=incident.id,
    )
    uow.emit("incident.updated", incident_summary(incident))


def _check_manual_guards(
    session: Session, incident: Incident, target: IncidentStatus, resolution: str | None
) -> None:
    if target is IncidentStatus.CONTAINED:
        raise Conflict(
            "USE_CONTAINMENT_APPLY",
            "Incidents become CONTAINED only by applying a containment plan.",
        )
    if target is IncidentStatus.CONTAINMENT_PROPOSED:
        proposed = session.scalar(
            select(func.count(ContainmentPlan.id)).where(
                ContainmentPlan.incident_id == incident.id,
                ContainmentPlan.status == PlanStatus.PROPOSED,
            )
        )
        if not proposed:
            raise Conflict(
                "NO_PROPOSED_PLAN", "Generate containment plans before proposing containment."
            )
    if target is IncidentStatus.RESOLVED:
        if incident.status is IncidentStatus.INVESTIGATING:
            if resolution not in EARLY_RESOLUTIONS:
                raise AppError(
                    422,
                    "RESOLUTION_REQUIRED",
                    "Resolving without containment requires a resolution: "
                    + ", ".join(sorted(EARLY_RESOLUTIONS)),
                )
        elif not incident.recovery_completed:
            raise Conflict(
                "RECOVERY_NOT_COMPLETED", "Execute the recovery actions before resolving."
            )
