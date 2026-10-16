from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, enum_column, utcnow
from app.models.enums import CredentialStatus, EnrollmentStatus, RegistrationStatus, TrustState
from app.models.hospital import Asset


class DeviceIdentity(Base):
    """Registration and trust state for an asset that signs messages."""

    __tablename__ = "device_identities"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    registration_status: Mapped[RegistrationStatus] = mapped_column(
        enum_column(RegistrationStatus, "registration_status")
    )
    trust_state: Mapped[TrustState] = mapped_column(enum_column(TrustState, "trust_state"))
    trust_reason: Mapped[str] = mapped_column(Text, default="")
    trust_changed_at: Mapped[datetime] = mapped_column(default=utcnow)
    telemetry_profile: Mapped[str | None] = mapped_column(String(48))
    allowed_message_types: Mapped[list[Any]]
    last_seen_at: Mapped[datetime | None]
    last_authenticated_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    asset: Mapped[Asset] = relationship()


class DeviceCredential(Base):
    """Credential metadata. The key itself is derived at runtime and never stored."""

    __tablename__ = "device_credentials"
    __table_args__ = (
        UniqueConstraint("asset_id", "key_version", name="uq_device_credentials_version"),
        Index(
            "uq_device_credentials_one_active",
            "asset_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        CheckConstraint("key_version >= 1", name="key_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), index=True)
    key_version: Mapped[int] = mapped_column(Integer)
    algorithm: Mapped[str] = mapped_column(String(32), default="HMAC-SHA256")
    fingerprint: Mapped[str] = mapped_column(String(16))
    status: Mapped[CredentialStatus] = mapped_column(enum_column(CredentialStatus, "status"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    retired_at: Mapped[datetime | None]
    retired_reason: Mapped[str | None] = mapped_column(Text)


class DeviceReplayState(Base):
    """Last accepted sequence per device. Row-locked (FOR UPDATE) during ingestion."""

    __tablename__ = "device_replay_state"
    __table_args__ = (CheckConstraint("last_sequence >= 0", name="sequence_non_negative"),)

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(BigInteger, default=0)
    last_message_at: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=utcnow)


class DeviceNonce(Base):
    """Nonces of authenticated, fresh messages (duplicate detection)."""

    __tablename__ = "device_nonces"

    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(index=True)
    telemetry_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("telemetry_events.id", ondelete="SET NULL")
    )


class EnrollmentRequest(Base):
    """A device asking to join. Never trusted until a security admin approves it."""

    __tablename__ = "enrollment_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claimed_device_id: Mapped[str] = mapped_column(String(64))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("assets.id"))
    requested_type: Mapped[str] = mapped_column(String(48))
    source_ref: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]]
    status: Mapped[EnrollmentStatus] = mapped_column(enum_column(EnrollmentStatus, "status"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    decided_at: Mapped[datetime | None]
    decided_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    correlation_id: Mapped[str] = mapped_column(String(36))
    epoch: Mapped[int] = mapped_column(Integer)
