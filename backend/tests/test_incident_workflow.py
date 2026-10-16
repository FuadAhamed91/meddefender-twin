"""Incident state machine, containment and recovery (acceptance #10, #11, #12)."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import DeviceCredential, IncidentEvent, SecurityPolicy
from app.models.enums import CredentialStatus
from tests.conftest import login


def open_gateway_incident(client, headers) -> dict:
    result = client.post("/api/v1/scenarios/D/run", json={}, headers=headers).json()
    assert result["status"] == "COMPLETED"
    incidents = client.get("/api/v1/incidents?open_only=true").json()
    return next(i for i in incidents if i["primary_asset_id"] == "ICU-GATEWAY-01")


def transition(client, headers, incident_id, target, **extra):
    return client.post(
        f"/api/v1/incidents/{incident_id}/transition",
        json={"target_status": target, "note": f"move to {target}", **extra},
        headers=headers,
    )


def test_incident_transitions_are_enforced(client):
    headers = login(client, "operator")
    incident = open_gateway_incident(client, headers)
    assert incident["status"] == "DETECTED"
    assert transition(client, headers, incident["id"], "RESOLVED").status_code == 409
    assert transition(client, headers, incident["id"], "INVESTIGATING").status_code == 200
    contained = transition(client, headers, incident["id"], "CONTAINED")
    assert contained.status_code == 409
    no_plan = transition(client, headers, incident["id"], "CONTAINMENT_PROPOSED")
    assert no_plan.json()["error"]["code"] == "NO_PROPOSED_PLAN"
    needs_reason = transition(client, headers, incident["id"], "RESOLVED")
    assert needs_reason.status_code == 422
    resolved = transition(client, headers, incident["id"], "RESOLVED", resolution="FALSE_POSITIVE")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"


def test_viewer_cannot_transition_incidents(client):
    headers = login(client, "operator")
    incident = open_gateway_incident(client, headers)
    client.post("/api/v1/auth/logout", headers=headers)
    viewer_headers = login(client, "viewer")
    assert transition(client, viewer_headers, incident["id"], "INVESTIGATING").status_code == 403


def test_containment_apply_changes_backend_state_and_emits_events(client, services, app):
    headers = login(client, "operator")
    incident = open_gateway_incident(client, headers)
    transition(client, headers, incident["id"], "INVESTIGATING")
    plans = client.post(
        f"/api/v1/incidents/{incident['id']}/containment/plans", headers=headers
    ).json()
    by = {p["strategy"]: p for p in plans}

    isolate = by["ISOLATE_ASSET"]
    assert isolate["required_role"] == "SECURITY_ADMIN"
    denied = client.post(
        f"/api/v1/containment/plans/{isolate['id']}/apply",
        json={"justification": "operator tries isolation", "confirm": True},
        headers=headers,
    )
    assert denied.status_code == 403

    queue = services.bus.subscribe()
    restrict = by["RESTRICT_TO_REQUIRED_FLOWS"]
    applied = client.post(
        f"/api/v1/containment/plans/{restrict['id']}/apply",
        json={"justification": "Limit gateway egress to the HL7 feed", "confirm": True},
        headers=headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "APPLIED"

    detail = client.get(f"/api/v1/incidents/{incident['id']}").json()
    assert detail["status"] == "CONTAINED"
    asset = client.get("/api/v1/assets/ICU-GATEWAY-01").json()
    assert asset["asset"]["containment_state"] == "RESTRICTED"
    status = {
        (r["destination_asset_id"], r["service"]): r["policy_status"]
        for r in asset["network_relationships"]
        if r["source_asset_id"] == "ICU-GATEWAY-01"
    }
    assert status[("MON-SERVER-01", "hl7-mllp")] == "PERMITTED"
    assert status[("ICU-MONITOR-01", "device-config")] == "BLOCKED"

    received = []
    while not queue.empty():
        received.append(queue.get_nowait()["type"])
    services.bus.unsubscribe(queue)
    assert "containment.applied" in received
    assert "asset.updated" in received


def test_recovery_rotates_keys_releases_containment_and_keeps_evidence(client, services):
    headers = login(client, "operator")
    incident = open_gateway_incident(client, headers)
    transition(client, headers, incident["id"], "INVESTIGATING")
    plans = client.post(
        f"/api/v1/incidents/{incident['id']}/containment/plans", headers=headers
    ).json()
    restrict = next(p for p in plans if p["strategy"] == "RESTRICT_TO_REQUIRED_FLOWS")
    client.post(
        f"/api/v1/containment/plans/{restrict['id']}/apply",
        json={"justification": "contain", "confirm": True},
        headers=headers,
    )
    with services.session_factory() as s:
        events_before = s.scalar(
            select(func.count(IncidentEvent.id)).where(IncidentEvent.incident_id == incident["id"])
        )
    early = client.post(
        f"/api/v1/incidents/{incident['id']}/recovery", json={"note": "too early"}, headers=headers
    )
    assert early.status_code == 409
    assert transition(client, headers, incident["id"], "RECOVERY").status_code == 200
    unfinished = transition(client, headers, incident["id"], "RESOLVED")
    assert unfinished.json()["error"]["code"] == "RECOVERY_NOT_COMPLETED"
    recovered = client.post(
        f"/api/v1/incidents/{incident['id']}/recovery",
        json={"note": "rotate and release"},
        headers=headers,
    )
    assert recovered.status_code == 200, recovered.text
    actions = {s["action"] for s in recovered.json()["steps"]}
    assert {"ROTATE_CREDENTIALS", "RELEASE_CONTAINMENT", "RESTORE_TRUSTED_STATE"} <= actions
    assert transition(client, headers, incident["id"], "RESOLVED").status_code == 200

    with services.session_factory() as s:
        creds = s.scalars(
            select(DeviceCredential).where(DeviceCredential.asset_id == "ICU-GATEWAY-01")
        ).all()
        assert {c.status for c in creds} == {CredentialStatus.ROTATED, CredentialStatus.ACTIVE}
        containment_policies = s.scalars(
            select(SecurityPolicy).where(SecurityPolicy.incident_id == incident["id"])
        ).all()
        assert containment_policies and not any(p.is_active for p in containment_policies)
        events_after = s.scalar(
            select(func.count(IncidentEvent.id)).where(IncidentEvent.incident_id == incident["id"])
        )
    assert events_after > events_before
    asset = client.get("/api/v1/assets/ICU-GATEWAY-01").json()
    assert asset["asset"]["containment_state"] == "NONE"
    assert asset["identity"]["trust_state"] == "REGISTERED"


def test_incident_replay_is_reconstructed_from_records(client):
    headers = login(client, "operator")
    incident = open_gateway_incident(client, headers)
    replay = client.get(f"/api/v1/incidents/{incident['id']}/replay").json()
    kinds = {f["kind"] for f in replay["frames"]}
    assert {"incident_event", "alert", "policy_decision"} <= kinds
    times = [f["t"] for f in replay["frames"]]
    assert times == sorted(times)
    assert replay["frames"][-1]["incident_status"] == "DETECTED"
    assert "ICU-GATEWAY-01" in replay["frames"][-1]["highlighted_assets"]
