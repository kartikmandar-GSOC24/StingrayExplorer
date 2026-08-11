"""Security contract tests for HEASARC downloads and native publication."""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import httpx
import pytest
import services.archive_service as archive_module
import services.utility_helpers as grant_module
from main import BACKEND_SESSION_HEADER, create_app
from pydantic import ValidationError
from routes.archive_routes import DownloadToDiskRequest, download_to_disk
from services.archive_service import (
    ARCHIVE_DOWNLOAD_CHUNK_BYTES,
    ARCHIVE_DOWNLOAD_TIMEOUTS,
    MAX_AGGREGATE_ARCHIVE_DOWNLOAD_BYTES,
    MAX_ARCHIVE_DOWNLOAD_BYTES,
    MAX_CONCURRENT_ARCHIVE_DOWNLOADS,
    ArchiveService,
)
from services.remote_source import (
    HEASARC_ARCHIVE_POLICY,
    RemoteSourceCancelled,
    RemoteSourceError,
    RemoteSourceHTTPError,
)
from services.utility_helpers import (
    FILE_GRANT_SECRET_ENV,
    FILE_GRANT_TTL_SECONDS,
    issue_file_grant,
)

TEST_SECRET = "archive-download-test-secret-that-is-at-least-32-bytes"
APPROVED_URL = "https://heasarc.gsfc.nasa.gov/FTP/nicer/data/file.evt"
SESSION_SECRET = "archive-download-session-secret-at-least-32-bytes"
DOWNLOAD_ROUTE = "/api/archive/download-to-disk"


class FakeRemoteStream:
    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_length: int | None = None,
        status_code: int = 200,
        failure: Exception | None = None,
    ) -> None:
        self.info = SimpleNamespace(
            content_length=content_length,
            status_code=status_code,
        )
        self._chunks = chunks
        self._failure = failure

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk
        if self._failure is not None:
            raise self._failure


class FakeRemoteClient:
    def __init__(self, remote_stream: FakeRemoteStream) -> None:
        self.remote_stream = remote_stream
        self.calls: list[dict[str, object]] = []

    @asynccontextmanager
    async def stream(self, url, *, max_bytes, cancellation_check=None):
        self.calls.append(
            {
                "url": url,
                "max_bytes": max_bytes,
                "cancellation_check": cancellation_check,
            }
        )
        yield self.remote_stream


@pytest.fixture(autouse=True)
def file_grant_secret(monkeypatch):
    monkeypatch.setenv(FILE_GRANT_SECRET_ENV, TEST_SECRET)


def write_grant(path) -> str:
    return issue_file_grant(str(path), access="write").grant


def install_remote_client(monkeypatch, remote_client: FakeRemoteClient):
    construction: dict[str, object] = {}

    def create_client(policy, **kwargs):
        construction["policy"] = policy
        construction.update(kwargs)
        return remote_client

    monkeypatch.setattr(archive_module, "RemoteSourceClient", create_client)
    return construction


async def collect_download(service: ArchiveService, **kwargs):
    return [event async for event in service.download_file_to_disk(**kwargs)]


@pytest.mark.asyncio
async def test_download_reopens_hashes_and_exclusively_publishes(
    tmp_path, state_manager, monkeypatch
):
    body = b"verified HEASARC bytes" * 50
    remote_client = FakeRemoteClient(
        FakeRemoteStream([body[:37], body[37:]], content_length=len(body))
    )
    construction = install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"
    service = ArchiveService(state_manager)

    events = await collect_download(
        service,
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert destination.read_bytes() == body
    assert [event["type"] for event in events] == ["progress", "progress", "complete"]
    complete = events[-1]
    assert complete == {
        "type": "complete",
        "file_name": "download.evt",
        "size_bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "warnings": [],
    }
    assert "destination_path" not in json.dumps(events)
    assert "destination_grant" not in json.dumps(events)
    assert str(destination) not in json.dumps(events)
    assert construction == {
        "policy": HEASARC_ARCHIVE_POLICY,
        "timeouts": ARCHIVE_DOWNLOAD_TIMEOUTS,
        "max_redirects": 5,
        "chunk_size": ARCHIVE_DOWNLOAD_CHUNK_BYTES,
    }
    assert remote_client.calls[0]["max_bytes"] == MAX_ARCHIVE_DOWNLOAD_BYTES
    assert list(tmp_path.glob(".stingray-export-*")) == []


def test_download_request_requires_a_strict_bounded_grant():
    with pytest.raises(ValidationError):
        DownloadToDiskRequest.model_validate(
            {"url": APPROVED_URL, "destination_path": "/tmp/download.evt"}
        )
    with pytest.raises(ValidationError):
        DownloadToDiskRequest.model_validate(
            {
                "url": APPROVED_URL,
                "destination_path": "/tmp/download.evt",
                "destination_grant": "grant",
                "unexpected": True,
            }
        )
    with pytest.raises(ValidationError):
        DownloadToDiskRequest.model_validate(
            {
                "url": APPROVED_URL,
                "destination_path": "/tmp/download.evt",
                "destination_grant": "x" * 513,
            }
        )


@pytest.mark.asyncio
async def test_route_does_not_reflect_missing_or_malformed_grants(
    tmp_path, state_manager
):
    destination = tmp_path / "private-destination.evt"
    malformed = "malformed-secret-grant"
    app = create_app(
        session_secret=SESSION_SECRET,
        file_grant_secret=TEST_SECRET,
    )
    app.state.state_manager = state_manager
    app.state.performance_monitor = None
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={BACKEND_SESSION_HEADER: SESSION_SECRET},
    ) as client:
        missing = await client.post(
            DOWNLOAD_ROUTE,
            json={
                "url": APPROVED_URL,
                "destination_path": str(destination),
            },
        )
        rejected = await client.post(
            DOWNLOAD_ROUTE,
            json={
                "url": APPROVED_URL,
                "destination_path": str(destination),
                "destination_grant": malformed,
            },
        )

    assert missing.status_code == 422
    assert str(destination) not in missing.text
    assert rejected.status_code == 200
    assert "authorization is invalid" in rejected.text
    assert str(destination) not in rejected.text
    assert malformed not in rejected.text
    assert not destination.exists()


@pytest.mark.asyncio
async def test_route_disconnect_closes_the_resource_owning_generator():
    cleanup_completed = False
    captured_cancellation_check = None

    class DisconnectingRequest:
        async def is_disconnected(self):
            return True

    class ResourceOwningService:
        async def download_file_to_disk(self, **kwargs):
            nonlocal cleanup_completed, captured_cancellation_check
            captured_cancellation_check = kwargs["cancellation_check"]
            try:
                yield {
                    "type": "progress",
                    "bytes_downloaded": 1,
                    "total_bytes": 2,
                    "percent": 50.0,
                }
            finally:
                cleanup_completed = True

    request = DisconnectingRequest()
    response = await download_to_disk(
        DownloadToDiskRequest(
            url=APPROVED_URL,
            destination_path="/native/download.evt",
            destination_grant="synthetic-grant",
        ),
        request,
        ResourceOwningService(),
    )

    assert [chunk async for chunk in response.body_iterator] == []
    assert cleanup_completed is True
    assert captured_cancellation_check == request.is_disconnected


@pytest.mark.asyncio
async def test_disconnect_after_publication_suppresses_sse_but_preserves_commit(
    tmp_path,
    state_manager,
    monkeypatch,
):
    body = b"verified bytes committed before the late disconnect"
    destination = tmp_path / "committed.evt"
    remote_client = FakeRemoteClient(FakeRemoteStream([body], content_length=len(body)))
    install_remote_client(monkeypatch, remote_client)

    class DisconnectAfterPublishRequest:
        async def is_disconnected(self):
            return destination.exists()

    response = await download_to_disk(
        DownloadToDiskRequest(
            url=APPROVED_URL,
            destination_path=str(destination),
            destination_grant=write_grant(destination),
        ),
        DisconnectAfterPublishRequest(),
        ArchiveService(state_manager),
    )

    chunks = [chunk async for chunk in response.body_iterator]
    assert len(chunks) == 1
    assert '"type": "progress"' in chunks[0]
    assert '"type": "complete"' not in chunks[0]
    assert destination.read_bytes() == body
    assert list(tmp_path.glob(".stingray-export-*")) == []

    replay = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )
    assert replay == [
        {
            "type": "error",
            "error": "A file already exists at the selected destination",
        }
    ]
    assert len(remote_client.calls) == 1


@pytest.mark.asyncio
async def test_early_route_disconnect_cleans_staging_and_releases_claim(
    tmp_path,
    state_manager,
    monkeypatch,
):
    body = b"private bytes that must not survive an early disconnect"
    destination = tmp_path / "cancelled.evt"
    remote_client = FakeRemoteClient(FakeRemoteStream([body], content_length=len(body)))
    install_remote_client(monkeypatch, remote_client)
    grant = write_grant(destination)

    class DisconnectedRequest:
        async def is_disconnected(self):
            return True

    response = await download_to_disk(
        DownloadToDiskRequest(
            url=APPROVED_URL,
            destination_path=str(destination),
            destination_grant=grant,
        ),
        DisconnectedRequest(),
        ArchiveService(state_manager),
    )

    assert [chunk async for chunk in response.body_iterator] == []
    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []

    retry = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=grant,
    )
    assert retry[-1]["type"] == "complete"
    assert destination.read_bytes() == body


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", ["malformed", "v2.1.2.3.bad"])
async def test_malformed_grant_never_starts_remote_io(
    grant, tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "download.evt"

    def forbidden_client(*_args, **_kwargs):
        raise AssertionError("remote client must not be constructed")

    monkeypatch.setattr(archive_module, "RemoteSourceClient", forbidden_client)
    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=grant,
    )

    assert events == [
        {
            "type": "error",
            "error": (
                "The save authorization is invalid or expired; choose the "
                "destination again"
            ),
        }
    ]
    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_grant_for_another_destination_is_rejected(
    tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "download.evt"
    other_destination = tmp_path / "other.evt"
    monkeypatch.setattr(
        archive_module,
        "RemoteSourceClient",
        lambda *_args, **_kwargs: pytest.fail("remote I/O must not start"),
    )

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(other_destination),
    )

    assert events[0]["type"] == "error"
    assert "authorization" in events[0]["error"]
    assert not destination.exists()


@pytest.mark.asyncio
async def test_expired_destination_grant_is_rejected_before_remote_io(
    tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "download.evt"
    issued = issue_file_grant(str(destination), access="write")
    monkeypatch.setattr(
        grant_module.time,
        "time",
        lambda: issued.expires_at + FILE_GRANT_TTL_SECONDS + 1,
    )
    monkeypatch.setattr(
        archive_module,
        "RemoteSourceClient",
        lambda *_args, **_kwargs: pytest.fail("remote I/O must not start"),
    )

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=issued.grant,
    )

    assert events[-1]["type"] == "error"
    assert "authorization" in events[-1]["error"]
    assert not destination.exists()


@pytest.mark.asyncio
async def test_grant_expiry_after_admission_does_not_abort_long_download(
    tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "long-download.evt"
    issued = issue_file_grant(str(destination), access="write")
    body = b"download admitted while the write grant was fresh"

    class GrantExpiringRemoteStream(FakeRemoteStream):
        async def aiter_bytes(self):
            yield body
            monkeypatch.setattr(
                grant_module.time,
                "time",
                lambda: issued.expires_at + 1,
            )

    remote_client = FakeRemoteClient(
        GrantExpiringRemoteStream([body], content_length=len(body))
    )
    install_remote_client(monkeypatch, remote_client)

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=issued.grant,
    )

    assert events[-1]["type"] == "complete"
    assert events[-1]["sha256"] == hashlib.sha256(body).hexdigest()
    assert grant_module.time.time() > issued.expires_at
    assert destination.read_bytes() == body
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_read_grant_cannot_authorize_an_archive_destination(
    tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "selected-input.evt"
    destination.write_bytes(b"existing input")
    read_grant = issue_file_grant(str(destination), access="read").grant
    monkeypatch.setattr(
        archive_module,
        "RemoteSourceClient",
        lambda *_args, **_kwargs: pytest.fail("remote I/O must not start"),
    )

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=read_grant,
    )

    assert events[-1]["type"] == "error"
    assert "authorization" in events[-1]["error"]
    assert destination.read_bytes() == b"existing input"


@pytest.mark.asyncio
async def test_existing_destination_is_never_overwritten(
    tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "download.evt"
    destination.write_bytes(b"user-owned")
    monkeypatch.setattr(
        archive_module,
        "RemoteSourceClient",
        lambda *_args, **_kwargs: pytest.fail("remote I/O must not start"),
    )

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events == [
        {"type": "error", "error": "A file already exists at the selected destination"}
    ]
    assert destination.read_bytes() == b"user-owned"
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure, expected_error",
    [
        (RemoteSourceCancelled("cancelled with /private/path"), "Download cancelled"),
        (
            RemoteSourceError("failed at https://example.invalid/?secret=leaked"),
            "The HEASARC download failed validation",
        ),
    ],
)
async def test_cancel_or_remote_failure_cleans_only_private_staging(
    failure, expected_error, tmp_path, state_manager, monkeypatch
):
    remote_client = FakeRemoteClient(
        FakeRemoteStream([b"partial"], content_length=20, failure=failure)
    )
    install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_bytes(b"keep")

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL + "?token=not-for-events",
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events[-1] == {"type": "error", "error": expected_error}
    assert all(event["type"] == "progress" for event in events[:-1])
    assert not destination.exists()
    assert unrelated.read_bytes() == b"keep"
    assert list(tmp_path.glob(".stingray-export-*")) == []
    serialized = json.dumps(events)
    assert "private" not in serialized
    assert "not-for-events" not in serialized
    assert "leaked" not in serialized


@pytest.mark.asyncio
async def test_content_length_mismatch_never_publishes(
    tmp_path, state_manager, monkeypatch
):
    remote_client = FakeRemoteClient(FakeRemoteStream([b"short"], content_length=10))
    install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events[-1] == {
        "type": "error",
        "error": "The HEASARC download failed validation",
    }
    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_partial_content_response_is_never_published(
    tmp_path, state_manager, monkeypatch
):
    remote_client = FakeRemoteClient(
        FakeRemoteStream(
            [b"internally consistent partial bytes"],
            content_length=35,
            status_code=206,
        )
    )
    install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events == [
        {
            "type": "error",
            "error": "The HEASARC download failed validation",
        }
    ]
    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_replayed_grant_cannot_start_parallel_destination_download(
    tmp_path, state_manager, monkeypatch
):
    remote_client = FakeRemoteClient(
        FakeRemoteStream([b"private in-progress bytes"], content_length=25)
    )
    install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"
    grant = write_grant(destination)
    first = ArchiveService(state_manager).download_file_to_disk(
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=grant,
    )

    try:
        assert (await anext(first))["type"] == "progress"
        replay_events = await collect_download(
            ArchiveService(state_manager),
            url=APPROVED_URL,
            destination_path=str(destination),
            destination_grant=grant,
        )

        assert replay_events == [
            {
                "type": "error",
                "error": "A download is already using the selected destination",
            }
        ]
        assert len(remote_client.calls) == 1
    finally:
        await first.aclose()
    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_process_wide_archive_download_capacity_is_fail_fast_and_bounded(
    tmp_path, state_manager, monkeypatch
):
    assert MAX_CONCURRENT_ARCHIVE_DOWNLOADS == 2
    assert (
        MAX_AGGREGATE_ARCHIVE_DOWNLOAD_BYTES
        == MAX_CONCURRENT_ARCHIVE_DOWNLOADS * MAX_ARCHIVE_DOWNLOAD_BYTES
    )
    remote_client = FakeRemoteClient(
        FakeRemoteStream([b"private in-progress bytes"], content_length=25)
    )
    install_remote_client(monkeypatch, remote_client)
    active_downloads = []
    rejected_destination = tmp_path / "over-capacity.evt"
    try:
        for index in range(MAX_CONCURRENT_ARCHIVE_DOWNLOADS):
            destination = tmp_path / f"active-{index}.evt"
            stream = ArchiveService(state_manager).download_file_to_disk(
                url=APPROVED_URL,
                destination_path=str(destination),
                destination_grant=write_grant(destination),
            )
            assert (await anext(stream))["type"] == "progress"
            active_downloads.append(stream)

        rejected = await collect_download(
            ArchiveService(state_manager),
            url=APPROVED_URL,
            destination_path=str(rejected_destination),
            destination_grant=write_grant(rejected_destination),
        )

        assert rejected == [
            {
                "type": "error",
                "error": "Too many archive downloads are already active",
            }
        ]
        assert len(remote_client.calls) == MAX_CONCURRENT_ARCHIVE_DOWNLOADS
    finally:
        for stream in active_downloads:
            await stream.aclose()
    assert not rejected_destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_publication_context_closes_before_terminal_success_is_yielded(
    tmp_path, state_manager, monkeypatch
):
    class TrackedPublication:
        def __init__(self):
            self.path = tmp_path / "download.evt"
            self.filename = "download.evt"
            self.data = b""
            self.context_closed = False

        def revalidate(self, _message):
            return None

        def assert_destination_available(self):
            return None

        def reserve_staging(self, _extension):
            return None

        @contextmanager
        def open_writer(self, _mode, *, encoding=None):
            del encoding
            stream = io.BytesIO()
            yield stream
            self.data = stream.getvalue()

        @contextmanager
        def open_reader(self, _mode, *, encoding=None):
            del encoding
            yield io.BytesIO(self.data)

        def verified_size(self):
            return len(self.data)

        def publish(self):
            return []

    publication = TrackedPublication()

    @contextmanager
    def tracked_publication(*_args, **_kwargs):
        try:
            yield publication
        finally:
            publication.context_closed = True

    monkeypatch.setattr(archive_module, "open_secure_publication", tracked_publication)
    remote_client = FakeRemoteClient(
        FakeRemoteStream([b"verified bytes"], content_length=14)
    )
    install_remote_client(monkeypatch, remote_client)
    stream = ArchiveService(state_manager).download_file_to_disk(
        url=APPROVED_URL,
        destination_path=str(publication.path),
        destination_grant="synthetic-grant",
    )

    assert (await anext(stream))["type"] == "progress"
    complete = await anext(stream)

    assert complete["type"] == "complete"
    assert publication.context_closed is True
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_cancellation_interrupts_slow_reopen_verification_and_joins_worker(
    tmp_path, state_manager, monkeypatch
):
    reader_started = threading.Event()
    body = b"x" * 100

    class SlowReader:
        def __init__(self):
            self.offset = 0
            self.read_count = 0

        def read(self, _maximum):
            reader_started.set()
            time.sleep(0.02)
            self.read_count += 1
            if self.offset >= len(body):
                return b""
            chunk = body[self.offset : self.offset + 1]
            self.offset += 1
            return chunk

    slow_reader = SlowReader()

    class CancellablePublication:
        def __init__(self):
            self.path = tmp_path / "cancelled-verification.evt"
            self.filename = self.path.name
            self.data = b""
            self.context_closed = False
            self.published = False

        def revalidate(self, _message):
            return None

        def assert_destination_available(self):
            return None

        def reserve_staging(self, _extension):
            return None

        @contextmanager
        def open_writer(self, _mode, *, encoding=None):
            del encoding
            stream = io.BytesIO()
            yield stream
            self.data = stream.getvalue()

        @contextmanager
        def open_reader(self, _mode, *, encoding=None):
            del encoding
            yield slow_reader

        def verified_size(self):
            return len(self.data)

        def publish(self):
            self.published = True
            return []

    publication = CancellablePublication()

    @contextmanager
    def tracked_publication(*_args, **_kwargs):
        try:
            yield publication
        finally:
            publication.context_closed = True

    monkeypatch.setattr(archive_module, "open_secure_publication", tracked_publication)
    remote_client = FakeRemoteClient(FakeRemoteStream([body], content_length=len(body)))
    install_remote_client(monkeypatch, remote_client)

    async def cancellation_requested():
        return reader_started.is_set()

    started_at = time.monotonic()
    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(publication.path),
        destination_grant="synthetic-grant",
        cancellation_check=cancellation_requested,
    )
    elapsed = time.monotonic() - started_at

    assert events[-1] == {"type": "error", "error": "Download cancelled"}
    assert publication.published is False
    assert publication.context_closed is True
    assert slow_reader.read_count < len(body)
    assert elapsed < 1.0


@pytest.mark.asyncio
async def test_cancellation_joins_slow_descriptor_owning_writer_before_teardown(
    tmp_path,
    state_manager,
    monkeypatch,
):
    writer_started = threading.Event()
    writer_closed = threading.Event()
    body = b"queued private bytes"

    class SlowWriter(io.BytesIO):
        def write(self, chunk):
            writer_started.set()
            time.sleep(0.05)
            return super().write(chunk)

    class CancellablePublication:
        def __init__(self):
            self.path = tmp_path / "cancelled-write.evt"
            self.filename = self.path.name
            self.context_closed = False
            self.published = False

        def revalidate(self, _message):
            return None

        def assert_destination_available(self):
            return None

        def reserve_staging(self, _extension):
            return None

        @contextmanager
        def open_writer(self, _mode, *, encoding=None):
            del encoding
            try:
                yield SlowWriter()
            finally:
                writer_closed.set()

        def publish(self):
            self.published = True
            return []

    publication = CancellablePublication()

    @contextmanager
    def tracked_publication(*_args, **_kwargs):
        try:
            yield publication
        finally:
            publication.context_closed = True

    monkeypatch.setattr(archive_module, "open_secure_publication", tracked_publication)
    remote_client = FakeRemoteClient(FakeRemoteStream([body], content_length=len(body)))
    install_remote_client(monkeypatch, remote_client)

    async def cancellation_requested():
        return writer_started.is_set()

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(publication.path),
        destination_grant="synthetic-grant",
        cancellation_check=cancellation_requested,
    )

    assert events[-1] == {"type": "error", "error": "Download cancelled"}
    assert writer_started.is_set()
    assert writer_closed.is_set()
    assert publication.context_closed is True
    assert publication.published is False


@pytest.mark.asyncio
async def test_cancellation_check_after_transfer_prevents_publication(
    tmp_path, state_manager, monkeypatch
):
    remote_client = FakeRemoteClient(
        FakeRemoteStream([b"complete private bytes"], content_length=22)
    )
    install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"

    def cancelled() -> bool:
        return True

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
        cancellation_check=cancelled,
    )

    assert events[-1] == {"type": "error", "error": "Download cancelled"}
    assert remote_client.calls[0]["cancellation_check"] is cancelled
    assert not destination.exists()
    assert list(tmp_path.glob(".stingray-export-*")) == []


@pytest.mark.asyncio
async def test_control_character_filename_is_rejected_before_remote_io(
    tmp_path, state_manager, monkeypatch
):
    destination = tmp_path / "unsafe\nname.evt"
    monkeypatch.setattr(
        archive_module,
        "RemoteSourceClient",
        lambda *_args, **_kwargs: pytest.fail("remote I/O must not start"),
    )

    events = await collect_download(
        ArchiveService(state_manager),
        url=APPROVED_URL,
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events == [
        {"type": "error", "error": "The download could not be published safely"}
    ]
    assert not destination.exists()


@pytest.mark.asyncio
async def test_non_heasarc_url_is_rejected_without_leaking_query(
    tmp_path, state_manager
):
    destination = tmp_path / "download.evt"
    secret = "TOP-SECRET-QUERY"

    events = await collect_download(
        ArchiveService(state_manager),
        url=f"https://evil.example/FTP/file.evt?token={secret}",
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events == [
        {
            "type": "error",
            "error": "The selected URL is not an approved HEASARC archive download",
        }
    ]
    assert secret not in json.dumps(events)
    assert not destination.exists()


@pytest.mark.asyncio
async def test_http_error_exposes_only_status_not_remote_path_or_query(
    tmp_path, state_manager, monkeypatch
):
    secret = "TOP-SECRET-QUERY"
    remote_client = FakeRemoteClient(
        FakeRemoteStream(
            [],
            failure=RemoteSourceHTTPError(
                403,
                "https://heasarc.gsfc.nasa.gov/FTP/private/file.evt",
            ),
        )
    )

    @asynccontextmanager
    async def failing_stream(*_args, **_kwargs):
        raise RemoteSourceHTTPError(
            403,
            "https://heasarc.gsfc.nasa.gov/FTP/private/file.evt",
        )
        yield  # pragma: no cover

    remote_client.stream = failing_stream
    install_remote_client(monkeypatch, remote_client)
    destination = tmp_path / "download.evt"

    events = await collect_download(
        ArchiveService(state_manager),
        url=f"{APPROVED_URL}?token={secret}",
        destination_path=str(destination),
        destination_grant=write_grant(destination),
    )

    assert events == [
        {"type": "error", "error": "The HEASARC server returned HTTP 403"}
    ]
    serialized = json.dumps(events)
    assert secret not in serialized
    assert "private/file" not in serialized
    assert str(destination) not in serialized
