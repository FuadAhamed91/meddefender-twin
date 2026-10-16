from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, enum_column, utcnow
from app.models.enums import (
    Criticality,
    DecisionOutcome,
    DependencyType,
    EnforcementMode,
    PolicyEffect,
    PolicyOrigin,
    PolicyType,
    RelationshipOrigin,
    RelationshipType,
)


class NetworkRelationship(Base):
    """A modeled communication path or L2 uplink.

    There is intentionally no 'allowed' column: whether traffic is permitted is computed by
    the policy engine at query time. A line in the twin never implies permission.
    """

    __tablename__ = "network_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_asset_id",
            "destination_asset_id",
            "service",
            "relationship_type",
            name="uq_network_relationships_edge",
        ),
        CheckConstraint("source_asset_id <> destination_asset_id", name="no_self_edge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    destination_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    relationship_type: Mapped[RelationshipType] = mapped_column(
        enum_column(RelationshipType, "relationship_type")
    )
    service: Mapped[str] = mapped_column(String(32))
    protocol_label: Mapped[str] = mapped_column(String(96))
    port: Mapped[int | None] = mapped_column(Integer)
    origin: Mapped[RelationshipOrigin] = mapped_column(enum_column(RelationshipOrigin, "origin"))
    description: Mapped[str] = mapped_column(Text, default="")
    first_seen_at: Mapped[datetime | None]
    last_seen_at: Mapped[datetime | None]
    observation_count: Mapped[int] = mapped_column(Integer, default=0)


class OperationalDependency(Base):
    """``dependent`` relies on ``provider``. Distinct from network connectivity."""

    __tablename__ = "operational_dependencies"
    __table_args__ = (
        UniqueConstraint(
            "dependent_asset_id",
            "provider_asset_id",
            "dependency_type",
            name="uq_operational_dependencies_edge",
        ),
        CheckConstraint("dependent_asset_id <> provider_asset_id", name="no_self_dependency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dependent_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    provider_asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    dependency_type: Mapped[DependencyType] = mapped_column(
        enum_column(DependencyType, "dependency_type")
    )
    criticality: Mapped[Criticality] = mapped_column(enum_column(Criticality, "criticality"))
    description: Mapped[str] = mapped_column(Text)
    carried_by_relationship_id: Mapped[int | None] = mapped_column(
        ForeignKey("network_relationships.id")
    )


class SecurityPolicy(Base):
    """Explicit, explainable allow/deny rule for network flows or device commands.

    Selectors: at most one of asset/zone per side; both null means 'any'.
    Lower ``priority`` is evaluated first; at equal priority DENY wins.
    """

    __tablename__ = "security_policies"
    __table_args__ = (
        CheckConstraint(
            "NOT (source_asset_id IS NOT NULL AND source_zone_id IS NOT NULL)",
            name="single_source_selector",
        ),
        CheckConstraint(
            "NOT (destination_asset_id IS NOT NULL AND destination_zone_id IS NOT NULL)",
            name="single_destination_selector",
        ),
        Index("ix_security_policies_active_type", "is_active", "policy_type"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    policy_type: Mapped[PolicyType] = mapped_column(enum_column(PolicyType, "policy_type"))
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    source_zone_id: Mapped[str | None] = mapped_column(ForeignKey("hospital_zones.id"))
    destination_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    destination_zone_id: Mapped[str | None] = mapped_column(ForeignKey("hospital_zones.id"))
    service_or_action: Mapped[str] = mapped_column(String(48), default="*")
    effect: Mapped[PolicyEffect] = mapped_column(enum_column(PolicyEffect, "effect"))
    priority: Mapped[int] = mapped_column(Integer)
    enforcement_mode: Mapped[EnforcementMode] = mapped_column(
        enum_column(EnforcementMode, "enforcement_mode")
    )
    enforcement_point_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    origin: Mapped[PolicyOrigin] = mapped_column(enum_column(PolicyOrigin, "origin"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    containment_plan_id: Mapped[int | None] = mapped_column(ForeignKey("containment_plans.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    deactivated_at: Mapped[datetime | None]


class PolicyDecision(Base):
    """Every policy evaluation that affected a message, flow or command."""

    __tablename__ = "policy_decisions"
    __table_args__ = (
        Index("ix_policy_decisions_decision_time", "decision", "evaluated_at"),
        Index("ix_policy_decisions_source_time", "source_ref", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    evaluated_at: Mapped[datetime] = mapped_column(default=utcnow)
    policy_type: Mapped[PolicyType] = mapped_column(enum_column(PolicyType, "policy_type"))
    source_ref: Mapped[str] = mapped_column(String(64))
    source_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    destination_ref: Mapped[str] = mapped_column(String(64))
    destination_asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    service_or_action: Mapped[str] = mapped_column(String(48))
    decision: Mapped[PolicyEffect] = mapped_column(enum_column(PolicyEffect, "decision"))
    outcome: Mapped[DecisionOutcome] = mapped_column(enum_column(DecisionOutcome, "outcome"))
    matched_policy_id: Mapped[str | None] = mapped_column(ForeignKey("security_policies.id"))
    reason: Mapped[str] = mapped_column(Text)
    explanation: Mapped[dict[str, Any]]
    telemetry_event_id: Mapped[int | None] = mapped_column(ForeignKey("telemetry_events.id"))
    simulation_run_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_runs.id"))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    epoch: Mapped[int] = mapped_column(Integer)
