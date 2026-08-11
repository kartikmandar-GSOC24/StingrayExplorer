"""
Job API routes for background task queue.

Provides REST endpoints for submitting, listing, streaming, and cancelling jobs.
"""

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from models.event_formats import InputEventFormat

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

class SubmitLoadJobRequest(BaseModel):
    """Request body for submitting a single file load job."""
    file_path: str = Field(..., description="Path to the file to load")
    name: str = Field(..., description="Name for the loaded event list")
    fmt: InputEventFormat = Field(default="ogip", description="File format")
    rmf_file: Optional[str] = Field(default=None, description="RMF file path")
    additional_columns: Optional[List[str]] = Field(default=None, description="Additional columns to load")
    high_precision: bool = Field(default=False, description="Use high precision loading")
    skip_checks: bool = Field(default=False, description="Skip validation checks")
    notes: Optional[str] = Field(default=None, description="User notes/comments")
    use_partial_loading: bool = Field(default=False, description="Use partial/lazy loading")
    partial_mode: str = Field(default="time_range", description="Partial loading mode")
    time_range_start: Optional[float] = Field(default=None, description="Start time for time range loading")
    time_range_end: Optional[float] = Field(default=None, description="End time for time range loading")
    event_start_index: Optional[int] = Field(default=None, description="Start index for event count loading")
    event_count: Optional[int] = Field(default=None, description="Number of events to load")


class FileConfig(BaseModel):
    """Configuration for a single file in batch loading."""
    file_path: str
    name: str
    fmt: InputEventFormat = "ogip"
    rmf_file: Optional[str] = None
    additional_columns: Optional[List[str]] = None
    high_precision: Optional[bool] = None
    skip_checks: Optional[bool] = None
    use_partial_loading: Optional[bool] = None
    partial_mode: Optional[str] = None
    time_range_start: Optional[float] = None
    time_range_end: Optional[float] = None
    event_start_index: Optional[int] = None
    event_count: Optional[int] = None
    notes: Optional[str] = None


class SubmitBatchJobRequest(BaseModel):
    """Request body for submitting a batch load job."""
    files: List[FileConfig] = Field(..., description="List of files to load")
    use_same_settings: bool = Field(default=True, description="Use shared settings for all files")
    shared_fmt: InputEventFormat = Field(default="ogip", description="Shared file format")
    shared_rmf_file: Optional[str] = Field(default=None, description="Shared RMF file path")
    shared_additional_columns: Optional[List[str]] = Field(default=None, description="Shared additional columns")
    shared_high_precision: bool = Field(default=False, description="Shared high precision setting")
    shared_skip_checks: bool = Field(default=False, description="Shared skip checks setting")
    shared_use_partial_loading: bool = Field(default=False, description="Shared partial loading setting")
    shared_partial_mode: str = Field(default="time_range", description="Shared partial loading mode")
    shared_time_range_start: Optional[float] = Field(default=None, description="Shared time range start")
    shared_time_range_end: Optional[float] = Field(default=None, description="Shared time range end")
    shared_event_start_index: Optional[int] = Field(default=None, description="Shared event start index")
    shared_event_count: Optional[int] = Field(default=None, description="Shared event count")


class SubmitUrlJobRequest(BaseModel):
    """Request body for submitting a URL download job."""
    url: str = Field(..., description="URL to download")
    name: str = Field(..., description="Name for the loaded event list")
    fmt: InputEventFormat = Field(default="ogip", description="File format")
    rmf_file: Optional[str] = Field(default=None, description="RMF file path")
    additional_columns: Optional[List[str]] = Field(default=None, description="Additional columns to load")
    high_precision: bool = Field(default=False, description="Use high precision loading")
    skip_checks: bool = Field(default=False, description="Skip validation checks")
    notes: Optional[str] = Field(default=None, description="User notes/comments")


class CheckNameRequest(BaseModel):
    """Request body for checking name conflicts."""
    name: str = Field(..., description="Name to check")


class ApiResponse(BaseModel):
    """Standard API response format."""
    success: bool
    data: Optional[Any] = None
    message: str = ""
    error: Optional[str] = None


# =============================================================================
# Helper Functions
# =============================================================================

def get_job_manager(request: Request):
    """Get the job manager from app state."""
    job_manager = getattr(request.app.state, "job_manager", None)
    if job_manager is None:
        raise HTTPException(status_code=500, detail="Job manager not initialized")
    return job_manager


# =============================================================================
# API Endpoints
# =============================================================================

@router.post("/submit-load", response_model=ApiResponse)
async def submit_load_job(request: Request, body: SubmitLoadJobRequest) -> ApiResponse:
    """
    Submit a single file load job.

    Returns immediately with the job ID. The actual loading happens
    asynchronously in a background thread.
    """
    job_manager = get_job_manager(request)

    try:
        job = job_manager.submit_load_job(
            file_path=body.file_path,
            name=body.name,
            fmt=body.fmt,
            rmf_file=body.rmf_file,
            additional_columns=body.additional_columns,
            high_precision=body.high_precision,
            skip_checks=body.skip_checks,
            notes=body.notes,
            use_partial_loading=body.use_partial_loading,
            partial_mode=body.partial_mode,
            time_range_start=body.time_range_start,
            time_range_end=body.time_range_end,
            event_start_index=body.event_start_index,
            event_count=body.event_count,
        )

        return ApiResponse(
            success=True,
            data=job.to_dict(),
            message=f"Job submitted: {job.display_name}",
        )

    except Exception as e:
        logger.exception("Failed to submit load job")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to submit job",
        )


@router.post("/submit-batch", response_model=ApiResponse)
async def submit_batch_job(request: Request, body: SubmitBatchJobRequest) -> ApiResponse:
    """
    Submit a batch load job for multiple files.

    Returns immediately with the job ID. The actual loading happens
    asynchronously in a background thread.
    """
    job_manager = get_job_manager(request)

    try:
        # Convert FileConfig models to dicts
        files = [f.model_dump() for f in body.files]

        job = job_manager.submit_batch_load_job(
            files=files,
            use_same_settings=body.use_same_settings,
            shared_fmt=body.shared_fmt,
            shared_rmf_file=body.shared_rmf_file,
            shared_additional_columns=body.shared_additional_columns,
            shared_high_precision=body.shared_high_precision,
            shared_skip_checks=body.shared_skip_checks,
            shared_use_partial_loading=body.shared_use_partial_loading,
            shared_partial_mode=body.shared_partial_mode,
            shared_time_range_start=body.shared_time_range_start,
            shared_time_range_end=body.shared_time_range_end,
            shared_event_start_index=body.shared_event_start_index,
            shared_event_count=body.shared_event_count,
        )

        return ApiResponse(
            success=True,
            data=job.to_dict(),
            message=f"Batch job submitted: {len(files)} files",
        )

    except Exception as e:
        logger.exception("Failed to submit batch job")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to submit batch job",
        )


@router.post("/submit-url", response_model=ApiResponse)
async def submit_url_job(request: Request, body: SubmitUrlJobRequest) -> ApiResponse:
    """
    Submit a URL download and load job.

    Returns immediately with the job ID. The actual download and loading
    happens asynchronously in a background thread.
    """
    job_manager = get_job_manager(request)

    try:
        job = job_manager.submit_url_load_job(
            url=body.url,
            name=body.name,
            fmt=body.fmt,
            rmf_file=body.rmf_file,
            additional_columns=body.additional_columns,
            high_precision=body.high_precision,
            skip_checks=body.skip_checks,
            notes=body.notes,
        )

        return ApiResponse(
            success=True,
            data=job.to_dict(),
            message=f"URL job submitted: {job.display_name}",
        )

    except Exception as e:
        logger.exception("Failed to submit URL job")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to submit URL job",
        )


@router.get("/", response_model=ApiResponse)
async def list_jobs(
    request: Request,
    include_completed: bool = True,
    limit: int = 50,
) -> ApiResponse:
    """
    List all jobs, newest first.

    Args:
        include_completed: Include completed/failed/cancelled jobs
        limit: Maximum number of jobs to return
    """
    job_manager = get_job_manager(request)

    try:
        jobs = job_manager.list_jobs(
            include_completed=include_completed,
            limit=limit,
        )

        return ApiResponse(
            success=True,
            data=[job.to_dict() for job in jobs],
            message=f"Found {len(jobs)} jobs",
        )

    except Exception as e:
        logger.exception("Failed to list jobs")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to list jobs",
        )


@router.get("/active", response_model=ApiResponse)
async def get_active_jobs(request: Request) -> ApiResponse:
    """Get all active (pending or running) jobs."""
    job_manager = get_job_manager(request)

    try:
        jobs = job_manager.get_active_jobs()

        return ApiResponse(
            success=True,
            data=[job.to_dict() for job in jobs],
            message=f"Found {len(jobs)} active jobs",
        )

    except Exception as e:
        logger.exception("Failed to get active jobs")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to get active jobs",
        )


@router.get("/stream")
async def stream_job_updates(request: Request):
    """
    SSE endpoint for real-time job updates.

    Streams job status updates as they happen, including:
    - job_created: New job submitted
    - job_started: Job execution started
    - job_progress: Job progress updated
    - job_completed: Job finished successfully
    - job_failed: Job failed with error
    - job_cancelled: Job was cancelled
    - heartbeat: Keep-alive signal

    First sends initial_state with all currently active jobs.
    """
    job_manager = get_job_manager(request)

    async def event_generator():
        """Generate SSE events from job updates."""
        async for update in job_manager.stream_updates():
            data = json.dumps(update)
            yield f"data: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/{job_id}", response_model=ApiResponse)
async def get_job(request: Request, job_id: str) -> ApiResponse:
    """Get a specific job by ID."""
    job_manager = get_job_manager(request)

    try:
        job = job_manager.get_job(job_id)

        if job is None:
            return ApiResponse(
                success=False,
                error="Job not found",
                message=f"No job found with ID: {job_id}",
            )

        return ApiResponse(
            success=True,
            data=job.to_dict(),
            message="Job found",
        )

    except Exception as e:
        logger.exception(f"Failed to get job {job_id}")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to get job",
        )


@router.post("/{job_id}/cancel", response_model=ApiResponse)
async def cancel_job(request: Request, job_id: str) -> ApiResponse:
    """
    Cancel a pending job.

    Only pending jobs can be cancelled. Running jobs cannot be interrupted.
    """
    job_manager = get_job_manager(request)

    try:
        success = job_manager.cancel_job(job_id)

        if success:
            return ApiResponse(
                success=True,
                message=f"Job {job_id} cancelled",
            )
        else:
            job = job_manager.get_job(job_id)
            if job is None:
                return ApiResponse(
                    success=False,
                    error="Job not found",
                    message=f"No job found with ID: {job_id}",
                )
            else:
                return ApiResponse(
                    success=False,
                    error="Cannot cancel job",
                    message=f"Job is {job.status.value}, only pending jobs can be cancelled",
                )

    except Exception as e:
        logger.exception(f"Failed to cancel job {job_id}")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to cancel job",
        )


@router.post("/check-name", response_model=ApiResponse)
async def check_name_conflict(request: Request, body: CheckNameRequest) -> ApiResponse:
    """
    Check if a name conflicts with existing data or pending jobs.

    Returns conflict status and suggests an alternative name if needed.
    """
    job_manager = get_job_manager(request)

    try:
        result = job_manager.check_name_conflict(body.name)

        return ApiResponse(
            success=True,
            data=result,
            message="Name conflict checked" if result["has_conflict"] else "Name available",
        )

    except Exception as e:
        logger.exception("Failed to check name conflict")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to check name conflict",
        )


@router.delete("/completed", response_model=ApiResponse)
async def clear_completed_jobs(request: Request) -> ApiResponse:
    """Clear all completed/failed/cancelled jobs."""
    job_manager = get_job_manager(request)

    try:
        count = job_manager.clear_completed_jobs()

        return ApiResponse(
            success=True,
            data={"cleared_count": count},
            message=f"Cleared {count} completed jobs",
        )

    except Exception as e:
        logger.exception("Failed to clear completed jobs")
        return ApiResponse(
            success=False,
            error=str(e),
            message="Failed to clear completed jobs",
        )
