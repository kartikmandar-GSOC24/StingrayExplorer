"""
API routes for EventList data operations.
"""

import asyncio
import json
import logging
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.event_formats import InputEventFormat
from services.data_service import DataService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_data_service(request: Request) -> DataService:
    """Get DataService instance from app state."""
    return DataService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


async def _run_data_operation(operation: str, target, /, *args, **kwargs):
    """Keep admission/native-reader exceptions inside the API envelope."""
    try:
        return await asyncio.to_thread(target, *args, **kwargs)
    except Exception as error:
        logger.error("Data operation %s failed (%s)", operation, type(error).__name__)
        return {
            "success": False,
            "data": None,
            "message": "The selected input could not be admitted or read",
            "error": "data_input_rejected",
        }


# Request/Response Models
PathText = Annotated[str, Field(min_length=1, max_length=4096)]
GrantText = Annotated[str, Field(min_length=1, max_length=512)]
NameText = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$",
    ),
]
NoteText = Annotated[str, Field(max_length=4096)]
ColumnText = Annotated[str, Field(min_length=1, max_length=64)]
TimeValue = Annotated[float, Field(ge=-1.0e15, le=1.0e15)]


class StrictRequest(BaseModel):
    """Bounded request base that rejects silently ignored fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class OptionalRmfRequest(StrictRequest):
    """Require an RMF path and native read grant as one indivisible pair."""

    rmf_file: Optional[PathText] = None
    rmf_grant: Optional[GrantText] = None

    @model_validator(mode="after")
    def require_complete_rmf_pair(self):
        if (self.rmf_file is None) != (self.rmf_grant is None):
            raise ValueError("rmf_file and rmf_grant must be provided together")
        return self


class GrantedInputRequest(StrictRequest):
    file_path: PathText
    file_grant: GrantText


class LoadEventListRequest(OptionalRmfRequest):
    file_path: PathText
    file_grant: GrantText
    name: NameText
    fmt: InputEventFormat = "ogip"
    additional_columns: Optional[List[ColumnText]] = Field(default=None, max_length=64)
    high_precision: bool = False
    skip_checks: bool = False
    notes: Optional[NoteText] = None


class LoadEventListFromUrlRequest(OptionalRmfRequest):
    url: Annotated[str, Field(min_length=1, max_length=4096)]
    name: NameText
    fmt: InputEventFormat = "ogip"
    additional_columns: Optional[List[ColumnText]] = Field(default=None, max_length=64)
    high_precision: bool = False
    skip_checks: bool = False
    notes: Optional[NoteText] = None


class CheckFileSizeRequest(GrantedInputRequest):
    pass


class LoadByTimeRangeRequest(GrantedInputRequest):
    """Request model for true lazy loading by time range."""

    name: NameText
    start_time: TimeValue
    end_time: TimeValue
    fmt: InputEventFormat = "ogip"
    notes: Optional[NoteText] = None

    @model_validator(mode="after")
    def require_ordered_time_range(self):
        if self.start_time >= self.end_time:
            raise ValueError("start_time must be less than end_time")
        return self


class LoadByEventCountRequest(GrantedInputRequest):
    """Request model for true lazy loading by event count."""

    name: NameText
    start_index: int = Field(default=0, ge=0, le=100_000_000)
    count: int = Field(default=10000, ge=1, le=10_000_000)
    fmt: InputEventFormat = "ogip"
    notes: Optional[NoteText] = None


class GetFileMetadataRequest(GrantedInputRequest):
    """Request model for getting file metadata without loading."""

    fmt: InputEventFormat = "ogip"


class SingleFileConfig(OptionalRmfRequest):
    """Configuration for a single file in batch load."""

    file_path: PathText
    file_grant: GrantText
    name: NameText
    fmt: InputEventFormat = "ogip"
    additional_columns: Optional[List[ColumnText]] = Field(default=None, max_length=64)
    high_precision: bool = False
    skip_checks: bool = False
    # Per-file partial loading (only used if use_same_settings=False)
    use_partial_loading: bool = False
    partial_mode: Literal["time_range", "event_count"] = "time_range"
    time_range_start: Optional[TimeValue] = None
    time_range_end: Optional[TimeValue] = None
    event_start_index: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    event_count: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    # Per-file notes
    notes: Optional[NoteText] = None

    @model_validator(mode="after")
    def require_complete_partial_settings(self):
        if not self.use_partial_loading:
            return self
        if self.partial_mode == "time_range":
            if self.time_range_start is None or self.time_range_end is None:
                raise ValueError("partial time-range loading requires both endpoints")
            if self.time_range_start >= self.time_range_end:
                raise ValueError("time_range_start must be less than time_range_end")
        elif self.event_count is None:
            raise ValueError("partial event-count loading requires event_count")
        return self


class BatchLoadEventListRequest(StrictRequest):
    """Request for batch loading multiple files."""

    files: List[SingleFileConfig] = Field(min_length=1, max_length=32)

    # Toggle: same settings vs per-file
    use_same_settings: bool = True

    # Shared settings (used when use_same_settings=True)
    shared_fmt: InputEventFormat = "ogip"
    shared_rmf_file: Optional[PathText] = None
    shared_rmf_grant: Optional[GrantText] = None
    shared_additional_columns: Optional[List[ColumnText]] = Field(
        default=None, max_length=64
    )
    shared_high_precision: bool = False
    shared_skip_checks: bool = False
    shared_use_partial_loading: bool = False
    shared_partial_mode: Literal["time_range", "event_count"] = "time_range"
    shared_time_range_start: Optional[TimeValue] = None
    shared_time_range_end: Optional[TimeValue] = None
    shared_event_start_index: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    shared_event_count: Optional[int] = Field(default=None, ge=1, le=10_000_000)

    @model_validator(mode="after")
    def require_complete_shared_rmf_pair(self):
        if (self.shared_rmf_file is None) != (self.shared_rmf_grant is None):
            raise ValueError(
                "shared_rmf_file and shared_rmf_grant must be provided together"
            )
        if self.shared_use_partial_loading and self.shared_partial_mode == "time_range":
            if (
                self.shared_time_range_start is None
                or self.shared_time_range_end is None
            ):
                raise ValueError(
                    "shared partial time-range loading requires both endpoints"
                )
            if self.shared_time_range_start >= self.shared_time_range_end:
                raise ValueError(
                    "shared_time_range_start must be less than shared_time_range_end"
                )
        elif self.shared_use_partial_loading and self.shared_event_count is None:
            raise ValueError(
                "shared partial event-count loading requires shared_event_count"
            )
        return self


class BatchFileSizeRequest(StrictRequest):
    """Request for checking batch file sizes."""

    files: List[GrantedInputRequest] = Field(min_length=1, max_length=32)


# Routes
@router.post("/load")
async def load_event_list(
    request: LoadEventListRequest,
    service: DataService = Depends(get_data_service),
):
    """Load an EventList from a file.

    Uses asyncio.to_thread() to avoid blocking the event loop,
    allowing other async operations (like resource monitoring) to continue.
    """
    return await _run_data_operation(
        "load",
        service.load_event_list,
        file_path=request.file_path,
        file_grant=request.file_grant,
        name=request.name,
        fmt=request.fmt,
        rmf_file=request.rmf_file,
        rmf_grant=request.rmf_grant,
        additional_columns=request.additional_columns,
        high_precision=request.high_precision,
        skip_checks=request.skip_checks,
        notes=request.notes,
    )


@router.post("/load-url")
async def load_event_list_from_url(
    request: LoadEventListFromUrlRequest,
    service: DataService = Depends(get_data_service),
):
    """Load an EventList from a URL.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    """
    return await _run_data_operation(
        "remote_load",
        service.load_event_list_from_url,
        url=request.url,
        name=request.name,
        fmt=request.fmt,
        rmf_file=request.rmf_file,
        rmf_grant=request.rmf_grant,
        additional_columns=request.additional_columns,
        high_precision=request.high_precision,
        skip_checks=request.skip_checks,
        notes=request.notes,
    )


@router.post("/load-url-stream")
async def load_event_list_from_url_stream(
    request: LoadEventListFromUrlRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Load an EventList from a URL with SSE streaming for progress updates.

    Returns Server-Sent Events (SSE) with download and processing progress,
    allowing the frontend to show real-time download progress.

    SSE Event Format:
    - type: "progress" - Download progress with bytes_downloaded, total_bytes, percent
    - type: "processing" - Download complete, now loading event list
    - type: "complete" - Successfully loaded, includes data summary
    - type: "error" - An error occurred
    """

    async def event_generator():
        async for event in service.load_event_list_from_url_stream(
            url=request.url,
            name=request.name,
            fmt=request.fmt,
            rmf_file=request.rmf_file,
            rmf_grant=request.rmf_grant,
            additional_columns=request.additional_columns,
            high_precision=request.high_precision,
            skip_checks=request.skip_checks,
            notes=request.notes,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{name}")
async def delete_event_list(
    name: NameText,
    service: DataService = Depends(get_data_service),
):
    """Delete an EventList from state."""
    return service.delete_event_list(name)


@router.get("/{name}")
async def get_event_list_info(
    name: NameText,
    service: DataService = Depends(get_data_service),
):
    """Get information about an EventList."""
    return service.get_event_list_info(name)


@router.get("/")
async def list_event_lists(
    service: DataService = Depends(get_data_service),
):
    """List all loaded EventLists."""
    return service.list_event_lists()


@router.post("/check-size")
async def check_file_size(
    request: CheckFileSizeRequest,
    service: DataService = Depends(get_data_service),
):
    """Check file size and get loading recommendations."""
    return await _run_data_operation(
        "size_check",
        service.check_file_size,
        request.file_path,
        request.file_grant,
    )


@router.delete("/")
async def clear_all_event_lists(
    service: DataService = Depends(get_data_service),
):
    """Clear all loaded EventLists from memory."""
    return service.clear_all_event_lists()


@router.get("/{name}/full-preview")
async def get_event_list_full_preview(
    name: NameText,
    # HTTP query values are text; FastAPI must parse them before enforcing bounds.
    time_limit: Annotated[int, Query(ge=1, le=10_000)] = 10,
    service: DataService = Depends(get_data_service),
):
    """Get full preview of an EventList with all attributes."""
    return service.get_event_list_full_preview(name=name, time_limit=time_limit)


# =========================================================================
# PARTIAL LOADING ROUTES
# These endpoints use FITSTimeseriesReader to load only a portion of the file
# =========================================================================


@router.post("/load-by-time-range")
async def load_event_list_by_time_range(
    request: LoadByTimeRangeRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Load events within a specific time range using true lazy loading.

    Uses FITSTimeseriesReader to load only events within the specified
    time window without reading the entire file into memory.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    """
    return await _run_data_operation(
        "time_range_load",
        service.load_event_list_by_time_range,
        file_path=request.file_path,
        file_grant=request.file_grant,
        name=request.name,
        start_time=request.start_time,
        end_time=request.end_time,
        fmt=request.fmt,
        notes=request.notes,
    )


@router.post("/load-by-event-count")
async def load_event_list_by_event_count(
    request: LoadByEventCountRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Load a specific number of events using true lazy loading.

    Uses FITSTimeseriesReader slicing to load only the requested events
    without reading the entire file into memory.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    """
    return await _run_data_operation(
        "event_count_load",
        service.load_event_list_by_event_count,
        file_path=request.file_path,
        file_grant=request.file_grant,
        name=request.name,
        start_index=request.start_index,
        count=request.count,
        fmt=request.fmt,
        notes=request.notes,
    )


@router.post("/metadata")
async def get_file_metadata(
    request: GetFileMetadataRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Get metadata from a FITS file without loading the full data.

    Returns file info, event count, time range, GTI, and loading recommendations
    without loading any event data into memory.

    Uses asyncio.to_thread() to avoid blocking the event loop.
    """
    return await _run_data_operation(
        "metadata",
        service.get_file_metadata,
        file_path=request.file_path,
        file_grant=request.file_grant,
        fmt=request.fmt,
    )


# =========================================================================
# BATCH LOADING ROUTES
# Load multiple files in parallel
# =========================================================================


@router.post("/check-batch-size")
async def check_batch_file_size(
    request: BatchFileSizeRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Check sizes of multiple files and estimate total memory usage.

    Returns per-file and total memory estimates with risk levels.
    """
    return await _run_data_operation(
        "batch_size_check",
        service.check_batch_file_size,
        files=[item.model_dump() for item in request.files],
    )


@router.post("/load-batch")
async def load_batch_event_lists(
    request: BatchLoadEventListRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Load multiple EventLists in parallel using threads.

    Supports two modes:
    - use_same_settings=True: Apply shared_* settings to all files
    - use_same_settings=False: Use per-file settings from each SingleFileConfig

    Returns aggregated results with successful[], failed[], and summary stats.

    Note: Uses asyncio.to_thread() to avoid blocking the event loop,
    allowing other async operations (like resource monitoring) to continue.
    """
    # Convert Pydantic models to dicts for the service
    files_dict = [f.model_dump() for f in request.files]

    # Run the blocking batch load in a thread to avoid blocking the event loop
    return await _run_data_operation(
        "batch_load",
        service.load_batch_event_lists,
        files=files_dict,
        use_same_settings=request.use_same_settings,
        shared_fmt=request.shared_fmt,
        shared_rmf_file=request.shared_rmf_file,
        shared_rmf_grant=request.shared_rmf_grant,
        shared_additional_columns=request.shared_additional_columns,
        shared_high_precision=request.shared_high_precision,
        shared_skip_checks=request.shared_skip_checks,
        shared_use_partial_loading=request.shared_use_partial_loading,
        shared_partial_mode=request.shared_partial_mode,
        shared_time_range_start=request.shared_time_range_start,
        shared_time_range_end=request.shared_time_range_end,
        shared_event_start_index=request.shared_event_start_index,
        shared_event_count=request.shared_event_count,
    )


@router.post("/load-batch-stream")
async def load_batch_event_lists_stream(
    request: BatchLoadEventListRequest,
    service: DataService = Depends(get_data_service),
):
    """
    Stream batch loading results via Server-Sent Events (SSE).

    Returns individual file completion events as they finish, allowing
    the frontend to update progress in real-time rather than waiting
    for all files to complete.

    SSE Event Format:
    - type: "file_complete" - A single file finished (success or failure)
    - type: "complete" - All files finished, includes summary stats
    - type: "error" - Pre-validation error (e.g., duplicate names)

    This endpoint is preferred for batch loading multiple files,
    especially when some files may be significantly larger than others.
    """
    files_dict = [f.model_dump() for f in request.files]

    async def event_generator():
        async for event in service.load_batch_event_lists_stream(
            files=files_dict,
            use_same_settings=request.use_same_settings,
            shared_fmt=request.shared_fmt,
            shared_rmf_file=request.shared_rmf_file,
            shared_rmf_grant=request.shared_rmf_grant,
            shared_additional_columns=request.shared_additional_columns,
            shared_high_precision=request.shared_high_precision,
            shared_skip_checks=request.shared_skip_checks,
            shared_use_partial_loading=request.shared_use_partial_loading,
            shared_partial_mode=request.shared_partial_mode,
            shared_time_range_start=request.shared_time_range_start,
            shared_time_range_end=request.shared_time_range_end,
            shared_event_start_index=request.shared_event_start_index,
            shared_event_count=request.shared_event_count,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind proxy
            "X-Content-Type-Options": "nosniff",
        },
    )
