"""Security tests for the Electron-main-only file-grant issuer."""

from __future__ import annotations

import os
import time
from pathlib import Path

import httpx
import pytest
from main import BACKEND_SESSION_HEADER, create_app
from routes import internal_grant_routes
from routes.internal_grant_routes import GRANT_ISSUER_HEADER
from services.utility_helpers import (
    FileGrantEligibilityError,
    FILE_GRANT_SECRET_ENV,
    FILE_GRANT_TTL_SECONDS,
    FILE_GRANT_VERSION,
    verify_file_grant,
)
from services.windows_secure_fs import WINDOWS_FILE_GRANT_VERSION

SESSION_SECRET = "session-secret-for-route-tests-32-bytes"
ISSUER_SECRET = "issuer-secret-for-route-tests-32-bytes"
SESSION_HEADERS = {BACKEND_SESSION_HEADER: SESSION_SECRET}
ISSUER_HEADERS = {
    BACKEND_SESSION_HEADER: SESSION_SECRET,
    GRANT_ISSUER_HEADER: ISSUER_SECRET,
}
ISSUE_PATH = "/internal/file-grants/issue"


def make_client(*, issuer_secret: str | None = ISSUER_SECRET):
    app = create_app(
        session_secret=SESSION_SECRET,
        file_grant_secret=issuer_secret,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_renderer_session_alone_cannot_issue_file_grants(tmp_path):
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    async with make_client() as client:
        missing = await client.post(
            ISSUE_PATH,
            headers=SESSION_HEADERS,
            json={"path": str(selected), "access": "read"},
        )
        wrong = await client.post(
            ISSUE_PATH,
            headers={**SESSION_HEADERS, GRANT_ISSUER_HEADER: "x" * 64},
            json={"path": str(selected), "access": "read"},
        )
        wrong_session = await client.post(
            ISSUE_PATH,
            headers={
                BACKEND_SESSION_HEADER: ISSUER_SECRET,
                GRANT_ISSUER_HEADER: ISSUER_SECRET,
            },
            json={"path": str(selected), "access": "read"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert wrong_session.status_code == 401
    assert ISSUER_SECRET not in missing.text + wrong.text + wrong_session.text


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["null", "http://localhost:5173"])
async def test_any_browser_origin_is_rejected_even_with_both_secrets(tmp_path, origin):
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    async with make_client() as client:
        response = await client.post(
            ISSUE_PATH,
            headers={**ISSUER_HEADERS, "Origin": origin},
            json={"path": str(selected), "access": "read"},
        )

    assert response.status_code == 403
    assert "grant" not in response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("configured_secret", [None, "too-short"])
async def test_missing_or_weak_issuer_configuration_fails_closed(
    tmp_path, configured_secret, monkeypatch
):
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    if configured_secret is None:
        monkeypatch.delenv(FILE_GRANT_SECRET_ENV, raising=False)
    async with make_client(issuer_secret=configured_secret) as client:
        response = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": str(selected), "access": "read"},
        )

    assert response.status_code == 503
    assert ISSUER_SECRET not in response.text


@pytest.mark.asyncio
async def test_ineligible_native_path_returns_bounded_actionable_400(
    tmp_path, monkeypatch
):
    selected = tmp_path / "selected.fits"

    def reject_ineligible_path(*_args, **_kwargs):
        raise FileGrantEligibilityError(
            "Windows reparse points, junctions, and symbolic links are not supported"
        )

    monkeypatch.setattr(
        internal_grant_routes,
        "issue_file_grant",
        reject_ineligible_path,
    )
    async with make_client() as client:
        response = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": str(selected), "access": "read"},
        )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail == (
        "Windows reparse points, junctions, and symbolic links are not supported"
    )
    assert len(detail) <= 256
    assert str(selected) not in response.text


@pytest.mark.asyncio
async def test_main_can_issue_and_verify_read_and_write_grants(tmp_path, monkeypatch):
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, ISSUER_SECRET)
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    destination = tmp_path / "export.ecsv"
    before = int(time.time())

    async with make_client() as client:
        read_response = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": str(selected), "access": "read"},
        )
        write_response = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": str(destination), "access": "write"},
        )

    assert read_response.status_code == 200
    assert write_response.status_code == 200
    assert read_response.headers["cache-control"] == "no-store"
    expected_version = (
        WINDOWS_FILE_GRANT_VERSION if os.name == "nt" else FILE_GRANT_VERSION
    )
    for response, path, access, must_exist in (
        (read_response, selected, "read", True),
        (write_response, destination, "write", False),
    ):
        payload = response.json()
        assert Path(payload["path"]) == path.resolve()
        assert payload["grant"].startswith(f"{expected_version}.")
        assert before + FILE_GRANT_TTL_SECONDS <= payload["expires_at"]
        assert payload["expires_at"] <= int(time.time()) + FILE_GRANT_TTL_SECONDS
        assert (
            verify_file_grant(
                payload["path"],
                payload["grant"],
                access=access,
                must_exist=must_exist,
            )
            == path.resolve()
        )


@pytest.mark.asyncio
async def test_issuer_request_is_strict_bounded_and_hidden_from_openapi(tmp_path):
    selected = tmp_path / "selected.fits"
    selected.write_bytes(b"fits")
    async with make_client() as client:
        invalid_access = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": str(selected), "access": "execute"},
        )
        unexpected_field = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": str(selected), "access": "read", "grant": "forged"},
        )
        oversized_path = await client.post(
            ISSUE_PATH,
            headers=ISSUER_HEADERS,
            json={"path": "x" * 4_097, "access": "read"},
        )
        schema = await client.get("/openapi.json", headers=SESSION_HEADERS)

    assert invalid_access.status_code == 422
    assert unexpected_field.status_code == 422
    assert oversized_path.status_code == 422
    assert schema.status_code == 200
    assert ISSUE_PATH not in schema.json()["paths"]
