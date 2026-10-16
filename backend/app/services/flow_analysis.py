"""Evaluation of network-sensor flow reports.

Each observed flow is attributed to assets by (synthetic) IP address and evaluated by the
policy engine. Routine permitted flows on modeled paths only update relationship counters;
denied, monitor-only or new flows are recorded as individual policy decisions and may raise
alerts. Unknown source addresses inside a hospital subnet become *discovered, unregistered*
endpoints: visible in the twin, never trusted.
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models import (
    Asset,
    DeviceIdentity,
    HospitalZone,
    NetworkRelationship,
    TwinState,
)
from app.models.enums import (
    ActorType,
    AssetKind,
    AuditDecision,
    Criticality,
    DecisionOutcome,
    PolicyType,
    RegistrationStatus,
    RelationshipOrigin,
    RelationshipType,
    TrustState,
)
from app.services import incidents, trust
from app.services.detection import rule as get_rule
from app.services.messages import FlowReportPayload
from app.services.policy_engine import PolicyEngine, endpoint_for_asset

if TYPE_CHECKING:
    from app.services.ingestion import Ingest

# Where a discovered endpoint is drawn: next to the zone's access/edge device.
DISCOVERY_PLACEMENT: dict[str, tuple[str, str, float, float]] = {
    "ZONE-ICU": ("ICU-COMMS", "ICU-SWITCH-01", 21.3, 22.0),
    "ZONE-IMG": ("IMG-NET-CLOSET", "IMG-SWITCH-01", 31.6, 22.0),
    "ZONE-DC": ("DC-SERVER-ROOM", "NET-GW-01", 1.6, 1.6),
    "ZONE-BMS": ("BMS-PLANT-ROOM", "BMS-GW-01", 34.5, 3.0),
}


def discovered_asset_id(ip: str) -> str:
    return "UNKNOWN-" + ip.replace(".", "-")


class FlowAnalysis:
    def analyze(self, ctx: Ingest, report: FlowReportPayload) -> dict[str, Any]:
        from app.services.ingestion import record_policy_decision

        session = ctx.session
        engine = PolicyEngine.load(session)
        ip_map: dict[str, Asset] = {
            a.ip_address: a
            for a in session.scalars(
                select(Asset).where(Asset.ip_address.is_not(None), Asset.is_active.is_(True))
            )
            if a.ip_address
        }
        zones = list(session.scalars(select(HospitalZone)))
        summary: dict[str, Any] = {
            "flows": len(report.flows),
            "routine": 0,
            "recorded": 0,
            "blocked": 0,
            "new_paths": 0,
            "discovered": [],
        }

        for flow in report.flows:
            src = ip_map.get(flow.src_ip)
            if src is None:
                src = self._discover(ctx, flow.src_ip, zones)
                if src is not None:
                    ip_map[flow.src_ip] = src
                    summary["discovered"].append(src.id)
            dst = ip_map.get(flow.dst_ip)
            src_ep = endpoint_for_asset(src, flow.src_ip)
            dst_ep = endpoint_for_asset(dst, flow.dst_ip)
            evaluation = engine.evaluate(PolicyType.NETWORK_FLOW, src_ep, dst_ep, flow.service)

            baseline = None
            if src is not None and dst is not None:
                baseline = session.scalars(
                    select(NetworkRelationship).where(
                        NetworkRelationship.source_asset_id == src.id,
                        NetworkRelationship.destination_asset_id == dst.id,
                        NetworkRelationship.service == flow.service,
                        NetworkRelationship.origin == RelationshipOrigin.BASELINE,
                    )
                ).first()
            if baseline is not None and evaluation.outcome is DecisionOutcome.PERMITTED:
                baseline.first_seen_at = baseline.first_seen_at or ctx.now
                baseline.last_seen_at = ctx.now
                baseline.observation_count += 1
                summary["routine"] += 1
                continue

            decision = record_policy_decision(
                ctx,
                PolicyType.NETWORK_FLOW,
                src_ep.ref,
                src,
                dst_ep.ref,
                dst,
                flow.service,
                evaluation,
            )
            summary["recorded"] += 1
            new_path = False
            observed: NetworkRelationship | None = None
            if src is not None and dst is not None and baseline is None:
                observed = session.scalars(
                    select(NetworkRelationship).where(
                        NetworkRelationship.source_asset_id == src.id,
                        NetworkRelationship.destination_asset_id == dst.id,
                        NetworkRelationship.service == flow.service,
                        NetworkRelationship.relationship_type == RelationshipType.DATA_FLOW,
                    )
                ).first()
                if observed is None:
                    from app.seed.catalog import SERVICES

                    label = SERVICES.get(
                        flow.service, (f"{flow.service} (observed)", flow.dst_port)
                    )[0]
                    observed = NetworkRelationship(
                        source_asset_id=src.id,
                        destination_asset_id=dst.id,
                        relationship_type=RelationshipType.DATA_FLOW,
                        service=flow.service,
                        protocol_label=label,
                        port=flow.dst_port,
                        origin=RelationshipOrigin.OBSERVED,
                        description="Observed by NET-SENSOR-01; not part of the modeled baseline.",
                        first_seen_at=ctx.now,
                        observation_count=0,
                    )
                    session.add(observed)
                    session.flush()
                    new_path = True
                    summary["new_paths"] += 1
                observed.last_seen_at = ctx.now
                observed.observation_count += 1

            blocked = evaluation.outcome is DecisionOutcome.BLOCKED
            summary["blocked"] += int(blocked)
            sensor_says_blocked = flow.enforcement_action == "blocked"
            evidence = {
                "flow": flow.model_dump(),
                "policy_decision_id": decision.id,
                "matched_policy_id": evaluation.matched_policy_id,
                "policy_reason": evaluation.reason,
                "sensor": ctx.identity.asset_id if ctx.identity else None,
                "telemetry_note": "Attribution by source IP (synthetic); a real attacker could spoof it.",
                "enforcement_consistent": sensor_says_blocked == blocked,
                "relationship_id": observed.id if observed else (baseline.id if baseline else None),
                "new_path": new_path,
            }
            rule_id: str | None = None
            if blocked:
                rule_id = "MD-NET-001"
            elif evaluation.outcome is DecisionOutcome.ALLOWED_MONITOR_ONLY:
                rule_id = "MD-NET-003"
            elif new_path:
                rule_id = "MD-NET-002"
            if blocked or evaluation.outcome is DecisionOutcome.ALLOWED_MONITOR_ONLY:
                ctx.uow.audit(
                    actor_type=ActorType.SYSTEM,
                    actor_id=evaluation.matched_policy_id or "default-deny",
                    action="FLOW_DENIED" if blocked else "FLOW_VIOLATION_MONITORED",
                    target_type="network_flow",
                    target_id=f"{src_ep.ref}->{dst_ep.ref}:{flow.service}"[:64],
                    decision=AuditDecision.DENY if blocked else AuditDecision.INFO,
                    reason=evaluation.reason,
                    details={"policy_decision_id": decision.id, "flow": flow.model_dump()},
                    simulation_run_id=ctx.msg.simulation_run_id,
                )
            if rule_id is not None:
                subject = src.id if src is not None else flow.src_ip
                outcome = incidents.raise_alert(
                    ctx.uow,
                    rule_id,
                    subject_ref=subject,
                    asset_id=src.id if src is not None else None,
                    evidence=evidence,
                    telemetry_event_id=None,
                    policy_decision_id=decision.id,
                    related_assets=[(dst.id, "TARGET")] if dst is not None else [],
                    simulation_run_id=ctx.msg.simulation_run_id,
                )
                if outcome.alert is not None:
                    ctx.alert_ids.append(outcome.alert.id)
                if (
                    outcome.incident is not None
                    and outcome.incident.reference not in ctx.incident_refs
                ):
                    ctx.incident_refs.append(outcome.incident.reference or str(outcome.incident.id))
                if get_rule(rule_id).marks_suspicious and src is not None:
                    identity = session.get(DeviceIdentity, src.id)
                    if identity is not None:
                        change = trust.mark_suspicious(
                            identity, f"{rule_id}: observed flow outside policy", ctx.now
                        )
                        if change:
                            ctx.trust_changes.append(change)
            ctx.uow.emit(
                "network.flow_observed",
                {
                    "source": src_ep.ref,
                    "destination": dst_ep.ref,
                    "service": flow.service,
                    "outcome": evaluation.outcome.value,
                    "matched_policy_id": evaluation.matched_policy_id,
                    "new_path": new_path,
                    "relationship_id": evidence["relationship_id"],
                    "policy_decision_id": decision.id,
                },
            )
        return summary

    def _discover(self, ctx: Ingest, ip: str, zones: list[HospitalZone]) -> Asset | None:
        session = ctx.session
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            return None
        zone = next((z for z in zones if address in ipaddress.ip_network(z.subnet)), None)
        if zone is None:
            return None  # outside hospital subnets: reported by address only
        asset_id = discovered_asset_id(ip)
        existing = session.get(Asset, asset_id)
        if existing is not None:
            existing.is_active = True
            return existing
        room_id, via, x, y = DISCOVERY_PLACEMENT[zone.id]
        asset = Asset(
            id=asset_id,
            display_name=f"Unregistered endpoint {ip}",
            asset_kind=AssetKind.UNKNOWN_ENDPOINT,
            asset_type="unknown_endpoint",
            is_logical=False,
            network_zone_id=zone.id,
            room_id=room_id,
            twin_node=None,
            position={"x": x, "y": y, "rotation": 0, "approximate": True, "attached_via": via},
            label_height=1.6,
            ip_address=ip,
            criticality=Criticality.MEDIUM,
            description=(
                f"Observed by the network sensor on {zone.name} (attached via {via}); not in the "
                "identity registry. Physical location is approximate."
            ),
            discovered=True,
        )
        session.add(asset)
        session.flush()
        session.add(
            DeviceIdentity(
                asset_id=asset_id,
                registration_status=RegistrationStatus.UNREGISTERED,
                trust_state=TrustState.UNREGISTERED,
                trust_reason="Observed on the network; never registered. Not trusted for any operation.",
                telemetry_profile=None,
                allowed_message_types=[],
            )
        )
        session.add(TwinState(asset_id=asset_id, version=0))
        session.flush()
        ctx.uow.audit(
            actor_type=ActorType.SYSTEM,
            actor_id=ctx.identity.asset_id if ctx.identity else "network-sensor",
            action="ENDPOINT_DISCOVERED",
            target_type="asset",
            target_id=asset_id,
            decision=AuditDecision.INFO,
            reason=f"Unregistered endpoint {ip} observed in {zone.id}; created as UNREGISTERED.",
            details={"ip": ip, "zone": zone.id, "attached_via": via},
            simulation_run_id=ctx.msg.simulation_run_id,
        )
        outcome = incidents.raise_alert(
            ctx.uow,
            "MD-ID-002",
            subject_ref=asset_id,
            asset_id=asset_id,
            evidence={
                "ip": ip,
                "zone": zone.id,
                "attached_via": via,
                "sensor": ctx.identity.asset_id if ctx.identity else None,
            },
            related_assets=[(via, "AFFECTED")],
            simulation_run_id=ctx.msg.simulation_run_id,
        )
        if outcome.alert is not None:
            ctx.alert_ids.append(outcome.alert.id)
        if outcome.incident is not None and outcome.incident.reference not in ctx.incident_refs:
            ctx.incident_refs.append(outcome.incident.reference or str(outcome.incident.id))
        ctx.uow.emit(
            "asset.discovered",
            {
                "asset_id": asset_id,
                "display_name": asset.display_name,
                "network_zone_id": zone.id,
                "room_id": room_id,
                "position": asset.position,
                "ip_address": ip,
                "trust_state": TrustState.UNREGISTERED.value,
            },
        )
        return asset
