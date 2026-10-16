"""Read models for the API: inventory, asset detail, twin snapshot and metrics.

Relationship status (permitted / blocked) is computed by the policy engine at query time;
it is never stored, so a line in the twin always reflects current policy.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound
from app.models import (
    Asset,
    AuditEvent,
    DeviceCredential,
    DeviceIdentity,
    EventLogEntry,
    Incident,
    IncidentAsset,
    NetworkRelationship,
    OperationalDependency,
    PolicyDecision,
    SecurityAlert,
    SecurityPolicy,
    SimulationState,
    TelemetryEvent,
    TwinState,
)
from app.models.enums import (
    ContainmentState,
    DecisionOutcome,
    IncidentStatus,
    PolicyEffect,
    PolicyOrigin,
    PolicyType,
    RelationshipType,
    TelemetryDecision,
)
from app.services.policy_engine import PolicyEngine, endpoint_for_asset
from app.services.profiles import COMMANDS, PROFILES


def current_epoch(session: Session) -> int:
    return session.scalar(select(SimulationState.epoch).where(SimulationState.id == 1)) or 1


def latest_event_id(session: Session) -> int:
    return session.scalar(select(func.max(EventLogEntry.id))) or 0


def open_incident_counts(session: Session, epoch: int) -> dict[str, int]:
    rows = session.execute(
        select(IncidentAsset.asset_id, func.count(IncidentAsset.incident_id))
        .join(Incident, Incident.id == IncidentAsset.incident_id)
        .where(Incident.status != IncidentStatus.RESOLVED, Incident.epoch == epoch)
        .group_by(IncidentAsset.asset_id)
    ).all()
    return {asset_id: count for asset_id, count in rows}


def asset_summaries(session: Session) -> list[dict[str, Any]]:
    epoch = current_epoch(session)
    assets = session.scalars(
        select(Asset).where(Asset.is_active.is_(True)).order_by(Asset.id)
    ).all()
    identities = {i.asset_id: i for i in session.scalars(select(DeviceIdentity))}
    twins = {t.asset_id: t for t in session.scalars(select(TwinState))}
    counts = open_incident_counts(session, epoch)
    return [_summary(a, identities.get(a.id), twins.get(a.id), counts.get(a.id, 0)) for a in assets]


def _summary(
    asset: Asset, identity: DeviceIdentity | None, twin: TwinState | None, open_incidents: int
) -> dict[str, Any]:
    return {
        "id": asset.id,
        "display_name": asset.display_name,
        "asset_kind": asset.asset_kind.value,
        "asset_type": asset.asset_type,
        "is_logical": asset.is_logical,
        "network_zone_id": asset.network_zone_id,
        "room_id": asset.room_id,
        "twin_node": asset.twin_node,
        "position": asset.position,
        "label_height": asset.label_height,
        "ip_address": asset.ip_address,
        "criticality": asset.criticality.value,
        "discovered": asset.discovered,
        "is_active": asset.is_active,
        "containment_state": asset.containment_state.value,
        "trust_state": identity.trust_state.value if identity else None,
        "registration_status": identity.registration_status.value if identity else None,
        "open_incident_count": open_incidents,
        "last_seen_at": identity.last_seen_at if identity else None,
        "twin_version": twin.version if twin else 0,
        "reported_decision": twin.reported_decision if twin else None,
    }


def twin_state_out(twin: TwinState) -> dict[str, Any]:
    return {
        "asset_id": twin.asset_id,
        "version": twin.version,
        "reported": twin.reported,
        "reported_at": twin.reported_at,
        "reported_decision": twin.reported_decision,
        "reported_event_id": twin.reported_event_id,
        "trusted": twin.trusted,
        "trusted_at": twin.trusted_at,
        "trusted_event_id": twin.trusted_event_id,
        "predicted": twin.predicted,
        "predicted_at": twin.predicted_at,
        "model_name": twin.model_name,
        "discrepancy": twin.discrepancy,
    }


def twin_snapshot(session: Session, now: datetime) -> dict[str, Any]:
    active_ids = set(session.scalars(select(Asset.id).where(Asset.is_active.is_(True))))
    return {
        "last_event_id": latest_event_id(session),
        "epoch": current_epoch(session),
        "generated_at": now,
        "assets": asset_summaries(session),
        "twin_states": [
            twin_state_out(t)
            for t in session.scalars(select(TwinState).order_by(TwinState.asset_id))
            if t.asset_id in active_ids
        ],
    }


def relationship_view(
    rel: NetworkRelationship, assets: dict[str, Asset], engine: PolicyEngine
) -> dict[str, Any]:
    base = {
        "id": rel.id,
        "source_asset_id": rel.source_asset_id,
        "destination_asset_id": rel.destination_asset_id,
        "relationship_type": rel.relationship_type.value,
        "service": rel.service,
        "protocol_label": rel.protocol_label,
        "port": rel.port,
        "origin": rel.origin.value,
        "description": rel.description,
        "first_seen_at": rel.first_seen_at,
        "last_seen_at": rel.last_seen_at,
        "observation_count": rel.observation_count,
        "crosses_zone_boundary": (
            assets[rel.source_asset_id].network_zone_id
            != assets[rel.destination_asset_id].network_zone_id
        )
        if rel.source_asset_id in assets and rel.destination_asset_id in assets
        else None,
    }
    if rel.relationship_type is RelationshipType.L2_UPLINK:
        return base | {
            "policy_status": "TOPOLOGY",
            "decision": None,
            "matched_policy_id": None,
            "policy_reason": "Layer-2 attachment only. Physical connectivity does not grant any permission.",
        }
    evaluation = engine.evaluate(
        PolicyType.NETWORK_FLOW,
        endpoint_for_asset(assets.get(rel.source_asset_id), rel.source_asset_id),
        endpoint_for_asset(assets.get(rel.destination_asset_id), rel.destination_asset_id),
        rel.service,
    )
    return base | {
        "policy_status": evaluation.outcome.value,
        "decision": evaluation.decision.value,
        "matched_policy_id": evaluation.matched_policy_id,
        "policy_reason": evaluation.reason,
    }


def dependency_view(dep: OperationalDependency, assets: dict[str, Asset]) -> dict[str, Any]:
    return {
        "id": dep.id,
        "dependent_asset_id": dep.dependent_asset_id,
        "dependent_name": assets[dep.dependent_asset_id].display_name
        if dep.dependent_asset_id in assets
        else dep.dependent_asset_id,
        "provider_asset_id": dep.provider_asset_id,
        "provider_name": assets[dep.provider_asset_id].display_name
        if dep.provider_asset_id in assets
        else dep.provider_asset_id,
        "dependency_type": dep.dependency_type.value,
        "criticality": dep.criticality.value,
        "description": dep.description,
        "carried_by_relationship_id": dep.carried_by_relationship_id,
    }


def policy_view(p: SecurityPolicy) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "policy_type": p.policy_type.value,
        "source": p.source_asset_id or (f"zone:{p.source_zone_id}" if p.source_zone_id else "*"),
        "destination": p.destination_asset_id
        or (f"zone:{p.destination_zone_id}" if p.destination_zone_id else "*"),
        "service_or_action": p.service_or_action,
        "effect": p.effect.value,
        "priority": p.priority,
        "enforcement_mode": p.enforcement_mode.value,
        "enforcement_point_id": p.enforcement_point_id,
        "origin": p.origin.value,
        "rationale": p.rationale,
    }


def asset_detail(session: Session, asset_id: str) -> dict[str, Any]:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise NotFound("Asset", asset_id)
    epoch = current_epoch(session)
    assets = {a.id: a for a in session.scalars(select(Asset))}
    identity = session.get(DeviceIdentity, asset_id)
    twin = session.get(TwinState, asset_id)
    engine = PolicyEngine.load(session)

    credentials = [
        {
            "key_version": c.key_version,
            "algorithm": c.algorithm,
            "fingerprint": c.fingerprint,
            "status": c.status.value,
            "created_at": c.created_at,
            "retired_at": c.retired_at,
            "retired_reason": c.retired_reason,
        }
        for c in session.scalars(
            select(DeviceCredential)
            .where(DeviceCredential.asset_id == asset_id)
            .order_by(DeviceCredential.key_version.desc())
        )
    ]

    zone_id = asset.network_zone_id
    policy_rows = session.scalars(
        select(SecurityPolicy)
        .where(
            SecurityPolicy.is_active.is_(True),
            or_(
                SecurityPolicy.source_asset_id == asset_id,
                SecurityPolicy.destination_asset_id == asset_id,
                SecurityPolicy.source_zone_id == zone_id if zone_id else False,
                SecurityPolicy.destination_zone_id == zone_id if zone_id else False,
                (SecurityPolicy.priority >= 1000),
            ),
        )
        .order_by(SecurityPolicy.priority, SecurityPolicy.id)
    ).all()

    relationships = session.scalars(
        select(NetworkRelationship)
        .where(
            or_(
                NetworkRelationship.source_asset_id == asset_id,
                NetworkRelationship.destination_asset_id == asset_id,
            )
        )
        .order_by(NetworkRelationship.id)
    ).all()
    deps_as_dependent = session.scalars(
        select(OperationalDependency).where(OperationalDependency.dependent_asset_id == asset_id)
    ).all()
    deps_as_provider = session.scalars(
        select(OperationalDependency).where(OperationalDependency.provider_asset_id == asset_id)
    ).all()

    incident_rows = session.execute(
        select(Incident, IncidentAsset.role)
        .join(IncidentAsset, IncidentAsset.incident_id == Incident.id)
        .where(IncidentAsset.asset_id == asset_id)
        .order_by(Incident.epoch.desc(), Incident.created_at.desc())
        .limit(15)
    ).all()

    audit_rows = session.scalars(
        select(AuditEvent)
        .where(or_(AuditEvent.target_id == asset_id, AuditEvent.actor_id == asset_id))
        .order_by(AuditEvent.id.desc())
        .limit(15)
    ).all()
    telemetry_rows = session.scalars(
        select(TelemetryEvent)
        .where(
            or_(TelemetryEvent.asset_id == asset_id, TelemetryEvent.claimed_device_id == asset_id)
        )
        .order_by(TelemetryEvent.id.desc())
        .limit(12)
    ).all()

    profile = (
        PROFILES.get(identity.telemetry_profile)
        if identity and identity.telemetry_profile
        else None
    )
    accepted_commands = [
        {
            "action": spec.action,
            "label": spec.label,
            "effect": spec.effect,
            "permitted_sources": [
                p.source_asset_id or (f"zone:{p.source_zone_id}" if p.source_zone_id else "*")
                for p in policy_rows
                if p.policy_type is PolicyType.DEVICE_COMMAND
                and p.destination_asset_id == asset_id
                and p.service_or_action == spec.action
                and p.effect is PolicyEffect.ALLOW
            ],
        }
        for spec in COMMANDS.values()
        if asset.asset_type in spec.target_types
    ]

    return {
        "asset": _summary(
            asset, identity, twin, open_incident_counts(session, epoch).get(asset_id, 0)
        )
        | {
            "description": asset.description,
            "zone_name": asset.zone.name if asset.zone else None,
            "room_name": asset.room.name if asset.room else None,
            "is_simulated": asset.is_simulated,
        },
        "identity": None
        if identity is None
        else {
            "registration_status": identity.registration_status.value,
            "trust_state": identity.trust_state.value,
            "trust_reason": identity.trust_reason,
            "trust_changed_at": identity.trust_changed_at,
            "telemetry_profile": identity.telemetry_profile,
            "allowed_message_types": identity.allowed_message_types,
            "last_seen_at": identity.last_seen_at,
            "last_authenticated_at": identity.last_authenticated_at,
            "credentials": credentials,
        },
        "telemetry_profile": None
        if profile is None
        else {
            "id": profile.id,
            "label": profile.label,
            "model": profile.model,
            "notes": profile.notes,
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "unit": f.unit,
                    "kind": f.kind,
                    "minimum": f.minimum,
                    "maximum": f.maximum,
                    "choices": list(f.choices),
                }
                for f in profile.fields
            ],
        },
        "twin_state": twin_state_out(twin) if twin else None,
        "permissions": {
            "outbound": [
                policy_view(p)
                for p in policy_rows
                if p.source_asset_id == asset_id or (zone_id and p.source_zone_id == zone_id)
            ],
            "inbound": [
                policy_view(p)
                for p in policy_rows
                if p.destination_asset_id == asset_id
                or (zone_id and p.destination_zone_id == zone_id)
            ],
            "defaults": [policy_view(p) for p in policy_rows if p.priority >= 1000],
            "accepted_commands": accepted_commands,
        },
        "network_relationships": [relationship_view(r, assets, engine) for r in relationships],
        "dependencies": {
            "relies_on": [dependency_view(d, assets) for d in deps_as_dependent],
            "relied_on_by": [dependency_view(d, assets) for d in deps_as_provider],
        },
        "incidents": [
            {
                "id": inc.id,
                "reference": inc.reference,
                "title": inc.title,
                "status": inc.status.value,
                "severity": inc.severity.value,
                "role": role,
                "epoch": inc.epoch,
                "current_epoch": inc.epoch == epoch,
                "created_at": inc.created_at,
            }
            for inc, role in incident_rows
        ],
        "recent_audit": [
            {
                "id": a.id,
                "occurred_at": a.occurred_at,
                "actor_id": a.actor_id,
                "action": a.action,
                "decision": a.decision.value,
                "reason": a.reason,
                "correlation_id": a.correlation_id,
            }
            for a in audit_rows
        ],
        "recent_telemetry": [
            {
                "id": t.id,
                "received_at": t.received_at,
                "message_type": t.message_type,
                "decision": t.decision.value,
                "reason_code": t.reason_code,
                "integrity_verified": t.integrity_verified,
                "sequence": t.sequence,
            }
            for t in telemetry_rows
        ],
    }


def metrics_summary(session: Session, now: datetime) -> dict[str, Any]:
    epoch = current_epoch(session)
    hour_ago = now - timedelta(hours=1)
    identities = session.scalars(select(DeviceIdentity)).all()
    active_ids = set(session.scalars(select(Asset.id).where(Asset.is_active.is_(True))))
    trust = Counter(i.trust_state.value for i in identities if i.asset_id in active_ids)
    assets = session.scalars(select(Asset).where(Asset.is_active.is_(True))).all()

    incidents = session.scalars(select(Incident).where(Incident.epoch == epoch)).all()
    open_incidents = [i for i in incidents if i.status is not IncidentStatus.RESOLVED]

    def tele_counts(since: datetime | None) -> dict[str, int]:
        q = select(TelemetryEvent.decision, func.count(TelemetryEvent.id)).where(
            TelemetryEvent.epoch == epoch
        )
        if since is not None:
            q = q.where(TelemetryEvent.received_at >= since)
        rows = session.execute(q.group_by(TelemetryEvent.decision)).all()
        out = {d.value: 0 for d in TelemetryDecision}
        out.update({d.value: c for d, c in rows})
        return out

    reasons = dict(
        session.execute(
            select(TelemetryEvent.reason_code, func.count(TelemetryEvent.id))
            .where(
                TelemetryEvent.epoch == epoch, TelemetryEvent.decision != TelemetryDecision.ACCEPTED
            )
            .group_by(TelemetryEvent.reason_code)
        ).all()
    )
    denials = dict(
        session.execute(
            select(PolicyDecision.policy_type, func.count(PolicyDecision.id))
            .where(PolicyDecision.epoch == epoch, PolicyDecision.decision == PolicyEffect.DENY)
            .group_by(PolicyDecision.policy_type)
        ).all()
    )
    alerts = session.scalars(select(SecurityAlert).where(SecurityAlert.epoch == epoch)).all()
    comm_anomalies = [a for a in alerts if a.rule_id.startswith("MD-NET")]
    recent_alerts = sorted(alerts, key=lambda a: a.id, reverse=True)[:8]
    containment_policies = session.scalar(
        select(func.count(SecurityPolicy.id)).where(
            SecurityPolicy.is_active.is_(True), SecurityPolicy.origin == PolicyOrigin.CONTAINMENT
        )
    )
    blocked_flows = session.scalar(
        select(func.count(PolicyDecision.id)).where(
            PolicyDecision.epoch == epoch,
            PolicyDecision.policy_type == PolicyType.NETWORK_FLOW,
            PolicyDecision.outcome == DecisionOutcome.BLOCKED,
        )
    )
    return {
        "epoch": epoch,
        "generated_at": now,
        "inventory": {
            "assets": len([a for a in assets if not a.is_logical]),
            "logical_services": len([a for a in assets if a.is_logical]),
            "device_identities": sum(trust.values()),
            "discovered_unregistered": len([a for a in assets if a.discovered]),
            "by_kind": dict(Counter(a.asset_kind.value for a in assets)),
        },
        "trust_distribution": dict(trust),
        "incidents": {
            "open": len(open_incidents),
            "total": len(incidents),
            "open_by_severity": dict(Counter(i.severity.value for i in open_incidents)),
            "open_by_status": dict(Counter(i.status.value for i in open_incidents)),
        },
        "telemetry": {"last_hour": tele_counts(hour_ago), "epoch_total": tele_counts(None)},
        "rejections_by_reason": reasons,
        "policy_denials": {k.value: v for k, v in denials.items()},
        "blocked_flows": blocked_flows or 0,
        "alerts": {
            "total": len(alerts),
            "by_classification": dict(Counter(a.classification.value for a in alerts)),
            "by_severity": dict(Counter(a.severity.value for a in alerts)),
        },
        "communication_anomalies": len(comm_anomalies),
        "containment": {
            "active_containment_policies": containment_policies or 0,
            "assets_contained": [
                {"asset_id": a.id, "state": a.containment_state.value}
                for a in assets
                if a.containment_state is not ContainmentState.NONE
            ],
        },
        "recent_alerts": [
            {
                "id": a.id,
                "created_at": a.created_at,
                "rule_id": a.rule_id,
                "title": a.title,
                "classification": a.classification.value,
                "severity": a.severity.value,
                "subject_ref": a.subject_ref,
                "incident_id": a.incident_id,
            }
            for a in recent_alerts
        ],
    }


def telemetry_timeseries(session: Session, now: datetime, minutes: int) -> list[dict[str, Any]]:
    since = now - timedelta(minutes=minutes)
    bucket = func.date_trunc("minute", TelemetryEvent.received_at)
    rows = session.execute(
        select(bucket.label("minute"), TelemetryEvent.decision, func.count(TelemetryEvent.id))
        .where(TelemetryEvent.received_at >= since)
        .group_by("minute", TelemetryEvent.decision)
        .order_by("minute")
    ).all()
    series: dict[datetime, dict[str, Any]] = {}
    for minute, decision, count in rows:
        entry = series.setdefault(
            minute, {"minute": minute, "ACCEPTED": 0, "HELD": 0, "REJECTED": 0}
        )
        entry[decision.value] = count
    return list(series.values())
