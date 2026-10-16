"""Incident replay: reconstruct what happened, in order, purely from persisted records.

Sources are joined by correlation id: the incident timeline, its alerts, the telemetry
events and policy decisions those alerts cite, and every audit event written under the same
correlation ids. Each frame carries the incident status and asset highlights *as of that
moment*, so the UI can step through the incident on the 3D twin.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import (
    AuditEvent,
    Incident,
    IncidentEvent,
    PolicyDecision,
    SecurityAlert,
    TelemetryEvent,
)


def incident_replay(session: Session, incident_id: int) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None:
        raise NotFound("Incident", incident_id)
    events = session.scalars(
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.id)
    ).all()
    alerts = session.scalars(
        select(SecurityAlert)
        .where(SecurityAlert.incident_id == incident_id)
        .order_by(SecurityAlert.id)
    ).all()
    correlation_ids = {e.correlation_id for e in events} | {a.correlation_id for a in alerts}
    telemetry_ids = {a.telemetry_event_id for a in alerts if a.telemetry_event_id} | {
        e.telemetry_event_id for e in events if e.telemetry_event_id
    }
    decision_ids = {a.policy_decision_id for a in alerts if a.policy_decision_id} | {
        e.policy_decision_id for e in events if e.policy_decision_id
    }
    telemetry = (
        session.scalars(select(TelemetryEvent).where(TelemetryEvent.id.in_(telemetry_ids))).all()
        if telemetry_ids
        else []
    )
    decisions = (
        session.scalars(select(PolicyDecision).where(PolicyDecision.id.in_(decision_ids))).all()
        if decision_ids
        else []
    )
    audits = (
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.correlation_id.in_(correlation_ids))
            .order_by(AuditEvent.id)
        ).all()
        if correlation_ids
        else []
    )
    audits = [
        a
        for a in audits
        if a.action != "TELEMETRY_REJECTED" or a.target_id in {str(t) for t in telemetry_ids}
    ]

    frames: list[tuple[datetime, int, dict[str, Any]]] = []
    order = {"telemetry": 0, "policy_decision": 1, "alert": 2, "audit": 3, "incident_event": 4}

    for t in telemetry:
        frames.append(
            (
                t.received_at,
                order["telemetry"],
                {
                    "kind": "telemetry",
                    "ref_id": t.id,
                    "summary": f"{t.claimed_device_id or 'unknown'} {t.message_type or 'message'} -> {t.decision.value} ({t.reason_code})",
                    "assets": [x for x in (t.asset_id,) if x],
                    "detail": {
                        "decision": t.decision.value,
                        "reason": t.reason,
                        "checks": t.checks,
                        "sequence": t.sequence,
                        "integrity_verified": t.integrity_verified,
                    },
                },
            )
        )
    for d in decisions:
        frames.append(
            (
                d.evaluated_at,
                order["policy_decision"],
                {
                    "kind": "policy_decision",
                    "ref_id": d.id,
                    "summary": f"{d.source_ref} -> {d.destination_ref} ({d.service_or_action}): {d.outcome.value}",
                    "assets": [x for x in (d.source_asset_id, d.destination_asset_id) if x],
                    "edge": {
                        "source": d.source_ref,
                        "destination": d.destination_ref,
                        "service": d.service_or_action,
                        "outcome": d.outcome.value,
                    },
                    "detail": {"reason": d.reason, "matched_policy_id": d.matched_policy_id},
                },
            )
        )
    for a in alerts:
        frames.append(
            (
                a.created_at,
                order["alert"],
                {
                    "kind": "alert",
                    "ref_id": a.id,
                    "summary": f"{a.rule_id} {a.title} [{a.classification.value}, {a.severity.value}]",
                    "assets": [x for x in (a.asset_id,) if x],
                    "detail": {
                        "evidence": a.evidence,
                        "confidence_note": a.confidence_note,
                        "subject": a.subject_ref,
                    },
                },
            )
        )
    for au in audits:
        if au.action in ("INCIDENT_CREATED", "INCIDENT_STATUS_CHANGED"):
            continue  # represented by incident events
        frames.append(
            (
                au.occurred_at,
                order["audit"],
                {
                    "kind": "audit",
                    "ref_id": au.id,
                    "summary": f"{au.action} by {au.actor_id} on {au.target_type}:{au.target_id} -> {au.decision.value}",
                    "assets": [au.target_id]
                    if au.target_type in ("asset", "device_identity")
                    else [],
                    "detail": {"reason": au.reason, "details": au.details},
                },
            )
        )
    for e in events:
        frames.append(
            (
                e.occurred_at,
                order["incident_event"],
                {
                    "kind": "incident_event",
                    "ref_id": e.id,
                    "event_type": e.event_type,
                    "summary": e.summary,
                    "assets": [],
                    "detail": e.details,
                },
            )
        )
    frames.sort(key=lambda f: (f[0], f[1], f[2]["ref_id"]))

    status = None
    highlighted: set[str] = set()
    trust: dict[str, str] = {}
    out = []
    for when, _, frame in frames:
        if frame["kind"] == "incident_event":
            if frame.get("event_type") == "CREATED":
                status = "DETECTED"
            elif frame.get("event_type") == "STATUS_CHANGED":
                status = frame["detail"].get("to", status)
        if frame["kind"] == "audit" and frame["summary"].startswith("TRUST_STATE_CHANGED"):
            target = frame["summary"].split("device_identity:")[-1].split(" ")[0]
            trust[target] = frame["detail"]["details"].get("to", trust.get(target, ""))
        highlighted.update(frame["assets"])
        out.append(
            frame
            | {
                "t": when,
                "incident_status": status,
                "highlighted_assets": sorted(highlighted),
                "trust_states": dict(trust),
            }
        )
    return {
        "incident": {
            "id": incident.id,
            "reference": incident.reference,
            "title": incident.title,
            "status": incident.status.value,
            "severity": incident.severity.value,
            "epoch": incident.epoch,
        },
        "frames": out,
        "sources": {
            "incident_events": len(events),
            "alerts": len(alerts),
            "telemetry_events": len(telemetry),
            "policy_decisions": len(decisions),
            "audit_events": len(audits),
        },
        "note": "Reconstructed from persisted records only; nothing here is generated for display.",
    }
