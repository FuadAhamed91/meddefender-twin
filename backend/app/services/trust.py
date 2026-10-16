"""Device trust-state machine.

Transitions are explicit; anything not listed raises ``InvalidTrustTransition``.

Design notes
* REGISTERED is not trusted for everything: it only means a credential exists. The first
  authentic, fresh, valid message proves key possession and moves it to AUTHENTICATED.
* Failed authentication never changes the *claimed* identity's state; otherwise anyone
  could lock out a real device by sending garbage under its ID.
* Suspicion is cleared only by a human (SUSPICIOUS -> AUTHENTICATED); it never decays
  automatically, so an attacker cannot launder it by sending clean messages.
* Leaving SUSPICIOUS, QUARANTINED or REVOKED through recovery requires re-provisioning (a
  new key version) and returns to REGISTERED, so the device must authenticate again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.models import DeviceIdentity
from app.models.enums import TrustState

T = TrustState

ALLOWED_TRANSITIONS: dict[TrustState, frozenset[TrustState]] = {
    T.UNREGISTERED: frozenset({T.REGISTERED}),
    T.REGISTERED: frozenset({T.AUTHENTICATED, T.SUSPICIOUS, T.QUARANTINED, T.REVOKED, T.OFFLINE}),
    T.AUTHENTICATED: frozenset({T.SUSPICIOUS, T.QUARANTINED, T.REVOKED, T.OFFLINE}),
    T.SUSPICIOUS: frozenset({T.AUTHENTICATED, T.QUARANTINED, T.REVOKED, T.REGISTERED}),
    T.QUARANTINED: frozenset({T.REGISTERED, T.REVOKED}),
    T.REVOKED: frozenset({T.REGISTERED}),
    T.OFFLINE: frozenset({T.AUTHENTICATED, T.SUSPICIOUS, T.QUARANTINED, T.REVOKED}),
}

# States whose messages are refused at the identity check.
REFUSED_STATES = frozenset({T.QUARANTINED, T.REVOKED, T.UNREGISTERED})


class InvalidTrustTransition(ValueError):
    pass


@dataclass(frozen=True)
class TrustChange:
    asset_id: str
    from_state: TrustState
    to_state: TrustState
    reason: str


def can_transition(current: TrustState, target: TrustState) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def transition(
    identity: DeviceIdentity, target: TrustState, reason: str, now: datetime
) -> TrustChange | None:
    """Apply a transition; returns None when already in the target state."""
    current = identity.trust_state
    if current is target:
        return None
    if not can_transition(current, target):
        raise InvalidTrustTransition(
            f"{identity.asset_id}: {current.value} -> {target.value} is not allowed"
        )
    identity.trust_state = target
    identity.trust_reason = reason
    identity.trust_changed_at = now
    return TrustChange(identity.asset_id, current, target, reason)


def mark_suspicious(identity: DeviceIdentity, reason: str, now: datetime) -> TrustChange | None:
    """Raise suspicion if the state machine allows it from the current state."""
    if identity.trust_state in (T.SUSPICIOUS, T.QUARANTINED, T.REVOKED, T.UNREGISTERED):
        return None
    return transition(identity, T.SUSPICIOUS, reason, now)


def mark_authenticated(identity: DeviceIdentity, now: datetime) -> TrustChange | None:
    """Promote after proof of key possession; never clears SUSPICIOUS automatically."""
    identity.last_authenticated_at = now
    if identity.trust_state in (T.REGISTERED, T.OFFLINE):
        return transition(
            identity, T.AUTHENTICATED, "Proved key possession with a fresh, valid message", now
        )
    return None
