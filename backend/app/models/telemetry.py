from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_column, utcnow
from app.models.enums import IngestChannel, TelemetryDecision


class TelemetryEvent(Base):
    """Every message that reached the ingestion boundary, accepted or not.

    ``claimed_device_id`` is whatever the sender claimed; ``asset_id`` is only set when the
    claim resolves to a registered identity. Rejected and held messages are evidence and are
    retained; routine accepted telemetry is pruned after the retention window.
    """

    __tablename__ = "telemetry_events"
    __table_args__ = (
        Index("ix_telemetry_events_asset_received", "asset_id", "received_at"),
        Index("ix_telemetry_events_decision_received", "decision", "received_at"),
        Index("ix_telemetry_events_claimed_received", "claimed_device_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    received_at: Mapped[datetime] = mapped_column(index=True)
    claimed_device_id: Mapped[str | None] = mapped_column(String(64))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    message_type: Mapped[str | None] = mapped_column(String(24))
    sequence: Mapped[int | None] = mapped_column(BigInteger)
    device_timestamp: Mapped[datetime | None]
    nonce: Mapped[str | None] = mapped_column(String(64))
    key_version: Mapped[int | None] = mapped_column(Integer)
    message_digest: Mapped[str] = mapped_column(String(64), index=True)
    raw_message: Mapped[str] = mapped_column(Text)
    presented_signature: Mapped[str | None] = mapped_column(String(64))
    integrity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[TelemetryDecision] = mapped_column(enum_column(TelemetryDecision, "decision"))
    reason_code: Mapped[str] = mapped_column(String(48))
    reason: Mapped[str] = mapped_column(Text)
    checks: Mapped[list[Any]]
    payload: Mapped[dict[str, Any] | None]
    channel: Mapped[IngestChannel] = mapped_column(enum_column(IngestChannel, "channel"))
    simulation_run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id"))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    epoch: Mapped[int] = mapped_column(Integer)


class TwinState(Base):
    """Three deliberately separate views of an asset's state.

    * reported  - the latest authentic, fresh claim from the device (may be invalid)
    * trusted   - the latest claim that passed every check (never overwritten by rejects)
    * predicted - what the deterministic model expects, given trusted inputs
    """

    __tablename__ = "twin_states"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    reported: Mapped[dict[str, Any] | None]
    reported_at: Mapped[datetime | None]
    reported_event_id: Mapped[int | None] = mapped_column(ForeignKey("telemetry_events.id"))
    reported_decision: Mapped[str | None] = mapped_column(String(16))
    trusted: Mapped[dict[str, Any] | None]
    trusted_at: Mapped[datetime | None]
    trusted_event_id: Mapped[int | None] = mapped_column(ForeignKey("telemetry_events.id"))
    predicted: Mapped[dict[str, Any] | None]
    predicted_at: Mapped[datetime | None]
    model_name: Mapped[str | None] = mapped_column(String(64))
    discrepancy: Mapped[dict[str, Any] | None]
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class SimDevice(Base):
    """Simulator ground truth: the 'physical world'. Never read by the security pipeline."""

    __tablename__ = "sim_devices"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    next_sequence: Mapped[int] = mapped_column(BigInteger, default=1)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    physical_state: Mapped[dict[str, Any]]
    online: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)
