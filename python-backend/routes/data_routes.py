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


class LoadEventListFromUrlRequest(BaseModel):
    url: str
    name: str
    fmt: str = "ogip"


class SaveEventListRequest(BaseModel):
    name: str
    file_path: str
    fmt: str = "ogip"


class CheckFileSizeRequest(BaseModel):
    file_path: str


class LoadEventListLazyRequest(BaseModel):
    file_path: str
    name: str
    fmt: str = "ogip"
    rmf_file: Optional[str] = None
    additional_columns: Optional[List[str]] = None
    safety_margin: float = 0.5


class LoadEventListPreviewRequest(BaseModel):
    file_path: str
    name: str
    preview_duration: float = 100.0
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


@router.post("/load-lazy")
async def load_event_list_lazy(
    request: LoadEventListLazyRequest,
    service: DataService = Depends(get_data_service),
):
    """Load an EventList using lazy loading for large files."""
    return service.load_event_list_lazy(
        file_path=request.file_path,
        name=request.name,
        fmt=request.fmt,
        rmf_file=request.rmf_file,
        additional_columns=request.additional_columns,
        safety_margin=request.safety_margin,
    )


@router.post("/load-preview")
async def load_event_list_preview(
    request: LoadEventListPreviewRequest,
    service: DataService = Depends(get_data_service),
):
    """Load only the first segment of a large file as a preview."""
    return service.load_event_list_preview(
        file_path=request.file_path,
        name=request.name,
        preview_duration=request.preview_duration,
        fmt=request.fmt,
    )


@router.get("/{name}/full-preview")
async def get_event_list_full_preview(
    name: str,
    time_limit: int = 10,
    service: DataService = Depends(get_data_service),
):
    """Get full preview of an EventList with all attributes."""
    return service.get_event_list_full_preview(name=name, time_limit=time_limit)
