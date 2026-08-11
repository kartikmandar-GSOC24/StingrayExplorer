"""Security contract tests for bounded HEASARC directory crawling."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
import services.archive_service as archive_module
from main import BACKEND_SESSION_HEADER, create_app
from routes.archive_routes import router as archive_router
from services.archive_service import (
    ARCHIVE_CRAWL_HOP_SECONDS,
    MAX_ARCHIVE_DIRECTORY_ENTRIES,
    MAX_ARCHIVE_DIRECTORY_HTML_BYTES,
    ArchiveService,
)
from services.remote_source import (
    HEASARC_ARCHIVE_POLICY,
    RemoteSourceSizeError,
)

SESSION_SECRET = "archive-crawl-session-secret-at-least-32-bytes"
FILE_GRANT_SECRET = "archive-crawl-file-grant-secret-at-least-32-bytes"
LIST_ROUTE = "/api/archive/list-files"
OBSID = "0123456789"
ROOT_URL = f"https://heasarc.gsfc.nasa.gov/FTP/xmm/data/rev0/{OBSID}/"


class FakeListingRemote:
    def __init__(self, responses: dict[str, bytes], *, after_fetch=None) -> None:
        self.responses = responses
        self.after_fetch = after_fetch
        self.calls: list[dict[str, object]] = []

    async def fetch_bytes(
        self,
        url,
        *,
        max_bytes,
        cancellation_check=None,
    ):
        self.calls.append(
            {
                "url": url,
                "max_bytes": max_bytes,
                "cancellation_check": cancellation_check,
            }
        )
        body = self.responses[url]
        if len(body) > max_bytes:
            raise RemoteSourceSizeError("bounded fake response was too large")
        if self.after_fetch is not None:
            self.after_fetch()
        return body, SimpleNamespace(
            status_code=200,
            content_type="text/html; charset=utf-8",
        )


def install_listing_remote(monkeypatch, remote: FakeListingRemote):
    constructions: list[dict[str, object]] = []

    def create_client(policy, **kwargs):
        constructions.append({"policy": policy, **kwargs})
        return remote

    monkeypatch.setattr(archive_module, "RemoteSourceClient", create_client)
    return constructions


async def crawl(service: ArchiveService, **kwargs):
    return await service.list_observation_files(
        mission="XMM-Newton",
        obsid=OBSID,
        recursive=True,
        max_depth=3,
        **kwargs,
    )


def test_list_files_route_is_registered_exactly_once():
    matching = [
        route
        for route in archive_router.routes
        if route.path == "/list-files" and "POST" in (route.methods or set())
    ]

    assert len(matching) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile_href",
    [
        "https://evil.example/x",
        "//evil.example/x",
        "sub%2Fescape/",
        "%2e%2e/",
        "sub%5cescape/",
        "safe/?token=SECRET",
        "safe/#frag",
        "%00.evt",
        "%GG",
        "%FF",
        "%252e%252e/",
        "%252fetc/",
    ],
)
async def test_non_child_href_is_rejected_before_any_child_hop(
    hostile_href,
    state_manager,
    monkeypatch,
):
    html = f'<html><a href="{hostile_href}">hostile</a><a href="safe/">safe</a></html>'
    remote = FakeListingRemote({ROOT_URL: html.encode()})
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result == {
        "success": False,
        "data": None,
        "message": "The archive directory listing failed validation",
        "error": "The archive crawl was rejected safely",
    }
    assert [call["url"] for call in remote.calls] == [ROOT_URL]
    serialized = json.dumps(result)
    assert hostile_href not in serialized
    assert "SECRET" not in serialized


@pytest.mark.asyncio
async def test_benign_navigation_is_skipped_and_file_survives(
    state_manager,
    monkeypatch,
):
    html = """
    <html><body>
      <a href="../">Parent</a>
      <a href="/icons/blank.gif">Icon</a>
      <a href="?C=N;O=D">Sort</a>
      <a href="event_cl.evt">event_cl.evt</a>
    </body></html>
    """
    remote = FakeListingRemote({ROOT_URL: html.encode()})
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result["success"] is True
    assert result["data"]["total_files"] == 1
    assert result["data"]["files"] == [
        {
            "path": "event_cl.evt",
            "name": "event_cl.evt",
            "is_directory": False,
            "file_type": "event",
            "size_bytes": None,
            "size_display": "Unknown",
            "full_url": ROOT_URL + "event_cl.evt",
        }
    ]
    assert len(remote.calls) == 1


@pytest.mark.asyncio
async def test_every_crawl_hop_uses_bounded_remote_source_without_head(
    state_manager,
    monkeypatch,
):
    sub_url = ROOT_URL + "sub/"
    remote = FakeListingRemote(
        {
            ROOT_URL: b'<a href="sub/">sub</a><a href="root.log">root.log</a>',
            sub_url: b'<a href="child.evt">child.evt</a>',
        }
    )
    constructions = install_listing_remote(monkeypatch, remote)

    class ForbiddenRawClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("crawl must not construct a raw httpx client")

    monkeypatch.setattr(httpx, "AsyncClient", ForbiddenRawClient)

    def cancelled():
        return False

    result = await crawl(
        ArchiveService(state_manager),
        cancellation_check=cancelled,
    )

    assert result["success"] is True
    assert [call["url"] for call in remote.calls] == [ROOT_URL, sub_url]
    assert all(
        call["max_bytes"] == MAX_ARCHIVE_DIRECTORY_HTML_BYTES
        and call["cancellation_check"] is cancelled
        for call in remote.calls
    )
    assert len(constructions) == 2
    assert all(item["policy"] == HEASARC_ARCHIVE_POLICY for item in constructions)
    assert all(
        item["timeouts"].total <= ARCHIVE_CRAWL_HOP_SECONDS
        and item["max_redirects"] == 3
        for item in constructions
    )
    root_file = result["data"]["files"][1]
    child_file = result["data"]["files"][0]["children"][0]
    assert root_file["size_bytes"] is None
    assert child_file["size_bytes"] is None


@pytest.mark.asyncio
async def test_crawl_rejects_oversized_directory_body(
    state_manager,
    monkeypatch,
):
    remote = FakeListingRemote(
        {ROOT_URL: b"x" * (MAX_ARCHIVE_DIRECTORY_HTML_BYTES + 1)}
    )
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result["success"] is False
    assert len(remote.calls) == 1
    assert remote.calls[0]["max_bytes"] == MAX_ARCHIVE_DIRECTORY_HTML_BYTES


@pytest.mark.asyncio
async def test_crawl_rejects_too_many_entries_without_child_fanout(
    state_manager,
    monkeypatch,
):
    html = "".join(
        f'<a href="dir-{index}/">dir</a>'
        for index in range(MAX_ARCHIVE_DIRECTORY_ENTRIES + 1)
    )
    remote = FakeListingRemote({ROOT_URL: html.encode()})
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result["success"] is False
    assert [call["url"] for call in remote.calls] == [ROOT_URL]


@pytest.mark.asyncio
async def test_shared_directory_budget_fails_closed_before_next_hop(
    state_manager,
    monkeypatch,
):
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_CRAWL_DIRECTORIES", 2)
    first_url = ROOT_URL + "first/"
    remote = FakeListingRemote(
        {
            ROOT_URL: b'<a href="first/">first</a><a href="second/">second</a>',
            first_url: b'<a href="one.evt">one</a>',
        }
    )
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result["success"] is False
    assert [call["url"] for call in remote.calls] == [ROOT_URL, first_url]
    assert result["data"] is None


@pytest.mark.asyncio
async def test_shared_entry_budget_fails_closed_across_directories(
    state_manager,
    monkeypatch,
):
    monkeypatch.setattr(archive_module, "MAX_ARCHIVE_CRAWL_ENTRIES", 2)
    sub_url = ROOT_URL + "sub/"
    remote = FakeListingRemote(
        {
            ROOT_URL: b'<a href="sub/">sub</a>',
            sub_url: b'<a href="one.evt">one</a><a href="two.evt">two</a>',
        }
    )
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result["success"] is False
    assert result["data"] is None
    assert [call["url"] for call in remote.calls] == [ROOT_URL, sub_url]


@pytest.mark.asyncio
async def test_total_crawl_deadline_stops_before_child_hop(
    state_manager,
    monkeypatch,
):
    clock = {"now": 0.0}
    monkeypatch.setattr(archive_module.time, "monotonic", lambda: clock["now"])
    remote = FakeListingRemote(
        {ROOT_URL: b'<a href="child/">child</a>'},
        after_fetch=lambda: clock.update(now=121.0),
    )
    install_listing_remote(monkeypatch, remote)

    result = await crawl(ArchiveService(state_manager))

    assert result["success"] is False
    assert result["message"] == "The archive directory listing timed out"
    assert [call["url"] for call in remote.calls] == [ROOT_URL]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"mission": "XMM-Newton", "obsid": OBSID, "max_depth": -1},
        {"mission": "XMM-Newton", "obsid": OBSID, "max_depth": 4},
        {"mission": "XMM-Newton", "obsid": OBSID, "max_depth": True},
        {"mission": "XMM-Newton", "obsid": OBSID, "recursive": "true"},
        {"mission": "XMM-Newton", "obsid": OBSID, "recursive": 1},
        {"mission": "XMM-Newton", "obsid": "../escape"},
        {"mission": "XMM-Newton", "obsid": "x" * 129},
        {"mission": "XMM-Newton", "obsid": OBSID, "obs_time": "x" * 65},
        {"mission": "XMM-Newton", "obsid": OBSID, "extra": True},
        {
            "mission": "RXTE",
            "obsid": OBSID,
            "obs_data": {"prnb": "12345", "extra": True},
        },
    ],
)
async def test_list_route_rejects_unbounded_or_coercive_requests(
    payload,
    state_manager,
):
    app = create_app(
        session_secret=SESSION_SECRET,
        file_grant_secret=FILE_GRANT_SECRET,
    )
    app.state.state_manager = state_manager
    app.state.performance_monitor = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={BACKEND_SESSION_HEADER: SESSION_SECRET},
    ) as client:
        response = await client.post(LIST_ROUTE, json=payload)

    assert response.status_code == 422
    assert "../escape" not in response.text
    assert "x" * 65 not in response.text
