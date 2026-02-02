"""
API routes for EventList data operations.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Request
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


class LoadByEventCountRequest(BaseModel):
    """Request model for true lazy loading by event count."""
    file_path: str
    name: str
    start_index: int = 0
    count: int = 10000
    fmt: str = "ogip"


class GetFileMetadataRequest(BaseModel):
    """Request model for getting file metadata without loading."""
    file_path: str
    fmt: str = "ogip"


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
