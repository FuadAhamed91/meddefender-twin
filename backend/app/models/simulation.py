from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_column, utcnow
from app.models.enums import SimulationRunStatus


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[SimulationRunStatus] = mapped_column(enum_column(SimulationRunStatus, "status"))
    seed: Mapped[int] = mapped_column(Integer)
    started_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]
    epoch: Mapped[int] = mapped_column(Integer)
    parameters: Mapped[dict[str, Any]]
    result: Mapped[dict[str, Any] | None]
    correlation_id: Mapped[str] = mapped_column(String(36))


class SimulationState(Base):
    """Singleton row describing the simulation baseline and generator."""

    __tablename__ = "simulation_state"
    __table_args__ = (CheckConstraint("id = 1", name="singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    epoch: Mapped[int] = mapped_column(Integer, default=1)
    generator_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    tick_count: Mapped[int] = mapped_column(BigInteger, default=0)
    last_tick_at: Mapped[datetime | None]
    baseline_loaded_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_reset_at: Mapped[datetime | None]
    last_reset_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class EventLogEntry(Base):
    """Persisted real-time events; WebSocket clients resynchronise from here by id."""

    __tablename__ = "event_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(index=True)
    event_type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]]
