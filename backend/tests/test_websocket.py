"""WebSocket contract: authentication, origin checks, live updates and resync (#12)."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from app.models.enums import IngestChannel, MessageType
from app.services.ingestion import InboundMessage
from tests.conftest import login

ORIGIN = {"origin": "http://testserver"}
VITALS = {"heart_rate_bpm": 75, "spo2_pct": 96, "resp_rate_bpm": 16, "alarm_config_version": 1}


def test_websocket_requires_session(client):
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws/events", headers=ORIGIN) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 4401


def test_websocket_rejects_foreign_origin(client):
    login(client, "viewer")
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect("/ws/events", headers={"origin": "https://evil.example"}) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == 4403


def test_websocket_streams_twin_updates(client, app, devices, settings):
    login(client, "viewer")
    with client.websocket_connect("/ws/events", headers=ORIGIN) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        msg = devices.message("ICU-MONITOR-03", MessageType.TELEMETRY, VITALS)
        client.post(
            "/api/v1/telemetry/ingest",
            content=msg.raw,
            headers={"X-MD-Signature": msg.signature_header},
        )
        seen = {}
        for _ in range(10):
            event = ws.receive_json()
            seen[event["type"]] = event
            if "twin.updated" in seen and "telemetry.processed" in seen:
                break
        assert seen["twin.updated"]["payload"]["asset_id"] == "ICU-MONITOR-03"
        assert seen["twin.updated"]["payload"]["trusted"] == VITALS
        assert seen["telemetry.processed"]["payload"]["decision"] == "ACCEPTED"
        from app.core.crypto import derive_device_key

        stream = str(seen)
        assert (
            derive_device_key(settings.master_secret_bytes, "ICU-MONITOR-03", 1).hex() not in stream
        )
        assert settings.device_key_master_secret.get_secret_value() not in stream


def test_websocket_resync_replays_missed_events(client, app, devices):
    login(client, "viewer")
    with client.websocket_connect("/ws/events", headers=ORIGIN) as ws:
        last_id = ws.receive_json()["latest_event_id"]
    pipeline = app.state.pipeline
    msg = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    pipeline.process(InboundMessage(msg.raw, msg.signature_header, IngestChannel.SCENARIO))
    with client.websocket_connect(f"/ws/events?since={last_id}", headers=ORIGIN) as ws:
        assert ws.receive_json()["type"] == "hello"
        missed = ws.receive_json()
        assert missed["id"] > last_id
        assert missed["type"] in ("telemetry.processed", "twin.updated", "trust.changed")
