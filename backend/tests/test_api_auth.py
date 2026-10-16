"""Authentication, sessions, CSRF and role-based access control (acceptance #14, #17)."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditEvent
from tests.conftest import PASSWORDS, login


def test_login_sets_httponly_session_and_returns_role(client):
    response = client.post(
        "/api/v1/auth/login", json={"username": "operator", "password": PASSWORDS["operator"]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["role"] == "OPERATOR"
    assert "run_scenarios" in body["user"]["permissions"]
    cookie_header = "; ".join(response.headers.get_list("set-cookie"))
    assert "md_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "samesite=strict" in cookie_header.lower()
    assert client.get("/api/v1/auth/me").json()["username"] == "operator"


def test_failed_logins_are_indistinguishable(client):
    wrong = client.post(
        "/api/v1/auth/login", json={"username": "operator", "password": "not-the-password"}
    )
    unknown = client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "whatever-123"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]


def test_account_locks_after_repeated_failures(client, services):
    for _ in range(services.settings.login_max_failures):
        client.post(
            "/api/v1/auth/login", json={"username": "viewer", "password": "wrong-password-1"}
        )
    locked = client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": PASSWORDS["viewer"]}
    )
    assert locked.status_code == 401
    with services.session_factory() as s:
        reasons = [
            a.reason
            for a in s.scalars(select(AuditEvent).where(AuditEvent.action == "LOGIN_FAILED"))
        ]
    assert any("locked" in r for r in reasons)


def test_unauthenticated_requests_are_rejected(client):
    for path in ("/api/v1/assets", "/api/v1/incidents", "/api/v1/audit", "/api/v1/twin/state"):
        response = client.get(path)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_state_changing_requests_require_csrf_token(client):
    login(client, "operator")
    response = client.post("/api/v1/scenarios/A/run", json={})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_TOKEN_INVALID"


def test_viewer_cannot_run_scenarios_and_denial_is_audited(client, services):
    headers = login(client, "viewer")
    response = client.post("/api/v1/scenarios/A/run", json={}, headers=headers)
    assert response.status_code == 403
    with services.session_factory() as s:
        denied = s.scalars(select(AuditEvent).where(AuditEvent.action == "ACCESS_DENIED")).one()
        assert denied.actor_id == "viewer"
        assert denied.decision.value == "DENY"


def test_operator_cannot_reset_or_manage_identities_or_policies(client):
    headers = login(client, "operator")
    assert (
        client.post(
            "/api/v1/simulation/reset", json={"reason": "try it"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/devices/ICU-MONITOR-01/revoke", json={"reason": "try it"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/api/v1/policies/NP-DEFAULT-DENY",
            json={"enforcement_mode": "MONITOR", "reason": "try it"},
            headers=headers,
        ).status_code
        == 403
    )


def test_security_admin_can_manage_identities(client):
    headers = login(client, "secadmin")
    response = client.post(
        "/api/v1/devices/ICU-PUMP-01/revoke", json={"reason": "test revoke"}, headers=headers
    )
    assert response.status_code == 200
    assert response.json()["trust_state"] == "REVOKED"


def test_invalid_input_returns_structured_error_without_echoing_values(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "", "password": "s3cret-value-123", "extra": 1},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "s3cret-value-123" not in response.text
    headers = login(client, "operator")
    bad = client.post(
        "/api/v1/incidents/1/transition",
        json={"target_status": "EXPLODED", "note": "x"},
        headers=headers,
    )
    assert bad.status_code == 422
    missing = client.get("/api/v1/assets/NOT-A-REAL-ASSET")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


def test_logout_revokes_session(client):
    headers = login(client, "viewer")
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_security_headers_present(client):
    response = client.get("/api/v1/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "X-Correlation-ID" in response.headers
