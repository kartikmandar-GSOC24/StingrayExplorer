"""Security-boundary tests for the loopback FastAPI application."""

import httpx
import pytest

from main import BACKEND_SESSION_HEADER, create_app


SESSION_SECRET = "a" * 64
AUTH_HEADERS = {BACKEND_SESSION_HEADER: SESSION_SECRET}
DEV_ORIGIN = "http://localhost:5173"


def make_client(*, session_secret: str | None = SESSION_SECRET):
    app = create_app(session_secret=session_secret)
    return app, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_health_is_public_and_exposes_no_application_state():
    _app, client = make_client()
    async with client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "stingray-explorer-backend",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("endpoint", "method"),
    [
        ("/", "GET"),
        ("/api/status", "GET"),
        ("/api/shutdown", "POST"),
        ("/api/logs/status", "GET"),
        ("/api/logs/stream", "GET"),
        ("/api/jobs/stream", "GET"),
    ],
)
async def test_privileged_routes_reject_missing_session(endpoint, method):
    _app, client = make_client()
    async with client:
        response = await client.request(method, endpoint)

    assert response.status_code == 401
    assert SESSION_SECRET not in response.text


@pytest.mark.asyncio
async def test_status_accepts_the_per_launch_session_from_electron_main():
    _app, client = make_client()
    async with client:
        response = await client.get("/api/status", headers=AUTH_HEADERS)

    assert response.status_code == 200
    assert "backend_resources" in response.json()
    assert SESSION_SECRET not in response.text


@pytest.mark.asyncio
async def test_wrong_origin_and_wrong_session_fail_before_route_execution():
    app, client = make_client()
    executions = 0

    @app.post("/api/security-test-marker")
    async def marker():
        nonlocal executions
        executions += 1
        return {"executed": True}

    async with client:
        wrong_origin = await client.post(
            "/api/security-test-marker",
            headers={**AUTH_HEADERS, "Origin": "https://attacker.example"},
        )
        wrong_session = await client.post(
            "/api/security-test-marker",
            headers={BACKEND_SESSION_HEADER: "b" * 64, "Origin": DEV_ORIGIN},
        )

    assert wrong_origin.status_code == 403
    assert wrong_session.status_code == 401
    assert executions == 0


@pytest.mark.asyncio
async def test_packaged_null_origin_requires_the_session_credential():
    _app, client = make_client()
    async with client:
        unauthorized = await client.get("/api/status", headers={"Origin": "null"})
        authorized = await client.get(
            "/api/status", headers={**AUTH_HEADERS, "Origin": "null"}
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


@pytest.mark.asyncio
async def test_missing_backend_session_configuration_fails_closed():
    _app, client = make_client(session_secret="")
    async with client:
        response = await client.get("/api/status", headers=AUTH_HEADERS)

    assert response.status_code == 503
    assert SESSION_SECRET not in response.text


@pytest.mark.asyncio
async def test_allowed_preflight_is_explicit_and_needs_no_secret():
    _app, client = make_client()
    async with client:
        response = await client.options(
            "/api/status",
            headers={
                "Origin": DEV_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": ("content-type,x-stingray-session"),
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == DEV_ORIGIN
    assert "POST" in response.headers["access-control-allow-methods"]
    assert (
        "x-stingray-session" in response.headers["access-control-allow-headers"].lower()
    )
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        },
        {
            "Origin": DEV_ORIGIN,
            "Access-Control-Request-Method": "PUT",
        },
        {
            "Origin": DEV_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization",
        },
    ],
)
async def test_disallowed_preflights_are_rejected(headers):
    _app, client = make_client()
    async with client:
        response = await client.options("/api/status", headers=headers)

    assert response.status_code == 400
