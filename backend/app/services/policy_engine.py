"""Explainable policy evaluation for network flows and device commands.

Semantics
---------
* Candidate policies are the active, non-disabled policies of the requested type whose
  source selector, destination selector and service/action all match the request.
* Candidates are ordered by ``priority`` (ascending); at equal priority DENY wins, then the
  policy id breaks ties so evaluation is fully deterministic.
* The first candidate decides. If none match, the implicit default is DENY.
* A DENY from a policy in MONITOR mode is reported as ``ALLOWED_MONITOR_ONLY``: the
  traffic is not blocked, but the violation is recorded and alerted.
* For commands, a trust gate runs first: only AUTHENTICATED identities may issue commands.

The engine is pure: it reads policies and asset facts and returns a decision; persisting
the decision is the caller's job. ``extra_policies`` lets the containment planner evaluate
hypothetical policy sets without writing anything.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Asset, DeviceIdentity, SecurityPolicy
from app.models.enums import (
    DecisionOutcome,
    EnforcementMode,
    PolicyEffect,
    PolicyType,
    TrustState,
)

DEFAULT_DENY_ID = "IMPLICIT-DEFAULT-DENY"
TRUST_GATE_ID = "BUILTIN-TRUST-GATE"


@dataclass(frozen=True)
class PolicyView:
    """Immutable snapshot of a policy (ORM rows or hypothetical containment rules)."""

    id: str
    name: str
    policy_type: PolicyType
    source_asset_id: str | None
    source_zone_id: str | None
    destination_asset_id: str | None
    destination_zone_id: str | None
    service_or_action: str
    effect: PolicyEffect
    priority: int
    enforcement_mode: EnforcementMode
    enforcement_point_id: str | None
    origin: str
    rationale: str = ""

    @classmethod
    def from_row(cls, row: SecurityPolicy) -> PolicyView:
        return cls(
            id=row.id,
            name=row.name,
            policy_type=row.policy_type,
            source_asset_id=row.source_asset_id,
            source_zone_id=row.source_zone_id,
            destination_asset_id=row.destination_asset_id,
            destination_zone_id=row.destination_zone_id,
            service_or_action=row.service_or_action,
            effect=row.effect,
            priority=row.priority,
            enforcement_mode=row.enforcement_mode,
            enforcement_point_id=row.enforcement_point_id,
            origin=row.origin.value if hasattr(row.origin, "value") else str(row.origin),
            rationale=row.rationale,
        )

    def describe_source(self) -> str:
        return self.source_asset_id or (
            f"zone {self.source_zone_id}" if self.source_zone_id else "any"
        )

    def describe_destination(self) -> str:
        return self.destination_asset_id or (
            f"zone {self.destination_zone_id}" if self.destination_zone_id else "any"
        )


@dataclass(frozen=True)
class Endpoint:
    """Who/what is on one side of a request. Unknown endpoints have no asset id."""

    ref: str
    asset_id: str | None
    zone_id: str | None


@dataclass
class PolicyEvaluation:
    decision: PolicyEffect
    outcome: DecisionOutcome
    matched_policy_id: str | None
    reason: str
    explanation: dict[str, Any] = field(default_factory=dict)

    @property
    def permitted(self) -> bool:
        return self.outcome is not DecisionOutcome.BLOCKED


def _selector_matches(asset_sel: str | None, zone_sel: str | None, endpoint: Endpoint) -> bool:
    if asset_sel is not None:
        return endpoint.asset_id == asset_sel
    if zone_sel is not None:
        return endpoint.zone_id == zone_sel
    return True


def _service_matches(policy_service: str, requested: str) -> bool:
    # A '*' request (used for "any service" reachability) only matches '*' policies, so a
    # DENY on one specific service never hides other potentially open services.
    if policy_service == "*":
        return True
    return policy_service == requested


def _sort_key(p: PolicyView) -> tuple[int, int, str]:
    return (p.priority, 0 if p.effect is PolicyEffect.DENY else 1, p.id)


class PolicyEngine:
    def __init__(self, policies: Sequence[PolicyView]) -> None:
        self._by_type: dict[PolicyType, list[PolicyView]] = {}
        for policy in policies:
            if policy.enforcement_mode is EnforcementMode.DISABLED:
                continue
            self._by_type.setdefault(policy.policy_type, []).append(policy)
        for items in self._by_type.values():
            items.sort(key=_sort_key)

    # ---- construction ------------------------------------------------------------------

    @classmethod
    def load(cls, session: Session, extra: Iterable[PolicyView] = ()) -> PolicyEngine:
        rows = session.scalars(select(SecurityPolicy).where(SecurityPolicy.is_active.is_(True)))
        return cls([PolicyView.from_row(r) for r in rows] + list(extra))

    # ---- evaluation ----------------------------------------------------------------------

    def evaluate(
        self,
        policy_type: PolicyType,
        source: Endpoint,
        destination: Endpoint,
        service_or_action: str,
    ) -> PolicyEvaluation:
        candidates = [
            p
            for p in self._by_type.get(policy_type, [])
            if _selector_matches(p.source_asset_id, p.source_zone_id, source)
            and _selector_matches(p.destination_asset_id, p.destination_zone_id, destination)
            and _service_matches(p.service_or_action, service_or_action)
        ]
        request = {
            "policy_type": policy_type.value,
            "source": source.ref,
            "source_zone": source.zone_id,
            "destination": destination.ref,
            "destination_zone": destination.zone_id,
            "service_or_action": service_or_action,
        }
        if not candidates:
            return PolicyEvaluation(
                decision=PolicyEffect.DENY,
                outcome=DecisionOutcome.BLOCKED,
                matched_policy_id=None,
                reason=(
                    f"No policy permits {source.ref} -> {destination.ref} "
                    f"({service_or_action}); default deny applies."
                ),
                explanation={
                    "request": request,
                    "matched": None,
                    "shadowed": [],
                    "default": "DENY",
                },
            )

        winner, shadowed = candidates[0], candidates[1:]
        if winner.effect is PolicyEffect.ALLOW:
            outcome = DecisionOutcome.PERMITTED
            verb = "permits"
        elif winner.enforcement_mode is EnforcementMode.MONITOR:
            outcome = DecisionOutcome.ALLOWED_MONITOR_ONLY
            verb = "denies (monitor-only, not blocked)"
        else:
            outcome = DecisionOutcome.BLOCKED
            verb = "denies"
        where = f" at {winner.enforcement_point_id}" if winner.enforcement_point_id else ""
        reason = (
            f"Policy {winner.id} ({winner.name}) {verb} {source.ref} -> {destination.ref} "
            f"({service_or_action}){where}."
        )
        return PolicyEvaluation(
            decision=winner.effect,
            outcome=outcome,
            matched_policy_id=winner.id,
            reason=reason,
            explanation={
                "request": request,
                "matched": _summarise(winner),
                "shadowed": [_summarise(p) for p in shadowed[:5]],
                "shadowed_count": len(shadowed),
            },
        )

    def evaluate_command(
        self,
        source: Endpoint,
        source_trust: TrustState | None,
        destination: Endpoint,
        action: str,
    ) -> PolicyEvaluation:
        if source_trust is not TrustState.AUTHENTICATED:
            state = source_trust.value if source_trust else "UNKNOWN"
            return PolicyEvaluation(
                decision=PolicyEffect.DENY,
                outcome=DecisionOutcome.BLOCKED,
                matched_policy_id=None,
                reason=(
                    f"Trust gate: {source.ref} is {state}; only AUTHENTICATED identities may "
                    "issue commands."
                ),
                explanation={
                    "request": {
                        "policy_type": PolicyType.DEVICE_COMMAND.value,
                        "source": source.ref,
                        "destination": destination.ref,
                        "service_or_action": action,
                    },
                    "matched": {"id": TRUST_GATE_ID, "effect": "DENY", "trust_state": state},
                    "shadowed": [],
                },
            )
        return self.evaluate(PolicyType.DEVICE_COMMAND, source, destination, action)


def _summarise(p: PolicyView) -> dict[str, Any]:
    return {
        "id": p.id,
        "name": p.name,
        "effect": p.effect.value,
        "priority": p.priority,
        "enforcement_mode": p.enforcement_mode.value,
        "enforcement_point": p.enforcement_point_id,
        "source": p.describe_source(),
        "destination": p.describe_destination(),
        "service_or_action": p.service_or_action,
        "origin": p.origin,
    }


def endpoint_for_asset(asset: Asset | None, ref: str | None = None) -> Endpoint:
    if asset is None:
        return Endpoint(ref=ref or "unknown", asset_id=None, zone_id=None)
    return Endpoint(ref=asset.id, asset_id=asset.id, zone_id=asset.network_zone_id)


def trust_of(session: Session, asset_id: str) -> TrustState | None:
    identity = session.get(DeviceIdentity, asset_id)
    return identity.trust_state if identity else None
