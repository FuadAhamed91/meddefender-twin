from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, enum_column, utcnow
from app.models.enums import AssetKind, ContainmentState, Criticality


class HospitalZone(Base):
    """A security / network zone. Its bounds describe the matching physical area in the twin."""

    __tablename__ = "hospital_zones"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    vlan_id: Mapped[int] = mapped_column(Integer)
    subnet: Mapped[str] = mapped_column(String(32))
    trust_level: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(16))
    bounds: Mapped[dict[str, Any]]


class Room(Base):
    """A physical room in the twin. Corridors have no area zone."""

    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    area_zone_id: Mapped[str | None] = mapped_column(ForeignKey("hospital_zones.id"))
    kind: Mapped[str] = mapped_column(String(24))
    bounds: Mapped[dict[str, Any]]


class Asset(Base):
    """A modeled asset: physical device/system, network element, or logical service.

    ``network_zone_id`` (security segment) and ``room_id`` (physical location) are
    deliberately independent: a BMS sensor can sit in the ICU while living on the BMS VLAN.
    """

    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("id ~ '^[A-Z0-9][A-Z0-9-]{1,47}$'", name="asset_id_format"),
        CheckConstraint(
            "(is_logical AND room_id IS NULL AND twin_node IS NULL) OR NOT is_logical",
            name="logical_assets_unplaced",
        ),
    )

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128))
    asset_kind: Mapped[AssetKind] = mapped_column(enum_column(AssetKind, "asset_kind"))
    asset_type: Mapped[str] = mapped_column(String(48))
    is_logical: Mapped[bool] = mapped_column(Boolean, default=False)
    network_zone_id: Mapped[str | None] = mapped_column(ForeignKey("hospital_zones.id"), index=True)
    room_id: Mapped[str | None] = mapped_column(ForeignKey("rooms.id"), index=True)
    twin_node: Mapped[str | None] = mapped_column(String(64), unique=True)
    position: Mapped[dict[str, Any] | None]
    label_height: Mapped[float | None] = mapped_column(Float)
    ip_address: Mapped[str | None] = mapped_column(String(45), unique=True)
    criticality: Mapped[Criticality] = mapped_column(enum_column(Criticality, "criticality"))
    description: Mapped[str] = mapped_column(Text, default="")
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    discovered: Mapped[bool] = mapped_column(Boolean, default=False)
    containment_state: Mapped[ContainmentState] = mapped_column(
        enum_column(ContainmentState, "containment_state"), default=ContainmentState.NONE
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    zone: Mapped[HospitalZone | None] = relationship(foreign_keys=[network_zone_id])
    room: Mapped[Room | None] = relationship(foreign_keys=[room_id])
