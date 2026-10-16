"""First vertical slice: a replayed device message is rejected, trusted state is unchanged,
the audit event is persisted and an incident is created according to the correlation rules."""

from __future__ import annotations

import threading

from sqlalchemy import func, select

from app.db.session import build_engine, build_session_factory
from app.models import (
    AuditEvent,
    DeviceIdentity,
    DeviceReplayState,
    Incident,
    IncidentEvent,
    SecurityAlert,
    TelemetryEvent,
    TwinState,
)
from app.models.enums import (
    IncidentStatus,
    IngestChannel,
    MessageType,
    TelemetryDecision,
    TrustState,
)
from app.services.context import AppServices
from app.services.flow_analysis import FlowAnalysis
from app.services.ingestion import InboundMessage, IngestionPipeline
from app.simulator.devices import SignedMessage
from app.simulator.world import WorldCommandSink

VITALS = {"heart_rate_bpm": 74, "spo2_pct": 97, "resp_rate_bpm": 15, "alarm_config_version": 1}


def inbound(msg: SignedMessage, signature: str | None = None) -> InboundMessage:
    return InboundMessage(
        raw=msg.raw,
        signature_header=signature if signature is not None else msg.signature_header,
        channel=IngestChannel.SCENARIO,
    )


def twin(services: AppServices, asset_id: str) -> TwinState:
    with services.session_factory() as session:
        state = session.get(TwinState, asset_id)
        assert state is not None
        return state


def test_valid_message_is_accepted_and_becomes_trusted(services, pipeline, devices):
    msg = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    result = pipeline.process(inbound(msg))

    assert result.decision is TelemetryDecision.ACCEPTED, result.checks
    assert result.authenticated
    assert [c["status"] for c in result.checks if c["check"] != "model"] == ["PASS"] * 8
    state = twin(services, "ICU-MONITOR-01")
    assert state.trusted == VITALS
    assert state.reported == VITALS
    assert state.trusted_event_id == result.telemetry_event_id
    with services.session_factory() as session:
        identity = session.get(DeviceIdentity, "ICU-MONITOR-01")
        assert identity.trust_state is TrustState.AUTHENTICATED
        assert session.get(DeviceReplayState, "ICU-MONITOR-01").last_sequence == msg.sequence


def test_invalid_hmac_is_rejected_and_changes_nothing(services, pipeline, devices):
    msg = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    tampered = msg.signature_header[:-4] + (
        "0000" if not msg.signature_header.endswith("0000") else "1111"
    )
    result = pipeline.process(inbound(msg, tampered))

    assert result.decision is TelemetryDecision.REJECTED
    assert result.reason_code == "BAD_SIGNATURE"
    assert not result.authenticated
    state = twin(services, "ICU-MONITOR-01")
    assert state.trusted is None and state.reported is None
    with services.session_factory() as session:
        # Failed authentication must not advance replay state or penalise the claimed identity.
        assert session.get(DeviceReplayState, "ICU-MONITOR-01").last_sequence == 0
        assert session.get(DeviceIdentity, "ICU-MONITOR-01").trust_state is TrustState.REGISTERED


def test_replayed_message_is_rejected_audited_and_opens_incident(services, pipeline, devices):
    original = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    first = pipeline.process(inbound(original))
    assert first.decision is TelemetryDecision.ACCEPTED
    trusted_before = twin(services, "ICU-MONITOR-01")

    replay = pipeline.process(inbound(original))  # exact same bytes and MAC

    assert replay.decision is TelemetryDecision.REJECTED
    assert replay.reason_code == "REPLAY_DUPLICATE"
    assert replay.authenticated, "a replay carries a valid MAC; integrity alone cannot stop it"
    statuses = {c["check"]: c["status"] for c in replay.checks}
    assert statuses["integrity"] == "PASS"
    assert statuses["sequence"] == "FAIL"
    assert statuses["nonce"] == "FAIL"

    trusted_after = twin(services, "ICU-MONITOR-01")
    assert trusted_after.trusted == trusted_before.trusted
    assert trusted_after.trusted_event_id == first.telemetry_event_id
    assert trusted_after.version == trusted_before.version

    with services.session_factory() as session:
        audit = session.scalars(
            select(AuditEvent).where(AuditEvent.action == "TELEMETRY_REJECTED")
        ).one()
        assert audit.decision.value == "DENY"
        assert audit.reason.startswith("REPLAY_DUPLICATE")
        assert audit.correlation_id == replay.correlation_id
        assert audit.target_id == str(replay.telemetry_event_id)
        assert audit.details["trusted_state_changed"] is False

        alert = session.scalars(select(SecurityAlert)).one()
        assert alert.rule_id == "MD-RPL-001"
        assert alert.evidence["original_event_id"] == first.telemetry_event_id
        incident = session.get(Incident, alert.incident_id)
        assert incident.status is IncidentStatus.DETECTED
        assert incident.primary_asset_id == "ICU-MONITOR-01"
        assert replay.incident_refs == [incident.reference]
        events = session.scalars(
            select(IncidentEvent).where(IncidentEvent.incident_id == incident.id)
        ).all()
        assert [e.event_type for e in events] == ["CREATED", "ALERT_ATTACHED"]
        # A replay proves capture, not key compromise: the device stays AUTHENTICATED.
        assert session.get(DeviceIdentity, "ICU-MONITOR-01").trust_state is TrustState.AUTHENTICATED


def test_repeated_replay_updates_the_same_incident(services, pipeline, devices):
    original = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    pipeline.process(inbound(original))
    pipeline.process(inbound(original))
    pipeline.process(inbound(original))
    with services.session_factory() as session:
        incidents = session.scalars(select(Incident)).all()
        assert len(incidents) == 1
        assert incidents[0].alert_count == 2


def test_stale_message_is_rejected(services, pipeline, devices, clock):
    msg = devices.message("ICU-MONITOR-02", MessageType.TELEMETRY, VITALS)
    clock.advance(services.settings.freshness_window_seconds + 5)
    result = pipeline.process(inbound(msg))
    assert result.decision is TelemetryDecision.REJECTED
    assert result.reason_code == "STALE"
    assert twin(services, "ICU-MONITOR-02").trusted is None


def test_old_captured_message_fails_sequence_and_freshness(services, pipeline, devices, clock):
    captured = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    assert pipeline.process(inbound(captured)).decision is TelemetryDecision.ACCEPTED
    clock.advance(120)
    newer = devices.message(
        "ICU-MONITOR-01", MessageType.TELEMETRY, VITALS | {"heart_rate_bpm": 76}
    )
    assert pipeline.process(inbound(newer)).decision is TelemetryDecision.ACCEPTED

    result = pipeline.process(inbound(captured))
    statuses = {c["check"]: c["status"] for c in result.checks}
    assert result.reason_code == "REPLAY_DUPLICATE"
    assert statuses["sequence"] == statuses["freshness"] == statuses["nonce"] == "FAIL"
    assert twin(services, "ICU-MONITOR-01").trusted["heart_rate_bpm"] == 76


def test_replay_protection_survives_restart(services, pipeline, devices, settings):
    original = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    assert pipeline.process(inbound(original)).decision is TelemetryDecision.ACCEPTED

    # Simulate an application restart: brand-new engine, pool and pipeline, same database.
    fresh_engine = build_engine(settings.database_url)
    try:
        restarted = AppServices(
            settings=settings,
            clock=services.clock,
            session_factory=build_session_factory(fresh_engine),
        )
        new_pipeline = IngestionPipeline(restarted, WorldCommandSink(), FlowAnalysis())
        result = new_pipeline.process(inbound(original))
        assert result.decision is TelemetryDecision.REJECTED
        assert result.reason_code == "REPLAY_DUPLICATE"
    finally:
        fresh_engine.dispose()


def test_concurrent_duplicates_are_accepted_at_most_once(services, pipeline, devices):
    msg = devices.message("ICU-MONITOR-03", MessageType.TELEMETRY, VITALS)
    barrier = threading.Barrier(4)
    results = []

    def submit() -> None:
        barrier.wait()
        results.append(pipeline.process(inbound(msg)))

    threads = [threading.Thread(target=submit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    decisions = sorted(r.decision.value for r in results)
    assert decisions.count("ACCEPTED") == 1, decisions
    assert decisions.count("REJECTED") == 3
    with services.session_factory() as session:
        accepted = session.scalar(
            select(func.count(TelemetryEvent.id)).where(
                TelemetryEvent.asset_id == "ICU-MONITOR-03",
                TelemetryEvent.decision == TelemetryDecision.ACCEPTED,
            )
        )
        assert accepted == 1


def test_unknown_identity_is_rejected(services, pipeline, devices):
    forged = devices.forged("ICU-MONITOR-09", MessageType.TELEMETRY, VITALS, sequence=1)
    result = pipeline.process(inbound(forged))
    assert result.decision is TelemetryDecision.REJECTED
    assert result.reason_code == "UNKNOWN_DEVICE"
    with services.session_factory() as session:
        alert = session.scalars(select(SecurityAlert)).one()
        assert alert.rule_id == "MD-ID-001"
        assert alert.subject_ref == "ICU-MONITOR-09"


def test_no_secret_material_anywhere_in_the_database(services, pipeline, devices, settings):
    from sqlalchemy import text

    from app.core.crypto import derive_device_key
    from app.db.base import Base

    pipeline.process(inbound(devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)))
    secrets_to_find = [
        derive_device_key(settings.master_secret_bytes, "ICU-MONITOR-01", 1).hex(),
        settings.device_key_master_secret.get_secret_value(),
    ]
    with services.session_factory() as session:
        for table in Base.metadata.sorted_tables:
            rows = session.execute(
                text(f"SELECT row_to_json(t)::text FROM {table.name} t")
            ).scalars()
            blob = " ".join(rows)
            for secret in secrets_to_find:
                assert secret not in blob, f"secret material found in {table.name}"
