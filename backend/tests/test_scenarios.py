"""Attack scenarios A-F run through the real pipeline; every expectation must be met."""

from __future__ import annotations

import pytest

from tests.conftest import login


def run(client, headers, scenario_id):
    response = client.post(
        f"/api/v1/scenarios/{scenario_id}/run", json={"seed": 7}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def unmet(result):
    return [e for e in result["result"]["expectations"] if not e["met"]]


@pytest.mark.parametrize("scenario_id", ["A", "B", "C", "D", "E"])
def test_scenario_meets_all_expectations(client, scenario_id):
    headers = login(client, "operator")
    result = run(client, headers, scenario_id)
    assert result["status"] == "COMPLETED", result["result"]["error"]
    assert result["result"]["expectations_total"] >= 4
    assert unmet(result) == [], unmet(result)
    assert result["result"]["all_met"] is True


def test_scenario_f_compares_plans_after_d(client):
    headers = login(client, "operator")
    assert unmet(run(client, headers, "D")) == []
    result = run(client, headers, "F")
    assert result["status"] == "COMPLETED", result["result"]["error"]
    assert unmet(result) == [], unmet(result)
    strategies = {row["strategy"] for row in result["result"]["artifacts"]["comparison"]}
    assert {"ISOLATE_ASSET", "RESTRICT_TO_REQUIRED_FLOWS", "REVOKE_CREDENTIALS"} <= strategies


def test_scenario_f_without_incident_reports_failed_precondition(client):
    headers = login(client, "operator")
    result = run(client, headers, "F")
    assert result["status"] == "FAILED"
    assert result["result"]["error"]["code"] == "PRECONDITION_FAILED"


def test_scenario_a_exercises_freshness_with_an_old_capture(client, clock):
    headers = login(client, "operator")
    run(client, headers, "A")
    clock.advance(90)
    second = run(client, headers, "A")
    labels = [step["label"] for step in second["result"]["steps"]]
    assert any("older captured message" in label for label in labels)
    assert unmet(second) == []


def test_scenario_catalog_lists_preconditions(client):
    login(client, "viewer")
    catalog = client.get("/api/v1/scenarios").json()
    assert [s["id"] for s in catalog] == ["A", "B", "C", "D", "E", "F"]
    f = next(s for s in catalog if s["id"] == "F")
    assert f["precondition_checks"][0]["met"] is False


def test_scenario_runs_are_persisted(client):
    headers = login(client, "operator")
    result = run(client, headers, "B")
    stored = client.get(f"/api/v1/simulation/runs/{result['id']}").json()
    assert stored["result"]["expectations_met"] == result["result"]["expectations_met"]
    events = client.get(f"/api/v1/telemetry/events?run_id={result['id']}").json()
    assert events and all(e["channel"] == "SCENARIO" for e in events)
