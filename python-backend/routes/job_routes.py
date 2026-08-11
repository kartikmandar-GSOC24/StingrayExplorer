"""
Job API routes for background task queue.

Provides REST endpoints for submitting, listing, streaming, and cancelling jobs.
"""

import json
import logging
import asyncio
from typing import Annotated, Any, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.event_formats import InputEventFormat

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Request/Response Models
# =============================================================================

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
JobIdText = Annotated[
    str,
    Path(
        min_length=36,
        max_length=36,
        pattern=(
            r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
            r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
        ),
    ),
]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class OptionalRmfRequest(StrictRequest):
    rmf_file: Optional[PathText] = None
    rmf_grant: Optional[GrantText] = None

    @model_validator(mode="after")
    def require_complete_rmf_pair(self):
        if (self.rmf_file is None) != (self.rmf_grant is None):
            raise ValueError("rmf_file and rmf_grant must be provided together")
        return self


class SubmitLoadJobRequest(OptionalRmfRequest):
    """Request body for submitting a single file load job."""

    file_path: PathText = Field(..., description="Path to the file to load")
    file_grant: GrantText
    name: NameText = Field(..., description="Name for the loaded event list")
    fmt: InputEventFormat = Field(default="ogip", description="File format")
    additional_columns: Optional[List[ColumnText]] = Field(
        default=None, max_length=64, description="Additional columns to load"
    )
    high_precision: bool = Field(
        default=False, description="Use high precision loading"
    )
    skip_checks: bool = Field(default=False, description="Skip validation checks")
    notes: Optional[NoteText] = Field(default=None, description="User notes/comments")
    use_partial_loading: bool = Field(
        default=False, description="Use partial/lazy loading"
    )
    partial_mode: Literal["time_range", "event_count"] = Field(
        default="time_range", description="Partial loading mode"
    )
    time_range_start: Optional[TimeValue] = Field(
        default=None, description="Start time for time range loading"
    )
    time_range_end: Optional[TimeValue] = Field(
        default=None, description="End time for time range loading"
    )
    event_start_index: Optional[int] = Field(
        default=None,
        ge=0,
        le=100_000_000,
        description="Start index for event count loading",
    )
    event_count: Optional[int] = Field(
        default=None, ge=1, le=10_000_000, description="Number of events to load"
    )

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


class FileConfig(OptionalRmfRequest):
    """Configuration for a single file in batch loading."""

    file_path: PathText
    file_grant: GrantText
    name: NameText
    fmt: InputEventFormat = "ogip"
    additional_columns: Optional[List[ColumnText]] = Field(default=None, max_length=64)
    high_precision: Optional[bool] = None
    skip_checks: Optional[bool] = None
    use_partial_loading: Optional[bool] = None
    partial_mode: Optional[Literal["time_range", "event_count"]] = None
    time_range_start: Optional[TimeValue] = None
    time_range_end: Optional[TimeValue] = None
    event_start_index: Optional[int] = Field(default=None, ge=0, le=100_000_000)
    event_count: Optional[int] = Field(default=None, ge=1, le=10_000_000)
    notes: Optional[NoteText] = None

    @model_validator(mode="after")
    def require_complete_partial_settings(self):
        if not self.use_partial_loading:
            return self
        mode = self.partial_mode or "time_range"
        if mode == "time_range":
            if self.time_range_start is None or self.time_range_end is None:
                raise ValueError("partial time-range loading requires both endpoints")
            if self.time_range_start >= self.time_range_end:
                raise ValueError("time_range_start must be less than time_range_end")
        elif self.event_count is None:
            raise ValueError("partial event-count loading requires event_count")
        return self


class SubmitBatchJobRequest(StrictRequest):
    """Request body for submitting a batch load job."""

    files: List[FileConfig] = Field(
        ..., min_length=1, max_length=32, description="List of files to load"
    )
    use_same_settings: bool = Field(
        default=True, description="Use shared settings for all files"
    )
    shared_fmt: InputEventFormat = Field(
        default="ogip", description="Shared file format"
    )
    shared_rmf_file: Optional[PathText] = Field(
        default=None, description="Shared RMF file path"
    )
    shared_rmf_grant: Optional[GrantText] = None
    shared_additional_columns: Optional[List[ColumnText]] = Field(
        default=None, max_length=64, description="Shared additional columns"
    )
    shared_high_precision: bool = Field(
        default=False, description="Shared high precision setting"
    )
    shared_skip_checks: bool = Field(
        default=False, description="Shared skip checks setting"
    )
    shared_use_partial_loading: bool = Field(
        default=False, description="Shared partial loading setting"
    )
    shared_partial_mode: Literal["time_range", "event_count"] = Field(
        default="time_range", description="Shared partial loading mode"
    )
    shared_time_range_start: Optional[TimeValue] = Field(
        default=None, description="Shared time range start"
    )
    shared_time_range_end: Optional[TimeValue] = Field(
        default=None, description="Shared time range end"
    )
    shared_event_start_index: Optional[int] = Field(
        default=None, ge=0, le=100_000_000, description="Shared event start index"
    )
    shared_event_count: Optional[int] = Field(
        default=None, ge=1, le=10_000_000, description="Shared event count"
    )

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


class SubmitUrlJobRequest(OptionalRmfRequest):
    """Request body for submitting a URL download job."""

    url: Annotated[str, Field(min_length=1, max_length=4096)] = Field(
        ..., description="URL to download"
    )
    name: NameText = Field(..., description="Name for the loaded event list")
    fmt: InputEventFormat = Field(default="ogip", description="File format")
    additional_columns: Optional[List[ColumnText]] = Field(
        default=None, max_length=64, description="Additional columns to load"
    )
    high_precision: bool = Field(
        default=False, description="Use high precision loading"
    )
    skip_checks: bool = Field(default=False, description="Skip validation checks")
    notes: Optional[NoteText] = Field(default=None, description="User notes/comments")


class CheckNameRequest(StrictRequest):
    """Request body for checking name conflicts."""

    name: NameText = Field(..., description="Name to check")


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
        job = await asyncio.to_thread(
            job_manager.submit_load_job,
            file_path=body.file_path,
            file_grant=body.file_grant,
            name=body.name,
            fmt=body.fmt,
            rmf_file=body.rmf_file,
            rmf_grant=body.rmf_grant,
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

    except Exception as error:
        logger.error("Failed to submit load job (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_submission_rejected",
            message="Failed to submit job",
        )


@router.post("/submit-batch", response_model=ApiResponse)
async def submit_batch_job(
    request: Request, body: SubmitBatchJobRequest
) -> ApiResponse:
    """
    Submit a batch load job for multiple files.

    Returns immediately with the job ID. The actual loading happens
    asynchronously in a background thread.
    """
    job_manager = get_job_manager(request)

    try:
        # Convert FileConfig models to dicts
        files = [f.model_dump() for f in body.files]

        job = await asyncio.to_thread(
            job_manager.submit_batch_load_job,
            files=files,
            use_same_settings=body.use_same_settings,
            shared_fmt=body.shared_fmt,
            shared_rmf_file=body.shared_rmf_file,
            shared_rmf_grant=body.shared_rmf_grant,
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

    except Exception as error:
        logger.error("Failed to submit batch job (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_submission_rejected",
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
        job = await asyncio.to_thread(
            job_manager.submit_url_load_job,
            url=body.url,
            name=body.name,
            fmt=body.fmt,
            rmf_file=body.rmf_file,
            rmf_grant=body.rmf_grant,
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

    except Exception as error:
        logger.error("Failed to submit URL job (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_submission_rejected",
            message="Failed to submit URL job",
        )


@router.get("/", response_model=ApiResponse)
async def list_jobs(
    request: Request,
    include_completed: bool = True,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
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

    except Exception as error:
        logger.error("Failed to list jobs (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_list_failed",
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

    except Exception as error:
        logger.error("Failed to get active jobs (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_list_failed",
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
            "Cache-Control": "no-store",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{job_id}", response_model=ApiResponse)
async def get_job(request: Request, job_id: JobIdText) -> ApiResponse:
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

    except Exception as error:
        logger.error("Failed to get job %s (%s)", job_id, type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_lookup_failed",
            message="Failed to get job",
        )


@router.post("/{job_id}/cancel", response_model=ApiResponse)
async def cancel_job(request: Request, job_id: JobIdText) -> ApiResponse:
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

    except Exception as error:
        logger.error("Failed to cancel job %s (%s)", job_id, type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_cancel_failed",
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
            message="Name conflict checked"
            if result["has_conflict"]
            else "Name available",
        )

    except Exception as error:
        logger.error("Failed to check name conflict (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_name_check_failed",
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

    except Exception as error:
        logger.error("Failed to clear completed jobs (%s)", type(error).__name__)
        return ApiResponse(
            success=False,
            error="job_clear_failed",
            message="Failed to clear completed jobs",
        )
