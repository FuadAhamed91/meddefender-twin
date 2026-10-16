"""Seed command: ``python -m app.seed`` (idempotent; skips if a baseline exists)."""

from __future__ import annotations

import sys

from app.core.clock import SystemClock
from app.core.config import get_settings
from app.db.session import build_engine, build_session_factory
from app.models.enums import ActorType, AuditDecision
from app.seed.loader import is_seeded, seed_baseline
from app.services import audit


def main() -> int:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    factory = build_session_factory(engine)
    with factory() as session, session.begin():
        if is_seeded(session):
            print("Baseline already present; nothing to do.")
            return 0
        summary = seed_baseline(session, settings)
        now = SystemClock().now()
        audit.append(
            session,
            [
                audit.AuditRecord(
                    occurred_at=now,
                    actor_type=ActorType.SYSTEM,
                    actor_id="seed",
                    action="BASELINE_SEEDED",
                    target_type="simulation",
                    target_id="baseline",
                    decision=AuditDecision.SUCCESS,
                    reason="Synthetic hospital baseline loaded.",
                    correlation_id="seed",
                    epoch=1,
                    details=summary,
                )
            ],
        )
    print("Seeded baseline:", summary)
    if not summary["users"]:
        print("No demo users created (set DEMO_PASSWORD_VIEWER / _OPERATOR / _ADMIN).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
