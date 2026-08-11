"""
API routes for HEASARC archive operations.

Provides endpoints for searching NASA's HEASARC archive and downloading
X-ray observation data with progress tracking.
"""

import asyncio
import json
import threading
from contextlib import aclosing
from datetime import date
from functools import partial
from typing import Annotated, Any, Callable, Literal, Optional, Tuple

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from services.archive_service import ArchiveService

router = APIRouter()


def get_archive_service(request: Request) -> ArchiveService:
    """Get ArchiveService instance from app state."""
    return ArchiveService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


ArchiveServiceDependency = Annotated[
    ArchiveService,
    Depends(get_archive_service),
]

ArchiveMission = Literal[
    "NICER",
    "NuSTAR",
    "XMM-Newton",
    "Chandra",
    "Swift",
    "RXTE",
    "IXPE",
    "Suzaku",
    "ASCA",
    "XRISM",
    "Hitomi",
]
MAX_CONCURRENT_ARCHIVE_SEARCHES = 2
ARCHIVE_SEARCH_RESPONSE_TIMEOUT_SECONDS = 35.0
ARCHIVE_SEARCH_CAPACITY = threading.BoundedSemaphore(MAX_CONCURRENT_ARCHIVE_SEARCHES)


def _execute_archive_search(
    operation: Callable[[], dict[str, Any]],
    capacity: threading.BoundedSemaphore,
) -> dict[str, Any]:
    try:
        return operation()
    finally:
        capacity.release()


def _consume_background_search(task: asyncio.Task[dict[str, Any]]) -> None:
    try:
        task.result()
    except BaseException:
        pass


async def _run_bounded_archive_search(
    service: ArchiveService,
    operation: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    """Run synchronous archive transport and parsing off-loop under capacity."""
    capacity = ARCHIVE_SEARCH_CAPACITY
    if not capacity.acquire(blocking=False):
        return service.create_result(
            success=False,
            data=None,
            message="Too many archive searches are already active",
            error="Archive search capacity is temporarily unavailable",
        )

    worker = asyncio.create_task(
        asyncio.to_thread(_execute_archive_search, operation, capacity)
    )
    try:
        return await asyncio.wait_for(
            asyncio.shield(worker),
            timeout=ARCHIVE_SEARCH_RESPONSE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        # The underlying synchronous library cannot be interrupted safely. It
        # retains its capacity slot until the bounded-session worker actually
        # exits, while the request receives a finite response wait.
        worker.add_done_callback(_consume_background_search)
        return service.create_result(
            success=False,
            data=None,
            message="The archive search timed out",
            error="The bounded archive search deadline expired",
        )
    except asyncio.CancelledError:
        worker.add_done_callback(_consume_background_search)
        raise


def _validate_iso_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(
            "Date must be a real calendar date in YYYY-MM-DD format"
        ) from error
    if parsed.isoformat() != value:
        raise ValueError("Date must use canonical YYYY-MM-DD format")
    return value


def _validate_display_text(value: str) -> str:
    if value != value.strip() or any(
        ord(character) < 0x20 or 0x7F <= ord(character) <= 0x9F for character in value
    ):
        raise ValueError("Text must be canonical and contain no control characters")
    return value


def _iso_dates_to_mjd_range(
    start_date: Optional[str],
    end_date: Optional[str],
) -> Optional[Tuple[float, float]]:
    """
    Convert ISO date strings to MJD time range tuple.

    Args:
        start_date: Start date in ISO format "YYYY-MM-DD" or None
        end_date: End date in ISO format "YYYY-MM-DD" or None

    Returns:
        Tuple of (mjd_start, mjd_end) or None if neither date is provided
    """
    if not start_date and not end_date:
        return None

    from astropy.time import Time

    # Use wide defaults when only one bound is specified
    mjd_start = 0.0  # Before any real observation
    mjd_end = 99999.0  # Far future

    if start_date:
        try:
            mjd_start = Time(start_date, format="iso").mjd
        except Exception as error:
            raise ValueError("Invalid start date") from error

    if end_date:
        try:
            # Add ~1 day to include the end date fully
            mjd_end = Time(end_date, format="iso").mjd + 1.0
        except Exception as error:
            raise ValueError("Invalid end date") from error

    return (mjd_start, mjd_end)


# Request/Response Models
class SearchByNameRequest(BaseModel):
    """Request model for searching by source name."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    source_name: str = Field(min_length=1, max_length=256)
    mission: ArchiveMission
    radius: float = Field(default=0.5, gt=0.0, le=10.0)
    max_results: int = Field(default=100, ge=1, le=1_000)
    min_exposure: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1_000_000_000.0,
    )
    start_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    end_date: Optional[str] = Field(default=None, min_length=10, max_length=10)

    _canonical_source_name = field_validator("source_name")(_validate_display_text)
    _real_dates = field_validator("start_date", "end_date")(_validate_iso_date)

    @model_validator(mode="after")
    def _ordered_date_range(self) -> "SearchByNameRequest":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("Start date must not be after end date")
        return self


class SearchByCoordinatesRequest(BaseModel):
    """Request model for searching by coordinates."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    ra: float = Field(ge=0.0, le=360.0)
    dec: float = Field(ge=-90.0, le=90.0)
    mission: ArchiveMission
    radius: float = Field(default=0.5, gt=0.0, le=10.0)
    max_results: int = Field(default=100, ge=1, le=1_000)
    min_exposure: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1_000_000_000.0,
    )
    start_date: Optional[str] = Field(default=None, min_length=10, max_length=10)
    end_date: Optional[str] = Field(default=None, min_length=10, max_length=10)

    _real_dates = field_validator("start_date", "end_date")(_validate_iso_date)

    @model_validator(mode="after")
    def _ordered_date_range(self) -> "SearchByCoordinatesRequest":
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise ValueError("Start date must not be after end date")
        return self


class SearchByObsidRequest(BaseModel):
    """Request model for searching by Observation ID."""

    model_config = ConfigDict(extra="forbid", strict=True)

    obsid: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    mission: ArchiveMission


class ObservationLookupData(BaseModel):
    """Bounded optional metadata used only for deterministic archive paths."""

    model_config = ConfigDict(extra="forbid", strict=True)

    ra: Optional[float] = Field(default=None, ge=0.0, le=360.0)
    dec: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    prnb: Optional[str] = Field(default=None, pattern=r"^[0-9]{1,6}$")


class ListFilesRequest(BaseModel):
    """Strict bounded request for crawling one known HEASARC observation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mission: ArchiveMission
    obsid: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    )
    obs_time: Optional[str] = Field(default=None, min_length=1, max_length=64)
    obs_data: Optional[ObservationLookupData] = None
    recursive: bool = True
    max_depth: int = Field(default=3, ge=0, le=3)


class DownloadToDiskRequest(BaseModel):
    """One approved remote source and one native-granted destination."""

    model_config = ConfigDict(extra="forbid", strict=True)

    url: str = Field(min_length=1, max_length=4_096)
    destination_path: str = Field(min_length=1, max_length=4_096)
    destination_grant: str = Field(min_length=1, max_length=512)


# Routes
@router.get("/catalogs")
async def get_catalogs(
    service: ArchiveServiceDependency,
):
    """
    Get list of supported HEASARC catalogs.

    Returns information about available X-ray mission catalogs
    that can be searched.
    """
    return service.get_supported_catalogs()


@router.post("/search/name")
async def search_by_name(
    request: SearchByNameRequest,
    service: ArchiveServiceDependency,
):
    """
    Search HEASARC for observations by source name.

    Resolves the source name to coordinates using SIMBAD/NED,
    then queries the HEASARC catalog for matching observations.

    Args:
        source_name: Astronomical source name (e.g., "Crab", "Cyg X-1", "NGC 3783")
        mission: Mission to search (e.g., "NICER", "NuSTAR", "Chandra")
        radius: Search radius in degrees (default: 0.5)
        max_results: Maximum number of results (default: 100)
    """
    time_range = _iso_dates_to_mjd_range(request.start_date, request.end_date)
    return await _run_bounded_archive_search(
        service,
        partial(
            service.search_by_name,
            source_name=request.source_name,
            mission=request.mission,
            radius=request.radius,
            max_results=request.max_results,
            min_exposure=request.min_exposure,
            time_range=time_range,
        ),
    )


@router.post("/search/coordinates")
async def search_by_coordinates(
    request: SearchByCoordinatesRequest,
    service: ArchiveServiceDependency,
):
    """
    Search HEASARC for observations by coordinates.

    Args:
        ra: Right Ascension in degrees
        dec: Declination in degrees
        mission: Mission to search (e.g., "NICER", "NuSTAR", "Chandra")
        radius: Search radius in degrees (default: 0.5)
        max_results: Maximum number of results (default: 100)
    """
    time_range = _iso_dates_to_mjd_range(request.start_date, request.end_date)
    return await _run_bounded_archive_search(
        service,
        partial(
            service.search_by_coordinates,
            ra=request.ra,
            dec=request.dec,
            mission=request.mission,
            radius=request.radius,
            max_results=request.max_results,
            min_exposure=request.min_exposure,
            time_range=time_range,
        ),
    )


@router.post("/search/obsid")
async def search_by_obsid(
    request: SearchByObsidRequest,
    service: ArchiveServiceDependency,
):
    """
    Search HEASARC for an observation by its Observation ID.

    Uses ADQL TAP query to directly look up the observation —
    no coordinates needed.

    Args:
        obsid: Observation ID (e.g., "4010080142")
        mission: Mission to search (e.g., "NICER", "NuSTAR")
    """
    return await _run_bounded_archive_search(
        service,
        partial(
            service.search_by_obsid,
            obsid=request.obsid,
            mission=request.mission,
        ),
    )


@router.get("/observation/{mission}/{obsid}")
async def get_observation_urls(
    mission: ArchiveMission,
    obsid: Annotated[
        str,
        Path(
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        ),
    ],
    service: ArchiveServiceDependency,
):
    """
    Get download URLs for a specific observation.

    Returns available download URLs from HEASARC, SciServer, and AWS
    for the specified observation.
    """
    return service.get_observation_download_urls(
        mission=mission,
        obsid=obsid,
    )


@router.post("/list-files")
async def list_observation_files(
    payload: ListFilesRequest,
    request: Request,
    service: ArchiveServiceDependency,
):
    """
    List all files in an observation directory.

    Returns a tree structure of files with metadata including:
    - File names and paths
    - File sizes (when available)
    - File type classification (event, calibration, auxiliary, log, other)
    - Full download URLs

    Args:
        mission: Mission key (e.g., "NICER", "NuSTAR", "Chandra")
        obsid: Observation ID
        obs_time: Observation time (MJD or ISO string) - required for some missions
        recursive: Whether to recursively list subdirectories (default: True)
        max_depth: Maximum recursion depth (default: 3)
    """
    return await service.list_observation_files(
        mission=payload.mission,
        obsid=payload.obsid,
        obs_time=payload.obs_time,
        obs_data=(payload.obs_data.model_dump() if payload.obs_data else None),
        recursive=payload.recursive,
        max_depth=payload.max_depth,
        cancellation_check=request.is_disconnected,
    )


@router.post("/download-to-disk")
async def download_to_disk(
    payload: DownloadToDiskRequest,
    request: Request,
    service: ArchiveServiceDependency,
):
    """
    Download a file from URL to local disk with SSE progress streaming.

    The authenticated backend enforces the HEASARC source policy and streams
    progress as Server-Sent Events (SSE).

    SSE Event Format:
    - type: "progress" - Download progress with bytes_downloaded, total_bytes, percent
    - type: "complete" - Download finished with verified file_name, size, and digest
    - type: "error" - An error occurred with error message

    The response never contains the destination path or grant. Disconnecting
    the renderer cancels work only before exclusive publication. Publication is
    the commit point: a disconnect after it suppresses the terminal SSE event but
    does not remove the completed destination.
    """

    async def event_generator():
        events = service.download_file_to_disk(
            url=payload.url,
            destination_path=payload.destination_path,
            destination_grant=payload.destination_grant,
            cancellation_check=request.is_disconnected,
        )
        async with aclosing(events):
            async for event in events:
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
        },
    )
