"""Registered-app smoke coverage for every Utilities category."""

import json
import math

import httpx
import pytest
from fastapi.responses import StreamingResponse

from main import (
    MAX_REQUEST_BODY_BYTES,
    MAX_SERIALIZED_VALIDATION_ERRORS,
    RequestBodyLimitMiddleware,
    create_app,
)
from services.state_manager import StateManager


class _ChunkedBody(httpx.AsyncByteStream):
    """Stream a body without giving HTTPX a Content-Length value."""

    def __init__(self, size: int, chunk_size: int = 64 * 1024) -> None:
        self.size = size
        self.chunk_size = chunk_size

    async def __aiter__(self):
        remaining = self.size
        while remaining:
            size = min(remaining, self.chunk_size)
            yield b"x" * size
            remaining -= size


def _strict_json(response: httpx.Response):
    def reject_constant(value: str):
        raise AssertionError(f"Non-standard JSON constant in response: {value}")

    return json.loads(response.content, parse_constant=reject_constant)


@pytest.mark.asyncio
async def test_registered_utility_routes_execute_representative_operations():
    app = create_app()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = {
            "statistics": await client.post(
                "/api/utilities/statistics/gaussian",
                json={
                    "probability": 0.15865525393145707,
                    "sidedness": "one-sided",
                },
            ),
            "gti": await client.post(
                "/api/utilities/gti/validate",
                json={
                    "gtis": [[0.0, 2.0], [3.0, 5.0]],
                    "time_reference": "relative_seconds",
                },
            ),
            "io": await client.get("/api/utilities/io/exportable-objects"),
            "mission_io": await client.get("/api/utilities/mission-io/capabilities"),
            "misc": await client.post(
                "/api/utilities/misc/window",
                json={"n_samples": 8, "window_type": "hamming"},
            ),
        }

    for category, response in responses.items():
        assert response.status_code == 200, (category, response.text)
        payload = response.json()
        assert set(("success", "data", "message", "error")) <= payload.keys()
        assert payload["success"] is True, (category, payload)

    assert math.isclose(responses["statistics"].json()["data"]["sigma"], 1.0)
    assert responses["gti"].json()["data"]["interval_count"] == 2
    assert responses["io"].json()["data"]["objects"] == []
    assert responses["mission_io"].json()["data"]["mission_count"] > 0
    assert len(responses["misc"].json()["data"]["window"]) == 8


@pytest.mark.asyncio
async def test_nonfinite_request_validation_is_itself_strict_json():
    app = create_app()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/utilities/statistics/gaussian",
            content='{"probability":NaN,"sidedness":"one-sided"}',
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 422
    payload = _strict_json(response)
    assert payload["detail"][0]["input"] is None
    assert "finite number" in payload["detail"][0]["msg"]


@pytest.mark.asyncio
@pytest.mark.parametrize("length_header", ["honest", "misleading", "missing"])
async def test_request_body_limit_rejects_declared_and_streamed_oversize_bodies(
    length_header,
):
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    oversized = MAX_REQUEST_BODY_BYTES + 1
    headers = {"content-type": "application/json"}

    if length_header == "missing":
        content = _ChunkedBody(oversized)
    else:
        content = b"x" * oversized
        if length_header == "misleading":
            headers["content-length"] = "1"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/utilities/statistics/gaussian",
            content=content,
            headers=headers,
        )

    assert response.status_code == 413
    assert _strict_json(response) == {"detail": "Request body exceeds the 8 MiB limit"}


@pytest.mark.asyncio
async def test_request_body_limit_preserves_streaming_responses():
    async def streaming_app(scope, receive, send):
        async def chunks():
            yield b"first\n"
            yield b"second\n"

        response = StreamingResponse(chunks(), media_type="text/plain")
        await response(scope, receive, send)

    app = RequestBodyLimitMiddleware(streaming_app, MAX_REQUEST_BODY_BYTES)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.text == "first\nsecond\n"


@pytest.mark.asyncio
async def test_validation_response_does_not_echo_large_rejected_input():
    app = create_app()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/utilities/statistics/gaussian",
            json={"probability": 0.5, "sidedness": "x" * 1_000_000},
        )

    assert response.status_code == 422
    assert len(response.content) < 4_096
    payload = _strict_json(response)
    assert payload["detail"][0]["input"] is None
    assert "x" * 1_000 not in response.text


@pytest.mark.asyncio
async def test_validation_response_caps_the_number_of_serialized_errors():
    app = create_app()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    transport = httpx.ASGITransport(app=app)
    invalid_values = [False] * (MAX_SERIALIZED_VALIDATION_ERRORS + 25)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/utilities/misc/rebin/linear",
            json={"x": invalid_values, "y": invalid_values, "dx_new": 1.0},
        )

    assert response.status_code == 422
    payload = _strict_json(response)
    assert len(payload["detail"]) == MAX_SERIALIZED_VALIDATION_ERRORS + 1
    assert payload["detail"][-1]["type"] == "validation_errors_omitted"
    assert all(error["input"] is None for error in payload["detail"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload"),
    [
        (
            "/api/utilities/gti/validate",
            {"gtis": [[False, 2.0]], "time_reference": "relative_seconds"},
        ),
        (
            "/api/utilities/gti/validate",
            {"gtis": [["0", 2.0]], "time_reference": "relative_seconds"},
        ),
        (
            "/api/utilities/io/convert-pi",
            {"rmf_path": "/tmp/test.rmf", "rmf_grant": "grant", "pi_values": [True]},
        ),
        (
            "/api/utilities/io/convert-pi",
            {"rmf_path": "/tmp/test.rmf", "rmf_grant": "grant", "pi_values": ["2"]},
        ),
        (
            "/api/utilities/mission-io/convert-pi",
            {"pi_values": [True], "mission_override": "NICER"},
        ),
        (
            "/api/utilities/mission-io/convert-pi",
            {"pi_values": [2.0], "mission_override": "NICER", "epoch_mjd": "50000"},
        ),
    ],
)
async def test_utility_request_models_reject_coercion_dependent_values(path, payload):
    app = create_app()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(path, json=payload)

    assert response.status_code == 422
