"""
API routes for EventList data operations.
"""

import asyncio
import json
from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.data_service import DataService
from services.state_manager import StateManager

router = APIRouter()


def get_data_service(request: Request) -> DataService:
    """Get DataService instance from app state."""
    return DataService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


# Request/Response Models
class LoadEventListRequest(BaseModel):
    file_path: str
    name: str
    fmt: str = "ogip"
    rmf_file: Optional[str] = None
    additional_columns: Optional[List[str]] = None
    high_precision: bool = False
    skip_checks: bool = False
    notes: Optional[str] = None


class LoadEventListFromUrlRequest(BaseModel):
    url: str
    name: str
    fmt: str = "ogip"
    rmf_file: Optional[str] = None
    additional_columns: Optional[List[str]] = None
    high_precision: bool = False
    skip_checks: bool = False


class SaveEventListRequest(BaseModel):
    name: str
    file_path: str
    fmt: str = "ogip"


class CheckFileSizeRequest(BaseModel):
    file_path: str


class LoadByTimeRangeRequest(BaseModel):
    """Request model for true lazy loading by time range."""
    file_path: str
    name: str
    start_time: float
    end_time: float
    fmt: str = "ogip"
    notes: Optional[str] = None


class LoadByEventCountRequest(BaseModel):
    """Request model for true lazy loading by event count."""
    file_path: str
    name: str
    start_index: int = 0
    count: int = 10000
    fmt: str = "ogip"
    notes: Optional[str] = None


class GetFileMetadataRequest(BaseModel):
    """Request model for getting file metadata without loading."""
    file_path: str
    fmt: str = "ogip"


class SingleFileConfig(BaseModel):
    """Configuration for a single file in batch load."""
    file_path: str
    name: str
    fmt: str = "ogip"
    rmf_file: Optional[str] = None
    additional_columns: Optional[List[str]] = None
    high_precision: bool = False
    skip_checks: bool = False
    # Per-file partial loading (only used if use_same_settings=False)
    use_partial_loading: bool = False
    partial_mode: str = "time_range"
    time_range_start: Optional[float] = None
    time_range_end: Optional[float] = None
    event_start_index: Optional[int] = None
    event_count: Optional[int] = None
    # Per-file notes
    notes: Optional[str] = None


class BatchLoadEventListRequest(BaseModel):
    """Request for batch loading multiple files."""
    files: List[SingleFileConfig]

    # Toggle: same settings vs per-file
    use_same_settings: bool = True

    # Shared settings (used when use_same_settings=True)
    shared_fmt: str = "ogip"
    shared_rmf_file: Optional[str] = None
    shared_additional_columns: Optional[List[str]] = None
    shared_high_precision: bool = False
    shared_skip_checks: bool = False
    shared_use_partial_loading: bool = False
    shared_partial_mode: str = "time_range"
    shared_time_range_start: Optional[float] = None
    shared_time_range_end: Optional[float] = None
    shared_event_start_index: Optional[int] = None
    shared_event_count: Optional[int] = None


class BatchFileSizeRequest(BaseModel):
    """Request for checking batch file sizes."""
    file_paths: List[str]


# Routes
@router.post("/load")
async def load_event_list(
    request: LoadEventListRequest,
    service: DataService = Depends(get_data_service),
):
    """Load an EventList from a file."""
    return service.load_event_list(
        file_path=request.file_path,
        name=request.name,
        fmt=request.fmt,
        rmf_file=request.rmf_file,
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
    """Load an EventList from a URL."""
    return service.load_event_list_from_url(
        url=request.url,
        name=request.name,
        fmt=request.fmt,
        rmf_file=request.rmf_file,
        additional_columns=request.additional_columns,
        high_precision=request.high_precision,
        skip_checks=request.skip_checks,
    )


@router.post("/save")
async def save_event_list(
    request: SaveEventListRequest,
    service: DataService = Depends(get_data_service),
):
    """Save an EventList to disk."""
    return service.save_event_list(
        name=request.name,
        file_path=request.file_path,
        fmt=request.fmt,
    )


@router.delete("/{name}")
async def delete_event_list(
    name: str,
    service: DataService = Depends(get_data_service),
):
    """Delete an EventList from state."""
    return service.delete_event_list(name)


@router.get("/{name}")
async def get_event_list_info(
    name: str,
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
    return service.check_file_size(request.file_path)


@router.delete("/")
async def clear_all_event_lists(
    service: DataService = Depends(get_data_service),
):
    """Clear all loaded EventLists from memory."""
    return service.clear_all_event_lists()


@router.get("/{name}/full-preview")
async def get_event_list_full_preview(
    name: str,
    time_limit: int = 10,
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
    """
    return service.load_event_list_by_time_range(
        file_path=request.file_path,
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
    """
    return service.load_event_list_by_event_count(
        file_path=request.file_path,
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
    """
    return service.get_file_metadata(
        file_path=request.file_path,
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
    return service.check_batch_file_size(file_paths=request.file_paths)


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
    return await asyncio.to_thread(
        service.load_batch_event_lists,
        files=files_dict,
        use_same_settings=request.use_same_settings,
        shared_fmt=request.shared_fmt,
        shared_rmf_file=request.shared_rmf_file,
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
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind proxy
        },
    )
