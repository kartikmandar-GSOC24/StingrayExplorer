"""Verify analysis routes run blocking work off the event loop.

A handler that calls the synchronous service directly blocks the loop, so a
concurrent asyncio.sleep cannot complete on time. With asyncio.to_thread, the
sleep returns at the expected time while the slow computation runs in a thread.
"""

import asyncio
import time

import httpx
import pytest

from services.state_manager import StateManager
from tests.backend_auth import (
    TEST_BACKEND_AUTH_HEADERS,
    TEST_BACKEND_SESSION_SECRET,
)
from utils.performance_monitor import PerformanceMonitor


@pytest.mark.asyncio
async def test_lightcurve_create_does_not_block_event_loop(monkeypatch):
    import services.lightcurve_service as lcs_mod
    from main import create_app

    def slow_create(self, **kwargs):
        time.sleep(0.6)
        return {"success": True, "data": None, "message": "ok", "error": None}

    monkeypatch.setattr(
        lcs_mod.LightcurveService, "create_lightcurve_from_event_list", slow_create
    )

    app = create_app(session_secret=TEST_BACKEND_SESSION_SECRET)
    # ASGITransport does not run the lifespan; provide state manually.
    app.state.state_manager = StateManager()
    app.state.performance_monitor = PerformanceMonitor()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        headers=TEST_BACKEND_AUTH_HEADERS,
    ) as client:
        slow_task = asyncio.create_task(
            client.post(
                "/api/lightcurve/from-event-list",
                json={"event_list_name": "x", "dt": 0.1, "output_name": "y"},
            )
        )
        # Start the clock before the first yield so the measurement captures
        # the block wherever the first scheduler checkpoint lands.
        t0 = time.monotonic()
        # Yield control so the slow task can start executing.
        await asyncio.sleep(0)

        # Measure how long the yield plus a 0.05s sleep actually take.
        # If the event loop is blocked by the sync service call, control
        # cannot return until the blocking work finishes (~0.6s later), so
        # the measured duration will be ~0.65s instead of ~0.05s.
        await asyncio.sleep(0.05)
        elapsed = time.monotonic() - t0

        probe = await client.get("/")
        slow_response = await slow_task

        assert probe.status_code == 200
        assert slow_response.status_code == 200
        # Without to_thread the sleep is delayed ~0.55s by the blocked loop.
        assert elapsed < 0.4, f"event loop was blocked for {elapsed:.2f}s"
