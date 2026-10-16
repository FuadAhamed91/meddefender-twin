"""Containment planning, application and recovery.

Plans are generated as *hypothetical* policy sets and compared without touching live
policy. Applying a plan is an explicit, authorized, audited operator action that writes
containment policies, changes identity/containment state and moves the incident to
CONTAINED. Plans whose impact would impair a high-criticality service require the
SECURITY_ADMIN role (risk-based authorization).

Recovery never deletes evidence: containment policies are deactivated (kept), keys are
rotated to a new version, and trusted state is re-anchored to the last known-good
observation recorded before the incident.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.core import crypto
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import (
    Asset,
    ContainmentPlan,
    DeviceCredential,
    DeviceIdentity,
    HospitalZone,
    Incident,
    NetworkRelationship,
    OperationalDependency,
    SecurityPolicy,
    SimDevice,
    TelemetryEvent,
    TwinState,
)
from app.models.enums import (
    CRITICALITY_RANK,
    ROLE_RANK,
    ActorType,
    AuditDecision,
    ContainmentState,
    CredentialStatus,
    Criticality,
    DecisionOutcome,
    EnforcementMode,
    IncidentStatus,
    PlanStatus,
    PolicyEffect,
    PolicyOrigin,
    PolicyType,
    RelationshipOrigin,
    RelationshipType,
    TelemetryDecision,
    TrustState,
    UserRole,
)
from app.services import incidents as incident_service
from app.services import trust
from app.services.auth import Principal
from app.services.context import UnitOfWork
from app.services.graph import GraphContext, attack_paths, dependency_impact
from app.services.policy_engine import PolicyView

CONTAINMENT_PRIORITY = 10
EXCEPTION_PRIORITY = 5
ANALYSIS_DEPTH = 3

STRATEGIES = (
    "ISOLATE_ASSET",
    "RESTRICT_TO_REQUIRED_FLOWS",
    "ISOLATE_ZONE_EGRESS",
    "REVOKE_CREDENTIALS",
)


def _policy(
    pid: str,
    name: str,
    *,
    src_asset: str | None = None,
    src_zone: str | None = None,
    dst_asset: str | None = None,
    dst_zone: str | None = None,
    service: str = "*",
    effect: PolicyEffect,
    priority: int,
    enforcement_point: str | None,
    rationale: str,
) -> dict[str, Any]:
    return {
        "id": pid,
        "name": name,
        "source_asset_id": src_asset,
        "source_zone_id": src_zone,
        "destination_asset_id": dst_asset,
        "destination_zone_id": dst_zone,
        "service_or_action": service,
        "effect": effect.value,
        "priority": priority,
        "enforcement_point_id": enforcement_point,
        "rationale": rationale,
    }


def plan_policy_view(spec: dict[str, Any]) -> PolicyView:
    return PolicyView(
        id=spec["id"],
        name=spec["name"],
        policy_type=PolicyType.NETWORK_FLOW,
        source_asset_id=spec["source_asset_id"],
        source_zone_id=spec["source_zone_id"],
        destination_asset_id=spec["destination_asset_id"],
        destination_zone_id=spec["destination_zone_id"],
        service_or_action=spec["service_or_action"],
        effect=PolicyEffect(spec["effect"]),
        priority=spec["priority"],
        enforcement_mode=EnforcementMode.ENFORCED,
        enforcement_point_id=spec["enforcement_point_id"],
        origin=PolicyOrigin.CONTAINMENT.value,
        rationale=spec["rationale"],
    )


def _edge_point(asset: Asset) -> str:
    return {"ZONE-ICU": "ICU-SWITCH-01", "ZONE-IMG": "IMG-SWITCH-01"}.get(
        asset.network_zone_id or "", "NET-GW-01"
    )


def _required_outbound(uow: UnitOfWork, target: Asset) -> list[NetworkRelationship]:
    """Baseline outbound flows that carry a HIGH/CRITICAL operational dependency."""
    session = uow.session
    rels = session.scalars(
        select(NetworkRelationship).where(
            NetworkRelationship.source_asset_id == target.id,
            NetworkRelationship.origin == RelationshipOrigin.BASELINE,
            NetworkRelationship.relationship_type != RelationshipType.L2_UPLINK,
        )
    ).all()
    required = []
    for rel in rels:
        deps = session.scalars(
            select(OperationalDependency).where(
                OperationalDependency.carried_by_relationship_id == rel.id
            )
        ).all()
        if any(CRITICALITY_RANK[d.criticality] >= CRITICALITY_RANK[Criticality.HIGH] for d in deps):
            required.append(rel)
    return required


def build_strategy(
    uow: UnitOfWork, strategy: str, target: Asset, incident: Incident
) -> dict[str, Any] | None:
    session = uow.session
    prefix = f"CT-{incident.reference or incident.id}-{strategy[:12]}"
    identity = session.get(DeviceIdentity, target.id)
    has_key = (
        identity is not None
        and session.scalars(
            select(DeviceCredential).where(
                DeviceCredential.asset_id == target.id,
                DeviceCredential.status == CredentialStatus.ACTIVE,
            )
        ).first()
        is not None
    )
    point = _edge_point(target)

    if strategy == "ISOLATE_ASSET":
        policies = [
            _policy(
                f"{prefix}-OUT",
                f"Isolate {target.id} (outbound)",
                src_asset=target.id,
                effect=PolicyEffect.DENY,
                priority=CONTAINMENT_PRIORITY,
                enforcement_point=point,
                rationale="Containment: full isolation.",
            ),
            _policy(
                f"{prefix}-IN",
                f"Isolate {target.id} (inbound)",
                dst_asset=target.id,
                effect=PolicyEffect.DENY,
                priority=CONTAINMENT_PRIORITY,
                enforcement_point=point,
                rationale="Containment: full isolation.",
            ),
        ]
        identity_changes = (
            [{"asset_id": target.id, "trust_state": TrustState.QUARANTINED.value}]
            if identity is not None
            and identity.trust_state not in (TrustState.UNREGISTERED, TrustState.REVOKED)
            else []
        )
        return {
            "name": f"Isolate {target.id}",
            "description": f"Block every flow to and from {target.id} at {point} and quarantine its identity.",
            "policies": policies,
            "identity_changes": identity_changes,
            "containment_state": ContainmentState.ISOLATED.value,
            "isolated": [target.id],
        }
    if strategy == "RESTRICT_TO_REQUIRED_FLOWS":
        required = _required_outbound(uow, target)
        outbound_any = session.scalars(
            select(NetworkRelationship).where(
                NetworkRelationship.source_asset_id == target.id,
                NetworkRelationship.relationship_type != RelationshipType.L2_UPLINK,
            )
        ).first()
        if outbound_any is None:
            return None
        policies = [
            _policy(
                f"{prefix}-KEEP-{i}",
                f"Keep {rel.source_asset_id} -> {rel.destination_asset_id} ({rel.service})",
                src_asset=rel.source_asset_id,
                dst_asset=rel.destination_asset_id,
                service=rel.service,
                effect=PolicyEffect.ALLOW,
                priority=EXCEPTION_PRIORITY,
                enforcement_point=point,
                rationale="Carries a high-criticality operational dependency.",
            )
            for i, rel in enumerate(required, start=1)
        ]
        policies.append(
            _policy(
                f"{prefix}-OUT",
                f"Restrict {target.id} outbound",
                src_asset=target.id,
                effect=PolicyEffect.DENY,
                priority=CONTAINMENT_PRIORITY,
                enforcement_point=point,
                rationale="Containment: block everything the asset originates except required flows.",
            )
        )
        return {
            "name": f"Restrict {target.id} to required flows",
            "description": (
                f"Allow only {len(required)} outbound flow(s) that carry high-criticality dependencies and block "
                f"everything else {target.id} originates. Inbound feeds are unaffected; identity state is unchanged."
            ),
            "policies": policies,
            "identity_changes": [],
            "containment_state": ContainmentState.RESTRICTED.value,
            "isolated": [],
        }
    if strategy == "ISOLATE_ZONE_EGRESS":
        if target.network_zone_id is None:
            return None
        zones = [
            z.id for z in session.scalars(select(HospitalZone)) if z.id != target.network_zone_id
        ]
        policies = [
            _policy(
                f"{prefix}-{zone[5:]}",
                f"Block {target.network_zone_id} -> {zone}",
                src_zone=target.network_zone_id,
                dst_zone=zone,
                effect=PolicyEffect.DENY,
                priority=CONTAINMENT_PRIORITY,
                enforcement_point="NET-GW-01",
                rationale="Containment: zone egress block.",
            )
            for zone in zones
        ]
        return {
            "name": f"Block {target.network_zone_id} egress",
            "description": f"Deny all traffic from {target.network_zone_id} to every other zone at NET-GW-01.",
            "policies": policies,
            "identity_changes": [],
            "containment_state": ContainmentState.RESTRICTED.value,
            "isolated": [],
        }
    if strategy == "REVOKE_CREDENTIALS":
        if not has_key:
            return None
        return {
            "name": f"Revoke {target.id} credentials",
            "description": (
                f"Revoke {target.id}'s active key. The platform refuses its messages, but network traffic is NOT "
                "blocked: identity revocation is not network containment."
            ),
            "policies": [],
            "identity_changes": [
                {
                    "asset_id": target.id,
                    "trust_state": TrustState.REVOKED.value,
                    "revoke_credential": True,
                }
            ],
            "containment_state": ContainmentState.NONE.value,
            "isolated": [],
        }
    raise ValueError(strategy)


def analyse(uow: UnitOfWork, target: Asset, spec: dict[str, Any]) -> dict[str, Any]:
    session = uow.session
    views = [plan_policy_view(p) for p in spec["policies"]]
    before_ctx = GraphContext.load(session)
    after_ctx = GraphContext.load(session, extra_policies=views)
    before = attack_paths(session, before_ctx, target.id, ANALYSIS_DEPTH, uow.epoch)
    after = attack_paths(session, after_ctx, target.id, ANALYSIS_DEPTH, uow.epoch)

    newly_blocked = [
        edge.as_dict()
        for edge in before_ctx.edges()
        if edge.permitted
        and after_ctx.status_of(edge.source, edge.destination, edge.service)
        is DecisionOutcome.BLOCKED
    ]
    isolated = set(spec["isolated"])
    impact_before = dependency_impact(session, before_ctx, set())
    impact_after = dependency_impact(session, after_ctx, isolated)
    before_keys = {
        (d["dependent_asset_id"], d["provider_asset_id"], d["dependency_type"])
        for d in impact_before["disrupted_dependencies"]
    }
    new_disruptions = [
        d
        for d in impact_after["disrupted_dependencies"]
        if (d["dependent_asset_id"], d["provider_asset_id"], d["dependency_type"])
        not in before_keys
    ]
    before_status = {s["asset_id"]: s["status"] for s in impact_before["services"]}
    services_changed = [
        s for s in impact_after["services"] if s["status"] != before_status.get(s["asset_id"])
    ]

    def high_value(reachable: list[dict[str, Any]]) -> int:
        return sum(1 for r in reachable if r["criticality"] in ("HIGH", "CRITICAL"))

    paths_before, paths_after = before["path_count"], after["path_count"]
    reduction = round(100 * (paths_before - paths_after) / paths_before, 1) if paths_before else 0.0
    impaired = [s for s in services_changed if s["status"] == "IMPAIRED"]
    degraded = [s for s in services_changed if s["status"] == "DEGRADED"]
    if paths_after == paths_before:
        reach_note = "Attack paths are unchanged: this option does not alter network reachability."
    else:
        reach_note = (
            f"Attack paths reduced from {paths_before} to {paths_after} ({reduction}% fewer)."
        )
    if impaired:
        impact_note = "Would impair: " + ", ".join(s["display_name"] for s in impaired) + "."
    elif degraded:
        impact_note = "Would degrade: " + ", ".join(s["display_name"] for s in degraded) + "."
    else:
        impact_note = "No modeled service is impaired or degraded."
    return {
        "metrics": {
            "paths_before": paths_before,
            "paths_after": paths_after,
            "path_reduction_pct": reduction,
            "reachable_before": len(before["reachable_assets"]),
            "reachable_after": len(after["reachable_assets"]),
            "high_value_reachable_before": high_value(before["reachable_assets"]),
            "high_value_reachable_after": high_value(after["reachable_assets"]),
            "flows_blocked": len(newly_blocked),
            "dependencies_disrupted": len(new_disruptions),
            "services_impaired": len(impaired),
            "services_degraded": len(degraded),
        },
        "blocked_flows": newly_blocked,
        "reachable_before": before["reachable_assets"],
        "residual_reachable": after["reachable_assets"],
        "residual_paths": after["paths"][:50],
        "disrupted_dependencies": new_disruptions,
        "service_impact": services_changed,
        "summary": f"{reach_note} {impact_note}",
        "limitations": [
            "Impact is computed from the modeled dependency graph only; real clinical workflows may differ.",
            "Reachability assumes enforcement points apply policy exactly as configured.",
        ],
    }


def generate_plans(
    uow: UnitOfWork, incident: Incident, actor: str, *, user_id: int | None
) -> list[ContainmentPlan]:
    session = uow.session
    if incident.epoch != uow.epoch:
        raise Conflict(
            "INCIDENT_FROM_PREVIOUS_BASELINE",
            "This incident belongs to a previous simulation baseline.",
        )
    if incident.status not in (IncidentStatus.INVESTIGATING, IncidentStatus.CONTAINMENT_PROPOSED):
        raise Conflict(
            "INVALID_STATE",
            f"Containment plans can be generated while INVESTIGATING or CONTAINMENT_PROPOSED (incident is {incident.status.value}).",
        )
    target = session.get(Asset, incident.primary_asset_id) if incident.primary_asset_id else None
    if target is None or target.is_logical:
        raise AppError(
            422, "NO_CONTAINABLE_ASSET", "The incident has no physical primary asset to contain."
        )

    for old in session.scalars(
        select(ContainmentPlan).where(
            ContainmentPlan.incident_id == incident.id,
            ContainmentPlan.status == PlanStatus.PROPOSED,
        )
    ):
        old.status = PlanStatus.SUPERSEDED

    plans: list[ContainmentPlan] = []
    for strategy in STRATEGIES:
        spec = build_strategy(uow, strategy, target, incident)
        if spec is None:
            continue
        analysis = analyse(uow, target, spec)
        required_role = (
            UserRole.SECURITY_ADMIN.value
            if analysis["metrics"]["services_impaired"]
            else UserRole.OPERATOR.value
        )
        analysis["required_role_reason"] = (
            "Impairs a modeled high-criticality service; requires SECURITY_ADMIN approval."
            if required_role == UserRole.SECURITY_ADMIN.value
            else "No high-criticality service impaired; OPERATOR may apply."
        )
        analysis["containment_state"] = spec["containment_state"]
        plan = ContainmentPlan(
            incident_id=incident.id,
            strategy=strategy,
            target_asset_id=target.id,
            name=spec["name"],
            description=spec["description"],
            status=PlanStatus.PROPOSED,
            required_role=required_role,
            analysis=analysis,
            policy_changes=spec["policies"],
            identity_changes=spec["identity_changes"],
            created_at=uow.now,
            created_by_user_id=user_id,
        )
        session.add(plan)
        plans.append(plan)
    session.flush()

    incident_service.add_incident_event(
        uow,
        incident,
        "CONTAINMENT_PROPOSED",
        f"{len(plans)} containment plan(s) generated for {target.id}",
        actor_type=ActorType.USER if user_id else ActorType.SYSTEM,
        actor_id=actor,
        details={
            "plans": [
                {"id": p.id, "strategy": p.strategy, "summary": p.analysis["summary"]}
                for p in plans
            ]
        },
    )
    uow.audit(
        actor_type=ActorType.USER if user_id else ActorType.SYSTEM,
        actor_id=actor,
        action="CONTAINMENT_PLANS_GENERATED",
        target_type="incident",
        target_id=incident.reference or str(incident.id),
        decision=AuditDecision.INFO,
        reason=f"Generated {len(plans)} plans for {target.id}; no policy changed.",
        details={"plan_ids": [p.id for p in plans]},
        incident_id=incident.id,
    )
    if incident.status is IncidentStatus.INVESTIGATING:
        incident_service.transition_incident(
            uow,
            incident,
            IncidentStatus.CONTAINMENT_PROPOSED,
            actor_id=actor,
            note="Containment options generated for comparison.",
            system=True,
        )
    uow.emit(
        "containment.plans_generated",
        {"incident_id": incident.id, "plan_ids": [p.id for p in plans]},
    )
    return plans


def apply_plan(
    uow: UnitOfWork, plan_id: int, principal: Principal, justification: str
) -> ContainmentPlan:
    session = uow.session
    plan = session.get(ContainmentPlan, plan_id, with_for_update=True)
    if plan is None:
        raise NotFound("Containment plan", plan_id)
    incident = session.get(Incident, plan.incident_id, with_for_update=True)
    assert incident is not None
    if ROLE_RANK[principal.role] < ROLE_RANK[UserRole(plan.required_role)]:
        uow.audit(
            actor_type=ActorType.USER,
            actor_id=principal.username,
            action="CONTAINMENT_APPLY_DENIED",
            target_type="containment_plan",
            target_id=str(plan.id),
            decision=AuditDecision.DENY,
            reason=f"Plan requires {plan.required_role}; user has {principal.role.value}.",
            incident_id=incident.id,
        )
        raise Forbidden(
            f"This plan requires the {plan.required_role} role: {plan.analysis.get('required_role_reason', '')}"
        )
    if plan.status is not PlanStatus.PROPOSED:
        raise Conflict(
            "PLAN_NOT_PROPOSED", f"Plan is {plan.status.value}; only PROPOSED plans can be applied."
        )
    if incident.status is not IncidentStatus.CONTAINMENT_PROPOSED:
        raise Conflict(
            "INVALID_STATE", f"Incident must be CONTAINMENT_PROPOSED (is {incident.status.value})."
        )

    created_policies = []
    for spec in plan.policy_changes:
        policy = SecurityPolicy(
            id=f"{spec['id']}-P{plan.id}"[:64],
            name=spec["name"],
            description=f"Created by containment plan {plan.id} for {incident.reference}.",
            rationale=spec["rationale"],
            policy_type=PolicyType.NETWORK_FLOW,
            source_asset_id=spec["source_asset_id"],
            source_zone_id=spec["source_zone_id"],
            destination_asset_id=spec["destination_asset_id"],
            destination_zone_id=spec["destination_zone_id"],
            service_or_action=spec["service_or_action"],
            effect=PolicyEffect(spec["effect"]),
            priority=spec["priority"],
            enforcement_mode=EnforcementMode.ENFORCED,
            enforcement_point_id=spec["enforcement_point_id"],
            origin=PolicyOrigin.CONTAINMENT,
            incident_id=incident.id,
            containment_plan_id=plan.id,
            created_by_user_id=principal.user_id,
            created_at=uow.now,
        )
        session.add(policy)
        created_policies.append(policy.id)

    trust_changes = []
    for change in plan.identity_changes:
        identity = session.get(DeviceIdentity, change["asset_id"], with_for_update=True)
        if identity is None:
            continue
        target_state = TrustState(change["trust_state"])
        if change.get("revoke_credential"):
            for cred in session.scalars(
                select(DeviceCredential).where(
                    DeviceCredential.asset_id == identity.asset_id,
                    DeviceCredential.status == CredentialStatus.ACTIVE,
                )
            ):
                cred.status = CredentialStatus.REVOKED
                cred.retired_at = uow.now
                cred.retired_reason = f"Revoked by containment plan {plan.id}"
        result = trust.transition(
            identity, target_state, f"Containment plan {plan.id} ({plan.strategy})", uow.now
        )
        if result:
            trust_changes.append(result)
            uow.emit(
                "trust.changed",
                {
                    "asset_id": result.asset_id,
                    "from": result.from_state.value,
                    "to": result.to_state.value,
                    "reason": result.reason,
                },
            )

    target = session.get(Asset, plan.target_asset_id)
    assert target is not None
    target.containment_state = ContainmentState(
        plan.analysis.get("containment_state", ContainmentState.NONE.value)
    )

    for other in session.scalars(
        select(ContainmentPlan).where(
            ContainmentPlan.incident_id == incident.id,
            ContainmentPlan.status == PlanStatus.PROPOSED,
            ContainmentPlan.id != plan.id,
        )
    ):
        other.status = PlanStatus.SUPERSEDED
    plan.status = PlanStatus.APPLIED
    plan.applied_at = uow.now
    plan.applied_by_user_id = principal.user_id
    plan.apply_justification = justification
    session.flush()

    incident_service.add_incident_event(
        uow,
        incident,
        "CONTAINMENT_APPLIED",
        f"Applied plan {plan.id}: {plan.name}",
        actor_type=ActorType.USER,
        actor_id=principal.username,
        details={
            "plan_id": plan.id,
            "strategy": plan.strategy,
            "justification": justification,
            "policies_created": created_policies,
            "trust_changes": [
                {"asset_id": t.asset_id, "from": t.from_state.value, "to": t.to_state.value}
                for t in trust_changes
            ],
            "containment_state": target.containment_state.value,
            "expected_effect": plan.analysis.get("summary"),
        },
    )
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="CONTAINMENT_APPLIED",
        target_type="containment_plan",
        target_id=str(plan.id),
        decision=AuditDecision.SUCCESS,
        reason=justification,
        details={
            "strategy": plan.strategy,
            "policies_created": created_policies,
            "target": target.id,
        },
        incident_id=incident.id,
    )
    incident_service.transition_incident(
        uow,
        incident,
        IncidentStatus.CONTAINED,
        actor_id=principal.username,
        note=f"Containment plan {plan.id} applied.",
        system=True,
    )
    uow.emit(
        "containment.applied",
        {
            "incident_id": incident.id,
            "plan_id": plan.id,
            "strategy": plan.strategy,
            "target_asset_id": target.id,
            "containment_state": target.containment_state.value,
            "policies_created": created_policies,
        },
    )
    uow.emit(
        "asset.updated",
        {"asset_id": target.id, "containment_state": target.containment_state.value},
    )
    return plan


def execute_recovery(
    uow: UnitOfWork,
    incident: Incident,
    principal: Principal,
    *,
    rotate_credentials: bool,
    release_containment: bool,
    restore_trusted_state: bool,
    note: str,
) -> dict[str, Any]:
    session = uow.session
    if incident.epoch != uow.epoch:
        raise Conflict(
            "INCIDENT_FROM_PREVIOUS_BASELINE",
            "This incident belongs to a previous simulation baseline.",
        )
    if incident.status is not IncidentStatus.RECOVERY:
        raise Conflict(
            "INVALID_STATE", f"Move the incident to RECOVERY first (it is {incident.status.value})."
        )

    plans = session.scalars(
        select(ContainmentPlan).where(ContainmentPlan.incident_id == incident.id)
    ).all()
    targets = {p.target_asset_id for p in plans if p.status is PlanStatus.APPLIED}
    if incident.primary_asset_id:
        targets.add(incident.primary_asset_id)
    steps: list[dict[str, Any]] = []

    if rotate_credentials:
        for asset_id in sorted(targets):
            identity = session.get(DeviceIdentity, asset_id, with_for_update=True)
            if identity is None or identity.registration_status.value != "REGISTERED":
                continue
            creds = session.scalars(
                select(DeviceCredential).where(DeviceCredential.asset_id == asset_id)
            ).all()
            if not creds:
                continue
            new_version = max(c.key_version for c in creds) + 1
            for cred in creds:
                if cred.status is CredentialStatus.ACTIVE:
                    cred.status = CredentialStatus.ROTATED
                    cred.retired_at = uow.now
                    cred.retired_reason = f"Rotated during recovery of {incident.reference}"
            session.flush()
            key = crypto.derive_device_key(
                uow.services.settings.master_secret_bytes, asset_id, new_version
            )
            session.add(
                DeviceCredential(
                    asset_id=asset_id,
                    key_version=new_version,
                    fingerprint=crypto.key_fingerprint(key),
                    status=CredentialStatus.ACTIVE,
                    created_at=uow.now,
                )
            )
            sim = session.get(SimDevice, asset_id, with_for_update=True)
            if sim is not None:
                sim.key_version = new_version  # simulated re-provisioning of the device
            change = None
            if identity.trust_state is not TrustState.REGISTERED and trust.can_transition(
                identity.trust_state, TrustState.REGISTERED
            ):
                change = trust.transition(
                    identity,
                    TrustState.REGISTERED,
                    "Re-provisioned with a new key; must re-authenticate",
                    uow.now,
                )
            steps.append(
                {
                    "action": "ROTATE_CREDENTIALS",
                    "asset_id": asset_id,
                    "new_key_version": new_version,
                    "fingerprint": crypto.key_fingerprint(key),
                    "trust_change": None
                    if change is None
                    else f"{change.from_state.value} -> {change.to_state.value}",
                }
            )
            if change:
                uow.emit(
                    "trust.changed",
                    {
                        "asset_id": asset_id,
                        "from": change.from_state.value,
                        "to": change.to_state.value,
                        "reason": change.reason,
                    },
                )

    if release_containment:
        released = []
        for policy in session.scalars(
            select(SecurityPolicy).where(
                SecurityPolicy.incident_id == incident.id, SecurityPolicy.is_active.is_(True)
            )
        ):
            policy.is_active = False
            policy.deactivated_at = uow.now
            released.append(policy.id)
        for plan in plans:
            if plan.status is PlanStatus.APPLIED:
                plan.status = PlanStatus.ROLLED_BACK
                plan.rolled_back_at = uow.now
                plan.rolled_back_by_user_id = principal.user_id
        for asset_id in targets:
            asset = session.get(Asset, asset_id)
            if asset is not None and asset.containment_state is not ContainmentState.NONE:
                asset.containment_state = ContainmentState.NONE
                uow.emit("asset.updated", {"asset_id": asset_id, "containment_state": "NONE"})
        steps.append(
            {
                "action": "RELEASE_CONTAINMENT",
                "policies_deactivated": released,
                "note": "Policies kept for evidence (deactivated, not deleted).",
            }
        )

    if restore_trusted_state:
        for asset_id in sorted(targets):
            twin = session.get(TwinState, asset_id)
            if twin is None:
                continue
            last_good = session.scalars(
                select(TelemetryEvent)
                .where(
                    TelemetryEvent.asset_id == asset_id,
                    TelemetryEvent.decision == TelemetryDecision.ACCEPTED,
                    TelemetryEvent.received_at < incident.created_at,
                    TelemetryEvent.message_type.in_(("TELEMETRY", "HEARTBEAT")),
                )
                .order_by(TelemetryEvent.id.desc())
                .limit(1)
            ).first()
            previous = twin.trusted_event_id
            if last_good is not None and last_good.payload is not None:
                twin.trusted = dict(last_good.payload)
                twin.trusted_at = last_good.received_at
                twin.trusted_event_id = last_good.id
            twin.discrepancy = None
            twin.predicted = None
            twin.predicted_at = None
            twin.version += 1
            twin.updated_at = uow.now
            steps.append(
                {
                    "action": "RESTORE_TRUSTED_STATE",
                    "asset_id": asset_id,
                    "restored_from_event_id": last_good.id if last_good else None,
                    "previous_trusted_event_id": previous,
                    "note": "Re-anchored to the last accepted observation before the incident."
                    if last_good
                    else "No pre-incident observation available; model state cleared.",
                }
            )
            from app.services.ingestion import twin_payload

            uow.emit("twin.updated", twin_payload(twin, session.get(DeviceIdentity, asset_id)))

    incident.recovery_completed = True
    incident.updated_at = uow.now
    incident_service.add_incident_event(
        uow,
        incident,
        "RECOVERY_EXECUTED",
        f"Recovery actions executed ({len(steps)} step(s))",
        actor_type=ActorType.USER,
        actor_id=principal.username,
        details={"steps": steps, "note": note},
    )
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="RECOVERY_EXECUTED",
        target_type="incident",
        target_id=incident.reference or str(incident.id),
        decision=AuditDecision.SUCCESS,
        reason=note,
        details={"steps": steps},
        incident_id=incident.id,
    )
    uow.emit("incident.updated", incident_service.incident_summary(incident))
    return {"incident_id": incident.id, "steps": steps}
