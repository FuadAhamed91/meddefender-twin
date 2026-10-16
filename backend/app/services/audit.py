"""Append-only, hash-chained audit trail.

Each entry's hash covers its content and the previous entry's hash. Appends take a
transaction-scoped advisory lock so the chain order equals id order even under concurrency.
``verify_chain`` recomputes every hash and reports the first break.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.models.enums import ActorType, AuditDecision

GENESIS_HASH = "0" * 64
AUDIT_CHAIN_LOCK_KEY = 0x4D44_4155  # "MDAU"


@dataclass
class AuditRecord:
    occurred_at: datetime
    actor_type: ActorType
    actor_id: str
    action: str
    target_type: str
    target_id: str
    decision: AuditDecision
    reason: str
    correlation_id: str
    epoch: int
    details: dict[str, Any] = field(default_factory=dict)
    incident_id: int | None = None
    simulation_run_id: int | None = None


def _hash_material(fields: dict[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def hashed_fields(
    *,
    occurred_at: datetime,
    actor_type: str,
    actor_id: str,
    action: str,
    target_type: str,
    target_id: str,
    decision: str,
    reason: str,
    correlation_id: str,
    incident_id: int | None,
    simulation_run_id: int | None,
    details: dict[str, Any],
    epoch: int,
) -> dict[str, Any]:
    return {
        "occurred_at": occurred_at.isoformat(timespec="microseconds"),
        "actor_type": actor_type,
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "decision": decision,
        "reason": reason,
        "correlation_id": correlation_id,
        "incident_id": incident_id,
        "simulation_run_id": simulation_run_id,
        "details": details,
        "epoch": epoch,
    }


def compute_entry_hash(prev_hash: str, fields: dict[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + b"|" + _hash_material(fields)).hexdigest()


def append(session: Session, records: list[AuditRecord]) -> list[AuditEvent]:
    """Append records to the chain inside the caller's transaction."""
    if not records:
        return []
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": AUDIT_CHAIN_LOCK_KEY})
    prev = (
        session.scalar(select(AuditEvent.entry_hash).order_by(AuditEvent.id.desc()).limit(1))
        or GENESIS_HASH
    )
    rows: list[AuditEvent] = []
    for rec in records:
        # Round-trip details through JSON so the hashed form equals what JSONB stores.
        details = json.loads(json.dumps(rec.details, default=str))
        fields = hashed_fields(
            occurred_at=rec.occurred_at,
            actor_type=rec.actor_type.value,
            actor_id=rec.actor_id,
            action=rec.action,
            target_type=rec.target_type,
            target_id=rec.target_id,
            decision=rec.decision.value,
            reason=rec.reason,
            correlation_id=rec.correlation_id,
            incident_id=rec.incident_id,
            simulation_run_id=rec.simulation_run_id,
            details=details,
            epoch=rec.epoch,
        )
        entry_hash = compute_entry_hash(prev, fields)
        row = AuditEvent(
            occurred_at=rec.occurred_at,
            actor_type=rec.actor_type,
            actor_id=rec.actor_id,
            action=rec.action,
            target_type=rec.target_type,
            target_id=rec.target_id,
            decision=rec.decision,
            reason=rec.reason,
            correlation_id=rec.correlation_id,
            incident_id=rec.incident_id,
            simulation_run_id=rec.simulation_run_id,
            details=details,
            epoch=rec.epoch,
            prev_hash=prev,
            entry_hash=entry_hash,
        )
        session.add(row)
        rows.append(row)
        prev = entry_hash
    session.flush()
    return rows


@dataclass
class ChainVerification:
    valid: bool
    checked: int
    first_invalid_id: int | None = None
    problem: str | None = None
    head_hash: str | None = None


def verify_chain(session: Session, batch_size: int = 2000) -> ChainVerification:
    prev = GENESIS_HASH
    checked = 0
    last_id = 0
    while True:
        rows = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.id > last_id)
            .order_by(AuditEvent.id)
            .limit(batch_size)
        ).all()
        if not rows:
            break
        for row in rows:
            if row.prev_hash != prev:
                return ChainVerification(
                    False, checked, row.id, "prev_hash does not match predecessor"
                )
            fields = hashed_fields(
                occurred_at=row.occurred_at,
                actor_type=row.actor_type.value,
                actor_id=row.actor_id,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                decision=row.decision.value,
                reason=row.reason,
                correlation_id=row.correlation_id,
                incident_id=row.incident_id,
                simulation_run_id=row.simulation_run_id,
                details=row.details,
                epoch=row.epoch,
            )
            if compute_entry_hash(prev, fields) != row.entry_hash:
                return ChainVerification(
                    False, checked, row.id, "entry content does not match its hash"
                )
            prev = row.entry_hash
            checked += 1
            last_id = row.id
    return ChainVerification(True, checked, head_hash=prev if checked else None)
