"""
Job data model for background task queue.

This module defines the Job dataclass and related enums for tracking
background tasks like file loading, data analysis, and downloads.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any, Dict, Optional
import uuid


_PUBLIC_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
_PUBLIC_DISPLAY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _().-]{0,127}$")


def _public_name(value: Any) -> str:
    if isinstance(value, str) and _PUBLIC_NAME.fullmatch(value):
        return value
    return "event-list"


def _public_count(value: Any) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 1_000_000_000
    ):
        return value
    return None


def _public_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        converted = float(value)
        if math.isfinite(converted) and abs(converted) <= 1.0e15:
            return converted
    return None


def _public_warnings(result: Dict[str, Any]) -> list[str] | None:
    warnings: list[str] = []
    if result.get("gti_warnings"):
        warnings.append("GTI validation reported warnings")
    if result.get("stingray_warnings"):
        warnings.append("The scientific reader reported warnings")
    issues = result.get("validation_issues")
    if isinstance(issues, list) and any(
        isinstance(issue, dict) and issue.get("severity") in {"warning", "error"}
        for issue in issues[:64]
    ):
        warnings.append("Data-quality validation reported issues")
    return warnings or None


def _public_single_result(result: Any) -> Dict[str, Any] | None:
    """Project an arbitrary internal result onto the public science summary."""
    if not isinstance(result, dict):
        return None
    public: Dict[str, Any] = {}
    event_count = _public_count(result.get("n_events", result.get("event_count")))
    if event_count is not None:
        public["event_count"] = event_count
    time_range = result.get("time_range")
    if isinstance(time_range, (list, tuple)) and len(time_range) == 2:
        time_start = _public_float(time_range[0])
        time_end = _public_float(time_range[1])
    else:
        time_start = _public_float(result.get("time_start"))
        time_end = _public_float(result.get("time_end"))
    if time_start is not None:
        public["time_start"] = time_start
    if time_end is not None:
        public["time_end"] = time_end
    warnings = _public_warnings(result)
    if warnings is not None:
        public["warnings"] = warnings
    return public or None


def _public_batch_result(result: Any) -> Dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    public: Dict[str, Any] = {}
    for key in ("successful", "failed"):
        items = result.get(key)
        if isinstance(items, list):
            public_items = []
            for item in items[:32]:
                if not isinstance(item, dict):
                    continue
                projected = {"name": _public_name(item.get("name"))}
                if key == "failed":
                    projected["error"] = "The selected file could not be loaded"
                public_items.append(projected)
            public[key] = public_items
    for key in ("success_count", "failure_count", "total_files"):
        count = _public_count(result.get(key))
        if count is not None:
            public[key] = count
    return public or None


class JobStatus(str, Enum):
    """Status of a background job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Type of background job."""

    LOAD_EVENT_LIST = "load_event_list"
    LOAD_BATCH = "load_batch"
    LOAD_FROM_URL = "load_from_url"
    # Future job types:
    # GENERATE_LIGHTCURVE = "generate_lightcurve"
    # COMPUTE_POWER_SPECTRUM = "compute_power_spectrum"
    # EXPORT_DATA = "export_data"
    # DOWNLOAD_ARCHIVE = "download_archive"


@dataclass
class Job:
    """
    Represents a background job in the queue.

    Attributes:
        id: Unique identifier for the job (UUID)
        type: Type of job (load_event_list, load_batch, etc.)
        status: Current status of the job
        progress: Progress percentage (0.0 to 1.0)
        progress_message: Human-readable progress message
        total_items: Total number of items to process (for batch jobs)
        completed_items: Number of items completed
        created_at: ISO timestamp when job was created
        started_at: ISO timestamp when job started running
        completed_at: ISO timestamp when job completed/failed/cancelled
        params: Private job execution options. Never serialized publicly.
        result: Result data on successful completion
        error: Error message on failure
        display_name: Human-readable name for the job (shown in UI)
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: JobType = JobType.LOAD_EVENT_LIST
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    progress_message: str = "Pending..."
    total_items: int = 1
    completed_items: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    display_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for JSON serialization."""
        progress_messages = {
            JobStatus.PENDING: "Pending...",
            JobStatus.RUNNING: "Running...",
            JobStatus.COMPLETED: "Completed",
            JobStatus.FAILED: "Failed",
            JobStatus.CANCELLED: "Cancelled",
        }
        public_result = (
            _public_batch_result(self.result)
            if self.type == JobType.LOAD_BATCH
            else _public_single_result(self.result)
        )
        public_display_name = (
            self.display_name
            if _PUBLIC_DISPLAY.fullmatch(self.display_name)
            else "Background job"
        )
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": progress_messages[self.status],
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "result": public_result,
            "error": "The background job could not be completed"
            if self.error
            else None,
            "display_name": public_display_name,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Job":
        """Create a Job from a dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            type=JobType(data.get("type", "load_event_list")),
            status=JobStatus(data.get("status", "pending")),
            progress=data.get("progress", 0.0),
            progress_message=data.get("progress_message", "Pending..."),
            total_items=data.get("total_items", 1),
            completed_items=data.get("completed_items", 0),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            params=data.get("params", {}),
            result=data.get("result"),
            error=data.get("error"),
            display_name=data.get("display_name", ""),
        )

    def start(self) -> None:
        """Mark job as started."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.progress_message = "Running..."

    def complete(self, result: Optional[Dict[str, Any]] = None) -> None:
        """Mark job as completed successfully."""
        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.progress = 1.0
        self.progress_message = "Completed"
        self.result = result

    def fail(self, error: str) -> None:
        """Mark job as failed."""
        self.status = JobStatus.FAILED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.error = error
        self.progress_message = f"Failed: {error}"

    def cancel(self) -> None:
        """Mark job as cancelled."""
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.progress_message = "Cancelled"

    def update_progress(
        self,
        progress: float,
        message: str = "",
        completed_items: Optional[int] = None,
    ) -> None:
        """Update job progress."""
        self.progress = min(max(progress, 0.0), 1.0)  # Clamp 0-1
        if message:
            self.progress_message = message
        if completed_items is not None:
            self.completed_items = completed_items

    @property
    def is_active(self) -> bool:
        """Check if job is still active (pending or running)."""
        return self.status in (JobStatus.PENDING, JobStatus.RUNNING)

    @property
    def is_finished(self) -> bool:
        """Check if job has finished (completed, failed, or cancelled)."""
        return self.status in (
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        )
