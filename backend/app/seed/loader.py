"""Reproducible baseline seed: zones, rooms, assets, identities, relationships, dependencies,
policies, simulator ground truth and (optionally) demo users."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import Settings
from app.models import (
    Asset,
    DeviceCredential,
    DeviceIdentity,
    DeviceReplayState,
    HospitalZone,
    NetworkRelationship,
    OperationalDependency,
    Room,
    SecurityPolicy,
    SimDevice,
    SimulationState,
    TwinState,
    User,
)
from app.models.enums import (
    AssetKind,
    CredentialStatus,
    EnforcementMode,
    PolicyEffect,
    PolicyOrigin,
    PolicyType,
    RegistrationStatus,
    RelationshipOrigin,
    RelationshipType,
    TrustState,
    UserRole,
)
from app.seed import catalog
from app.services.profiles import DEFAULT_MESSAGE_TYPES
from app.simulator.world import initial_state

BASELINE_PRIORITY = 100
ZONE_DENY_PRIORITY = 50
DEFAULT_DENY_PRIORITY = 1000


def layout_path() -> Path:
    override = os.environ.get("LAYOUT_PATH")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "shared" / "hospital_layout.json"


@lru_cache
def load_layout() -> dict[str, Any]:
    with layout_path().open(encoding="utf-8") as fh:
        return json.load(fh)


def enforcement_point(source: Asset, destination: Asset) -> str:
    if source.network_zone_id == destination.network_zone_id == "ZONE-ICU":
        return "ICU-SWITCH-01"
    if source.network_zone_id == destination.network_zone_id == "ZONE-IMG":
        return "IMG-SWITCH-01"
    return "NET-GW-01"


def flow_policy_id(source: str, destination: str, service: str) -> str:
    return f"NP-{source}-TO-{destination}-{service.upper()}"[:64]


def command_policy_id(source: str, destination: str, action: str) -> str:
    return f"CP-{source}-TO-{destination}-{action.upper().replace('_', '-')}"[:64]


def seed_baseline(session: Session, settings: Settings) -> dict[str, int]:
    """Insert the baseline. Assumes an empty database (see ``is_seeded``)."""
    layout = load_layout()

    for zone in layout["zones"]:
        session.add(
            HospitalZone(
                id=zone["id"],
                name=zone["name"],
                description=zone["description"],
                vlan_id=zone["vlan_id"],
                subnet=zone["subnet"],
                trust_level=zone["trust_level"],
                color=zone["color"],
                bounds=zone["bounds"],
            )
        )
    session.flush()
    for room in layout["rooms"]:
        session.add(
            Room(
                id=room["id"],
                name=room["name"],
                area_zone_id=room["area_zone"],
                kind=room["kind"],
                bounds=room["bounds"],
            )
        )
    session.flush()

    assets: dict[str, Asset] = {}
    for item in layout["assets"]:
        criticality, description = catalog.ASSET_DETAILS[item["id"]]
        asset = Asset(
            id=item["id"],
            display_name=item["name"],
            asset_kind=AssetKind(item["kind"]),
            asset_type=item["type"],
            is_logical=False,
            network_zone_id=item["network_zone"],
            room_id=item["room"],
            twin_node=f"AST_{item['id']}",
            position={
                "x": item["position"][0],
                "y": item["position"][1],
                "rotation": item["rotation"],
            },
            label_height=item["label_height"],
            ip_address=item["ip"],
            criticality=criticality,
            description=description,
        )
        session.add(asset)
        assets[asset.id] = asset
    for service_id, name, criticality, description in catalog.LOGICAL_SERVICES:
        asset = Asset(
            id=service_id,
            display_name=name,
            asset_kind=AssetKind.CLINICAL_SERVICE,
            asset_type="logical_service",
            is_logical=True,
            criticality=criticality,
            description=description,
        )
        session.add(asset)
        assets[asset.id] = asset
    session.flush()

    master = settings.master_secret_bytes
    for asset_id, profile in catalog.IDENTITY_PROFILES.items():
        key = crypto.derive_device_key(master, asset_id, 1)
        session.add(
            DeviceIdentity(
                asset_id=asset_id,
                registration_status=RegistrationStatus.REGISTERED,
                trust_state=TrustState.REGISTERED,
                trust_reason="Provisioned in baseline; not yet authenticated.",
                telemetry_profile=profile,
                allowed_message_types=[t.value for t in DEFAULT_MESSAGE_TYPES[profile]],
            )
        )
        session.add(
            DeviceCredential(
                asset_id=asset_id,
                key_version=1,
                fingerprint=crypto.key_fingerprint(key),
                status=CredentialStatus.ACTIVE,
            )
        )
        session.add(DeviceReplayState(asset_id=asset_id, last_sequence=0))
        session.add(
            SimDevice(
                asset_id=asset_id,
                next_sequence=1,
                key_version=1,
                physical_state=initial_state(asset_id, profile),
            )
        )
    for asset_id in assets:
        session.add(TwinState(asset_id=asset_id, version=0))
    session.flush()

    relationships: dict[tuple[str, str, str], NetworkRelationship] = {}
    for flow in catalog.BASELINE_FLOWS:
        rel = NetworkRelationship(
            source_asset_id=flow.source,
            destination_asset_id=flow.destination,
            relationship_type=flow.kind,
            service=flow.service,
            protocol_label=flow.protocol,
            port=flow.port,
            origin=RelationshipOrigin.BASELINE,
            description=flow.description,
        )
        session.add(rel)
        relationships[(flow.source, flow.destination, flow.service)] = rel
        src, dst = assets[flow.source], assets[flow.destination]
        session.add(
            SecurityPolicy(
                id=flow_policy_id(flow.source, flow.destination, flow.service),
                name=f"Allow {flow.source} -> {flow.destination} ({flow.service})",
                description=flow.description,
                rationale=f"Required for: {flow.description}.",
                policy_type=PolicyType.NETWORK_FLOW,
                source_asset_id=flow.source,
                destination_asset_id=flow.destination,
                service_or_action=flow.service,
                effect=PolicyEffect.ALLOW,
                priority=BASELINE_PRIORITY,
                enforcement_mode=EnforcementMode.ENFORCED,
                enforcement_point_id=enforcement_point(src, dst),
                origin=PolicyOrigin.BASELINE,
            )
        )
    for src_id, dst_id in catalog.L2_UPLINKS:
        session.add(
            NetworkRelationship(
                source_asset_id=src_id,
                destination_asset_id=dst_id,
                relationship_type=RelationshipType.L2_UPLINK,
                service="link",
                protocol_label="Layer-2 uplink (topology only; not a permission)",
                port=None,
                origin=RelationshipOrigin.BASELINE,
                description="Physical/L2 attachment. Does not imply any permitted communication.",
            )
        )
    for policy_id, src_zone, dst_zone, rationale in catalog.ZONE_DENIES:
        session.add(
            SecurityPolicy(
                id=policy_id,
                name=f"Deny {src_zone} -> {dst_zone}",
                description=rationale,
                rationale=rationale,
                policy_type=PolicyType.NETWORK_FLOW,
                source_zone_id=src_zone,
                destination_zone_id=dst_zone,
                service_or_action="*",
                effect=PolicyEffect.DENY,
                priority=ZONE_DENY_PRIORITY,
                enforcement_mode=EnforcementMode.ENFORCED,
                enforcement_point_id="NET-GW-01",
                origin=PolicyOrigin.BASELINE,
            )
        )
    session.add(
        SecurityPolicy(
            id="NP-DEFAULT-DENY",
            name="Default deny (network)",
            description="Anything not explicitly allowed is denied.",
            rationale="Least privilege.",
            policy_type=PolicyType.NETWORK_FLOW,
            service_or_action="*",
            effect=PolicyEffect.DENY,
            priority=DEFAULT_DENY_PRIORITY,
            enforcement_mode=EnforcementMode.ENFORCED,
            enforcement_point_id="NET-GW-01",
            origin=PolicyOrigin.BASELINE,
        )
    )
    for src_id, dst_id, action, rationale in catalog.COMMAND_ALLOWS:
        session.add(
            SecurityPolicy(
                id=command_policy_id(src_id, dst_id, action),
                name=f"Allow {src_id} to {action} on {dst_id}",
                description=rationale,
                rationale=rationale,
                policy_type=PolicyType.DEVICE_COMMAND,
                source_asset_id=src_id,
                destination_asset_id=dst_id,
                service_or_action=action,
                effect=PolicyEffect.ALLOW,
                priority=BASELINE_PRIORITY,
                enforcement_mode=EnforcementMode.ENFORCED,
                enforcement_point_id=None,
                origin=PolicyOrigin.BASELINE,
            )
        )
    session.add(
        SecurityPolicy(
            id="CP-DEFAULT-DENY",
            name="Default deny (commands)",
            description="Commands not explicitly allowed are refused by the command broker.",
            rationale="Least privilege.",
            policy_type=PolicyType.DEVICE_COMMAND,
            service_or_action="*",
            effect=PolicyEffect.DENY,
            priority=DEFAULT_DENY_PRIORITY,
            enforcement_mode=EnforcementMode.ENFORCED,
            enforcement_point_id=None,
            origin=PolicyOrigin.BASELINE,
        )
    )
    session.flush()

    for (
        dependent,
        provider,
        dep_type,
        criticality,
        description,
        carried,
    ) in catalog.BASELINE_DEPENDENCIES:
        session.add(
            OperationalDependency(
                dependent_asset_id=dependent,
                provider_asset_id=provider,
                dependency_type=dep_type,
                criticality=criticality,
                description=description,
                carried_by_relationship_id=relationships[carried].id if carried else None,
            )
        )
    session.add(
        SimulationState(id=1, epoch=1, generator_enabled=settings.generator_enabled, tick_count=0)
    )
    session.flush()

    users = seed_demo_users(session, settings)
    return {
        "zones": len(layout["zones"]),
        "rooms": len(layout["rooms"]),
        "assets": len(assets),
        "identities": len(catalog.IDENTITY_PROFILES),
        "flows": len(catalog.BASELINE_FLOWS),
        "dependencies": len(catalog.BASELINE_DEPENDENCIES),
        "users": users,
    }


DEMO_USERS = (
    ("viewer", "Demo Viewer", UserRole.VIEWER, "demo_password_viewer"),
    ("operator", "Demo Operator", UserRole.OPERATOR, "demo_password_operator"),
    ("secadmin", "Demo Security Admin", UserRole.SECURITY_ADMIN, "demo_password_admin"),
)


def seed_demo_users(session: Session, settings: Settings) -> int:
    hasher = PasswordHasher()
    created = 0
    for username, display_name, role, setting_name in DEMO_USERS:
        secret = getattr(settings, setting_name)
        if secret is None:
            continue
        password = secret.get_secret_value()
        if len(password) < 12:
            raise ValueError(f"{setting_name.upper()} must be at least 12 characters")
        if session.scalars(select(User).where(User.username == username)).first():
            continue
        session.add(
            User(
                username=username,
                display_name=display_name,
                role=role,
                password_hash=hasher.hash(password),
            )
        )
        created += 1
    session.flush()
    return created


def is_seeded(session: Session) -> bool:
    return session.get(SimulationState, 1) is not None
