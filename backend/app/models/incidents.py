from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, enum_column, utcnow
from app.models.enums import (
    ActorType,
    AlertClassification,
    IncidentStatus,
    PlanStatus,
    Severity,
)


class SecurityAlert(Base):
    """A deterministic rule hit with its evidence and confidence limitations."""

    __tablename__ = "security_alerts"
    __table_args__ = (
        Index("ix_security_alerts_asset_time", "asset_id", "created_at"),
        Index("ix_security_alerts_subject_rule_time", "subject_ref", "rule_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(index=True)
    rule_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    classification: Mapped[AlertClassification] = mapped_column(
        enum_column(AlertClassification, "classification", length=40)
    )
    severity: Mapped[Severity] = mapped_column(enum_column(Severity, "severity"))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    subject_ref: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any]]
    confidence_note: Mapped[str] = mapped_column(Text)
    telemetry_event_id: Mapped[int | None] = mapped_column(ForeignKey("telemetry_events.id"))
    policy_decision_id: Mapped[int | None] = mapped_column(ForeignKey("policy_decisions.id"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    simulation_run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id"))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    epoch: Mapped[int] = mapped_column(Integer)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        # At most one open incident per correlation key within a simulation epoch.
        Index(
            "uq_incidents_open_correlation",
            "correlation_key",
            "epoch",
            unique=True,
            postgresql_where=text("status <> 'RESOLVED'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str | None] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(48))
    status: Mapped[IncidentStatus] = mapped_column(enum_column(IncidentStatus, "status"))
    severity: Mapped[Severity] = mapped_column(enum_column(Severity, "severity"))
    primary_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    primary_subject_ref: Mapped[str] = mapped_column(String(64))
    detection_rule_id: Mapped[str] = mapped_column(String(32))
    correlation_key: Mapped[str] = mapped_column(String(160))
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    recovery_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    resolution: Mapped[str | None] = mapped_column(String(32))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(index=True)
    updated_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None]
    simulation_run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id"))
    epoch: Mapped[int] = mapped_column(Integer, index=True)

    events: Mapped[list[IncidentEvent]] = relationship(
        back_populates="incident", order_by="IncidentEvent.id"
    )
    assets: Mapped[list[IncidentAsset]] = relationship(back_populates="incident")


class IncidentAsset(Base):
    __tablename__ = "incident_assets"

    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(32))
    added_at: Mapped[datetime] = mapped_column(default=utcnow)

    incident: Mapped[Incident] = relationship(back_populates="assets")


class IncidentEvent(Base):
    """Incident timeline entry. Never edited or deleted (recovery keeps the evidence)."""

    __tablename__ = "incident_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    occurred_at: Mapped[datetime]
    event_type: Mapped[str] = mapped_column(String(40))
    actor_type: Mapped[ActorType] = mapped_column(enum_column(ActorType, "actor_type"))
    actor_id: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]]
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("security_alerts.id"))
    policy_decision_id: Mapped[int | None] = mapped_column(ForeignKey("policy_decisions.id"))
    telemetry_event_id: Mapped[int | None] = mapped_column(ForeignKey("telemetry_events.id"))
    correlation_id: Mapped[str] = mapped_column(String(36))

    incident: Mapped[Incident] = relationship(back_populates="events")


class ContainmentPlan(Base):
    __tablename__ = "containment_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    strategy: Mapped[str] = mapped_column(String(40))
    target_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[PlanStatus] = mapped_column(enum_column(PlanStatus, "status"))
    required_role: Mapped[str] = mapped_column(String(32))
    analysis: Mapped[dict[str, Any]]
    policy_changes: Mapped[list[Any]]
    identity_changes: Mapped[list[Any]]
    created_at: Mapped[datetime]
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    applied_at: Mapped[datetime | None]
    applied_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    apply_justification: Mapped[str | None] = mapped_column(Text)
    rolled_back_at: Mapped[datetime | None]
    rolled_back_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
