"""Background simulation loop: advances the simulated world and makes honest devices emit
signed messages through the real ingestion pipeline.

Scenario runs take ``scenario_lock`` so generator traffic cannot interleave with a scenario
and blur its before/after comparisons.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, exists, or_, select

from app.models import (
    Asset,
    DeviceIdentity,
    DeviceNonce,
    EventLogEntry,
    IncidentEvent,
    NetworkRelationship,
    PolicyDecision,
    SecurityAlert,
    SimDevice,
    SimulationState,
    TelemetryEvent,
    TwinState,
)
from app.models.enums import (
    ActorType,
    AuditDecision,
    ContainmentState,
    DecisionOutcome,
    IngestChannel,
    MessageType,
    PolicyType,
    RelationshipOrigin,
    RelationshipType,
    TelemetryDecision,
    TrustState,
)
from app.services import trust
from app.services.context import AppServices
from app.services.ingestion import InboundMessage, IngestionPipeline
from app.services.policy_engine import PolicyEngine, endpoint_for_asset
from app.simulator.devices import DeviceFactory
from app.simulator.world import advance, telemetry_payload

logger = logging.getLogger(__name__)

FLOW_REPORT_EVERY = 6
MAINTENANCE_EVERY = 12
OFFLINE_AFTER_SECONDS = 60
EVENT_LOG_RETENTION = timedelta(hours=2)


class SimulationRuntime:
    def __init__(self, services: AppServices, pipeline: IngestionPipeline) -> None:
        self.services = services
        self.pipeline = pipeline
        self.devices = DeviceFactory(services)
        self.scenario_lock = threading.Lock()

    async def run_forever(self) -> None:
        interval = max(1.0, self.services.settings.generator_interval_seconds)
        while True:
            try:
                await asyncio.to_thread(self.tick)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Simulation tick failed")
            await asyncio.sleep(interval)

    # ---- one tick ---------------------------------------------------------------------------

    def tick(self) -> dict[str, Any]:
        if not self.scenario_lock.acquire(blocking=False):
            return {"skipped": "scenario running"}
        try:
            return self._tick()
        finally:
            self.scenario_lock.release()

    def _tick(self) -> dict[str, Any]:
        now = self.services.clock.now()
        interval = self.services.settings.generator_interval_seconds
        plans: list[tuple[str, MessageType, dict[str, Any], str | None]] = []
        with self.services.session_factory() as session, session.begin():
            state = session.get(SimulationState, 1, with_for_update=True)
            if state is None:
                return {"skipped": "not seeded"}
            if not state.generator_enabled:
                enabled = False
                tick = state.tick_count
            else:
                enabled = True
                dt = (now - state.last_tick_at).total_seconds() if state.last_tick_at else interval
                dt = min(max(dt, 0.0), 60.0)
                state.tick_count += 1
                state.last_tick_at = now
                tick = state.tick_count
                identities = {i.asset_id: i for i in session.scalars(select(DeviceIdentity))}
                assets = {a.id: a for a in session.scalars(select(Asset))}
                sims = session.scalars(
                    select(SimDevice).order_by(SimDevice.asset_id).with_for_update()
                ).all()
                hvac = next(
                    (
                        dict(s.physical_state)
                        for s in sims
                        if (
                            identities.get(s.asset_id)
                            and identities[s.asset_id].telemetry_profile == "hvac_controller"
                        )
                    ),
                    None,
                )
                for sim in sims:
                    identity = identities.get(sim.asset_id)
                    if identity is None or not identity.telemetry_profile:
                        continue
                    sim.physical_state = advance(
                        sim.asset_id,
                        identity.telemetry_profile,
                        sim.physical_state,
                        dt=dt,
                        tick=tick,
                        hvac=hvac,
                    )
                    sim.updated_at = now
                    asset = assets.get(sim.asset_id)
                    if (
                        not sim.online
                        or asset is None
                        or asset.containment_state is ContainmentState.ISOLATED
                    ):
                        continue  # isolated devices cannot reach the platform
                    profile = identity.telemetry_profile
                    if profile == "network_sensor":
                        continue
                    mtype = (
                        MessageType.HEARTBEAT if profile == "heartbeat" else MessageType.TELEMETRY
                    )
                    if mtype is MessageType.HEARTBEAT and tick % 3 != 0:
                        continue
                    plans.append(
                        (
                            sim.asset_id,
                            mtype,
                            telemetry_payload(sim.asset_id, profile, sim.physical_state, tick),
                            asset.ip_address,
                        )
                    )
        processed = 0
        if enabled:
            for asset_id, mtype, payload, ip in plans:
                msg = self.devices.message(asset_id, mtype, payload)
                self.pipeline.process(
                    InboundMessage(
                        msg.raw, msg.signature_header, IngestChannel.GENERATOR, transport_source=ip
                    )
                )
                processed += 1
            if tick % FLOW_REPORT_EVERY == 0:
                self.send_baseline_flow_report(now)
        if not enabled or tick % MAINTENANCE_EVERY == 0:
            self.maintenance(now)
        return {"tick": tick, "enabled": enabled, "messages": processed}

    # ---- network sensor -------------------------------------------------------------------

    def baseline_flows(self) -> list[dict[str, Any]]:
        """Honest traffic on modeled paths, with the enforcement decision each enforcement
        point would take under the current policy set."""
        with self.services.session_factory() as session:
            engine = PolicyEngine.load(session)
            assets = {
                a.id: a for a in session.scalars(select(Asset).where(Asset.is_active.is_(True)))
            }
            rels = session.scalars(
                select(NetworkRelationship).where(
                    NetworkRelationship.origin == RelationshipOrigin.BASELINE,
                    NetworkRelationship.relationship_type != RelationshipType.L2_UPLINK,
                )
            ).all()
            flows = []
            for rel in rels:
                src, dst = assets.get(rel.source_asset_id), assets.get(rel.destination_asset_id)
                if src is None or dst is None or not src.ip_address or not dst.ip_address:
                    continue
                if src.containment_state is ContainmentState.ISOLATED:
                    continue  # an isolated host's traffic never leaves its port
                outcome = engine.evaluate(
                    PolicyType.NETWORK_FLOW,
                    endpoint_for_asset(src),
                    endpoint_for_asset(dst),
                    rel.service,
                ).outcome
                flows.append(
                    flow_record(
                        src.ip_address, dst.ip_address, rel.service, rel.port, outcome, "NET-GW-01"
                    )
                )
            return flows

    def send_baseline_flow_report(self, now: datetime) -> None:
        flows = self.baseline_flows()
        if not flows:
            return
        payload = {
            "window_start": (now - timedelta(seconds=30)).isoformat(),
            "window_end": now.isoformat(),
            "flows": flows,
        }
        msg = self.devices.message("NET-SENSOR-01", MessageType.FLOW_REPORT, payload)
        self.pipeline.process(
            InboundMessage(
                msg.raw,
                msg.signature_header,
                IngestChannel.GENERATOR,
                transport_source="10.20.10.40",
            )
        )

    # ---- maintenance ------------------------------------------------------------------------

    def maintenance(self, now: datetime) -> dict[str, int]:
        settings = self.services.settings
        result: dict[str, int] = {}
        with self.services.uow() as uow:
            session = uow.session
            cutoff = now - timedelta(hours=settings.telemetry_retention_hours)
            session.execute(
                delete(DeviceNonce).where(
                    DeviceNonce.first_seen_at
                    < now - timedelta(hours=settings.nonce_retention_hours)
                )
            )
            te = TelemetryEvent
            prunable = (
                delete(te)
                .where(
                    te.decision == TelemetryDecision.ACCEPTED,
                    te.received_at < cutoff,
                    ~exists().where(
                        or_(
                            TwinState.trusted_event_id == te.id,
                            TwinState.reported_event_id == te.id,
                        )
                    ),
                    ~exists().where(SecurityAlert.telemetry_event_id == te.id),
                    ~exists().where(PolicyDecision.telemetry_event_id == te.id),
                    ~exists().where(IncidentEvent.telemetry_event_id == te.id),
                )
                .execution_options(synchronize_session=False)
            )
            result["telemetry_pruned"] = session.execute(prunable).rowcount or 0
            result["events_pruned"] = (
                session.execute(
                    delete(EventLogEntry).where(
                        EventLogEntry.created_at < now - EVENT_LOG_RETENTION
                    )
                ).rowcount
                or 0
            )
            stale = now - timedelta(seconds=OFFLINE_AFTER_SECONDS)
            offline = 0
            for identity in session.scalars(
                select(DeviceIdentity)
                .where(
                    DeviceIdentity.trust_state.in_(
                        (TrustState.AUTHENTICATED, TrustState.REGISTERED)
                    ),
                    DeviceIdentity.last_seen_at < stale,
                )
                .with_for_update()
            ):
                change = trust.transition(
                    identity,
                    TrustState.OFFLINE,
                    f"No authentic message for {OFFLINE_AFTER_SECONDS}s",
                    now,
                )
                if change:
                    offline += 1
                    uow.audit(
                        actor_type=ActorType.SYSTEM,
                        actor_id="liveness-monitor",
                        action="TRUST_STATE_CHANGED",
                        target_type="device_identity",
                        target_id=identity.asset_id,
                        decision=AuditDecision.INFO,
                        reason=change.reason,
                        details={"from": change.from_state.value, "to": change.to_state.value},
                    )
                    uow.emit(
                        "trust.changed",
                        {
                            "asset_id": identity.asset_id,
                            "from": change.from_state.value,
                            "to": change.to_state.value,
                            "reason": change.reason,
                        },
                    )
            result["went_offline"] = offline
        return result


def flow_record(
    src_ip: str,
    dst_ip: str,
    service: str,
    port: int | None,
    outcome: DecisionOutcome,
    point: str,
    packets: int = 40,
) -> dict[str, Any]:
    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "service": service,
        "dst_port": port,
        "packets": packets,
        "bytes": packets * 512,
        "enforcement_action": "blocked" if outcome is DecisionOutcome.BLOCKED else "permitted",
        "enforcement_point": point,
    }
