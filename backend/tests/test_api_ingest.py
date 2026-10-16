"""HTTP device ingestion: HMAC authentication, replay handling and safe responses."""

from __future__ import annotations

from app.models.enums import MessageType
from tests.conftest import login

VITALS = {"heart_rate_bpm": 72, "spo2_pct": 98, "resp_rate_bpm": 14, "alarm_config_version": 1}


def post(client, msg, signature=None):
    return client.post(
        "/api/v1/telemetry/ingest",
        content=msg.raw,
        headers={
            "X-MD-Signature": signature if signature is not None else msg.signature_header,
            "Content-Type": "application/json",
        },
    )


def test_valid_message_accepted_over_http(client, devices):
    response = post(client, devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS))
    assert response.status_code == 202
    assert response.json()["decision"] == "ACCEPTED"
    assert response.json()["reason_code"] == "OK"


def test_bad_signature_and_unknown_device_look_identical(client, devices):
    msg = devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS)
    bad_sig = post(client, msg, "hmac-sha256=" + "0" * 64)
    unknown = post(
        client, devices.forged("ICU-MONITOR-77", MessageType.TELEMETRY, VITALS, sequence=1)
    )
    assert bad_sig.status_code == unknown.status_code == 401
    assert bad_sig.json()["reason_code"] is None
    assert unknown.json()["reason_code"] is None


def test_replay_over_http_is_409(client, devices):
    msg = devices.message("ICU-MONITOR-02", MessageType.TELEMETRY, VITALS)
    assert post(client, msg).status_code == 202
    replay = post(client, msg)
    assert replay.status_code == 409
    assert replay.json()["reason_code"] == "REPLAY_DUPLICATE"


def test_oversized_and_malformed_bodies(client, services):
    big = client.post(
        "/api/v1/telemetry/ingest",
        content=b"{" + b" " * (services.settings.max_message_bytes + 10) + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert big.status_code == 413
    malformed = client.post(
        "/api/v1/telemetry/ingest",
        content=b"not json",
        headers={"X-MD-Signature": "hmac-sha256=" + "0" * 64},
    )
    assert malformed.status_code == 400


def test_rejection_detail_is_for_soc_users_not_devices(client, devices):
    response = post(
        client,
        devices.message("ICU-MONITOR-01", MessageType.TELEMETRY, VITALS),
        "hmac-sha256=" + "1" * 64,
    )
    event_id = response.json()["event_id"]
    assert client.get(f"/api/v1/telemetry/events/{event_id}").status_code == 401
    login(client, "viewer")
    detail = client.get(f"/api/v1/telemetry/events/{event_id}").json()
    assert detail["reason_code"] == "BAD_SIGNATURE"
    assert any(c["check"] == "integrity" and c["status"] == "FAIL" for c in detail["checks"])
