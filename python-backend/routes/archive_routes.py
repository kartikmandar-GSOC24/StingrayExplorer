"""
API routes for HEASARC archive operations.

Provides endpoints for searching NASA's HEASARC archive and downloading
X-ray observation data with progress tracking.
"""

import json
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services.archive_service import ArchiveService

router = APIRouter()


def get_archive_service(request: Request) -> ArchiveService:
    """Get ArchiveService instance from app state."""
    return ArchiveService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


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
        except Exception:
            pass

    if end_date:
        try:
            # Add ~1 day to include the end date fully
            mjd_end = Time(end_date, format="iso").mjd + 1.0
        except Exception:
            pass

    return (mjd_start, mjd_end)


# Request/Response Models
class SearchByNameRequest(BaseModel):
    """Request model for searching by source name."""
    source_name: str
    mission: str
    radius: float = 0.5  # Search radius in degrees
    max_results: int = 100
    min_exposure: Optional[float] = None  # Minimum exposure in seconds
    start_date: Optional[str] = None  # ISO date string "YYYY-MM-DD"
    end_date: Optional[str] = None  # ISO date string "YYYY-MM-DD"


class SearchByCoordinatesRequest(BaseModel):
    """Request model for searching by coordinates."""
    ra: float  # Right Ascension in degrees
    dec: float  # Declination in degrees
    mission: str
    radius: float = 0.5  # Search radius in degrees
    max_results: int = 100
    min_exposure: Optional[float] = None  # Minimum exposure in seconds
    start_date: Optional[str] = None  # ISO date string "YYYY-MM-DD"
    end_date: Optional[str] = None  # ISO date string "YYYY-MM-DD"


class SearchByObsidRequest(BaseModel):
    """Request model for searching by Observation ID."""
    obsid: str
    mission: str


class ListFilesRequest(BaseModel):
    """Request model for listing files in an observation directory."""
    mission: str
    obsid: str
    obs_time: Optional[str] = None  # Observation time (MJD or ISO string) for directory lookup
    obs_data: Optional[Dict[str, Any]] = None  # Additional observation data (e.g., prnb for RXTE, ra/dec for locate_data)
    recursive: bool = True
    max_depth: int = 3


class DownloadToDiskRequest(BaseModel):
    """Request model for downloading a file to local disk."""
    url: str  # URL to download from
    save_path: str  # Local path to save the file


# Routes
@router.get("/catalogs")
async def get_catalogs(
    service: ArchiveService = Depends(get_archive_service),
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
    service: ArchiveService = Depends(get_archive_service),
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
    return service.search_by_name(
        source_name=request.source_name,
        mission=request.mission,
        radius=request.radius,
        max_results=request.max_results,
        min_exposure=request.min_exposure,
        time_range=time_range,
    )


@router.post("/search/coordinates")
async def search_by_coordinates(
    request: SearchByCoordinatesRequest,
    service: ArchiveService = Depends(get_archive_service),
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
    return service.search_by_coordinates(
        ra=request.ra,
        dec=request.dec,
        mission=request.mission,
        radius=request.radius,
        max_results=request.max_results,
        min_exposure=request.min_exposure,
        time_range=time_range,
    )


@router.post("/search/obsid")
async def search_by_obsid(
    request: SearchByObsidRequest,
    service: ArchiveService = Depends(get_archive_service),
):
    """
    Search HEASARC for an observation by its Observation ID.

    Uses ADQL TAP query to directly look up the observation —
    no coordinates needed.

    Args:
        obsid: Observation ID (e.g., "4010080142")
        mission: Mission to search (e.g., "NICER", "NuSTAR")
    """
    return service.search_by_obsid(
        obsid=request.obsid,
        mission=request.mission,
    )


@router.get("/observation/{mission}/{obsid}")
async def get_observation_urls(
    mission: str,
    obsid: str,
    service: ArchiveService = Depends(get_archive_service),
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
    request: ListFilesRequest,
    service: ArchiveService = Depends(get_archive_service),
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
        mission=request.mission,
        obsid=request.obsid,
        obs_time=request.obs_time,
        obs_data=request.obs_data,
        recursive=request.recursive,
        max_depth=request.max_depth,
    )


@router.post("/download-to-disk")
async def download_to_disk(
    request: DownloadToDiskRequest,
    service: ArchiveService = Depends(get_archive_service),
):
    """
    Download a file from URL to local disk with SSE progress streaming.

    This endpoint bypasses CORS restrictions by downloading through the backend.
    Progress is streamed as Server-Sent Events (SSE).

    SSE Event Format:
    - type: "progress" - Download progress with bytes_downloaded, total_bytes, percent
    - type: "complete" - Download finished with file_path and size_bytes
    - type: "error" - An error occurred with error message

    Args:
        url: URL to download from (e.g., HEASARC HTTPS URL)
        save_path: Local path to save the file
    """
    async def event_generator():
        async for event in service.download_file_to_disk(
            url=request.url,
            save_path=request.save_path,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
