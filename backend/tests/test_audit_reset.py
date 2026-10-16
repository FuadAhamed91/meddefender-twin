"""Audit immutability, hash chain, reset semantics and persistence (acceptance #13, #15, #16)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.main import create_app
from app.models import AuditEvent, Incident, IncidentEvent
from app.models.audit import AuditImmutableError
from app.models.enums import IngestChannel, MessageType
from app.services import audit
from app.services.ingestion import InboundMessage
from tests.conftest import login

VITALS = {"heart_rate_bpm": 70, "spo2_pct": 97, "resp_rate_bpm": 14, "alarm_config_version": 1}


def test_audit_rows_cannot_be_updated_or_deleted(services, client):
    login(client, "viewer")  # writes LOGIN_SUCCEEDED
    with services.session_factory() as s, s.begin():
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE audit_events SET reason = 'edited'"))
    with services.session_factory() as s, s.begin():
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM audit_events"))
    with services.session_factory() as s, s.begin():
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("TRUNCATE audit_events"))
    with services.session_factory() as s:
        row = s.scalars(select(AuditEvent)).first()
        row.reason = "edited through the ORM"
        with pytest.raises(AuditImmutableError):
            s.flush()


def test_incident_timeline_is_append_only(services, client):
    headers = login(client, "operator")
    client.post("/api/v1/scenarios/A/run", json={}, headers=headers)
    with services.session_factory() as s, s.begin():
        assert s.scalar(select(func.count(IncidentEvent.id))) > 0
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM incident_events"))


def test_audit_events_record_decision_and_reason(client, services):
    headers = login(client, "operator")
    run = client.post("/api/v1/scenarios/B/run", json={}, headers=headers).json()
    denied = client.get("/api/v1/audit?action=COMMAND_DENIED").json()
    assert denied, "command denial must be audited"
    entry = denied[0]
    assert entry["decision"] == "DENY"
    assert "denies" in entry["reason"]
    assert entry["simulation_run_id"] == run["id"]
    assert entry["correlation_id"]
    assert entry["details"]["policy_decision_id"]


def test_hash_chain_verifies_and_detects_tampering(client, services, engine):
    headers = login(client, "operator")
    client.post("/api/v1/scenarios/A/run", json={}, headers=headers)
    result = client.get("/api/v1/audit/verify").json()
    assert result["valid"] is True and result["checked"] > 5

    # A database owner can bypass the trigger (documented limitation); the chain exposes it.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE audit_events DISABLE TRIGGER audit_events_no_update_delete"))
        target = conn.execute(
            text("SELECT id FROM audit_events ORDER BY id LIMIT 1 OFFSET 2")
        ).scalar()
        conn.execute(
            text("UPDATE audit_events SET reason = 'quietly rewritten' WHERE id = :id"),
            {"id": target},
        )
        conn.execute(text("ALTER TABLE audit_events ENABLE TRIGGER audit_events_no_update_delete"))
    with services.session_factory() as s:
        verification = audit.verify_chain(s)
    assert verification.valid is False
    assert verification.first_invalid_id == target


def test_reset_restores_baseline_without_erasing_history(client, services, pipeline, devices):
    operator = login(client, "operator")
    captured = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    pipeline.process(
        InboundMessage(captured.raw, captured.signature_header, IngestChannel.SCENARIO)
    )
    client.post("/api/v1/scenarios/D/run", json={}, headers=operator)
    with services.session_factory() as s:
        audit_before = s.scalar(select(func.count(AuditEvent.id)))
        incidents_before = s.scalar(select(func.count(Incident.id)))
    client.post("/api/v1/auth/logout", headers=operator)

    admin = login(client, "secadmin")
    reset = client.post(
        "/api/v1/simulation/reset", json={"reason": "new demo baseline"}, headers=admin
    )
    assert reset.status_code == 200, reset.text
    assert reset.json()["epoch"] == 2

    with services.session_factory() as s:
        assert s.scalar(select(func.count(AuditEvent.id))) > audit_before
        assert s.scalar(select(func.count(Incident.id))) == incidents_before
    assert client.get("/api/v1/audit/verify").json()["valid"] is True
    assert client.get("/api/v1/incidents").json() == []  # current epoch is clean
    previous = client.get("/api/v1/incidents?include_previous_epochs=true").json()
    assert len(previous) == incidents_before
    old = previous[0]
    detail = client.get(f"/api/v1/incidents/{old['id']}").json()
    assert detail["read_only"] is True
    blocked = client.post(
        f"/api/v1/incidents/{old['id']}/transition",
        json={"target_status": "INVESTIGATING", "note": "should be read-only"},
        headers=admin,
    )
    assert blocked.status_code == 409

    gateway = client.get("/api/v1/assets/ICU-GATEWAY-01").json()
    assert gateway["identity"]["trust_state"] == "REGISTERED"
    # Replay state is intentionally NOT reset: messages captured before the reset stay dead.
    replay = pipeline.process(
        InboundMessage(captured.raw, captured.signature_header, IngestChannel.SCENARIO)
    )
    assert replay.reason_code == "REPLAY_DUPLICATE"


def test_state_survives_application_restart(services, client):
    headers = login(client, "operator")
    client.post("/api/v1/scenarios/E/run", json={}, headers=headers)
    incidents = client.get("/api/v1/incidents").json()
    twin = client.get("/api/v1/assets/HVAC-SENSOR-01").json()["twin_state"]

    from fastapi.testclient import TestClient

    with TestClient(create_app(services=services, start_background=False)) as fresh:
        login(fresh, "viewer")
        assert fresh.get("/api/v1/incidents").json() == incidents
        assert fresh.get("/api/v1/assets/HVAC-SENSOR-01").json()["twin_state"] == twin
