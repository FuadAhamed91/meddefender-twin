"""Test fixtures. Tests run against a real PostgreSQL database (TEST_DATABASE_URL).

The schema is created by running the Alembic migrations, so migrations are exercised too.
Before each test every table is truncated and the baseline re-seeded. Truncating the
append-only tables requires disabling their triggers as the table owner, which is exactly
the limitation documented in docs/THREAT_MODEL.md (a DB owner can bypass application-level
immutability).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import Engine, text

from alembic import command
from app.core.clock import ManualClock
from app.core.config import Settings
from app.db.base import Base
from app.db.session import build_engine, build_session_factory
from app.models import User
from app.models.enums import UserRole
from app.seed.loader import seed_baseline
from app.services.context import AppServices
from app.services.flow_analysis import FlowAnalysis
from app.services.ingestion import IngestionPipeline
from app.simulator.devices import DeviceFactory
from app.simulator.world import WorldCommandSink

BACKEND_DIR = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://meddefender:meddefender-local-dev@127.0.0.1:55432/meddefender_test",
)
MASTER_SECRET = "test-only-master-secret-0123456789-abcdefghijklmnop"
APPEND_ONLY = ("audit_events", "incident_events")
FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1)
PASSWORDS = {
    "viewer": "viewer-password-123",
    "operator": "operator-password-123",
    "secadmin": "secadmin-password-123",
}


@pytest.fixture(scope="session")
def settings() -> Settings:
    # _env_file=None: tests must never pick up a developer's local .env.
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="test",
        database_url=TEST_DATABASE_URL,
        device_key_master_secret=MASTER_SECRET,  # type: ignore[arg-type]
        generator_enabled=False,
        allowed_origins=["http://testserver", "http://localhost:5173"],
    )


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Iterator[Engine]:
    eng = build_engine(settings.database_url)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    yield eng
    eng.dispose()


def reset_database(engine: Engine) -> None:
    tables = [t.name for t in Base.metadata.sorted_tables]
    with engine.begin() as conn:
        for table in APPEND_ONLY:
            conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
        conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        for table in APPEND_ONLY:
            conn.execute(text(f"ALTER TABLE {table} ENABLE TRIGGER USER"))


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(datetime(2026, 10, 16, 8, 0, 0, tzinfo=UTC))


@pytest.fixture
def services(engine: Engine, settings: Settings, clock: ManualClock) -> AppServices:
    reset_database(engine)
    factory = build_session_factory(engine)
    with factory() as session, session.begin():
        seed_baseline(session, settings)
        for username, password in PASSWORDS.items():
            role = {
                "viewer": UserRole.VIEWER,
                "operator": UserRole.OPERATOR,
                "secadmin": UserRole.SECURITY_ADMIN,
            }[username]
            session.add(
                User(
                    username=username,
                    display_name=username.title(),
                    role=role,
                    password_hash=FAST_HASHER.hash(password),
                )
            )
    return AppServices(settings=settings, clock=clock, session_factory=factory)


@pytest.fixture
def pipeline(services: AppServices) -> IngestionPipeline:
    return IngestionPipeline(
        services, command_sink=WorldCommandSink(), flow_analyzer=FlowAnalysis()
    )


@pytest.fixture
def devices(services: AppServices) -> DeviceFactory:
    return DeviceFactory(services)


@pytest.fixture
def app(services: AppServices):
    from app.main import create_app

    return create_app(services=services, start_background=False)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client


def login(client, username: str) -> dict[str, str]:
    """Sign in and return the CSRF header the client must send on unsafe requests."""
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORDS[username]}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}
