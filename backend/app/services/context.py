"""Application service container and the unit of work used by every write path."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from types import TracebackType
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.clock import Clock
from app.core.config import Settings
from app.models import EventLogEntry, SimulationState
from app.models.enums import ActorType, AuditDecision
from app.services import audit
from app.services.events import EventBus, event_message, record_event


@dataclass
class AppServices:
    settings: Settings
    clock: Clock
    session_factory: sessionmaker[Session]
    bus: EventBus = field(default_factory=EventBus)

    def uow(self, correlation_id: str | None = None) -> UnitOfWork:
        return UnitOfWork(self, correlation_id=correlation_id)


class UnitOfWork:
    """One transaction. Audit records are chained and events published only on commit."""

    def __init__(self, services: AppServices, correlation_id: str | None = None) -> None:
        self.services = services
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.now: datetime = services.clock.now()
        self._session: Session | None = None
        self._audit: list[audit.AuditRecord] = []
        self._events: list[EventLogEntry] = []
        self._epoch: int | None = None
        self.published: list[dict[str, Any]] = []

    # ---- lifecycle ------------------------------------------------------------------------

    def __enter__(self) -> UnitOfWork:
        self._session = self.services.session_factory()
        self._session.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            if exc_type is None:
                audit.append(session, self._audit)
                session.flush()
                messages = [event_message(entry) for entry in self._events]
                session.commit()
                self.published = messages
                self.services.bus.publish(messages)
            else:
                session.rollback()
        finally:
            session.close()

    @property
    def session(self) -> Session:
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside its context manager")
        return self._session

    @property
    def epoch(self) -> int:
        if self._epoch is None:
            self._epoch = (
                self.session.scalar(select(SimulationState.epoch).where(SimulationState.id == 1))
                or 1
            )
        return self._epoch

    # ---- recording ------------------------------------------------------------------------

    def audit(
        self,
        *,
        actor_type: ActorType,
        actor_id: str,
        action: str,
        target_type: str,
        target_id: str,
        decision: AuditDecision,
        reason: str,
        details: dict[str, Any] | None = None,
        incident_id: int | None = None,
        simulation_run_id: int | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        self._audit.append(
            audit.AuditRecord(
                occurred_at=occurred_at or self.now,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                decision=decision,
                reason=reason,
                correlation_id=self.correlation_id,
                epoch=self.epoch,
                details=details or {},
                incident_id=incident_id,
                simulation_run_id=simulation_run_id,
            )
        )

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self._events.append(record_event(self.session, self.now, event_type, payload))
