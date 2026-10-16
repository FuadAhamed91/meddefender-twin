"""Serverless mode: live events over HTTP polling and on-demand simulation ticks."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import SimulationRun, SimulationState
from app.models.enums import SimulationRunStatus
from app.services.ingestion import IngestionPipeline
from app.simulator.runtime import SimulationRuntime
from tests.conftest import login


def test_polling_requires_a_session(client):
    assert client.get("/api/v1/events?since=0").status_code == 401


def test_polling_returns_persisted_events_after_the_cursor(client, services, pipeline):
    with services.session_factory() as session, session.begin():
        session.get(SimulationState, 1).generator_enabled = True
    SimulationRuntime(services, pipeline).tick()  # honest devices emit messages -> events
    login(client, "viewer")
    first = client.get("/api/v1/events?since=0").json()
    assert first["resync_required"] is False
    assert first["events"], "a generator tick persists live events"
    ids = [e["id"] for e in first["events"]]
    assert ids == sorted(ids) and ids[-1] == first["latest_event_id"]
    again = client.get(f"/api/v1/events?since={first['latest_event_id']}").json()
    assert again["events"] == []


def test_tick_if_due_ticks_once_per_interval(services, pipeline: IngestionPipeline, clock):
    runtime = SimulationRuntime(services, pipeline)
    interval = services.settings.generator_interval_seconds
    with services.session_factory() as session, session.begin():
        session.get(SimulationState, 1).generator_enabled = True
    assert "tick" in runtime.tick_if_due()
    assert runtime.tick_if_due() == {"skipped": "not due"}
    clock.advance(interval)
    assert "tick" in runtime.tick_if_due()


def test_tick_if_due_waits_for_a_running_scenario(services, pipeline: IngestionPipeline, clock):
    runtime = SimulationRuntime(services, pipeline)
    with services.session_factory() as session, session.begin():
        session.get(SimulationState, 1).generator_enabled = True
        session.add(
            SimulationRun(
                scenario_id="A",
                status=SimulationRunStatus.RUNNING,
                started_at=clock.now(),
                epoch=1,
                seed=7,
                parameters={},
                correlation_id="test-serverless",
            )
        )
    assert runtime.tick_if_due() == {"skipped": "scenario running"}
    with services.session_factory() as session:
        assert session.scalars(select(SimulationRun)).one().status is SimulationRunStatus.RUNNING


def test_serverless_app_is_wired_without_lifespan(settings):
    app = create_app(settings.model_copy(update={"serverless": True}))
    assert isinstance(app.state.runtime, SimulationRuntime)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").json()["database"] == "ok"
