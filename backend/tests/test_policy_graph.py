"""Policy evaluation, attack-path analysis and graph separation (acceptance #7, #8, #9)."""

from __future__ import annotations

from app.models.enums import DecisionOutcome, PolicyEffect, PolicyType, TrustState
from app.services.containment import plan_policy_view
from app.services.graph import GraphContext, attack_paths
from app.services.policy_engine import Endpoint, PolicyEngine
from tests.conftest import login


def ep(asset_id: str, zone: str) -> Endpoint:
    return Endpoint(ref=asset_id, asset_id=asset_id, zone_id=zone)


GATEWAY = ep("ICU-GATEWAY-01", "ZONE-ICU")
MONITOR = ep("ICU-MONITOR-01", "ZONE-ICU")


def engine(services) -> PolicyEngine:
    with services.session_factory() as session:
        return PolicyEngine.load(session)


def test_modeled_flow_is_permitted_with_explanation(services):
    result = engine(services).evaluate(PolicyType.NETWORK_FLOW, MONITOR, GATEWAY, "monitor-feed")
    assert result.outcome is DecisionOutcome.PERMITTED
    assert result.matched_policy_id == "NP-ICU-MONITOR-01-TO-ICU-GATEWAY-01-MONITOR-FEED"
    assert "permits" in result.reason


def test_unlisted_path_is_denied_by_default(services):
    result = engine(services).evaluate(
        PolicyType.NETWORK_FLOW, GATEWAY, ep("IMG-SERVER-01", "ZONE-DC"), "dicom"
    )
    assert result.decision is PolicyEffect.DENY
    assert result.outcome is DecisionOutcome.BLOCKED
    assert result.matched_policy_id == "NP-DEFAULT-DENY"


def test_zone_boundary_rule_wins_over_lower_priority(services):
    result = engine(services).evaluate(
        PolicyType.NETWORK_FLOW, ep("IMG-WS-01", "ZONE-IMG"), MONITOR, "device-config"
    )
    assert result.outcome is DecisionOutcome.BLOCKED
    assert result.matched_policy_id == "ZB-IMG-TO-ICU"


def test_wrong_service_on_a_permitted_pair_is_denied(services):
    result = engine(services).evaluate(
        PolicyType.NETWORK_FLOW, GATEWAY, ep("MON-SERVER-01", "ZONE-DC"), "ssh"
    )
    assert result.outcome is DecisionOutcome.BLOCKED


def test_command_trust_gate_runs_before_policy(services):
    e = engine(services)
    target = MONITOR
    allowed = e.evaluate_command(GATEWAY, TrustState.AUTHENTICATED, target, "update_alarm_limits")
    gated = e.evaluate_command(GATEWAY, TrustState.SUSPICIOUS, target, "update_alarm_limits")
    assert allowed.outcome is DecisionOutcome.PERMITTED
    assert gated.outcome is DecisionOutcome.BLOCKED
    assert "Trust gate" in gated.reason


def test_attack_paths_follow_only_permitted_flows(services):
    with services.session_factory() as session:
        ctx = GraphContext.load(session)
        result = attack_paths(session, ctx, "ICU-GATEWAY-01", 3, 1)
    reachable = {r["asset_id"]: r for r in result["reachable_assets"]}
    assert reachable["MON-SERVER-01"]["min_hops"] == 1
    assert reachable["APP-SERVER-01"]["classification"] == "HYPOTHETICAL"
    assert reachable["IAM-SERVER-01"]["min_hops"] == 3
    assert "IMG-SERVER-01" not in reachable
    assert "ICU-PUMP-01" not in reachable
    # A shared access switch (L2 uplink) is topology, never a traversable permission.
    assert "ICU-SWITCH-01" not in reachable
    nearby = {n["asset_id"] for n in result["nearby_unreachable"]}
    assert {"ICU-PUMP-01", "HVAC-SENSOR-01", "ICU-WS-01"} <= nearby


def test_hypothetical_isolation_removes_paths_without_writing(services):
    deny_all = [
        plan_policy_view(
            {
                "id": "TEST-ISO",
                "name": "isolate",
                "source_asset_id": "ICU-GATEWAY-01",
                "source_zone_id": None,
                "destination_asset_id": None,
                "destination_zone_id": None,
                "service_or_action": "*",
                "effect": "DENY",
                "priority": 10,
                "enforcement_point_id": "ICU-SWITCH-01",
                "rationale": "test",
            }
        )
    ]
    with services.session_factory() as session:
        after = attack_paths(
            session, GraphContext.load(session, extra_policies=deny_all), "ICU-GATEWAY-01", 3, 1
        )
        before = attack_paths(session, GraphContext.load(session), "ICU-GATEWAY-01", 3, 1)
    assert after["path_count"] == 0
    assert before["path_count"] > 0


def test_network_and_dependency_graphs_are_distinct(client):
    login(client, "viewer")
    network = client.get("/api/v1/graph/network").json()
    deps = client.get("/api/v1/graph/dependencies").json()
    net_pairs = {(e["source"], e["destination"]) for e in network["edges"]}
    dep_pairs = {(e["dependent"], e["provider"]) for e in deps["edges"]}
    # Services exist only in the dependency graph; they have no network presence.
    assert not any(n["id"].startswith("SVC-") for n in network["nodes"])
    assert any(d.startswith("SVC-") for d, _ in dep_pairs)
    # Connectivity without dependency: the HVAC sensor talks to the BMS gateway, but the
    # gateway does not depend on it. Dependency without direct connectivity also exists.
    assert ("HVAC-SENSOR-01", "BMS-GW-01") in net_pairs
    assert ("BMS-GW-01", "HVAC-SENSOR-01") not in dep_pairs
    assert ("SVC-CLINICAL-RECORDS", "SVC-STAFF-IDENTITY") in dep_pairs
    l2 = [e for e in network["edges"] if e["relationship_type"] == "L2_UPLINK"]
    assert l2 and all(e["policy_status"] == "TOPOLOGY" for e in l2)


def test_relationship_status_reflects_current_policy(client):
    headers = login(client, "secadmin")
    path = "/api/v1/policies/NP-ICU-GATEWAY-01-TO-MON-SERVER-01-HL7-MLLP"
    detail = client.get("/api/v1/assets/ICU-GATEWAY-01").json()
    rel = next(
        r
        for r in detail["network_relationships"]
        if r["destination_asset_id"] == "MON-SERVER-01" and r["service"] == "hl7-mllp"
    )
    assert rel["policy_status"] == "PERMITTED"
    assert (
        client.patch(
            path, json={"enforcement_mode": "DISABLED", "reason": "test"}, headers=headers
        ).status_code
        == 200
    )
    detail = client.get("/api/v1/assets/ICU-GATEWAY-01").json()
    rel = next(
        r
        for r in detail["network_relationships"]
        if r["destination_asset_id"] == "MON-SERVER-01" and r["service"] == "hl7-mllp"
    )
    assert rel["policy_status"] == "BLOCKED"


def test_policy_dry_run_endpoint(client):
    headers = login(client, "viewer")
    response = client.post(
        "/api/v1/policies/evaluate",
        headers=headers,
        json={
            "policy_type": "DEVICE_COMMAND",
            "source_asset_id": "IMG-WS-01",
            "destination_asset_id": "ICU-MONITOR-01",
            "service_or_action": "update_alarm_limits",
        },
    )
    assert response.status_code == 200
    # IMG-WS-01 is only REGISTERED (not yet authenticated), so the trust gate answers first.
    assert response.json()["outcome"] == "BLOCKED"
