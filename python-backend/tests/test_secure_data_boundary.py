"""Adversarial coverage for native-grant data and private job resources."""

from __future__ import annotations

import asyncio
import gzip
import logging
import shutil
import threading
import time
from concurrent.futures import Future
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import h5py
import numpy as np
import pytest
from astropy.io import fits
from pydantic import ValidationError
from stingray import EventList

import services.data_service as data_service_module
import services.job_manager as job_manager_module
from main import create_app
from models.job import Job
from routes.data_routes import (
    BatchFileSizeRequest,
    BatchLoadEventListRequest,
    LoadEventListRequest,
    load_event_list as load_event_list_route,
)
from routes.job_routes import (
    SubmitBatchJobRequest,
    SubmitLoadJobRequest,
    submit_load_job,
)
from services.data_service import DataService
from services.job_manager import JobManager
from services.remote_source import GENERAL_HTTPS_POLICY, RemoteSourceError
from services.state_manager import StateManager
from services.utility_helpers import issue_file_grant
from tests.backend_auth import TEST_BACKEND_SESSION_SECRET


SECRET = "secure-data-boundary-secret-at-least-32-bytes"


@pytest.fixture(autouse=True)
def file_grant_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STINGRAY_FILE_GRANT_SECRET", SECRET)


def _grant(path: Path) -> str:
    return issue_file_grant(str(path), access="read").grant


def _write_hdf5(path: Path, times: list[float]) -> None:
    EventList(
        time=np.asarray(times, dtype=float),
        gti=np.asarray([[min(times), max(times)]], dtype=float),
    ).write(str(path), fmt="hdf5")


def _write_event_fits(path: Path) -> None:
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "NICER"
    primary.header["INSTRUME"] = "XTI"
    events = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="TIME", format="D", unit="s", array=[1.0, 2.0]),
            fits.Column(name="PI", format="J", array=[0, 1]),
        ],
        name="EVENTS",
    )
    events.header["MJDREFI"] = 58_000
    events.header["MJDREFF"] = 0.0
    events.header["TIMESYS"] = "TT"
    events.header["TIMEUNIT"] = "s"
    events.header["TSTART"] = 1.0
    events.header["TSTOP"] = 2.0
    fits.HDUList([primary, events]).writeto(path, checksum=True)


def _write_rmf(path: Path, energies: tuple[float, float]) -> None:
    ebounds = fits.BinTableHDU.from_columns(
        [
            fits.Column(name="CHANNEL", format="J", array=[0, 1]),
            fits.Column(
                name="E_MIN",
                format="D",
                unit="keV",
                array=[energies[0], energies[1]],
            ),
            fits.Column(
                name="E_MAX",
                format="D",
                unit="keV",
                array=[energies[0], energies[1]],
            ),
        ],
        name="EBOUNDS",
    )
    fits.HDUList([fits.PrimaryHDU(), ebounds]).writeto(path, checksum=True)


def test_request_models_require_exact_grants_pairs_bounds_and_no_extras() -> None:
    with pytest.raises(ValidationError, match="file_grant"):
        LoadEventListRequest(file_path="/selected/events.evt", name="events")
    with pytest.raises(ValidationError, match="rmf_file and rmf_grant"):
        LoadEventListRequest(
            file_path="/selected/events.evt",
            file_grant="grant",
            name="events",
            rmf_file="/selected/cal.rmf",
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        LoadEventListRequest(
            file_path="/selected/events.evt",
            file_grant="grant",
            name="events",
            surprise=True,
        )
    with pytest.raises(ValidationError, match="extra_forbidden"):
        LoadEventListRequest(
            file_path="/selected/events.evt",
            file_grant="grant",
            name="events",
            _file_source="forged-internal-capability",
        )
    with pytest.raises(ValidationError):
        LoadEventListRequest(
            file_path="/selected/events.evt",
            file_grant="grant",
            name="events",
            high_precision="false",
        )
    with pytest.raises(ValidationError):
        LoadEventListRequest(
            file_path="/selected/events.evt",
            file_grant="grant",
            name="/private/events",
        )
    with pytest.raises(ValidationError):
        BatchLoadEventListRequest(
            files=[
                {
                    "file_path": f"/selected/{index}.evt",
                    "file_grant": "grant",
                    "name": f"events-{index}",
                }
                for index in range(33)
            ]
        )
    BatchFileSizeRequest(
        files=[{"file_path": "/selected/events.evt", "file_grant": "grant"}]
    )
    with pytest.raises(ValidationError, match="shared_rmf"):
        SubmitBatchJobRequest(
            files=[
                {
                    "file_path": "/selected/events.evt",
                    "file_grant": "grant",
                    "name": "events",
                }
            ],
            shared_rmf_file="/selected/cal.rmf",
        )


def test_every_local_route_is_grant_shaped_and_legacy_save_is_absent() -> None:
    app = create_app(session_secret=TEST_BACKEND_SESSION_SECRET)
    route_paths = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("POST", "/api/data/save") not in route_paths
    assert not hasattr(DataService, "save_event_list")
    assert {"file_path", "file_grant"} <= set(LoadEventListRequest.model_fields)
    assert {"files"} <= set(BatchFileSizeRequest.model_fields)
    assert {"file_path", "file_grant"} <= set(SubmitLoadJobRequest.model_fields)


def test_hdf5_load_uses_h5py_over_anonymous_spool_not_selected_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "events.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    seen: list[Any] = []
    original_h5py_file = h5py.File

    class TrackedH5pyFile(original_h5py_file):
        def __init__(self, source, *args, **kwargs):
            seen.append(source)
            assert not isinstance(source, (str, bytes, Path))
            super().__init__(source, *args, **kwargs)

    monkeypatch.setattr(data_service_module.h5py, "File", TrackedH5pyFile)
    result = DataService(StateManager()).load_event_list(
        str(selected),
        "events",
        fmt="hdf5",
        file_grant=_grant(selected),
    )

    assert result["success"] is True
    assert seen


def test_path_swap_after_grant_open_cannot_redirect_hdf5_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected = tmp_path / "selected.hdf5"
    original = tmp_path / "original.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    grant = _grant(selected)
    original_spool = data_service_module._spooled_copy
    swapped = False

    @contextmanager
    def swap_then_spool(source, *, max_bytes, cancellation_check=None):
        nonlocal swapped
        if not swapped:
            swapped = True
            selected.rename(original)
            _write_hdf5(selected, [90.0, 91.0])
        with original_spool(
            source,
            max_bytes=max_bytes,
            cancellation_check=cancellation_check,
        ) as stream:
            yield stream

    monkeypatch.setattr(data_service_module, "_spooled_copy", swap_then_spool)
    state = StateManager()
    result = DataService(state).load_event_list(
        str(selected), "events", fmt="hdf5", file_grant=grant
    )

    assert result["success"] is True
    assert state.get_event_data("events").time.tolist() == [1.0, 2.0]


def test_native_open_failure_does_not_expose_selected_path(tmp_path: Path) -> None:
    selected = tmp_path / "private-selected-events.hdf5"
    moved = tmp_path / "moved.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    grant = _grant(selected)
    selected.rename(moved)

    with pytest.raises(PermissionError) as raised:
        DataService(StateManager()).load_event_list(
            str(selected), "events", fmt="hdf5", file_grant=grant
        )

    assert str(selected) not in str(raised.value)


def test_rmf_swap_after_grant_open_cannot_redirect_calibration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = tmp_path / "events.evt"
    rmf = tmp_path / "selected.rmf"
    original_rmf = tmp_path / "original.rmf"
    _write_event_fits(events)
    _write_rmf(rmf, (1.0, 2.0))
    event_grant = _grant(events)
    rmf_grant = _grant(rmf)
    original_spool = data_service_module._spooled_copy
    swapped = False

    @contextmanager
    def swap_rmf_then_spool(source, *, max_bytes, cancellation_check=None):
        nonlocal swapped
        if source.path == rmf.resolve() and not swapped:
            swapped = True
            rmf.rename(original_rmf)
            _write_rmf(rmf, (100.0, 200.0))
        with original_spool(
            source,
            max_bytes=max_bytes,
            cancellation_check=cancellation_check,
        ) as stream:
            yield stream

    monkeypatch.setattr(data_service_module, "_spooled_copy", swap_rmf_then_spool)
    state = StateManager()
    result = DataService(state).load_event_list(
        str(events),
        "events",
        fmt="ogip",
        rmf_file=str(rmf),
        file_grant=event_grant,
        rmf_grant=rmf_grant,
    )

    assert result["success"] is True
    assert state.get_event_data("events").energy.tolist() == [1.0, 2.0]


def test_gzip_ogip_load_is_preserved_without_reopening_selected_path(
    tmp_path: Path,
) -> None:
    uncompressed = tmp_path / "events.evt"
    selected = tmp_path / "events.evt.gz"
    _write_event_fits(uncompressed)
    with uncompressed.open("rb") as source, gzip.open(selected, "wb") as target:
        shutil.copyfileobj(source, target)

    result = DataService(StateManager()).load_event_list(
        str(selected), "events", fmt="ogip", file_grant=_grant(selected)
    )

    assert result["success"] is True
    assert result["data"]["n_events"] == 2
    assert "stingray-input-" not in repr(result)


def test_batch_rejects_one_bad_grant_before_any_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.hdf5"
    second = tmp_path / "second.hdf5"
    _write_hdf5(first, [1.0, 2.0])
    _write_hdf5(second, [3.0, 4.0])
    service = DataService(StateManager())
    monkeypatch.setattr(
        service,
        "load_event_list",
        lambda *args, **kwargs: pytest.fail("load started before batch pinning"),
    )

    with pytest.raises(PermissionError):
        service.load_batch_event_lists(
            [
                {
                    "file_path": str(first),
                    "file_grant": _grant(first),
                    "name": "first",
                },
                {
                    "file_path": str(second),
                    "file_grant": "forged",
                    "name": "second",
                },
            ]
        )


def test_shared_rmf_batch_is_serialized_to_avoid_seek_races(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = []
    for index in range(3):
        path = tmp_path / f"events-{index}.evt"
        path.write_bytes(b"placeholder")
        files.append(
            {
                "file_path": str(path),
                "file_grant": _grant(path),
                "name": f"events-{index}",
            }
        )
    rmf = tmp_path / "shared.rmf"
    rmf.write_bytes(b"placeholder")
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def fake_load(*args, **kwargs):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {
            "success": True,
            "data": {"n_events": 1},
            "message": "loaded",
            "error": None,
        }

    service = DataService(StateManager())
    monkeypatch.setattr(service, "load_event_list", fake_load)
    result = service.load_batch_event_lists(
        files,
        shared_rmf_file=str(rmf),
        shared_rmf_grant=_grant(rmf),
        max_workers=3,
    )

    assert result["success"] is True
    assert result["data"]["summary"]["workers_used"] == 1
    assert maximum_active == 1


class _CapturingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...]]] = []
        self.futures: list[Future] = []

    def submit(self, target, *args) -> Future:
        future = Future()
        self.calls.append((target, args))
        self.futures.append(future)
        return future

    def shutdown(self, *args, **kwargs) -> None:
        if kwargs.get("cancel_futures"):
            for future in self.futures:
                future.cancel()
        return None


def _manager_with_captured_executor(
    state: StateManager,
) -> tuple[JobManager, _CapturingExecutor]:
    manager = JobManager(state, DataService(state), max_workers=1)
    manager._executor.shutdown(wait=False, cancel_futures=True)
    executor = _CapturingExecutor()
    manager._executor = executor
    return manager, executor


def test_queued_job_pins_before_return_redacts_and_cleans_after_success(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected.hdf5"
    original = tmp_path / "original.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    state = StateManager()
    manager, executor = _manager_with_captured_executor(state)
    job = manager.submit_load_job(
        str(selected),
        "events",
        fmt="hdf5",
        file_grant=_grant(selected),
    )
    public = job.to_dict()
    assert "params" not in public
    assert str(selected) not in repr(public)
    assert job.id in manager._resources

    selected.rename(original)
    _write_hdf5(selected, [90.0, 91.0])
    target, args = executor.calls[0]
    target(*args)
    executor.futures[0].set_result(None)

    assert job.status.value == "completed"
    assert state.get_event_data("events").time.tolist() == [1.0, 2.0]
    assert job.id not in manager._resources
    assert str(selected) not in repr(job.to_dict())


def test_pending_job_cancel_closes_private_descriptor_and_redacts_updates(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    manager, _executor = _manager_with_captured_executor(StateManager())
    job = manager.submit_load_job(
        str(selected),
        "events",
        fmt="hdf5",
        file_grant=_grant(selected),
    )
    source = manager._resources[job.id].private["file_source"]

    assert manager.cancel_job(job.id) is True
    assert source.stream.closed is True
    assert job.id not in manager._resources
    updates = list(manager._update_queue.queue)
    assert "job_failed" not in {update["type"] for update in updates}
    assert str(selected) not in repr(updates)
    assert "file_grant" not in repr(updates)


def test_running_job_cancel_defers_close_until_worker_exits(tmp_path: Path) -> None:
    selected = tmp_path / "selected.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    manager, executor = _manager_with_captured_executor(StateManager())
    job = manager.submit_load_job(
        str(selected),
        "events",
        fmt="hdf5",
        file_grant=_grant(selected),
    )
    source = manager._resources[job.id].private["file_source"]
    assert executor.futures[0].set_running_or_notify_cancel() is True
    job.start()

    assert manager.cancel_job(job.id) is True
    assert source.stream.closed is False
    assert manager.clear_completed_jobs() == 0
    assert manager.get_job(job.id) is job
    assert source.stream.closed is False
    target, args = executor.calls[0]
    target(*args)
    executor.futures[0].set_result(None)

    assert job.status.value == "cancelled"
    assert source.stream.closed is True
    assert job.id not in manager._resources


def test_url_job_failure_redacts_url_and_cleans_pinned_rmf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rmf = tmp_path / "private-calibration.rmf"
    rmf.write_bytes(b"calibration")
    state = StateManager()
    manager, executor = _manager_with_captured_executor(state)

    def fail_remote_load(*args, **kwargs):
        raise RuntimeError(
            "do not expose https://user:password@example.test/file?token=secret"
        )

    monkeypatch.setattr(
        manager._data_service, "load_event_list_from_url", fail_remote_load
    )
    supplied_url = "https://example.test/events.evt?private=query"
    job = manager.submit_url_load_job(
        supplied_url,
        "events",
        rmf_file=str(rmf),
        rmf_grant=_grant(rmf),
    )
    source = manager._resources[job.id].private["rmf_source"]
    assert supplied_url not in repr(job.to_dict())

    target, args = executor.calls[0]
    target(*args)
    executor.futures[0].set_result(None)

    public = job.to_dict()
    assert job.status.value == "failed"
    assert public["error"] == "The background job could not be completed"
    assert supplied_url not in repr(public)
    assert str(rmf) not in repr(public)
    assert source.stream.closed is True
    assert job.id not in manager._resources


def test_batch_job_pins_all_inputs_before_return_and_cleans_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [tmp_path / "first.hdf5", tmp_path / "second.hdf5"]
    for index, path in enumerate(paths):
        _write_hdf5(path, [float(index + 1), float(index + 2)])
    state = StateManager()
    manager, executor = _manager_with_captured_executor(state)

    def fail_load(*args, **kwargs):
        raise RuntimeError(f"do not expose {paths[0]}")

    monkeypatch.setattr(manager._data_service, "load_event_list", fail_load)
    job = manager.submit_batch_load_job(
        [
            {
                "file_path": str(path),
                "file_grant": _grant(path),
                "name": f"events-{index}",
            }
            for index, path in enumerate(paths)
        ]
    )
    sources = list(manager._resources[job.id].private["file_sources"])
    assert all(not source.stream.closed for source in sources)
    assert all(str(path) not in repr(job.to_dict()) for path in paths)

    target, args = executor.calls[0]
    target(*args)
    executor.futures[0].set_result(None)

    assert job.status.value == "failed"
    assert all(source.stream.closed for source in sources)
    assert job.id not in manager._resources
    assert all(str(path) not in repr(job.to_dict()) for path in paths)


def test_shutdown_cancels_pending_job_and_closes_capabilities(tmp_path: Path) -> None:
    selected = tmp_path / "selected.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    manager, _executor = _manager_with_captured_executor(StateManager())
    job = manager.submit_load_job(
        str(selected),
        "events",
        fmt="hdf5",
        file_grant=_grant(selected),
    )
    source = manager._resources[job.id].private["file_source"]

    manager.shutdown()

    assert job.status.value == "cancelled"
    assert "job_failed" not in {
        update["type"] for update in manager._update_queue.queue
    }
    assert source.stream.closed is True
    assert job.id not in manager._resources


def test_shutdown_marks_running_job_cancelled_and_cleans_after_worker_exit(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "selected.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    manager, executor = _manager_with_captured_executor(StateManager())
    job = manager.submit_load_job(
        str(selected),
        "events",
        fmt="hdf5",
        file_grant=_grant(selected),
    )
    source = manager._resources[job.id].private["file_source"]
    assert executor.futures[0].set_running_or_notify_cancel() is True

    manager.shutdown()

    assert job.status.value == "cancelled"
    assert source.stream.closed is False
    target, args = executor.calls[0]
    target(*args)
    executor.futures[0].set_result(None)
    assert source.stream.closed is True
    assert job.id not in manager._resources


def test_job_public_result_recursively_drops_capability_fields() -> None:
    job = Job(
        result={
            "n_events": 2,
            "time_range": [1.0, 2.0],
            "notes": "opened /private/source.evt with token=secret",
            "message": "https://user:secret@example.test/file?token=x",
            "stingray_warnings": ["unclosed /private/source.evt"],
            "nested": {
                "source_url": "https://user:secret@example.test/file?token=x",
                "file_path": "/private/file",
            },
        }
    )
    job.fail("do not expose /private/file or https://example.test/?token=x")

    public = job.to_dict()
    assert "params" not in public
    assert public["result"] == {
        "event_count": 2,
        "time_start": 1.0,
        "time_end": 2.0,
        "warnings": ["The scientific reader reported warnings"],
    }
    assert public["error"] == "The background job could not be completed"
    assert public["progress_message"] == "Failed"
    assert "/private/file" not in repr(public)
    assert "token=secret" not in repr(public)


def test_scientific_failures_do_not_expose_native_or_private_paths(
    tmp_path: Path,
) -> None:
    selected = tmp_path / "private-secret-events.hdf5"
    selected.write_bytes(b"not hdf5")
    result = DataService(StateManager()).load_event_list(
        str(selected), "events", fmt="hdf5", file_grant=_grant(selected)
    )

    assert result["success"] is False
    assert result["error"] == "event_read_failed"
    assert str(selected) not in repr(result)
    assert "stingray-input-" not in repr(result)


def test_remote_loader_uses_general_policy_cap_and_returns_no_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "events.hdf5"
    _write_hdf5(source, [1.0, 2.0])
    body = source.read_bytes()
    observed: dict[str, Any] = {}

    class FakeRemoteStream:
        def __init__(self) -> None:
            self.info = SimpleNamespace(content_length=len(body))
            self.bytes_read = 0

        async def aiter_bytes(self):
            self.bytes_read = len(body)
            yield body

    class FakeRemoteClient:
        def __init__(self, policy) -> None:
            observed["policy"] = policy

        @asynccontextmanager
        async def stream(self, url, *, max_bytes, cancellation_check=None):
            observed["url"] = url
            observed["max_bytes"] = max_bytes
            yield FakeRemoteStream()

    monkeypatch.setattr(data_service_module, "RemoteSourceClient", FakeRemoteClient)
    supplied = "https://example.test/events.hdf5?private=query"
    result = DataService(StateManager()).load_event_list_from_url(
        supplied, "events", fmt="hdf5"
    )

    assert result["success"] is True
    assert observed["policy"] is GENERAL_HTTPS_POLICY
    assert observed["max_bytes"] == data_service_module.REMOTE_EVENT_LIMIT
    assert supplied not in repr(result)


def test_direct_remote_load_pins_optional_rmf_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = tmp_path / "events.evt"
    selected_rmf = tmp_path / "selected.rmf"
    original_rmf = tmp_path / "original.rmf"
    _write_event_fits(events)
    _write_rmf(selected_rmf, (1.0, 2.0))
    body = events.read_bytes()

    class FakeRemoteStream:
        info = SimpleNamespace(content_length=len(body))
        bytes_read = 0

        async def aiter_bytes(self):
            self.bytes_read = len(body)
            yield body

    class SwappingRemoteClient:
        def __init__(self, _policy) -> None:
            pass

        @asynccontextmanager
        async def stream(self, _url, *, max_bytes, cancellation_check=None):
            selected_rmf.rename(original_rmf)
            _write_rmf(selected_rmf, (100.0, 200.0))
            yield FakeRemoteStream()

    monkeypatch.setattr(data_service_module, "RemoteSourceClient", SwappingRemoteClient)
    state = StateManager()
    result = DataService(state).load_event_list_from_url(
        "https://example.test/events.evt",
        "events",
        fmt="ogip",
        rmf_file=str(selected_rmf),
        rmf_grant=_grant(selected_rmf),
    )

    assert result["success"] is True
    assert state.get_event_data("events").energy.tolist() == [1.0, 2.0]


def test_streaming_remote_load_pins_optional_rmf_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = tmp_path / "events.evt"
    selected_rmf = tmp_path / "selected.rmf"
    original_rmf = tmp_path / "original.rmf"
    _write_event_fits(events)
    _write_rmf(selected_rmf, (1.0, 2.0))
    body = events.read_bytes()

    class FakeRemoteStream:
        info = SimpleNamespace(content_length=len(body))
        bytes_read = 0

        async def aiter_bytes(self):
            self.bytes_read = len(body)
            yield body

    class SwappingRemoteClient:
        def __init__(self, _policy) -> None:
            pass

        @asynccontextmanager
        async def stream(self, _url, *, max_bytes, cancellation_check=None):
            selected_rmf.rename(original_rmf)
            _write_rmf(selected_rmf, (100.0, 200.0))
            yield FakeRemoteStream()

    monkeypatch.setattr(data_service_module, "RemoteSourceClient", SwappingRemoteClient)
    state = StateManager()
    service = DataService(state)

    async def collect_events():
        return [
            event
            async for event in service.load_event_list_from_url_stream(
                "https://example.test/events.evt",
                "events",
                fmt="ogip",
                rmf_file=str(selected_rmf),
                rmf_grant=_grant(selected_rmf),
            )
        ]

    streamed = asyncio.run(collect_events())

    assert streamed[-1]["type"] == "complete"
    assert state.get_event_data("events").energy.tolist() == [1.0, 2.0]


def test_remote_policy_failures_do_not_expose_any_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supplied = "https://example.test/private/events.evt?token=secret"

    class RejectingRemoteClient:
        def __init__(self, _policy) -> None:
            pass

        @asynccontextmanager
        async def stream(self, url, *, max_bytes, cancellation_check=None):
            raise RemoteSourceError(f"rejected {url}")
            yield  # pragma: no cover

    monkeypatch.setattr(
        data_service_module, "RemoteSourceClient", RejectingRemoteClient
    )
    service = DataService(StateManager())
    result = service.load_event_list_from_url(supplied, "events")

    async def collect_events():
        return [
            event
            async for event in service.load_event_list_from_url_stream(
                supplied, "streamed"
            )
        ]

    streamed = asyncio.run(collect_events())

    assert result["success"] is False
    assert "https://" not in repr(result)
    assert supplied not in repr(result)
    assert "https://" not in repr(streamed)
    assert supplied not in repr(streamed)


def test_job_submission_route_redacts_native_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    selected = "/private/selected/events.hdf5"
    grant = "private-grant-token"

    class RejectingManager:
        def submit_load_job(self, **_kwargs):
            raise OSError(f"could not open {selected} using {grant}")

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(job_manager=RejectingManager()))
    )
    body = SubmitLoadJobRequest(
        file_path=selected,
        file_grant=grant,
        name="events",
        fmt="hdf5",
    )
    with caplog.at_level(logging.ERROR):
        response = asyncio.run(submit_load_job(request, body))

    assert response.success is False
    assert response.error == "job_submission_rejected"
    assert selected not in repr(response)
    assert grant not in repr(response)
    assert selected not in caplog.text
    assert grant not in caplog.text


def test_data_route_maps_native_failure_to_sanitized_envelope(
    caplog: pytest.LogCaptureFixture,
) -> None:
    selected = "/private/selected/events.hdf5"
    grant = "private-grant-token"

    class RejectingService:
        def load_event_list(self, **_kwargs):
            raise OSError(f"could not open {selected} using {grant}")

    body = LoadEventListRequest(
        file_path=selected,
        file_grant=grant,
        name="events",
        fmt="hdf5",
    )
    with caplog.at_level(logging.ERROR):
        response = asyncio.run(load_event_list_route(body, RejectingService()))

    assert response["error"] == "data_input_rejected"
    assert selected not in repr(response)
    assert grant not in repr(response)
    assert selected not in caplog.text
    assert grant not in caplog.text


def test_stream_disconnect_signals_and_drains_worker_before_closing_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rmf = tmp_path / "selected.rmf"
    rmf.write_bytes(b"calibration")
    started = threading.Event()
    cancellation_seen = threading.Event()
    allow_worker_exit = threading.Event()
    observed: dict[str, Any] = {}

    class FakeRemoteStream:
        info = SimpleNamespace(content_length=4)
        bytes_read = 0

        async def aiter_bytes(self):
            self.bytes_read = 4
            yield b"data"

    class FakeRemoteClient:
        def __init__(self, _policy) -> None:
            pass

        @asynccontextmanager
        async def stream(self, _url, *, max_bytes, cancellation_check=None):
            yield FakeRemoteStream()

    service = DataService(StateManager())

    def wait_for_cancel(
        event_stream,
        _name,
        _fmt,
        _rmf_file,
        _rmf_grant,
        _columns,
        _high_precision,
        _skip_checks,
        _notes,
        rmf_source,
        cancellation_check,
    ):
        observed["rmf_source"] = rmf_source
        started.set()
        while not cancellation_check():
            time.sleep(0.001)
        cancellation_seen.set()
        assert allow_worker_exit.wait(2.0)
        observed["event_closed_during_worker"] = event_stream.closed
        observed["rmf_closed_during_worker"] = rmf_source.stream.closed
        return {"success": False, "message": "cancelled"}

    monkeypatch.setattr(data_service_module, "RemoteSourceClient", FakeRemoteClient)
    monkeypatch.setattr(service, "_load_remote_stream", wait_for_cancel)

    async def cancel_consumer() -> None:
        async def consume() -> None:
            async for _event in service.load_event_list_from_url_stream(
                "https://example.test/events.evt",
                "events",
                rmf_file=str(rmf),
                rmf_grant=_grant(rmf),
            ):
                pass

        task = asyncio.create_task(consume())
        assert await asyncio.to_thread(started.wait, 2.0)
        task.cancel()
        assert await asyncio.to_thread(cancellation_seen.wait, 2.0)
        task.cancel()
        await asyncio.sleep(0)
        assert observed["rmf_source"].stream.closed is False
        allow_worker_exit.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_consumer())

    assert observed["event_closed_during_worker"] is False
    assert observed["rmf_closed_during_worker"] is False
    assert observed["rmf_source"].stream.closed is True


def test_batch_stream_maps_bad_grant_to_sanitized_error(tmp_path: Path) -> None:
    selected = tmp_path / "private-events.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    service = DataService(StateManager())

    async def collect_events():
        return [
            event
            async for event in service.load_batch_event_lists_stream(
                [
                    {
                        "file_path": str(selected),
                        "file_grant": "forged-private-grant",
                        "name": "events",
                    }
                ]
            )
        ]

    events = asyncio.run(collect_events())

    assert events == [
        {
            "type": "error",
            "error": "The selected batch could not be admitted or loaded",
        }
    ]
    assert str(selected) not in repr(events)
    assert "forged-private-grant" not in repr(events)


def test_job_capability_budget_rejects_before_pinning_and_releases(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / "first.hdf5"
    second = tmp_path / "second.hdf5"
    _write_hdf5(first, [1.0, 2.0])
    _write_hdf5(second, [3.0, 4.0])
    monkeypatch.setattr(job_manager_module, "MAX_RETAINED_CAPABILITIES", 1)
    manager, _executor = _manager_with_captured_executor(StateManager())
    first_job = manager.submit_load_job(
        str(first), "first", fmt="hdf5", file_grant=_grant(first)
    )

    with pytest.raises(RuntimeError, match="capacity"):
        manager.submit_load_job(
            str(second), "second", fmt="hdf5", file_grant=_grant(second)
        )

    assert manager._reserved_jobs == 1
    assert manager._retained_capabilities == 1
    assert manager.cancel_job(first_job.id) is True
    assert manager._reserved_jobs == 0
    assert manager._retained_capabilities == 0


def test_job_reservation_released_when_grant_pin_fails(tmp_path: Path) -> None:
    selected = tmp_path / "selected.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    manager, _executor = _manager_with_captured_executor(StateManager())

    with pytest.raises(PermissionError):
        manager.submit_load_job(
            str(selected), "events", fmt="hdf5", file_grant="forged"
        )

    assert manager._reserved_jobs == 0
    assert manager._retained_capabilities == 0


def test_cancel_wins_against_inflight_completion(tmp_path: Path) -> None:
    selected = tmp_path / "selected.hdf5"
    _write_hdf5(selected, [1.0, 2.0])
    manager, executor = _manager_with_captured_executor(StateManager())
    started = threading.Event()
    finish = threading.Event()

    def delayed_success(*_args, **_kwargs):
        started.set()
        assert finish.wait(2.0)
        return {"success": True, "data": {"n_events": 2}}

    manager._data_service.load_event_list = delayed_success
    job = manager.submit_load_job(
        str(selected), "events", fmt="hdf5", file_grant=_grant(selected)
    )
    source = manager._resources[job.id].private["file_source"]
    assert executor.futures[0].set_running_or_notify_cancel() is True
    target, args = executor.calls[0]
    worker = threading.Thread(target=target, args=args)
    worker.start()
    assert started.wait(2.0)

    assert manager.cancel_job(job.id) is True
    finish.set()
    worker.join(timeout=2.0)
    assert not worker.is_alive()
    executor.futures[0].set_result(None)

    assert job.status.value == "cancelled"
    assert source.stream.closed is True
    event_types = [update["type"] for update in manager._update_queue.queue]
    assert "job_completed" not in event_types


def test_remote_scientific_failure_redacts_url_and_reader_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BadRemoteStream:
        info = SimpleNamespace(content_length=9)
        bytes_read = 0

        async def aiter_bytes(self):
            self.bytes_read = 9
            yield b"not-hdf5"

    class BadRemoteClient:
        def __init__(self, _policy) -> None:
            pass

        @asynccontextmanager
        async def stream(self, _url, *, max_bytes, cancellation_check=None):
            yield BadRemoteStream()

    monkeypatch.setattr(data_service_module, "RemoteSourceClient", BadRemoteClient)
    supplied = "https://example.test/events.hdf5?token=private"
    result = DataService(StateManager()).load_event_list_from_url(
        supplied, "events", fmt="hdf5"
    )

    assert result["success"] is False
    assert result["error"] == "event_read_failed"
    assert supplied not in repr(result)
    assert "token=private" not in repr(result)
