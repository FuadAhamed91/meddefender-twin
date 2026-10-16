"""Deterministic attack scenarios A-F.

Every scenario drives the *real* ingestion pipeline (channel SCENARIO); none writes alerts,
incidents or trust changes directly. After the steps run, each expectation is evaluated
against persisted state and reported as met/unmet, so the console shows what actually
happened rather than what was supposed to happen.

All traffic is synthetic and confined to this application. Nothing touches real systems.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from app.core.errors import AppError
from app.models import (
    Asset,
    AuditEvent,
    DeviceIdentity,
    EnrollmentRequest,
    Incident,
    PolicyDecision,
    SecurityAlert,
    SecurityPolicy,
    SimDevice,
    SimulationRun,
    SimulationState,
    TelemetryEvent,
    TwinState,
)
from app.models.enums import (
    ActorType,
    AuditDecision,
    DecisionOutcome,
    EnrollmentStatus,
    IncidentStatus,
    IngestChannel,
    MessageType,
    PolicyOrigin,
    PolicyType,
    SimulationRunStatus,
    TelemetryDecision,
    TrustState,
)
from app.seed.catalog import SERVICES
from app.services import containment, incidents
from app.services.auth import Principal
from app.services.context import AppServices
from app.services.graph import GraphContext, attack_paths
from app.services.ingestion import InboundMessage, IngestionPipeline, IngestionResult
from app.services.policy_engine import PolicyEngine, endpoint_for_asset
from app.simulator.devices import DeviceFactory, SignedMessage
from app.simulator.runtime import SimulationRuntime, flow_record
from app.simulator.world import telemetry_payload

ROGUE_IP = "10.20.110.250"
GATEWAY_IP = "10.20.110.5"
SENSOR_IP = "10.20.10.40"


@dataclass(frozen=True)
class ScenarioInfo:
    id: str
    title: str
    summary: str
    narrative: str
    expected: tuple[str, ...]
    controls: tuple[str, ...]
    preconditions: tuple[str, ...]


@dataclass
class ScenarioContext:
    services: AppServices
    pipeline: IngestionPipeline
    devices: DeviceFactory
    run_id: int
    rng: random.Random
    steps: list[dict[str, Any]] = field(default_factory=list)
    expectations: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    artifacts: dict[str, Any] = field(default_factory=dict)

    # ---- state helpers ------------------------------------------------------------------------

    def twin(self, asset_id: str) -> dict[str, Any]:
        with self.services.session_factory() as s:
            t = s.get(TwinState, asset_id)
            return (
                {}
                if t is None
                else {
                    "trusted": t.trusted,
                    "trusted_event_id": t.trusted_event_id,
                    "reported": t.reported,
                    "predicted": t.predicted,
                    "version": t.version,
                }
            )

    def trust_state(self, asset_id: str) -> str | None:
        with self.services.session_factory() as s:
            identity = s.get(DeviceIdentity, asset_id)
            return identity.trust_state.value if identity else None

    def ground_truth(self, asset_id: str) -> dict[str, Any]:
        with self.services.session_factory() as s:
            sim = s.get(SimDevice, asset_id)
            return dict(sim.physical_state) if sim else {}

    def tick(self) -> int:
        with self.services.session_factory() as s:
            return s.scalar(select(SimulationState.tick_count).where(SimulationState.id == 1)) or 0

    def honest(
        self, asset_id: str, message_type: MessageType = MessageType.TELEMETRY
    ) -> SignedMessage:
        with self.services.session_factory() as s:
            identity = s.get(DeviceIdentity, asset_id)
            assert identity is not None and identity.telemetry_profile
            profile = (
                "heartbeat" if message_type is MessageType.HEARTBEAT else identity.telemetry_profile
            )
            payload = telemetry_payload(asset_id, profile, self.ground_truth(asset_id), self.tick())
        return self.devices.message(asset_id, message_type, payload)

    def ensure_authenticated(self, asset_id: str) -> None:
        state = self.trust_state(asset_id)
        if state in (TrustState.REGISTERED.value, TrustState.OFFLINE.value):
            with self.services.session_factory() as s:
                identity = s.get(DeviceIdentity, asset_id)
                profile = identity.telemetry_profile if identity else None
            mtype = MessageType.HEARTBEAT if profile == "heartbeat" else MessageType.TELEMETRY
            self.send(
                f"{asset_id} sends an honest message to (re)authenticate",
                self.honest(asset_id, mtype),
                actor=asset_id,
            )

    # ---- traffic -----------------------------------------------------------------------------

    def send(
        self,
        label: str,
        msg: SignedMessage | tuple[bytes, str | None],
        *,
        actor: str,
        transport_source: str | None = None,
    ) -> IngestionResult:
        raw, signature = (msg.raw, msg.signature_header) if isinstance(msg, SignedMessage) else msg
        result = self.pipeline.process(
            InboundMessage(
                raw,
                signature,
                IngestChannel.SCENARIO,
                transport_source=transport_source,
                simulation_run_id=self.run_id,
            )
        )
        self.steps.append(
            {
                "index": len(self.steps) + 1,
                "label": label,
                "actor": actor,
                "transport_source": transport_source,
                "telemetry_event_id": result.telemetry_event_id,
                "decision": result.decision.value,
                "reason_code": result.reason_code,
                "reason": result.reason,
                "authenticated": result.authenticated,
                "checks": result.checks,
                "alert_ids": result.alert_ids,
                "incident_refs": result.incident_refs,
                "trust_changes": result.trust_changes,
                "policy_decision_ids": result.policy_decision_ids,
                "correlation_id": result.correlation_id,
                "extra": {k: v for k, v in result.extra.items() if not k.startswith("_")},
            }
        )
        return result

    def flow_report(
        self, label: str, flows: list[tuple[str, str, str]], *, actor: str
    ) -> IngestionResult:
        """NET-SENSOR-01 reports flows; each is enforced by the (simulated) enforcement point
        using the current policy set before being reported."""
        with self.services.session_factory() as s:
            engine = PolicyEngine.load(s)
            by_ip = {
                a.ip_address: a
                for a in s.scalars(select(Asset).where(Asset.ip_address.is_not(None)))
            }
            records = []
            for src_ip, dst_ip, service in flows:
                src, dst = by_ip.get(src_ip), by_ip.get(dst_ip)
                outcome = engine.evaluate(
                    PolicyType.NETWORK_FLOW,
                    endpoint_for_asset(src, src_ip),
                    endpoint_for_asset(dst, dst_ip),
                    service,
                ).outcome
                records.append(
                    flow_record(
                        src_ip,
                        dst_ip,
                        service,
                        SERVICES.get(service, ("", None))[1],
                        outcome,
                        "NET-GW-01",
                        packets=self.rng.randint(12, 90),
                    )
                )
        now = self.services.clock.now()
        payload = {
            "window_start": (now - timedelta(seconds=30)).isoformat(),
            "window_end": now.isoformat(),
            "flows": records,
        }
        msg = self.devices.message("NET-SENSOR-01", MessageType.FLOW_REPORT, payload)
        result = self.send(label, msg, actor=actor, transport_source=SENSOR_IP)
        self.steps[-1]["flows"] = records
        return result

    # ---- reporting -------------------------------------------------------------------------

    def expect(self, label: str, met: bool, detail: str = "") -> None:
        self.expectations.append({"label": label, "met": bool(met), "detail": detail})

    def note(self, text: str) -> None:
        self.notes.append(text)


# =========================================================================================
# Scenario implementations
# =========================================================================================

VITAL_KEYS = ("heart_rate_bpm", "spo2_pct", "resp_rate_bpm")


def scenario_a(ctx: ScenarioContext) -> None:
    asset = "ICU-MONITOR-01"
    captured = ctx.honest(asset)
    r1 = ctx.send("ICU-MONITOR-01 sends a valid, signed reading", captured, actor=asset)
    before = ctx.twin(asset)
    r2 = ctx.send(
        "On-path attacker replays the captured message (identical bytes and MAC)",
        captured,
        actor="on-path attacker",
    )
    after = ctx.twin(asset)

    freshness = ctx.services.settings.freshness_window_seconds
    with ctx.services.session_factory() as s:
        old = s.scalars(
            select(TelemetryEvent)
            .where(
                TelemetryEvent.asset_id == asset,
                TelemetryEvent.decision == TelemetryDecision.ACCEPTED,
                TelemetryEvent.presented_signature.is_not(None),
                TelemetryEvent.received_at
                < ctx.services.clock.now() - timedelta(seconds=freshness),
            )
            .order_by(TelemetryEvent.id)
            .limit(1)
        ).first()
        old_raw = (
            (old.raw_message.encode("utf-8"), f"hmac-sha256={old.presented_signature}")
            if old
            else None
        )
    r3 = None
    if old_raw is not None:
        r3 = ctx.send(
            "Attacker replays an older captured message", old_raw, actor="on-path attacker"
        )
    else:
        ctx.note(
            f"No accepted message older than {freshness}s exists yet, so the stale-replay step was skipped. "
            "Let the telemetry generator run for a minute and re-run to exercise the freshness check."
        )

    statuses = {c["check"]: c["status"] for c in r2.checks}
    ctx.expect("Valid reading accepted", r1.decision is TelemetryDecision.ACCEPTED, r1.reason)
    ctx.expect(
        "Replay rejected by replay protection",
        r2.decision is TelemetryDecision.REJECTED
        and r2.reason_code in ("REPLAY_DUPLICATE", "DUPLICATE_NONCE"),
        f"{r2.reason_code}: {r2.reason}",
    )
    ctx.expect(
        "Replay passed HMAC verification: integrity alone cannot stop replay",
        statuses.get("integrity") == "PASS",
    )
    ctx.expect(
        "Trusted state unchanged by the replay",
        before.get("trusted_event_id") == after.get("trusted_event_id")
        and before.get("trusted") == after.get("trusted"),
        f"trusted event #{after.get('trusted_event_id')}",
    )
    with ctx.services.session_factory() as s:
        audited = s.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.correlation_id == r2.correlation_id,
                AuditEvent.action == "TELEMETRY_REJECTED",
            )
        )
    ctx.expect("Rejection written to the audit trail", bool(audited))
    ctx.expect("Incident created or updated", bool(r2.incident_refs), ", ".join(r2.incident_refs))
    ctx.expect(
        "Device not penalised (a replay proves capture, not key compromise)",
        ctx.trust_state(asset) == TrustState.AUTHENTICATED.value,
        ctx.trust_state(asset) or "",
    )
    if r3 is not None:
        st3 = {c["check"]: c["status"] for c in r3.checks}
        ctx.expect(
            "Older capture fails sequence and freshness checks",
            st3.get("sequence") == "FAIL" and st3.get("freshness") == "FAIL",
            r3.reason,
        )
    ctx.artifacts["focus_assets"] = [asset]


def scenario_b(ctx: ScenarioContext) -> None:
    monitor, workstation = "ICU-MONITOR-01", "IMG-WS-01"
    ctx.ensure_authenticated(workstation)
    truth_before = ctx.ground_truth(monitor)
    cmd = ctx.devices.message(
        workstation,
        MessageType.COMMAND,
        {
            "target": monitor,
            "action": "update_alarm_limits",
            "parameters": {"hr_low": 30, "hr_high": 190, "spo2_low": 75},
        },
    )
    r = ctx.send(
        f"{workstation} (authenticated, imaging zone) asks to change {monitor} alarm limits",
        cmd,
        actor=workstation,
    )
    truth_after = ctx.ground_truth(monitor)
    statuses = {c["check"]: c["status"] for c in r.checks}
    ctx.expect(
        "Command denied by the policy engine",
        r.decision is TelemetryDecision.REJECTED and r.reason_code == "POLICY_DENIED",
        r.reason,
    )
    ctx.expect(
        "Sender was authenticated: authentication is not authorization",
        statuses.get("integrity") == "PASS",
    )
    ctx.expect(
        "Simulated device state unchanged",
        truth_before.get("alarm_limits") == truth_after.get("alarm_limits")
        and truth_before.get("alarm_config_version") == truth_after.get("alarm_config_version"),
        f"alarm config version {truth_after.get('alarm_config_version')}",
    )
    with ctx.services.session_factory() as s:
        decision = (
            s.get(PolicyDecision, r.policy_decision_ids[0]) if r.policy_decision_ids else None
        )
        denied_audit = s.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.correlation_id == r.correlation_id, AuditEvent.action == "COMMAND_DENIED"
            )
        )
    ctx.expect(
        "Denial explained and persisted",
        decision is not None and decision.outcome is DecisionOutcome.BLOCKED,
        decision.reason if decision else "",
    )
    ctx.expect("Denial written to the audit trail", bool(denied_audit))
    ctx.expect(
        "Incident opened for the misbehaving identity",
        bool(r.incident_refs),
        ", ".join(r.incident_refs),
    )
    ctx.expect(
        f"{workstation} marked SUSPICIOUS (confirmed policy violation)",
        ctx.trust_state(workstation) == TrustState.SUSPICIOUS.value,
        ctx.trust_state(workstation) or "",
    )

    gateway, other = "ICU-GATEWAY-01", "ICU-MONITOR-02"
    ctx.ensure_authenticated(gateway)
    if ctx.trust_state(gateway) == TrustState.AUTHENTICATED.value:
        before_v = ctx.ground_truth(other).get("alarm_config_version")
        ok = ctx.devices.message(
            gateway,
            MessageType.COMMAND,
            {
                "target": other,
                "action": "update_alarm_limits",
                "parameters": {"hr_low": 50, "hr_high": 125, "spo2_low": 90},
            },
        )
        r2 = ctx.send(
            f"Positive control: {gateway} (authorized) sends the same action to {other}",
            ok,
            actor=gateway,
        )
        after_v = ctx.ground_truth(other).get("alarm_config_version")
        ctx.expect(
            "Positive control: the same action from an authorized identity is delivered",
            r2.decision is TelemetryDecision.ACCEPTED and after_v == (before_v or 0) + 1,
            r2.reason,
        )
    else:
        ctx.note(
            f"Positive control skipped: {gateway} is {ctx.trust_state(gateway)} (commands are trust-gated). Reset the baseline to run it."
        )
    ctx.artifacts["focus_assets"] = [workstation, monitor]


def scenario_c(ctx: ScenarioContext) -> None:
    from app.services.administration import submit_enrollment

    spoofed = "ICU-MONITOR-02"
    trust_before = ctx.trust_state(spoofed)
    r1 = ctx.flow_report(
        "NET-SENSOR-01 observes traffic from an unknown endpoint on the ICU segment",
        [
            (ROGUE_IP, "10.20.110.5", "monitor-feed"),
            (ROGUE_IP, "10.20.10.22", "hl7-mllp"),
            (ROGUE_IP, "10.20.10.21", "https"),
        ],
        actor="NET-SENSOR-01",
    )
    rogue_id = "UNKNOWN-" + ROGUE_IP.replace(".", "-")
    fake = ctx.devices.forged(
        "ICU-MONITOR-04",
        MessageType.TELEMETRY,
        {"heart_rate_bpm": 70, "spo2_pct": 97, "resp_rate_bpm": 14, "alarm_config_version": 1},
        sequence=1,
    )
    r2 = ctx.send(
        "Rogue device sends telemetry as an unregistered identity (ICU-MONITOR-04)",
        fake,
        actor="rogue device",
        transport_source=ROGUE_IP,
    )
    spoof_results = []
    for i in range(3):
        forged = ctx.devices.forged(
            spoofed,
            MessageType.TELEMETRY,
            {"heart_rate_bpm": 140, "spo2_pct": 82, "resp_rate_bpm": 30, "alarm_config_version": 1},
            sequence=900_000 + i,
        )
        spoof_results.append(
            ctx.send(
                f"Rogue device impersonates {spoofed} without its key (attempt {i + 1})",
                forged,
                actor="rogue device",
                transport_source=ROGUE_IP,
            )
        )
    with ctx.services.uow() as uow:
        enrollment = submit_enrollment(
            uow,
            claimed_device_id="ICU-MONITOR-04",
            requested_type="patient_monitor",
            source_ref=ROGUE_IP,
            details={"note": "self-enrollment attempt by rogue device"},
            simulation_run_id=ctx.run_id,
        )
    ctx.steps.append(
        {
            "index": len(ctx.steps) + 1,
            "label": "Rogue device requests enrollment as ICU-MONITOR-04",
            "actor": "rogue device",
            "decision": enrollment["status"],
            "reason": "Enrollment requests are never trusted automatically; a security admin must decide.",
        }
    )

    with ctx.services.session_factory() as s:
        rogue = s.get(Asset, rogue_id)
        identity = s.get(DeviceIdentity, rogue_id)
        decisions = s.scalars(
            select(PolicyDecision).where(PolicyDecision.source_asset_id == rogue_id)
        ).all()
        incident_ids = {
            a.incident_id
            for a in s.scalars(select(SecurityAlert).where(SecurityAlert.subject_ref == rogue_id))
        }
        req = s.get(EnrollmentRequest, enrollment["request_id"])
    ctx.expect(
        "Unknown endpoint recorded as UNREGISTERED, never trusted",
        rogue is not None
        and identity is not None
        and identity.trust_state is TrustState.UNREGISTERED,
    )
    ctx.expect(
        "All flows from the rogue endpoint blocked by default deny",
        bool(decisions) and all(d.outcome is DecisionOutcome.BLOCKED for d in decisions),
        f"{len(decisions)} decisions",
    )
    ctx.expect(
        "Telemetry from an unregistered identity rejected", r2.reason_code == "UNKNOWN_DEVICE"
    )
    ctx.expect(
        "Impersonation attempts fail authentication",
        all(r.reason_code == "BAD_SIGNATURE" for r in spoof_results),
    )
    ctx.expect(
        f"{spoofed} not penalised for failures it did not cause",
        ctx.trust_state(spoofed) == trust_before,
        f"{trust_before} -> {ctx.trust_state(spoofed)}",
    )
    ctx.expect(
        "Enrollment request pending, not registered",
        req is not None and req.status is EnrollmentStatus.PENDING,
    )
    ctx.expect(
        "Evidence correlated into one incident for the rogue endpoint",
        len(incident_ids - {None}) == 1,
        ", ".join(r1.incident_refs),
    )
    ctx.artifacts["focus_assets"] = [rogue_id, spoofed]


def scenario_d(ctx: ScenarioContext) -> None:
    gateway = "ICU-GATEWAY-01"
    ctx.ensure_authenticated(gateway)
    r1 = ctx.flow_report(
        f"NET-SENSOR-01 observes {gateway} reaching beyond its permitted communication policy",
        [
            (GATEWAY_IP, "10.20.10.22", "ssh"),
            (GATEWAY_IP, "10.20.10.23", "ldaps"),
            (GATEWAY_IP, "10.20.10.24", "dicom"),
            (GATEWAY_IP, "10.20.110.21", "device-config"),
            (GATEWAY_IP, "10.20.120.11", "dicom"),
            (GATEWAY_IP, "10.20.110.12", "device-config"),
            (GATEWAY_IP, "10.20.10.22", "hl7-mllp"),
        ],
        actor="NET-SENSOR-01",
    )
    cmd = ctx.devices.message(
        gateway,
        MessageType.COMMAND,
        {
            "target": "ICU-MONITOR-02",
            "action": "update_alarm_limits",
            "parameters": {"hr_low": 25, "hr_high": 220, "spo2_low": 70},
        },
    )
    r2 = ctx.send(
        f"{gateway} (now SUSPICIOUS) tries to push alarm limits to ICU-MONITOR-02",
        cmd,
        actor=gateway,
    )

    with ctx.services.uow() as uow:
        graph = GraphContext.load(uow.session)
        analysis = attack_paths(uow.session, graph, gateway, 3, uow.epoch)
        incident = uow.session.scalars(
            select(Incident).where(
                Incident.primary_asset_id == gateway,
                Incident.epoch == uow.epoch,
                Incident.status != IncidentStatus.RESOLVED,
            )
        ).first()
        if incident is not None:
            incidents.link_assets(
                uow,
                incident,
                [(r["asset_id"], "POTENTIALLY_REACHABLE") for r in analysis["reachable_assets"]],
            )
            incidents.add_incident_event(
                uow,
                incident,
                "ATTACK_PATH_ANALYZED",
                f"{len(analysis['reachable_assets'])} asset(s) reachable under current policy; {len(analysis['nearby_unreachable'])} nearby but unreachable",
                actor_type=ActorType.SYSTEM,
                actor_id="graph-engine",
                details={
                    "reachable": analysis["reachable_assets"],
                    "nearby_unreachable": [n["asset_id"] for n in analysis["nearby_unreachable"]],
                    "observed_attempts": analysis["observed_attempts"],
                    "assumptions": analysis["assumptions"],
                },
            )
    ctx.artifacts["attack_paths"] = analysis
    reach = {r["asset_id"]: r for r in analysis["reachable_assets"]}
    nearby = {n["asset_id"] for n in analysis["nearby_unreachable"]}
    with ctx.services.session_factory() as s:
        blocked = s.scalar(
            select(func.count(PolicyDecision.id)).where(
                PolicyDecision.source_asset_id == gateway,
                PolicyDecision.outcome == DecisionOutcome.BLOCKED,
                PolicyDecision.simulation_run_id == ctx.run_id,
            )
        )
    ctx.expect(
        "Flows outside policy blocked and recorded",
        (blocked or 0) >= 5,
        f"{blocked} blocked decisions",
    )
    ctx.expect(
        f"{gateway} marked SUSPICIOUS", ctx.trust_state(gateway) == TrustState.SUSPICIOUS.value
    )
    ctx.expect(
        "Command from the suspicious gateway refused by the trust gate",
        r2.reason_code == "TRUST_GATE",
        r2.reason,
    )
    ctx.expect("Incident tracks the gateway", bool(r1.incident_refs), ", ".join(r1.incident_refs))
    ctx.expect(
        "Monitoring server reachable over a permitted, observed channel",
        reach.get("MON-SERVER-01", {}).get("classification") == "DEMONSTRATED",
    )
    ctx.expect(
        "Clinical application server reachable only hypothetically (via a compromised intermediate)",
        reach.get("APP-SERVER-01", {}).get("classification") == "HYPOTHETICAL",
    )
    ctx.expect("Imaging archive not reachable (all attempts denied)", "IMG-SERVER-01" not in reach)
    ctx.expect(
        "Infusion pump is nearby but unreachable",
        "ICU-PUMP-01" in nearby and "ICU-PUMP-01" not in reach,
    )
    ctx.expect(
        "ICU environment sensor sits in the ICU but on the BMS network: nearby, unreachable",
        "HVAC-SENSOR-01" in nearby,
    )
    ctx.artifacts["focus_assets"] = [gateway]


def scenario_e(ctx: ScenarioContext) -> None:
    sensor, hvac = "HVAC-SENSOR-01", "HVAC-CTRL-01"
    if not ctx.twin(hvac).get("trusted"):
        ctx.send("HVAC-CTRL-01 reports its setpoint (model input)", ctx.honest(hvac), actor=hvac)
    if not ctx.twin(sensor).get("trusted"):
        ctx.send(
            "HVAC-SENSOR-01 honest reading (initialises the model)",
            ctx.honest(sensor),
            actor=sensor,
        )
    r1 = ctx.send("HVAC-SENSOR-01 honest reading", ctx.honest(sensor), actor=sensor)
    baseline = ctx.twin(sensor)
    truth = ctx.ground_truth(sensor)
    manipulated = round(float(truth["temperature_c"]) + 8.3, 2)
    m = ctx.devices.message(
        sensor,
        MessageType.TELEMETRY,
        {"temperature_c": manipulated, "humidity_pct": float(truth["humidity_pct"])},
    )
    r2 = ctx.send(
        f"Sensor reports {manipulated} °C: plausible range, but far from the model prediction",
        m,
        actor="manipulated sensor",
    )
    after_hold = ctx.twin(sensor)
    impossible = ctx.devices.message(
        sensor,
        MessageType.TELEMETRY,
        {"temperature_c": 85.0, "humidity_pct": float(truth["humidity_pct"])},
    )
    r3 = ctx.send(
        "Sensor reports 85.0 °C: outside the physical limits for this device",
        impossible,
        actor="manipulated sensor",
    )
    malformed = ctx.devices.message(
        sensor,
        MessageType.TELEMETRY,
        {"temperature_c": "hot", "humidity_pct": float(truth["humidity_pct"])},
    )
    r4 = ctx.send(
        'Sensor reports temperature "hot": schema violation', malformed, actor="manipulated sensor"
    )
    final = ctx.twin(sensor)

    with ctx.services.session_factory() as s:
        classes = {
            a.id: a.classification.value
            for a in s.scalars(
                select(SecurityAlert).where(
                    SecurityAlert.id.in_(r2.alert_ids + r3.alert_ids + r4.alert_ids)
                )
            )
        }
    ctx.expect(
        "Honest reading accepted within model tolerance",
        r1.decision is TelemetryDecision.ACCEPTED,
        r1.reason,
    )
    ctx.expect(
        "Model discrepancy HELD for review, not trusted",
        r2.decision is TelemetryDecision.HELD
        and after_hold.get("trusted_event_id") == baseline.get("trusted_event_id"),
        r2.reason,
    )
    ctx.expect(
        "Discrepancy reported as a SUSPECTED anomaly, not proof of attack",
        any(classes.get(i) == "SUSPECTED_ANOMALY" for i in r2.alert_ids),
    )
    ctx.expect(
        "Out-of-limits value rejected as a validation failure",
        r3.reason_code == "OUT_OF_RANGE"
        and any(classes.get(i) == "VALIDATION_FAILURE" for i in r3.alert_ids),
        r3.reason,
    )
    ctx.expect("Schema violation rejected", r4.reason_code == "SCHEMA_INVALID", r4.reason)
    ctx.expect(
        "Trusted state never overwritten by invalid input",
        final.get("trusted_event_id") == baseline.get("trusted_event_id")
        and final.get("trusted") == baseline.get("trusted"),
        f"trusted {final.get('trusted')}",
    )
    ctx.expect(
        "Reported, trusted and predicted values all available for comparison",
        bool(final.get("reported")) and bool(final.get("trusted")) and bool(final.get("predicted")),
    )
    ctx.expect(
        f"{sensor} marked SUSPICIOUS after an authentic out-of-limits report",
        ctx.trust_state(sensor) == TrustState.SUSPICIOUS.value,
    )
    ctx.artifacts["focus_assets"] = [sensor]


def scenario_f(ctx: ScenarioContext) -> None:
    gateway = "ICU-GATEWAY-01"
    with ctx.services.uow() as uow:
        incident = uow.session.scalars(
            select(Incident)
            .where(
                Incident.primary_asset_id == gateway,
                Incident.epoch == uow.epoch,
                Incident.status != IncidentStatus.RESOLVED,
            )
            .with_for_update()
        ).first()
        if incident is None:
            raise AppError(
                409,
                "PRECONDITION_FAILED",
                "Scenario F needs an open incident for ICU-GATEWAY-01. Run Scenario D first.",
            )
        active_before = uow.session.scalar(
            select(func.count(SecurityPolicy.id)).where(
                SecurityPolicy.is_active.is_(True),
                SecurityPolicy.origin == PolicyOrigin.CONTAINMENT,
            )
        )
        if incident.status is IncidentStatus.DETECTED:
            incidents.transition_incident(
                uow,
                incident,
                IncidentStatus.INVESTIGATING,
                actor_id="scenario-F",
                note="Investigation opened to evaluate containment options.",
                system=True,
            )
        if incident.status not in (
            IncidentStatus.INVESTIGATING,
            IncidentStatus.CONTAINMENT_PROPOSED,
        ):
            raise AppError(
                409,
                "PRECONDITION_FAILED",
                f"Incident {incident.reference} is {incident.status.value}; containment planning needs INVESTIGATING.",
            )
        plans = containment.generate_plans(uow, incident, "scenario-F", user_id=None)
        comparison = [
            {
                "plan_id": p.id,
                "strategy": p.strategy,
                "name": p.name,
                "required_role": p.required_role,
                **p.analysis["metrics"],
                "summary": p.analysis["summary"],
            }
            for p in plans
        ]
        reference = incident.reference
    with ctx.services.session_factory() as s:
        active_after = s.scalar(
            select(func.count(SecurityPolicy.id)).where(
                SecurityPolicy.is_active.is_(True),
                SecurityPolicy.origin == PolicyOrigin.CONTAINMENT,
            )
        )
    ctx.steps.append(
        {
            "index": len(ctx.steps) + 1,
            "label": f"Generate and compare containment plans for {reference}",
            "actor": "operator (simulated)",
            "decision": "PROPOSED",
            "reason": f"{len(plans)} plans compared; nothing applied.",
        }
    )
    ctx.artifacts["comparison"] = comparison
    ctx.artifacts["incident_reference"] = reference
    by = {c["strategy"]: c for c in comparison}
    iso, res, rev = (
        by.get("ISOLATE_ASSET"),
        by.get("RESTRICT_TO_REQUIRED_FLOWS"),
        by.get("REVOKE_CREDENTIALS"),
    )
    ctx.expect("At least three containment options compared", len(comparison) >= 3)
    ctx.expect(
        "Full isolation removes every attack path from the gateway",
        bool(iso) and iso["paths_after"] == 0,
    )
    ctx.expect(
        "Full isolation impairs central monitoring, so it requires SECURITY_ADMIN",
        bool(iso) and iso["services_impaired"] >= 1 and iso["required_role"] == "SECURITY_ADMIN",
    )
    ctx.expect(
        "Restricting to required flows reduces paths with no high-criticality impairment",
        bool(res) and res["paths_after"] < res["paths_before"] and res["services_impaired"] == 0,
    )
    ctx.expect(
        "Restriction leaves residual paths (trade-off made visible)",
        bool(res) and res["paths_after"] > 0,
    )
    ctx.expect(
        "Credential revocation alone does not change network reachability",
        bool(rev) and rev["paths_after"] == rev["paths_before"],
    )
    ctx.expect("Comparison changed no live policy", active_before == active_after)
    ctx.artifacts["focus_assets"] = [gateway]


SCENARIOS: dict[str, tuple[ScenarioInfo, Callable[[ScenarioContext], None]]] = {
    "A": (
        ScenarioInfo(
            "A",
            "Replayed medical telemetry",
            "Capture a valid monitor reading and replay it.",
            "An on-path attacker records a genuine, signed bedside-monitor message and sends it again, then replays an older capture.",
            (
                "Replay rejected by sequence/nonce (and freshness for old captures)",
                "Trusted state unchanged",
                "Audit event and incident recorded",
                "Device trust unchanged",
            ),
            (
                "HMAC-SHA-256",
                "Monotonic sequence",
                "Nonce uniqueness",
                "Freshness window",
                "Row-locked replay state",
            ),
            ("ICU-MONITOR-01 registered with an active key",),
        ),
        scenario_a,
    ),
    "B": (
        ScenarioInfo(
            "B",
            "Unauthorized device command",
            "A low-privilege identity tries to change ICU monitor alarm limits.",
            "IMG-WS-01 authenticates correctly but asks the command broker to change a bedside monitor's alarm limits, which no policy allows.",
            (
                "Command denied with an explanation",
                "Simulated device state unchanged",
                "Identity marked SUSPICIOUS",
                "Positive control: authorized source succeeds",
            ),
            ("Command policy (default deny)", "Trust gate", "Least privilege per identity"),
            ("IMG-WS-01 registered", "ICU-GATEWAY-01 AUTHENTICATED for the positive control"),
        ),
        scenario_b,
    ),
    "C": (
        ScenarioInfo(
            "C",
            "Rogue device registration",
            "An unknown endpoint appears on the ICU segment and tries to talk, impersonate and enroll.",
            "A device that is not in the registry plugs into the ICU network, attempts connections, sends telemetry under an unregistered ID, "
            "impersonates ICU-MONITOR-02 without its key, and asks to be enrolled.",
            (
                "Endpoint discovered as UNREGISTERED",
                "All flows blocked",
                "Telemetry and impersonation rejected",
                "Enrollment left pending",
                "Impersonated device not penalised",
            ),
            (
                "Identity registry",
                "Default-deny flow policy",
                "HMAC authentication",
                "Enrollment approval",
            ),
            ("NET-SENSOR-01 registered",),
        ),
        scenario_c,
    ),
    "D": (
        ScenarioInfo(
            "D",
            "Compromised gateway and lateral movement",
            "The ICU gateway starts reaching outside its permitted communication policy.",
            "ICU-GATEWAY-01 behaves as if compromised: it probes servers, imaging and the infusion pump, and abuses its permitted configuration channel.",
            (
                "Unauthorized flows blocked",
                "Gateway SUSPICIOUS; commands trust-gated",
                "Attack paths only over permitted flows",
                "Reachable vs merely nearby distinguished",
            ),
            ("Flow policy", "New-path detection", "Policy-aware graph traversal"),
            ("ICU-GATEWAY-01 registered",),
        ),
        scenario_d,
    ),
    "E": (
        ScenarioInfo(
            "E",
            "Telemetry manipulation",
            "An ICU environment sensor reports values that conflict with the model, its limits and its schema.",
            "HVAC-SENSOR-01 sends a plausible-but-wrong temperature, then a physically impossible one, then a malformed one.",
            (
                "Model discrepancy HELD as a suspected anomaly",
                "Limit and schema failures rejected",
                "Trusted state never overwritten",
                "Reported/trusted/predicted shown together",
            ),
            ("Schema validation", "Physical limits", "Deterministic thermal model"),
            ("HVAC-CTRL-01 trusted setpoint available (initialised automatically)",),
        ),
        scenario_e,
    ),
    "F": (
        ScenarioInfo(
            "F",
            "Containment planning",
            "Compare containment options for the compromised gateway before changing anything.",
            "For the open ICU-GATEWAY-01 incident, generate isolation, restriction, zone-egress and revocation plans and compare their trade-offs.",
            (
                "Plans compared on paths, blocked flows and dependency impact",
                "High-impact plans require SECURITY_ADMIN",
                "No live policy changed until an operator applies a plan",
            ),
            (
                "Hypothetical policy evaluation",
                "Dependency impact propagation",
                "Risk-based authorization",
            ),
            ("An open incident for ICU-GATEWAY-01 (run Scenario D first)",),
        ),
        scenario_f,
    ),
}


def scenario_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": info.id,
            "title": info.title,
            "summary": info.summary,
            "narrative": info.narrative,
            "expected": list(info.expected),
            "controls": list(info.controls),
            "preconditions": list(info.preconditions),
        }
        for info, _ in SCENARIOS.values()
    ]


def check_preconditions(services: AppServices, scenario_id: str) -> list[dict[str, Any]]:
    with services.session_factory() as s:
        epoch = s.scalar(select(SimulationState.epoch).where(SimulationState.id == 1)) or 1
        if scenario_id == "F":
            incident = s.scalars(
                select(Incident).where(
                    Incident.primary_asset_id == "ICU-GATEWAY-01",
                    Incident.epoch == epoch,
                    Incident.status.in_(
                        (
                            IncidentStatus.DETECTED,
                            IncidentStatus.INVESTIGATING,
                            IncidentStatus.CONTAINMENT_PROPOSED,
                        )
                    ),
                )
            ).first()
            return [
                {
                    "label": "Open ICU-GATEWAY-01 incident (DETECTED/INVESTIGATING/CONTAINMENT_PROPOSED)",
                    "met": incident is not None,
                    "detail": incident.reference if incident else "Run Scenario D first",
                }
            ]
        if scenario_id == "B":
            gw = s.get(DeviceIdentity, "ICU-GATEWAY-01")
            return [
                {
                    "label": "ICU-GATEWAY-01 not suspicious (needed for the positive control)",
                    "met": gw is not None
                    and gw.trust_state
                    not in (TrustState.SUSPICIOUS, TrustState.QUARANTINED, TrustState.REVOKED),
                    "detail": gw.trust_state.value if gw else "missing",
                }
            ]
        required = {
            "A": "ICU-MONITOR-01",
            "C": "NET-SENSOR-01",
            "D": "ICU-GATEWAY-01",
            "E": "HVAC-SENSOR-01",
        }[scenario_id]
        identity = s.get(DeviceIdentity, required)
        ok = identity is not None and identity.trust_state not in (
            TrustState.QUARANTINED,
            TrustState.REVOKED,
        )
        return [
            {
                "label": f"{required} can send messages",
                "met": ok,
                "detail": identity.trust_state.value if identity else "missing",
            }
        ]


def run_scenario(
    services: AppServices,
    pipeline: IngestionPipeline,
    runtime: SimulationRuntime | None,
    scenario_id: str,
    principal: Principal | None,
    seed: int = 7,
) -> SimulationRun:
    if scenario_id not in SCENARIOS:
        raise AppError(404, "NOT_FOUND", f"Scenario '{scenario_id}' does not exist.")
    info, fn = SCENARIOS[scenario_id]
    correlation = str(uuid.uuid4())
    actor = principal.username if principal else "system"
    with services.uow(correlation) as uow:
        run = SimulationRun(
            scenario_id=scenario_id,
            status=SimulationRunStatus.RUNNING,
            seed=seed,
            started_by_user_id=principal.user_id if principal else None,
            started_at=uow.now,
            epoch=uow.epoch,
            parameters={"seed": seed, "title": info.title},
            correlation_id=correlation,
        )
        uow.session.add(run)
        uow.session.flush()
        run_id = run.id
        uow.audit(
            actor_type=ActorType.USER if principal else ActorType.SYSTEM,
            actor_id=actor,
            action="SCENARIO_STARTED",
            target_type="simulation_run",
            target_id=str(run_id),
            decision=AuditDecision.INFO,
            reason=f"Scenario {scenario_id}: {info.title}",
            simulation_run_id=run_id,
        )
        uow.emit(
            "simulation.run_started",
            {"run_id": run_id, "scenario_id": scenario_id, "title": info.title},
        )

    ctx = ScenarioContext(services, pipeline, DeviceFactory(services), run_id, random.Random(seed))
    lock = runtime.scenario_lock if runtime is not None else None
    status, error = SimulationRunStatus.COMPLETED, None
    if lock is not None:
        lock.acquire()
    try:
        fn(ctx)
    except AppError as exc:
        status, error = SimulationRunStatus.FAILED, {"code": exc.code, "message": exc.message}
    except Exception as exc:  # pragma: no cover - surfaced in the run result
        status, error = (
            SimulationRunStatus.FAILED,
            {"code": "SCENARIO_ERROR", "message": str(exc)[:300]},
        )
    finally:
        if lock is not None:
            lock.release()

    met = sum(1 for e in ctx.expectations if e["met"])
    result = {
        "steps": ctx.steps,
        "expectations": ctx.expectations,
        "expectations_met": met,
        "expectations_total": len(ctx.expectations),
        "all_met": status is SimulationRunStatus.COMPLETED and met == len(ctx.expectations),
        "notes": ctx.notes,
        "artifacts": ctx.artifacts,
        "error": error,
        "incidents": sorted({ref for step in ctx.steps for ref in step.get("incident_refs", [])}),
    }
    with services.uow(correlation) as uow:
        run = uow.session.get(SimulationRun, run_id)
        assert run is not None
        run.status = status
        run.completed_at = uow.now
        run.result = result
        uow.audit(
            actor_type=ActorType.USER if principal else ActorType.SYSTEM,
            actor_id=actor,
            action="SCENARIO_COMPLETED",
            target_type="simulation_run",
            target_id=str(run_id),
            decision=AuditDecision.SUCCESS
            if status is SimulationRunStatus.COMPLETED
            else AuditDecision.FAILURE,
            reason=f"Scenario {scenario_id}: {met}/{len(ctx.expectations)} expectations met"
            + (f"; error {error['code']}" if error else ""),
            simulation_run_id=run_id,
        )
        uow.emit(
            "simulation.run_completed",
            {
                "run_id": run_id,
                "scenario_id": scenario_id,
                "status": status.value,
                "expectations_met": met,
                "expectations_total": len(ctx.expectations),
                "focus_assets": ctx.artifacts.get("focus_assets", []),
            },
        )
    with services.session_factory() as s:
        stored = s.get(SimulationRun, run_id)
        assert stored is not None
        s.expunge(stored)
        return stored
