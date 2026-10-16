"""Administrative operations: simulation reset, generator control, device identity
management, enrollment decisions and policy enforcement modes.

Reset restores a known baseline in a NEW epoch. It never deletes audit events, incidents,
incident timelines, alerts, telemetry evidence or policy decisions. Replay state and
device-side counters are deliberately NOT reset, so messages captured before a reset can
never become valid again.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select

from app.core import crypto
from app.core.errors import Conflict, NotFound
from app.models import (
    Asset,
    ContainmentPlan,
    DeviceCredential,
    DeviceIdentity,
    DeviceReplayState,
    EnrollmentRequest,
    NetworkRelationship,
    SecurityPolicy,
    SimDevice,
    SimulationState,
    TwinState,
)
from app.models.enums import (
    ActorType,
    AuditDecision,
    ContainmentState,
    CredentialStatus,
    EnforcementMode,
    EnrollmentStatus,
    PlanStatus,
    PolicyOrigin,
    RegistrationStatus,
    RelationshipOrigin,
    TrustState,
)
from app.services import trust
from app.services.auth import Principal
from app.services.context import UnitOfWork
from app.simulator.world import initial_state


def reset_simulation(uow: UnitOfWork, principal: Principal, reason: str) -> dict[str, Any]:
    session = uow.session
    state = session.get(SimulationState, 1, with_for_update=True)
    assert state is not None
    old_epoch = state.epoch
    state.epoch = old_epoch + 1
    state.last_reset_at = uow.now
    state.last_reset_by_user_id = principal.user_id
    uow._epoch = state.epoch  # subsequent records belong to the new baseline

    counts: dict[str, int] = {}
    deactivated = 0
    for policy in session.scalars(
        select(SecurityPolicy).where(
            SecurityPolicy.origin != PolicyOrigin.BASELINE, SecurityPolicy.is_active.is_(True)
        )
    ):
        policy.is_active = False
        policy.deactivated_at = uow.now
        deactivated += 1
    restored_modes = 0
    for policy in session.scalars(
        select(SecurityPolicy).where(SecurityPolicy.origin == PolicyOrigin.BASELINE)
    ):
        if not policy.is_active or policy.enforcement_mode is not EnforcementMode.ENFORCED:
            policy.is_active = True
            policy.enforcement_mode = EnforcementMode.ENFORCED
            policy.deactivated_at = None
            restored_modes += 1
    counts["policies_deactivated"] = deactivated
    counts["baseline_policies_restored"] = restored_modes

    hidden = 0
    for asset in session.scalars(
        select(Asset).where(Asset.discovered.is_(True), Asset.is_active.is_(True))
    ):
        asset.is_active = False
        hidden += 1
    counts["discovered_endpoints_retired"] = hidden

    restored_identities = 0
    for identity in session.scalars(select(DeviceIdentity)):
        asset = session.get(Asset, identity.asset_id)
        if asset is None or asset.discovered:
            continue
        # Administrative baseline restore (audited below), not a protocol transition.
        identity.registration_status = RegistrationStatus.REGISTERED
        identity.trust_state = TrustState.REGISTERED
        identity.trust_reason = (
            f"Baseline restored by reset (epoch {state.epoch}); must re-authenticate."
        )
        identity.trust_changed_at = uow.now
        has_active = session.scalars(
            select(DeviceCredential).where(
                DeviceCredential.asset_id == identity.asset_id,
                DeviceCredential.status == CredentialStatus.ACTIVE,
            )
        ).first()
        if has_active is None:
            creds = session.scalars(
                select(DeviceCredential).where(DeviceCredential.asset_id == identity.asset_id)
            ).all()
            version = max((c.key_version for c in creds), default=0) + 1
            key = crypto.derive_device_key(
                uow.services.settings.master_secret_bytes, identity.asset_id, version
            )
            session.add(
                DeviceCredential(
                    asset_id=identity.asset_id,
                    key_version=version,
                    fingerprint=crypto.key_fingerprint(key),
                    status=CredentialStatus.ACTIVE,
                    created_at=uow.now,
                )
            )
            sim = session.get(SimDevice, identity.asset_id)
            if sim is not None:
                sim.key_version = version
        restored_identities += 1
    counts["identities_restored"] = restored_identities

    for asset in session.scalars(
        select(Asset).where(Asset.containment_state != ContainmentState.NONE)
    ):
        asset.containment_state = ContainmentState.NONE

    for sim in session.scalars(select(SimDevice)):
        identity = session.get(DeviceIdentity, sim.asset_id)
        if identity is not None and identity.telemetry_profile:
            sim.physical_state = initial_state(sim.asset_id, identity.telemetry_profile)
        sim.online = True
        sim.updated_at = uow.now

    for twin in session.scalars(select(TwinState)):
        twin.reported = twin.trusted = twin.predicted = twin.discrepancy = None
        twin.reported_at = twin.trusted_at = twin.predicted_at = None
        twin.reported_event_id = twin.trusted_event_id = None
        twin.reported_decision = None
        twin.model_name = None
        twin.version += 1
        twin.updated_at = uow.now

    removed = session.execute(
        delete(NetworkRelationship).where(NetworkRelationship.origin == RelationshipOrigin.OBSERVED)
    ).rowcount
    counts["observed_relationships_cleared"] = removed or 0
    for rel in session.scalars(select(NetworkRelationship)):
        rel.first_seen_at = rel.last_seen_at = None
        rel.observation_count = 0

    for req in session.scalars(
        select(EnrollmentRequest).where(EnrollmentRequest.status == EnrollmentStatus.PENDING)
    ):
        req.status = EnrollmentStatus.EXPIRED
        req.decided_at = uow.now
        req.decision_reason = "Expired by simulation reset"
    for plan in session.scalars(
        select(ContainmentPlan).where(ContainmentPlan.status == PlanStatus.PROPOSED)
    ):
        plan.status = PlanStatus.SUPERSEDED

    replay_rows = len(session.scalars(select(DeviceReplayState)).all())
    counts["replay_state_rows_preserved"] = replay_rows
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="SIMULATION_RESET",
        target_type="simulation",
        target_id=f"epoch-{state.epoch}",
        decision=AuditDecision.SUCCESS,
        reason=reason,
        details=counts
        | {
            "previous_epoch": old_epoch,
            "preserved": [
                "audit_events",
                "incidents",
                "incident_events",
                "security_alerts",
                "telemetry_events",
                "policy_decisions",
                "device_replay_state",
                "sim_device counters",
            ],
        },
    )
    uow.emit(
        "simulation.reset",
        {"epoch": state.epoch, "previous_epoch": old_epoch, "by": principal.username},
    )
    return {"epoch": state.epoch, "previous_epoch": old_epoch, **counts}


def set_generator(uow: UnitOfWork, principal: Principal, enabled: bool) -> SimulationState:
    state = uow.session.get(SimulationState, 1, with_for_update=True)
    assert state is not None
    state.generator_enabled = enabled
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="GENERATOR_TOGGLED",
        target_type="simulation",
        target_id="generator",
        decision=AuditDecision.SUCCESS,
        reason=f"Telemetry generator {'enabled' if enabled else 'paused'}.",
    )
    uow.emit("simulation.generator", {"enabled": enabled})
    return state


def _identity(uow: UnitOfWork, asset_id: str) -> DeviceIdentity:
    identity = uow.session.get(DeviceIdentity, asset_id, with_for_update=True)
    if identity is None:
        raise NotFound("Device identity", asset_id)
    return identity


def revoke_device(
    uow: UnitOfWork, principal: Principal, asset_id: str, reason: str
) -> dict[str, Any]:
    identity = _identity(uow, asset_id)
    revoked = 0
    for cred in uow.session.scalars(
        select(DeviceCredential).where(
            DeviceCredential.asset_id == asset_id,
            DeviceCredential.status == CredentialStatus.ACTIVE,
        )
    ):
        cred.status = CredentialStatus.REVOKED
        cred.retired_at = uow.now
        cred.retired_reason = reason
        revoked += 1
    change = trust.transition(
        identity, TrustState.REVOKED, f"Revoked by {principal.username}: {reason}", uow.now
    )
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="DEVICE_REVOKED",
        target_type="device_identity",
        target_id=asset_id,
        decision=AuditDecision.SUCCESS,
        reason=reason,
        details={"credentials_revoked": revoked},
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
    return {
        "asset_id": asset_id,
        "trust_state": identity.trust_state.value,
        "credentials_revoked": revoked,
    }


def rotate_device_key(
    uow: UnitOfWork, principal: Principal, asset_id: str, reason: str
) -> dict[str, Any]:
    session = uow.session
    identity = _identity(uow, asset_id)
    if identity.registration_status is not RegistrationStatus.REGISTERED:
        raise Conflict("NOT_REGISTERED", f"{asset_id} is not a registered identity.")
    creds = session.scalars(
        select(DeviceCredential).where(DeviceCredential.asset_id == asset_id)
    ).all()
    version = max((c.key_version for c in creds), default=0) + 1
    for cred in creds:
        if cred.status is CredentialStatus.ACTIVE:
            cred.status = CredentialStatus.ROTATED
            cred.retired_at = uow.now
            cred.retired_reason = reason
    session.flush()
    key = crypto.derive_device_key(uow.services.settings.master_secret_bytes, asset_id, version)
    session.add(
        DeviceCredential(
            asset_id=asset_id,
            key_version=version,
            fingerprint=crypto.key_fingerprint(key),
            status=CredentialStatus.ACTIVE,
            created_at=uow.now,
        )
    )
    sim = session.get(SimDevice, asset_id, with_for_update=True)
    if sim is not None:
        sim.key_version = version
    change = None
    if identity.trust_state in (TrustState.QUARANTINED, TrustState.REVOKED, TrustState.SUSPICIOUS):
        change = trust.transition(
            identity, TrustState.REGISTERED, "Re-provisioned with a new key", uow.now
        )
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="DEVICE_KEY_ROTATED",
        target_type="device_identity",
        target_id=asset_id,
        decision=AuditDecision.SUCCESS,
        reason=reason,
        details={"new_key_version": version, "fingerprint": crypto.key_fingerprint(key)},
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
    return {
        "asset_id": asset_id,
        "key_version": version,
        "fingerprint": crypto.key_fingerprint(key),
        "trust_state": identity.trust_state.value,
    }


def clear_suspicion(
    uow: UnitOfWork, principal: Principal, asset_id: str, reason: str
) -> dict[str, Any]:
    identity = _identity(uow, asset_id)
    if identity.trust_state is not TrustState.SUSPICIOUS:
        raise Conflict(
            "NOT_SUSPICIOUS", f"{asset_id} is {identity.trust_state.value}, not SUSPICIOUS."
        )
    change = trust.transition(
        identity,
        TrustState.AUTHENTICATED,
        f"Suspicion cleared by {principal.username}: {reason}",
        uow.now,
    )
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="SUSPICION_CLEARED",
        target_type="device_identity",
        target_id=asset_id,
        decision=AuditDecision.SUCCESS,
        reason=reason,
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
    return {"asset_id": asset_id, "trust_state": identity.trust_state.value}


def decide_enrollment(
    uow: UnitOfWork, principal: Principal, request_id: int, approve: bool, reason: str
) -> dict[str, Any]:
    session = uow.session
    req = session.get(EnrollmentRequest, request_id, with_for_update=True)
    if req is None:
        raise NotFound("Enrollment request", request_id)
    if req.status is not EnrollmentStatus.PENDING:
        raise Conflict("ALREADY_DECIDED", f"Request is {req.status.value}.")
    req.status = EnrollmentStatus.APPROVED if approve else EnrollmentStatus.REJECTED
    req.decided_at = uow.now
    req.decided_by_user_id = principal.user_id
    req.decision_reason = reason
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="ENROLLMENT_APPROVED" if approve else "ENROLLMENT_REJECTED",
        target_type="enrollment_request",
        target_id=str(req.id),
        decision=AuditDecision.SUCCESS,
        reason=reason,
        details={
            "claimed_device_id": req.claimed_device_id,
            "note": "Approval records intent only; the "
            "simulation does not provision keys for externally submitted devices.",
        },
    )
    uow.emit("enrollment.decided", {"request_id": req.id, "status": req.status.value})
    return {"request_id": req.id, "status": req.status.value}


def set_policy_mode(
    uow: UnitOfWork, principal: Principal, policy_id: str, mode: EnforcementMode, reason: str
) -> SecurityPolicy:
    policy = uow.session.get(SecurityPolicy, policy_id, with_for_update=True)
    if policy is None:
        raise NotFound("Policy", policy_id)
    previous = policy.enforcement_mode
    policy.enforcement_mode = mode
    uow.audit(
        actor_type=ActorType.USER,
        actor_id=principal.username,
        action="POLICY_MODE_CHANGED",
        target_type="policy",
        target_id=policy_id,
        decision=AuditDecision.SUCCESS,
        reason=reason,
        details={"from": previous.value, "to": mode.value},
    )
    uow.emit("policy.changed", {"policy_id": policy_id, "from": previous.value, "to": mode.value})
    return policy


def submit_enrollment(
    uow: UnitOfWork,
    *,
    claimed_device_id: str,
    requested_type: str,
    source_ref: str | None,
    details: dict[str, Any],
    simulation_run_id: int | None = None,
) -> dict[str, Any]:
    """A device asks to join. The request is recorded as PENDING and never grants trust."""
    from app.models import Incident, IncidentAsset
    from app.models.enums import IncidentStatus
    from app.services import incidents as incident_service

    session = uow.session
    asset = (
        session.scalars(select(Asset).where(Asset.ip_address == source_ref)).first()
        if source_ref
        else None
    )
    req = EnrollmentRequest(
        claimed_device_id=claimed_device_id,
        asset_id=asset.id if asset else None,
        requested_type=requested_type,
        source_ref=source_ref,
        details=details,
        status=EnrollmentStatus.PENDING,
        created_at=uow.now,
        correlation_id=uow.correlation_id,
        epoch=uow.epoch,
    )
    session.add(req)
    session.flush()
    uow.audit(
        actor_type=ActorType.DEVICE,
        actor_id=claimed_device_id,
        action="ENROLLMENT_REQUESTED",
        target_type="enrollment_request",
        target_id=str(req.id),
        decision=AuditDecision.INFO,
        reason="Recorded as PENDING; a security administrator must decide. No trust granted.",
        details={"source_ref": source_ref, "requested_type": requested_type},
        simulation_run_id=simulation_run_id,
    )
    if asset is not None:
        incident = session.scalars(
            select(Incident)
            .join(IncidentAsset, IncidentAsset.incident_id == Incident.id)
            .where(
                IncidentAsset.asset_id == asset.id,
                Incident.epoch == uow.epoch,
                Incident.status != IncidentStatus.RESOLVED,
            )
        ).first()
        if incident is not None:
            incident_service.add_incident_event(
                uow,
                incident,
                "ENROLLMENT_REQUESTED",
                f"{asset.id} requested enrollment as {claimed_device_id}",
                actor_type=ActorType.DEVICE,
                actor_id=asset.id,
                details={"request_id": req.id, "requested_type": requested_type},
            )
    uow.emit(
        "enrollment.requested",
        {"request_id": req.id, "claimed_device_id": claimed_device_id, "source_ref": source_ref},
    )
    return {"request_id": req.id, "status": req.status.value}
