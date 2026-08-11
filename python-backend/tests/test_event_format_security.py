"""Regression coverage for the EventList format security boundary."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

import services.data_service as data_service_module
import services.job_manager as job_manager_module
from main import create_app
from models.event_formats import (
    CANONICAL_INPUT_EVENT_FORMATS,
    INPUT_EVENT_FORMATS,
    OUTPUT_EVENT_FORMATS,
    require_input_event_format,
    require_output_event_format,
)
from routes.data_routes import (
    BatchLoadEventListRequest,
    GetFileMetadataRequest,
    LoadByEventCountRequest,
    LoadByTimeRangeRequest,
    LoadEventListFromUrlRequest,
    LoadEventListRequest,
    SingleFileConfig,
)
from routes.job_routes import (
    FileConfig,
    SubmitBatchJobRequest,
    SubmitLoadJobRequest,
    SubmitUrlJobRequest,
)
from services.data_service import DataService
from services.job_manager import JobManager
from services.state_manager import StateManager
from tests.backend_auth import (
    TEST_BACKEND_AUTH_HEADERS,
    TEST_BACKEND_SESSION_SECRET,
)


UNSAFE_FORMATS = ("pickle", "unknown-format", "votable", "evt")
TEST_FILE_GRANT = "test-native-file-grant"

RequestBuilder = Callable[[str], BaseModel]
REQUEST_BUILDERS: tuple[tuple[str, RequestBuilder], ...] = (
    (
        "data-load",
        lambda fmt: LoadEventListRequest(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            name="events",
            fmt=fmt,
        ),
    ),
    (
        "data-load-url",
        lambda fmt: LoadEventListFromUrlRequest(
            url="https://example.test/events.evt", name="events", fmt=fmt
        ),
    ),
    (
        "data-time-range",
        lambda fmt: LoadByTimeRangeRequest(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            name="events",
            start_time=0.0,
            end_time=1.0,
            fmt=fmt,
        ),
    ),
    (
        "data-event-count",
        lambda fmt: LoadByEventCountRequest(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            name="events",
            fmt=fmt,
        ),
    ),
    (
        "data-metadata",
        lambda fmt: GetFileMetadataRequest(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            fmt=fmt,
        ),
    ),
    (
        "data-batch-item",
        lambda fmt: SingleFileConfig(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            name="events",
            fmt=fmt,
        ),
    ),
    (
        "data-batch-shared",
        lambda fmt: BatchLoadEventListRequest(
            files=[
                {
                    "file_path": "/selected/events.evt",
                    "file_grant": TEST_FILE_GRANT,
                    "name": "events",
                }
            ],
            shared_fmt=fmt,
        ),
    ),
    (
        "data-batch-per-file",
        lambda fmt: BatchLoadEventListRequest(
            files=[
                {
                    "file_path": "/selected/events.evt",
                    "file_grant": TEST_FILE_GRANT,
                    "name": "events",
                    "fmt": fmt,
                }
            ],
            use_same_settings=False,
        ),
    ),
    (
        "job-load",
        lambda fmt: SubmitLoadJobRequest(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            name="events",
            fmt=fmt,
        ),
    ),
    (
        "job-batch-item",
        lambda fmt: FileConfig(
            file_path="/selected/events.evt",
            file_grant=TEST_FILE_GRANT,
            name="events",
            fmt=fmt,
        ),
    ),
    (
        "job-batch-shared",
        lambda fmt: SubmitBatchJobRequest(
            files=[
                {
                    "file_path": "/selected/events.evt",
                    "file_grant": TEST_FILE_GRANT,
                    "name": "events",
                }
            ],
            shared_fmt=fmt,
        ),
    ),
    (
        "job-batch-per-file",
        lambda fmt: SubmitBatchJobRequest(
            files=[
                {
                    "file_path": "/selected/events.evt",
                    "file_grant": TEST_FILE_GRANT,
                    "name": "events",
                    "fmt": fmt,
                }
            ],
            use_same_settings=False,
        ),
    ),
    (
        "job-url",
        lambda fmt: SubmitUrlJobRequest(
            url="https://example.test/events.evt", name="events", fmt=fmt
        ),
    ),
)


@pytest.mark.parametrize("unsafe_format", UNSAFE_FORMATS)
@pytest.mark.parametrize(
    ("_case", "build_request"),
    REQUEST_BUILDERS,
    ids=[case for case, _builder in REQUEST_BUILDERS],
)
def test_request_models_reject_unsafe_input_formats(
    _case: str, build_request: RequestBuilder, unsafe_format: str
) -> None:
    with pytest.raises(ValidationError):
        build_request(unsafe_format)


@pytest.mark.parametrize("fmt", sorted(INPUT_EVENT_FORMATS))
@pytest.mark.parametrize(
    ("_case", "build_request"),
    REQUEST_BUILDERS,
    ids=[case for case, _builder in REQUEST_BUILDERS],
)
def test_request_models_preserve_supported_input_formats(
    _case: str, build_request: RequestBuilder, fmt: str
) -> None:
    data = build_request(fmt).model_dump()
    if "per-file" in _case:
        actual_format = data["files"][0]["fmt"]
    else:
        actual_format = data["shared_fmt" if "shared" in _case else "fmt"]
    assert actual_format == fmt


def test_batch_job_file_format_defaults_to_ogip_instead_of_none() -> None:
    config = FileConfig(
        file_path="/selected/events.evt",
        file_grant=TEST_FILE_GRANT,
        name="events",
    )
    assert config.fmt == "ogip"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint", ["/api/data/load-url", "/api/data/load-url-stream"]
)
@pytest.mark.parametrize("unsafe_format", UNSAFE_FORMATS)
async def test_url_routes_reject_unsafe_format_before_network(
    monkeypatch: pytest.MonkeyPatch, endpoint: str, unsafe_format: str
) -> None:
    def forbidden_network(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("network access occurred before format validation")

    monkeypatch.setattr(DataService, "load_event_list_from_url", forbidden_network)
    monkeypatch.setattr(
        DataService, "load_event_list_from_url_stream", forbidden_network
    )

    app = create_app(session_secret=TEST_BACKEND_SESSION_SECRET)
    app.state.state_manager = StateManager()
    app.state.performance_monitor = None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_BACKEND_AUTH_HEADERS,
    ) as client:
        response = await client.post(
            endpoint,
            json={
                "url": "https://example.test/events.evt",
                "name": "events",
                "fmt": unsafe_format,
            },
        )

    assert response.status_code == 422


class _ForbiddenState:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"state accessed before format validation: {name}")


def _forbidden_io(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("filesystem or network access occurred before validation")


@pytest.fixture()
def data_service_without_io(monkeypatch: pytest.MonkeyPatch) -> DataService:
    monkeypatch.setattr(httpx, "AsyncClient", _forbidden_io)
    monkeypatch.setattr(
        data_service_module.tempfile, "NamedTemporaryFile", _forbidden_io
    )
    monkeypatch.setattr(data_service_module.os.path, "getsize", _forbidden_io)
    monkeypatch.setattr(data_service_module.os, "makedirs", _forbidden_io)
    monkeypatch.setattr(data_service_module.fits, "open", _forbidden_io)
    monkeypatch.setattr(data_service_module, "FITSTimeseriesReader", _forbidden_io)
    monkeypatch.setattr(data_service_module.EventList, "read", _forbidden_io)
    monkeypatch.setattr(data_service_module, "ThreadPoolExecutor", _forbidden_io)
    monkeypatch.setattr(DataService, "_detect_fits_file_type", _forbidden_io)
    return DataService(state_manager=_ForbiddenState())


ServiceCall = Callable[[DataService, str], Any]
DIRECT_SERVICE_CALLS: tuple[tuple[str, ServiceCall], ...] = (
    (
        "local-load",
        lambda service, fmt: service.load_event_list(
            "/selected/events.h5", "events", fmt=fmt
        ),
    ),
    (
        "url-load",
        lambda service, fmt: service.load_event_list_from_url(
            "https://example.test/events.evt", "events", fmt=fmt
        ),
    ),
    (
        "time-range",
        lambda service, fmt: service.load_event_list_by_time_range(
            "/selected/events.evt", "events", 0.0, 1.0, fmt=fmt
        ),
    ),
    (
        "event-count",
        lambda service, fmt: service.load_event_list_by_event_count(
            "/selected/events.evt", "events", fmt=fmt
        ),
    ),
    (
        "metadata",
        lambda service, fmt: service.get_file_metadata("/selected/events.evt", fmt=fmt),
    ),
    (
        "memory-estimate",
        lambda service, fmt: service._estimate_memory_usage(100, fmt=fmt),
    ),
    (
        "memory-safety",
        lambda service, fmt: service._can_load_safely("/selected/events.evt", fmt=fmt),
    ),
    (
        "batch-shared",
        lambda service, fmt: service.load_batch_event_lists(
            [{"file_path": "/selected/events.evt", "name": "events"}],
            shared_fmt=fmt,
        ),
    ),
    (
        "batch-item",
        lambda service, fmt: service.load_batch_event_lists(
            [
                {
                    "file_path": "/selected/events.evt",
                    "name": "events",
                    "fmt": fmt,
                }
            ],
            use_same_settings=False,
        ),
    ),
    (
        "batch-ignored-item",
        lambda service, fmt: service.load_batch_event_lists(
            [
                {
                    "file_path": "/selected/events.evt",
                    "name": "events",
                    "fmt": fmt,
                }
            ],
            shared_fmt="ogip",
        ),
    ),
)


@pytest.mark.parametrize("unsafe_format", UNSAFE_FORMATS)
@pytest.mark.parametrize(
    ("_case", "invoke"),
    DIRECT_SERVICE_CALLS,
    ids=[case for case, _invoke in DIRECT_SERVICE_CALLS],
)
def test_direct_data_service_rejects_unsafe_input_before_io(
    data_service_without_io: DataService,
    _case: str,
    invoke: ServiceCall,
    unsafe_format: str,
) -> None:
    with pytest.raises(ValueError, match="Unsupported input EventList format"):
        invoke(data_service_without_io, unsafe_format)


@pytest.mark.asyncio
@pytest.mark.parametrize("unsafe_format", UNSAFE_FORMATS)
@pytest.mark.parametrize("stream_kind", ["url", "batch-shared", "batch-item"])
async def test_direct_streaming_services_reject_unsafe_input_before_io(
    data_service_without_io: DataService,
    unsafe_format: str,
    stream_kind: str,
) -> None:
    if stream_kind == "url":
        stream = data_service_without_io.load_event_list_from_url_stream(
            "https://example.test/events.evt", "events", fmt=unsafe_format
        )
    elif stream_kind == "batch-shared":
        stream = data_service_without_io.load_batch_event_lists_stream(
            [{"file_path": "/selected/events.evt", "name": "events"}],
            shared_fmt=unsafe_format,
        )
    else:
        stream = data_service_without_io.load_batch_event_lists_stream(
            [
                {
                    "file_path": "/selected/events.evt",
                    "name": "events",
                    "fmt": unsafe_format,
                }
            ],
            use_same_settings=False,
        )

    with pytest.raises(ValueError, match="Unsupported input EventList format"):
        await anext(stream)


def test_legacy_data_save_surface_is_retired() -> None:
    app = create_app(session_secret=TEST_BACKEND_SESSION_SECRET)
    route_paths = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("POST", "/api/data/save") not in route_paths
    assert not hasattr(DataService, "save_event_list")


class _NoSubmitExecutor:
    def __init__(self) -> None:
        self.submissions = 0

    def submit(self, *_args: Any, **_kwargs: Any) -> None:
        self.submissions += 1
        raise AssertionError("job scheduled before format validation")

    def shutdown(self, *_args: Any, **_kwargs: Any) -> None:
        return None


JobCall = Callable[[JobManager, str], Any]
DIRECT_JOB_CALLS: tuple[tuple[str, JobCall], ...] = (
    (
        "load",
        lambda manager, fmt: manager.submit_load_job(
            "/selected/events.evt", "events", fmt=fmt
        ),
    ),
    (
        "url",
        lambda manager, fmt: manager.submit_url_load_job(
            "https://example.test/events.evt", "events", fmt=fmt
        ),
    ),
    (
        "batch-shared",
        lambda manager, fmt: manager.submit_batch_load_job(
            [{"file_path": "/selected/events.evt", "name": "events"}],
            shared_fmt=fmt,
        ),
    ),
    (
        "batch-item",
        lambda manager, fmt: manager.submit_batch_load_job(
            [
                {
                    "file_path": "/selected/events.evt",
                    "name": "events",
                    "fmt": fmt,
                }
            ],
            use_same_settings=False,
        ),
    ),
    (
        "batch-ignored-item",
        lambda manager, fmt: manager.submit_batch_load_job(
            [
                {
                    "file_path": "/selected/events.evt",
                    "name": "events",
                    "fmt": fmt,
                }
            ],
            shared_fmt="ogip",
        ),
    ),
)


@pytest.mark.parametrize("unsafe_format", UNSAFE_FORMATS)
@pytest.mark.parametrize(
    ("_case", "invoke"),
    DIRECT_JOB_CALLS,
    ids=[case for case, _invoke in DIRECT_JOB_CALLS],
)
def test_job_manager_rejects_unsafe_formats_before_scheduling(
    monkeypatch: pytest.MonkeyPatch,
    _case: str,
    invoke: JobCall,
    unsafe_format: str,
) -> None:
    executor = _NoSubmitExecutor()
    monkeypatch.setattr(
        job_manager_module,
        "ThreadPoolExecutor",
        lambda **_kwargs: executor,
    )
    manager = JobManager(state_manager=object(), data_service=object())

    with pytest.raises(ValueError, match="Unsupported input EventList format"):
        invoke(manager, unsafe_format)

    assert executor.submissions == 0
    assert manager.list_jobs() == []
    assert manager._futures == {}
    assert manager._update_queue.empty()


@pytest.mark.parametrize("fmt", sorted(INPUT_EVENT_FORMATS))
def test_format_policy_preserves_supported_input_values(fmt: str) -> None:
    expected = "ogip" if fmt == "hea" else fmt
    assert require_input_event_format(fmt) == expected


def test_hea_is_only_a_compatibility_alias() -> None:
    assert "hea" in INPUT_EVENT_FORMATS
    assert "hea" not in CANONICAL_INPUT_EVENT_FORMATS
    assert require_input_event_format("hea") == "ogip"


@pytest.mark.parametrize("fmt", sorted(OUTPUT_EVENT_FORMATS))
def test_format_policy_preserves_supported_output_values(fmt: str) -> None:
    assert require_output_event_format(fmt) == fmt
