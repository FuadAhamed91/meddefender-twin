"""FastAPI dependencies: services, sessions, authentication, CSRF and role checks.

Authorization is enforced here, on the server, for every sensitive route. Hiding buttons in
the UI is a usability feature only.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.crypto import hash_token
from app.core.errors import AppError, Forbidden
from app.models.enums import ROLE_RANK, ActorType, AuditDecision, UserRole
from app.services.auth import Principal, resolve_session
from app.services.context import AppServices

SESSION_COOKIE = "md_session"
CSRF_COOKIE = "md_csrf"
CSRF_HEADER = "X-CSRF-Token"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def get_services(request: Request) -> AppServices:
    return request.app.state.services


def db_session(services: AppServices = Depends(get_services)) -> Iterator[Session]:
    """Read-only request session (writes go through a UnitOfWork)."""
    with services.session_factory() as session:
        yield session


def correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "")


def get_principal(request: Request, services: AppServices = Depends(get_services)) -> Principal:
    principal = resolve_session(services, request.cookies.get(SESSION_COOKIE))
    if principal is None:
        raise AppError(401, "AUTHENTICATION_REQUIRED", "Sign in to continue.")
    if request.method in UNSAFE_METHODS:
        presented = request.headers.get(CSRF_HEADER, "")
        if not presented or not hmac.compare_digest(
            hash_token(presented), principal.csrf_token_hash
        ):
            raise AppError(403, "CSRF_TOKEN_INVALID", "Missing or invalid CSRF token.")
    return principal


def require_role(minimum: UserRole) -> Callable[..., Principal]:
    def dependency(
        request: Request,
        principal: Principal = Depends(get_principal),
        services: AppServices = Depends(get_services),
    ) -> Principal:
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum]:
            with services.uow(correlation_id(request) or None) as uow:
                uow.audit(
                    actor_type=ActorType.USER,
                    actor_id=principal.username,
                    action="ACCESS_DENIED",
                    target_type="endpoint",
                    target_id=f"{request.method} {request.url.path}"[:64],
                    decision=AuditDecision.DENY,
                    reason=f"Role {principal.role.value} is below required {minimum.value}.",
                    details={"required_role": minimum.value, "role": principal.role.value},
                )
            raise Forbidden(f"This action requires the {minimum.value} role.")
        return principal

    return dependency


viewer = require_role(UserRole.VIEWER)
operator = require_role(UserRole.OPERATOR)
security_admin = require_role(UserRole.SECURITY_ADMIN)
