"""
Job data model for background task queue.

This module defines the Job dataclass and related enums for tracking
background tasks like file loading, data analysis, and downloads.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


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
        params: Job-specific parameters (file paths, names, options, etc.)
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
        return {
            "id": self.id,
            "type": self.type.value,
            "status": self.status.value,
            "progress": self.progress,
            "progress_message": self.progress_message,
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "params": self.params,
            "result": self.result,
            "error": self.error,
            "display_name": self.display_name,
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
