from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_column
from app.models.enums import ActorType, AuditDecision


class AuditEvent(Base):
    """Append-only, hash-chained audit record.

    Immutability is enforced three ways: no update/delete code paths exist, ORM events
    refuse updates/deletes, and a PostgreSQL trigger (see migrations) rejects UPDATE,
    DELETE and TRUNCATE. ``entry_hash`` chains each row to its predecessor so silent edits
    are detectable. This is tamper-evident, not tamper-proof: a database superuser can still
    disable triggers and rewrite the chain.
    """

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_action_time", "action", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(index=True)
    actor_type: Mapped[ActorType] = mapped_column(enum_column(ActorType, "actor_type"))
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    decision: Mapped[AuditDecision] = mapped_column(enum_column(AuditDecision, "decision"))
    reason: Mapped[str] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    simulation_run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id"))
    details: Mapped[dict[str, Any]]
    epoch: Mapped[int] = mapped_column(Integer)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditEvent, "before_update")
def _refuse_update(*_: object) -> None:
    raise AuditImmutableError("audit_events is append-only; updates are not permitted")


@event.listens_for(AuditEvent, "before_delete")
def _refuse_delete(*_: object) -> None:
    raise AuditImmutableError("audit_events is append-only; deletes are not permitted")
