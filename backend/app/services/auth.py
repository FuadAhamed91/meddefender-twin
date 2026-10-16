"""Human authentication: argon2id passwords, server-side sessions, CSRF tokens, lockout.

* Session and CSRF tokens are random 256-bit values; only their SHA-256 hashes are stored.
* The session cookie is HttpOnly + SameSite=Strict; the CSRF token is returned to the
  client and must be echoed in ``X-CSRF-Token`` on every state-changing request.
* Unknown users get the same response and a comparable argon2 cost as wrong passwords.
* Consecutive failures lock the account for a configurable period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select

from app.core import crypto
from app.core.errors import AppError
from app.models import User, UserSession
from app.models.enums import ActorType, AuditDecision, UserRole
from app.services.context import AppServices

_HASHER = PasswordHasher()
# Pre-computed hash used to spend comparable time on unknown usernames.
_DUMMY_HASH = _HASHER.hash("meddefender-dummy-password-for-timing")
TOUCH_INTERVAL = timedelta(seconds=60)


@dataclass(frozen=True)
class Principal:
    user_id: int
    username: str
    display_name: str
    role: UserRole
    session_id: int
    csrf_token_hash: str


@dataclass(frozen=True)
class LoginResult:
    principal: Principal
    session_token: str
    csrf_token: str


def login(
    services: AppServices,
    username: str,
    password: str,
    client_ip: str | None,
    user_agent: str | None,
) -> LoginResult:
    settings = services.settings
    with services.uow() as uow:
        user = uow.session.scalars(
            select(User).where(User.username == username).with_for_update()
        ).first()
        now = uow.now
        failure_reason: str | None = None
        if user is None:
            _verify_quietly(_DUMMY_HASH, password)
            failure_reason = "unknown user"
        elif not user.is_active:
            _verify_quietly(_DUMMY_HASH, password)
            failure_reason = "account disabled"
        elif user.locked_until is not None and user.locked_until > now:
            failure_reason = "account locked"
        elif not _verify_quietly(user.password_hash, password):
            user.failed_login_count += 1
            failure_reason = "wrong password"
            if user.failed_login_count >= settings.login_max_failures:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                user.failed_login_count = 0
                failure_reason = "wrong password; account locked"

        if failure_reason is not None:
            uow.audit(
                actor_type=ActorType.USER,
                actor_id=username[:64] or "(empty)",
                action="LOGIN_FAILED",
                target_type="user",
                target_id=username[:64] or "(empty)",
                decision=AuditDecision.FAILURE,
                reason=failure_reason,
                details={"client_ip": client_ip},
            )
            failed = True
        else:
            failed = False
            assert user is not None
            user.failed_login_count = 0
            user.locked_until = None
            user.last_login_at = now
            if _HASHER.check_needs_rehash(user.password_hash):
                user.password_hash = _HASHER.hash(password)
            session_token = crypto.new_token()
            csrf_token = crypto.new_token()
            row = UserSession(
                user_id=user.id,
                token_hash=crypto.hash_token(session_token),
                csrf_token_hash=crypto.hash_token(csrf_token),
                created_at=now,
                expires_at=now + timedelta(minutes=settings.session_ttl_minutes),
                last_seen_at=now,
                client_ip=(client_ip or "")[:64] or None,
                user_agent=(user_agent or "")[:256] or None,
            )
            uow.session.add(row)
            uow.session.flush()
            uow.audit(
                actor_type=ActorType.USER,
                actor_id=user.username,
                action="LOGIN_SUCCEEDED",
                target_type="user",
                target_id=user.username,
                decision=AuditDecision.SUCCESS,
                reason="Password verified; session created.",
                details={"client_ip": client_ip, "session_id": row.id, "role": user.role.value},
            )
            principal = Principal(
                user.id, user.username, user.display_name, user.role, row.id, row.csrf_token_hash
            )
    if failed:
        # Same message for every failure so usernames cannot be enumerated.
        raise AppError(401, "INVALID_CREDENTIALS", "Invalid username or password.")
    return LoginResult(principal, session_token, csrf_token)


def _verify_quietly(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def resolve_session(services: AppServices, token: str | None) -> Principal | None:
    if not token or len(token) > 200:
        return None
    token_hash = crypto.hash_token(token)
    factory = services.session_factory
    now = services.clock.now()
    with factory() as session, session.begin():
        row = session.scalars(
            select(UserSession).where(UserSession.token_hash == token_hash)
        ).first()
        if row is None or row.revoked_at is not None or row.expires_at <= now:
            return None
        idle = timedelta(minutes=services.settings.session_idle_minutes)
        if now - row.last_seen_at > idle:
            row.revoked_at = now
            return None
        user = session.get(User, row.user_id)
        if user is None or not user.is_active:
            return None
        if now - row.last_seen_at > TOUCH_INTERVAL:
            row.last_seen_at = now
        return Principal(
            user.id, user.username, user.display_name, user.role, row.id, row.csrf_token_hash
        )


def logout(services: AppServices, principal: Principal) -> None:
    with services.uow() as uow:
        row = uow.session.get(UserSession, principal.session_id)
        if row is not None and row.revoked_at is None:
            row.revoked_at = uow.now
        uow.audit(
            actor_type=ActorType.USER,
            actor_id=principal.username,
            action="LOGOUT",
            target_type="user",
            target_id=principal.username,
            decision=AuditDecision.SUCCESS,
            reason="Session revoked by user.",
            details={"session_id": principal.session_id},
        )
