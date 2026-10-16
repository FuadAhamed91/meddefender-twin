from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text

from app.api.deps import CSRF_COOKIE, SESSION_COOKIE, get_principal, get_services
from app.models.enums import UserRole
from app.schemas.api import ErrorResponse, LoginRequest, LoginResponse, UserOut
from app.services import auth
from app.services.auth import Principal
from app.services.context import AppServices

router = APIRouter(prefix="/api/v1", tags=["auth"])

ROLE_PERMISSIONS: dict[UserRole, list[str]] = {
    UserRole.VIEWER: ["view"],
    UserRole.OPERATOR: [
        "view",
        "run_scenarios",
        "manage_incidents",
        "propose_containment",
        "apply_containment",
        "execute_recovery",
        "toggle_generator",
        "verify_audit",
    ],
    UserRole.SECURITY_ADMIN: [
        "view",
        "run_scenarios",
        "manage_incidents",
        "propose_containment",
        "apply_containment",
        "execute_recovery",
        "toggle_generator",
        "apply_high_impact_containment",
        "manage_identities",
        "manage_policies",
        "reset_simulation",
        "verify_audit",
    ],
}


def user_out(principal: Principal) -> UserOut:
    return UserOut(
        username=principal.username,
        display_name=principal.display_name,
        role=principal.role.value,
        permissions=ROLE_PERMISSIONS[principal.role],
    )


@router.get("/health", tags=["system"])
def health(services: AppServices = Depends(get_services)) -> dict[str, str]:
    with services.session_factory() as session:
        session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "mode": "simulation"}


@router.post("/auth/login", response_model=LoginResponse, responses={401: {"model": ErrorResponse}})
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    services: AppServices = Depends(get_services),
) -> LoginResponse:
    result = await run_in_threadpool(
        auth.login,
        services,
        body.username,
        body.password,
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
    )
    settings = services.settings
    max_age = settings.session_ttl_minutes * 60
    response.set_cookie(
        SESSION_COOKIE,
        result.session_token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        result.csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return LoginResponse(user=user_out(result.principal), csrf_token=result.csrf_token)


@router.post("/auth/logout", status_code=204, responses={401: {"model": ErrorResponse}})
def logout(
    response: Response,
    principal: Principal = Depends(get_principal),
    services: AppServices = Depends(get_services),
) -> Response:
    auth.logout(services, principal)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/auth/me", response_model=UserOut, responses={401: {"model": ErrorResponse}})
def me(principal: Principal = Depends(get_principal)) -> UserOut:
    return user_out(principal)
