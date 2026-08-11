"""Security regressions for bounded off-loop HEASARC searches."""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest
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
    ARCHIVE_SEARCH_TOTAL_SECONDS,
    HEASARC_TAP_URL,
    MAX_ARCHIVE_OBSID_REMOTE_ROWS,
    MAX_ARCHIVE_SEARCH_REMOTE_ROWS,
    ArchiveSearchBudget,
    ArchiveService,
)


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
    return SearchByCoordinatesRequest(ra=83.633, dec=22.0145, mission="NICER")


class FakeSecureArchiveClient:
    calls: list[dict[str, object]] = []
    sesame_body = b"%J 83.63240000 +22.01740000\n"
    tap_body = b"<?xml version='1.0'?><VOTABLE version='1.3'><RESOURCE><TABLE><FIELD name='obsid' datatype='char' arraysize='*'/><DATA><TABLEDATA><TR><TD>5001010204</TD></TR></TABLEDATA></DATA></TABLE></RESOURCE></VOTABLE>"

    def __init__(self, policy, *, timeouts, max_redirects):
        self.policy = policy
        self.timeouts = timeouts
        self.max_redirects = max_redirects

    async def fetch_text(self, url, *, max_bytes, **_kwargs):
        self.calls.append(
            {
                "kind": "sesame",
                "url": url,
                "policy": self.policy.name,
                "max_bytes": max_bytes,
                "timeouts": self.timeouts,
                "max_redirects": self.max_redirects,
            }
        )
        return self.sesame_body.decode(), SimpleNamespace(content_type="text/plain")

    async def post_form_bytes(
        self, url, fields, *, max_bytes, max_request_bytes, **_kwargs
    ):
        self.calls.append(
            {
                "kind": "tap",
                "url": url,
                "fields": dict(fields),
                "policy": self.policy.name,
                "max_bytes": max_bytes,
                "max_request_bytes": max_request_bytes,
                "timeouts": self.timeouts,
                "max_redirects": self.max_redirects,
            }
        )
        return self.tap_body, SimpleNamespace(content_type="text/xml")


def test_archive_searches_use_one_pinned_client_per_hop_and_bound_requests(
    state_manager, monkeypatch
):
    FakeSecureArchiveClient.calls = []
    monkeypatch.setattr(archive_module, "RemoteSourceClient", FakeSecureArchiveClient)
    service = ArchiveService(state_manager)

    name_result = service.search_by_name("Crab", "NICER", max_results=100)
    coordinate_result = service.search_by_coordinates(83.633, 22.0145, "NICER")
    obsid_result = service.search_by_obsid("4010080142", "NICER")

    assert name_result["success"] is True
    assert coordinate_result["success"] is True
    assert obsid_result["success"] is True
    assert [call["kind"] for call in FakeSecureArchiveClient.calls] == [
        "sesame",
        "tap",
        "tap",
        "tap",
    ]
    sesame = FakeSecureArchiveClient.calls[0]
    assert sesame["max_bytes"] == 64 * 1024
    assert sesame["max_redirects"] == 0
    for call in FakeSecureArchiveClient.calls[1:]:
        assert call["url"] == HEASARC_TAP_URL
        assert call["max_bytes"] == 32 * 1024**2
        assert call["max_request_bytes"] == 64 * 1024
        assert call["max_redirects"] == 0
        assert call["fields"]["MAXREC"] in {
            MAX_ARCHIVE_SEARCH_REMOTE_ROWS,
            MAX_ARCHIVE_OBSID_REMOTE_ROWS,
        }


def test_region_and_obsid_adql_are_local_and_allowlisted(state_manager, monkeypatch):
    service = ArchiveService(state_manager)
    queries: list[tuple[str, int]] = []
    monkeypatch.setattr(
        service,
        "_query_tap",
        lambda query, maxrec, budget: (queries.append((query, maxrec)) or Table()),
    )
    coords = SkyCoord(83.633 * u.deg, 22.0145 * u.deg)
    monkeypatch.setattr(service, "_resolve_source_name", lambda _name, _budget: coords)

    service.search_by_name("Crab", "NICER")
    service.search_by_coordinates(83.633, 22.0145, "NICER")
    service.search_by_obsid("4010080142", "NICER")

    assert queries[0][0] == (
        "SELECT * FROM nicermastr WHERE CONTAINS("
        "POINT('ICRS',83.633,22.0145),CIRCLE('ICRS',83.633,22.0145,0.5))=1"
    )
    assert queries[0][1] == MAX_ARCHIVE_SEARCH_REMOTE_ROWS
    assert queries[2] == (
        "SELECT * FROM nicermastr WHERE obsid = '4010080142'",
        MAX_ARCHIVE_OBSID_REMOTE_ROWS,
    )


def test_source_name_parser_is_local_and_does_not_use_astropy_network(monkeypatch):
    service = object.__new__(ArchiveService)
    monkeypatch.setattr(
        archive_module.SkyCoord,
        "from_name",
        lambda _name: (_ for _ in ()).throw(AssertionError("network resolver used")),
    )

    class SesameClient(FakeSecureArchiveClient):
        async def fetch_text(self, url, *, max_bytes, **kwargs):
            return "%J 83.6324 +22.0174", SimpleNamespace(content_type="text/plain")

    monkeypatch.setattr(archive_module, "RemoteSourceClient", SesameClient)
    coords = service._resolve_source_name("Crab")
    assert coords is not None
    assert coords.ra.deg == pytest.approx(83.6324)
    assert coords.dec.deg == pytest.approx(22.0174)


def test_archive_search_budget_is_shared_and_monotonic():
    budget = ArchiveSearchBudget.start()
    assert 0 < budget.remaining() <= ARCHIVE_SEARCH_TOTAL_SECONDS
    budget.deadline = time.monotonic() - 1
    with pytest.raises(archive_module.RemoteSourceTimeout):
        budget.remaining()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "route,payload",
    [
        (search_by_name, SearchByNameRequest(source_name="Crab", mission="NICER")),
        (search_by_coordinates, coordinate_request()),
        (search_by_obsid, SearchByObsidRequest(obsid="4010080142", mission="NICER")),
    ],
)
async def test_every_archive_search_route_runs_on_a_worker_thread(
    route, payload, monkeypatch
):
    monkeypatch.setattr(
        route_module, "ARCHIVE_SEARCH_CAPACITY", threading.BoundedSemaphore(2)
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
        route_module, "ARCHIVE_SEARCH_CAPACITY", threading.BoundedSemaphore(2)
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
        route_module, "ARCHIVE_SEARCH_CAPACITY", threading.BoundedSemaphore(capacity)
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
    assert rejected["message"] == "Too many archive searches are already active"
    assert rejected_service.calls == 0

    release.set()
    assert all(result["success"] for result in await asyncio.gather(*active))


@pytest.mark.asyncio
async def test_timed_out_search_keeps_capacity_until_worker_finishes(monkeypatch):
    monkeypatch.setattr(
        route_module, "ARCHIVE_SEARCH_CAPACITY", threading.BoundedSemaphore(1)
    )
    monkeypatch.setattr(route_module, "ARCHIVE_SEARCH_RESPONSE_TIMEOUT_SECONDS", 0.02)
    release = threading.Event()
    started = threading.Event()

    def blocking_operation():
        started.set()
        release.wait(timeout=1.0)
        return result_envelope()

    timed_out = await search_by_coordinates(
        coordinate_request(), RouteSearchService(blocking_operation)
    )
    assert started.is_set()
    assert timed_out["message"] == "The archive search timed out"

    rejected_service = RouteSearchService(lambda: result_envelope("unexpected"))
    rejected = await search_by_coordinates(coordinate_request(), rejected_service)
    assert rejected["message"] == "Too many archive searches are already active"
    assert rejected_service.calls == 0

    release.set()
    deadline = time.monotonic() + 1.0
    while True:
        retry = await search_by_coordinates(
            coordinate_request(), RouteSearchService(result_envelope)
        )
        if retry["success"]:
            break
        assert time.monotonic() < deadline
        await asyncio.sleep(0.01)
