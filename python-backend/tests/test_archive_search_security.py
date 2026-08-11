"""Security regressions for bounded off-loop HEASARC searches."""

from __future__ import annotations

import asyncio
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
import requests
import routes.archive_routes as route_module
import services.archive_service as archive_module
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table
from routes.archive_routes import (
    SearchByCoordinatesRequest,
    SearchByNameRequest,
    SearchByObsidRequest,
    search_by_coordinates,
    search_by_name,
    search_by_obsid,
)
from services.archive_service import (
    ARCHIVE_SEARCH_CONNECT_TIMEOUT_SECONDS,
    ARCHIVE_SEARCH_READ_TIMEOUT_SECONDS,
    MAX_ARCHIVE_OBSID_REMOTE_ROWS,
    MAX_ARCHIVE_SEARCH_REMOTE_ROWS,
    ArchiveSearchSession,
    ArchiveService,
)


class RecordingHeasarc:
    def __init__(self) -> None:
        self.region_calls: list[dict[str, object]] = []
        self.tap_calls: list[dict[str, object]] = []

    def query_region(self, position, **kwargs):
        self.region_calls.append({"position": position, **kwargs})
        return Table()

    def query_tap(self, query, **kwargs):
        self.tap_calls.append({"query": query, **kwargs})
        return SimpleNamespace(to_table=lambda: Table())


def install_heasarc_recorder(monkeypatch):
    recorder = RecordingHeasarc()

    @contextmanager
    def open_client():
        yield recorder

    monkeypatch.setattr(archive_module, "_open_heasarc_client", open_client)
    return recorder


def result_envelope(message: str = "finished") -> dict[str, object]:
    return {
        "success": True,
        "data": {"observations": []},
        "message": message,
        "error": None,
    }


class RouteSearchService:
    def __init__(self, operation) -> None:
        self.operation = operation
        self.calls = 0

    def create_result(self, success, data=None, message="", error=None, **kwargs):
        return {
            "success": success,
            "data": data,
            "message": message,
            "error": error,
            **kwargs,
        }

    def search_by_name(self, **_kwargs):
        self.calls += 1
        return self.operation()

    def search_by_coordinates(self, **_kwargs):
        self.calls += 1
        return self.operation()

    def search_by_obsid(self, **_kwargs):
        self.calls += 1
        return self.operation()


def coordinate_request() -> SearchByCoordinatesRequest:
    return SearchByCoordinatesRequest(
        ra=83.633,
        dec=22.0145,
        mission="NICER",
    )


def test_archive_searches_pass_finite_remote_row_bounds(
    state_manager,
    monkeypatch,
):
    recorder = install_heasarc_recorder(monkeypatch)
    service = ArchiveService(state_manager)
    monkeypatch.setattr(
        service,
        "_resolve_source_name",
        lambda _source: SkyCoord(83.633 * u.deg, 22.0145 * u.deg),
    )

    name_result = service.search_by_name("Crab", "NICER", max_results=100)
    coordinate_result = service.search_by_coordinates(
        83.633,
        22.0145,
        "NICER",
        max_results=100,
    )
    obsid_result = service.search_by_obsid("4010080142", "NICER")

    assert name_result["success"] is True
    assert coordinate_result["success"] is True
    assert obsid_result["success"] is True
    assert len(recorder.region_calls) == 2
    assert all(
        call["columns"] == "*"
        and isinstance(call["maxrec"], int)
        and 0 < call["maxrec"] <= MAX_ARCHIVE_SEARCH_REMOTE_ROWS
        for call in recorder.region_calls
    )
    assert recorder.tap_calls == [
        {
            "query": "SELECT * FROM nicermastr WHERE obsid = '4010080142'",
            "maxrec": MAX_ARCHIVE_OBSID_REMOTE_ROWS,
        }
    ]


def test_archive_search_session_injects_and_preserves_timeouts(monkeypatch):
    captured: list[object] = []

    def fake_request(_session, _method, _url, **kwargs):
        captured.append(kwargs.get("timeout"))
        return SimpleNamespace()

    monkeypatch.setattr(requests.Session, "request", fake_request)
    session = ArchiveSearchSession()
    try:
        session.request("GET", "https://heasarc.gsfc.nasa.gov/xamin/vo/tap")
        session.request(
            "GET",
            "https://heasarc.gsfc.nasa.gov/xamin/vo/tap",
            timeout=(1.0, 2.0),
        )
    finally:
        session.close()

    assert captured == [
        (
            ARCHIVE_SEARCH_CONNECT_TIMEOUT_SECONDS,
            ARCHIVE_SEARCH_READ_TIMEOUT_SECONDS,
        ),
        (1.0, 2.0),
    ]


def test_real_heasarc_factory_installs_bounded_session_without_network():
    with archive_module._open_heasarc_client() as client:
        assert isinstance(client._session, ArchiveSearchSession)
        assert client.tap._session is client._session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,payload",
    [
        (
            search_by_name,
            SearchByNameRequest(source_name="Crab", mission="NICER"),
        ),
        (search_by_coordinates, coordinate_request()),
        (
            search_by_obsid,
            SearchByObsidRequest(obsid="4010080142", mission="NICER"),
        ),
    ],
)
async def test_every_archive_search_route_runs_on_a_worker_thread(
    route,
    payload,
    monkeypatch,
):
    monkeypatch.setattr(
        route_module,
        "ARCHIVE_SEARCH_CAPACITY",
        threading.BoundedSemaphore(2),
    )
    event_loop_thread = threading.get_ident()
    worker_threads: list[int] = []
    service = RouteSearchService(
        lambda: (worker_threads.append(threading.get_ident()) or result_envelope())
    )

    result = await route(payload, service)

    assert result["success"] is True
    assert worker_threads and worker_threads[0] != event_loop_thread


@pytest.mark.asyncio
async def test_archive_search_route_keeps_event_loop_responsive(monkeypatch):
    monkeypatch.setattr(
        route_module,
        "ARCHIVE_SEARCH_CAPACITY",
        threading.BoundedSemaphore(2),
    )
    release = threading.Event()
    service = RouteSearchService(
        lambda: (release.wait(timeout=0.5) and result_envelope()) or result_envelope()
    )

    task = asyncio.create_task(search_by_coordinates(coordinate_request(), service))
    started_at = time.monotonic()
    await asyncio.sleep(0.02)
    heartbeat_elapsed = time.monotonic() - started_at
    release.set()
    result = await task

    assert heartbeat_elapsed < 0.2
    assert result["success"] is True


@pytest.mark.asyncio
async def test_archive_search_capacity_is_process_global_and_fail_fast(monkeypatch):
    capacity = 2
    monkeypatch.setattr(
        route_module,
        "ARCHIVE_SEARCH_CAPACITY",
        threading.BoundedSemaphore(capacity),
    )
    monkeypatch.setattr(route_module, "ARCHIVE_SEARCH_RESPONSE_TIMEOUT_SECONDS", 1.0)
    release = threading.Event()
    started = [threading.Event() for _index in range(capacity)]

    def blocking_operation(index):
        started[index].set()
        release.wait(timeout=1.0)
        return result_envelope()

    services = [
        RouteSearchService(lambda index=index: blocking_operation(index))
        for index in range(capacity)
    ]
    active = [
        asyncio.create_task(search_by_coordinates(coordinate_request(), service))
        for service in services
    ]
    for event in started:
        assert await asyncio.to_thread(event.wait, 0.5)

    rejected_service = RouteSearchService(lambda: result_envelope("unexpected"))
    rejected = await search_by_coordinates(coordinate_request(), rejected_service)

    assert rejected == {
        "success": False,
        "data": None,
        "message": "Too many archive searches are already active",
        "error": "Archive search capacity is temporarily unavailable",
    }
    assert rejected_service.calls == 0

    release.set()
    assert all(result["success"] for result in await asyncio.gather(*active))
    retry = await search_by_coordinates(
        coordinate_request(),
        RouteSearchService(result_envelope),
    )
    assert retry["success"] is True


@pytest.mark.asyncio
async def test_timed_out_search_keeps_capacity_until_worker_finishes(monkeypatch):
    monkeypatch.setattr(
        route_module,
        "ARCHIVE_SEARCH_CAPACITY",
        threading.BoundedSemaphore(1),
    )
    monkeypatch.setattr(route_module, "ARCHIVE_SEARCH_RESPONSE_TIMEOUT_SECONDS", 0.02)
    release = threading.Event()
    started = threading.Event()

    def blocking_operation():
        started.set()
        release.wait(timeout=1.0)
        return result_envelope()

    timed_out_service = RouteSearchService(blocking_operation)
    timed_out = await search_by_coordinates(coordinate_request(), timed_out_service)

    assert started.is_set()
    assert timed_out == {
        "success": False,
        "data": None,
        "message": "The archive search timed out",
        "error": "The bounded archive search deadline expired",
    }

    rejected_service = RouteSearchService(lambda: result_envelope("unexpected"))
    rejected = await search_by_coordinates(coordinate_request(), rejected_service)
    assert rejected["message"] == "Too many archive searches are already active"
    assert rejected_service.calls == 0

    release.set()
    deadline = time.monotonic() + 1.0
    while True:
        retry = await search_by_coordinates(
            coordinate_request(),
            RouteSearchService(result_envelope),
        )
        if retry["success"]:
            break
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
