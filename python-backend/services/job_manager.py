"""
Job Manager for background task queue.

This module provides a thread-safe job queue system with SSE streaming
for real-time progress updates. Jobs are executed in a ThreadPoolExecutor
to avoid blocking the main event loop.
"""

import asyncio
import logging
import queue
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from models.event_formats import (
    require_batch_input_formats,
    require_input_event_format,
)
from models.job import Job, JobStatus, JobType
from services.utility_helpers import (
    GrantedReadFile,
    open_verified_read_grant,
    validate_derived_name,
)

logger = logging.getLogger(__name__)

# Maximum number of completed jobs to retain
MAX_COMPLETED_JOBS = 100
MAX_ACTIVE_JOBS = 32
MAX_RETAINED_CAPABILITIES = 256


@dataclass
class _JobResources:
    """Private capability owner; none of these fields enter a public Job DTO."""

    stack: ExitStack
    private: Dict[str, Any] = field(default_factory=dict)
    release_reservation: Callable[[], None] | None = None
    _closed: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        try:
            self.stack.close()
        finally:
            if self.release_reservation is not None:
                self.release_reservation()


class JobManager:
    """
    Thread-safe background job manager with SSE streaming support.

    Manages a queue of background jobs, executing them in a thread pool
    while providing real-time progress updates via SSE.
    """

    def __init__(
        self,
        state_manager: Any,
        data_service: Any,
        max_workers: int = 4,
    ) -> None:
        """
        Initialize the job manager.

        Args:
            state_manager: StateManager instance for checking name conflicts
            data_service: DataService instance for executing load operations
            max_workers: Maximum number of concurrent worker threads
        """
        self._state_manager = state_manager
        self._data_service = data_service
        self._lock = threading.RLock()

        # Job storage: id -> Job
        self._jobs: Dict[str, Job] = {}

        # Thread pool for background execution
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="job_worker"
        )

        # Futures for tracking running jobs
        self._futures: Dict[str, Future] = {}
        self._resources: Dict[str, _JobResources] = {}
        self._created_job_ids: set[str] = set()
        self._capacity_lock = threading.Lock()
        self._reserved_jobs = 0
        self._retained_capabilities = 0

        # SSE update queue for broadcasting job updates
        self._update_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=1000)

        # Active SSE connections counter
        self._active_connections = 0

        logger.info(f"JobManager initialized with {max_workers} workers")

    def shutdown(self) -> None:
        """Shutdown the job manager and its thread pool."""
        logger.info("Shutting down JobManager...")
        with self._lock:
            jobs_to_cancel = [job for job in self._jobs.values() if job.is_active]
            for job in jobs_to_cancel:
                self._broadcast_created_once_locked(job)
                job.cancel()
                self._broadcast_update("job_cancelled", job)
        self._executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            finished_ids = [
                job_id
                for job_id, future in self._futures.items()
                if future.cancelled() or future.done()
            ]
            resources = [self._resources.pop(job_id, None) for job_id in finished_ids]
        for resource in resources:
            if resource is not None:
                resource.close()
        logger.info("JobManager shutdown complete")

    # =========================================================================
    # Job Management
    # =========================================================================

    def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(
        self,
        include_completed: bool = True,
        limit: int = 50,
    ) -> List[Job]:
        """
        List all jobs, newest first.

        Args:
            include_completed: Include completed/failed/cancelled jobs
            limit: Maximum number of jobs to return

        Returns:
            List of jobs sorted by creation time (newest first)
        """
        with self._lock:
            jobs = list(self._jobs.values())

            if not include_completed:
                jobs = [j for j in jobs if j.is_active]

            # Sort by created_at descending (newest first)
            jobs.sort(key=lambda j: j.created_at, reverse=True)

            return jobs[:limit]

    def get_active_jobs(self) -> List[Job]:
        """Get all active (pending or running) jobs."""
        with self._lock:
            return [j for j in self._jobs.values() if j.is_active]

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel a pending job.

        Only pending jobs can be cancelled. Running jobs cannot be
        interrupted (thread pool limitation).

        Args:
            job_id: ID of the job to cancel

        Returns:
            True if job was cancelled, False if not found or not cancellable
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                return False

            # Mark the public state first: Future.cancel() invokes completion
            # callbacks synchronously and must not transiently publish failure.
            self._broadcast_created_once_locked(job)
            job.cancel()
            self._broadcast_update("job_cancelled", job)

            future = self._futures.get(job_id)
            cancelled_before_start = bool(
                future and not future.done() and future.cancel()
            )
            logger.info(f"Cancelled job {job_id}")
            if cancelled_before_start:
                resource = self._resources.pop(job_id, None)
                if resource is not None:
                    resource.close()
            return True

    def clear_completed_jobs(self) -> int:
        """
        Remove all completed/failed/cancelled jobs.

        Returns:
            Number of jobs removed
        """
        with self._lock:
            to_remove = []
            for job_id, job in self._jobs.items():
                future = self._futures.get(job_id)
                if job.is_finished and (future is None or future.done()):
                    to_remove.append(job_id)

            for job_id in to_remove:
                del self._jobs[job_id]
                self._futures.pop(job_id, None)
                self._created_job_ids.discard(job_id)
                resource = self._resources.pop(job_id, None)
                if resource is not None:
                    resource.close()

            logger.info(f"Cleared {len(to_remove)} completed jobs")
            return len(to_remove)

    def _cleanup_old_jobs(self) -> None:
        """Remove oldest completed jobs if exceeding limit."""
        with self._lock:
            finished_jobs = []
            for job_id, job in self._jobs.items():
                future = self._futures.get(job_id)
                if job.is_finished and (future is None or future.done()):
                    finished_jobs.append((job_id, job))

            if len(finished_jobs) <= MAX_COMPLETED_JOBS:
                return

            # Sort by completed_at (oldest first)
            finished_jobs.sort(key=lambda x: x[1].completed_at or "")

            # Remove oldest jobs exceeding limit
            to_remove = len(finished_jobs) - MAX_COMPLETED_JOBS
            for job_id, _ in finished_jobs[:to_remove]:
                del self._jobs[job_id]
                self._futures.pop(job_id, None)
                self._created_job_ids.discard(job_id)
                resource = self._resources.pop(job_id, None)
                if resource is not None:
                    resource.close()

            logger.debug(f"Cleaned up {to_remove} old completed jobs")

    # =========================================================================
    # Name Conflict Checking
    # =========================================================================

    def check_name_conflict(self, name: str) -> Dict[str, Any]:
        """
        Check if a name conflicts with existing data or pending jobs.

        Args:
            name: Name to check

        Returns:
            Dict with conflict status and suggested alternative if needed
        """
        with self._lock:
            # Check against loaded event lists
            if self._state_manager.has_event_data(name):
                return {
                    "has_conflict": True,
                    "conflict_source": "loaded_data",
                    "suggested_name": self._suggest_unique_name(name),
                }

            # Check against pending/running job names
            for job in self._jobs.values():
                if job.is_active:
                    # Check job's target name(s)
                    job_name = job.params.get("name")
                    if job_name == name:
                        return {
                            "has_conflict": True,
                            "conflict_source": "pending_job",
                            "job_id": job.id,
                            "suggested_name": self._suggest_unique_name(name),
                        }

                    # For batch jobs, check all file names
                    files = job.params.get("files", [])
                    for f in files:
                        if f.get("name") == name:
                            return {
                                "has_conflict": True,
                                "conflict_source": "pending_job",
                                "job_id": job.id,
                                "suggested_name": self._suggest_unique_name(name),
                            }

            return {"has_conflict": False}

    def _suggest_unique_name(self, base_name: str) -> str:
        """Generate a unique name by appending a number suffix."""
        # Get all existing names
        existing_names = set()

        # From state manager
        existing_names.update(self._state_manager.list_event_names())

        # From active jobs
        for job in self._jobs.values():
            if job.is_active:
                if job.params.get("name"):
                    existing_names.add(job.params["name"])
                for f in job.params.get("files", []):
                    if f.get("name"):
                        existing_names.add(f["name"])

        # Find a unique name
        if base_name not in existing_names:
            return base_name

        counter = 1
        while f"{base_name}_{counter}" in existing_names:
            counter += 1

        return f"{base_name}_{counter}"

    # =========================================================================
    # Job Submission
    # =========================================================================

    def _reserve_submission(self, capability_count: int) -> None:
        with self._capacity_lock:
            if self._reserved_jobs >= MAX_ACTIVE_JOBS:
                raise RuntimeError("The background job queue is full")
            if (
                self._retained_capabilities + capability_count
                > MAX_RETAINED_CAPABILITIES
            ):
                raise RuntimeError("The background input capacity is full")
            self._reserved_jobs += 1
            self._retained_capabilities += capability_count

    def _release_submission(self, capability_count: int) -> None:
        with self._capacity_lock:
            self._reserved_jobs = max(0, self._reserved_jobs - 1)
            self._retained_capabilities = max(
                0, self._retained_capabilities - capability_count
            )

    def _resource_owner(
        self,
        stack: ExitStack,
        private: Dict[str, Any],
        capability_count: int,
    ) -> _JobResources:
        return _JobResources(
            stack,
            private,
            lambda: self._release_submission(capability_count),
        )

    def _start_job(self, job: Job) -> bool:
        with self._lock:
            self._broadcast_created_once_locked(job)
            if job.status != JobStatus.PENDING:
                return False
            job.start()
            self._broadcast_update("job_started", job)
            return True

    def _broadcast_created_once_locked(self, job: Job) -> None:
        if job.id in self._created_job_ids:
            return
        self._created_job_ids.add(job.id)
        self._broadcast_update("job_created", job)

    def _update_running_job(
        self,
        job: Job,
        progress: float,
        message: str,
        completed_items: int | None = None,
    ) -> bool:
        with self._lock:
            if job.status != JobStatus.RUNNING:
                return False
            job.update_progress(progress, message, completed_items)
            self._broadcast_update("job_progress", job)
            return True

    def _complete_running_job(self, job: Job, result: Dict[str, Any] | None) -> bool:
        with self._lock:
            if job.status != JobStatus.RUNNING:
                return False
            job.complete(result)
            self._broadcast_update("job_completed", job)
            return True

    def _fail_active_job(self, job: Job, message: str) -> bool:
        with self._lock:
            if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
                return False
            job.fail(message)
            self._broadcast_update("job_failed", job)
            return True

    @staticmethod
    def _pin_read(
        stack: ExitStack,
        file_path: str,
        file_grant: str | None,
    ) -> GrantedReadFile:
        if not file_grant:
            raise PermissionError(
                "A native read grant is required for the selected file"
            )
        try:
            return stack.enter_context(open_verified_read_grant(file_path, file_grant))
        except Exception:
            raise PermissionError(
                "The selected file could not be verified; select it again"
            ) from None

    def _schedule(
        self,
        job: Job,
        resources: _JobResources,
        target,
    ) -> Job:
        with self._lock:
            self._jobs[job.id] = job
            self._resources[job.id] = resources
            self._cleanup_old_jobs()
        try:
            future = self._executor.submit(target, job)
        except Exception:
            with self._lock:
                self._jobs.pop(job.id, None)
                self._resources.pop(job.id, None)
                self._created_job_ids.discard(job.id)
            resources.close()
            raise
        with self._lock:
            self._futures[job.id] = future
            self._broadcast_created_once_locked(job)
        future.add_done_callback(
            lambda completed: self._on_job_complete(job.id, completed)
        )
        return job

    def _private_resources(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            resources = self._resources.get(job_id)
        if resources is None:
            raise RuntimeError("Private job resources are unavailable")
        return resources.private

    def submit_load_job(
        self,
        file_path: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
        notes: Optional[str] = None,
        use_partial_loading: bool = False,
        partial_mode: str = "time_range",
        time_range_start: Optional[float] = None,
        time_range_end: Optional[float] = None,
        event_start_index: Optional[int] = None,
        event_count: Optional[int] = None,
        file_grant: str | None = None,
        rmf_grant: str | None = None,
    ) -> Job:
        """Pin all local inputs before scheduling a single load."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        if (rmf_file is None) != (rmf_grant is None):
            raise ValueError("rmf_file and rmf_grant must be provided together")

        capability_count = 1 + int(rmf_file is not None)
        self._reserve_submission(capability_count)
        stack = ExitStack()
        try:
            file_source = self._pin_read(stack, file_path, file_grant)
            rmf_source = (
                self._pin_read(stack, rmf_file, rmf_grant)
                if rmf_file is not None
                else None
            )
        except Exception:
            stack.close()
            self._release_submission(capability_count)
            raise

        job = Job(
            type=JobType.LOAD_EVENT_LIST,
            display_name=f"Load {name}",
            params={
                "name": name,
                "fmt": fmt,
                "additional_columns": additional_columns,
                "high_precision": high_precision,
                "skip_checks": skip_checks,
                "notes": notes,
                "use_partial_loading": use_partial_loading,
                "partial_mode": partial_mode,
                "time_range_start": time_range_start,
                "time_range_end": time_range_end,
                "event_start_index": event_start_index,
                "event_count": event_count,
            },
        )
        resources = self._resource_owner(
            stack,
            {
                "file_path": file_path,
                "file_source": file_source,
                "rmf_file": rmf_file,
                "rmf_source": rmf_source,
            },
            capability_count,
        )
        scheduled = self._schedule(job, resources, self._execute_load_job)
        logger.info("Submitted local load job %s", job.id)
        return scheduled

    def submit_batch_load_job(
        self,
        files: List[Dict[str, Any]],
        use_same_settings: bool = True,
        shared_fmt: str = "ogip",
        shared_rmf_file: Optional[str] = None,
        shared_additional_columns: Optional[List[str]] = None,
        shared_high_precision: bool = False,
        shared_skip_checks: bool = False,
        shared_use_partial_loading: bool = False,
        shared_partial_mode: str = "time_range",
        shared_time_range_start: Optional[float] = None,
        shared_time_range_end: Optional[float] = None,
        shared_event_start_index: Optional[int] = None,
        shared_event_count: Optional[int] = None,
        shared_rmf_grant: str | None = None,
    ) -> Job:
        """Pin every batch input before scheduling any scientific work."""
        files, shared_fmt = require_batch_input_formats(files, shared_fmt)
        for item in files:
            name_error = validate_derived_name(item.get("name", ""))
            if name_error:
                raise ValueError(name_error)
        if (shared_rmf_file is None) != (shared_rmf_grant is None):
            raise ValueError(
                "shared_rmf_file and shared_rmf_grant must be provided together"
            )

        capability_count = len(files)
        if use_same_settings:
            capability_count += int(shared_rmf_file is not None)
        else:
            capability_count += sum(item.get("rmf_file") is not None for item in files)
        self._reserve_submission(capability_count)
        stack = ExitStack()
        retained_files: List[GrantedReadFile] = []
        retained_rmfs: List[GrantedReadFile | None] = []
        private_files: List[Dict[str, Any]] = []
        try:
            shared_source = (
                self._pin_read(stack, shared_rmf_file, shared_rmf_grant)
                if use_same_settings and shared_rmf_file is not None
                else None
            )
            for item in files:
                retained_files.append(
                    self._pin_read(stack, item["file_path"], item.get("file_grant"))
                )
                if use_same_settings:
                    retained_rmfs.append(shared_source)
                else:
                    rmf_path = item.get("rmf_file")
                    rmf_grant = item.get("rmf_grant")
                    if (rmf_path is None) != (rmf_grant is None):
                        raise ValueError(
                            "rmf_file and rmf_grant must be provided together"
                        )
                    retained_rmfs.append(
                        self._pin_read(stack, rmf_path, rmf_grant)
                        if rmf_path is not None
                        else None
                    )
                private_files.append(
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"file_grant", "rmf_grant"}
                    }
                )
        except Exception:
            stack.close()
            self._release_submission(capability_count)
            raise

        job = Job(
            type=JobType.LOAD_BATCH,
            display_name=f"Batch load ({len(files)} files)",
            total_items=len(files),
            params={
                "files": [{"name": item.get("name", "")} for item in files],
                "use_same_settings": use_same_settings,
                "shared_fmt": shared_fmt,
                "shared_additional_columns": shared_additional_columns,
                "shared_high_precision": shared_high_precision,
                "shared_skip_checks": shared_skip_checks,
                "shared_use_partial_loading": shared_use_partial_loading,
                "shared_partial_mode": shared_partial_mode,
                "shared_time_range_start": shared_time_range_start,
                "shared_time_range_end": shared_time_range_end,
                "shared_event_start_index": shared_event_start_index,
                "shared_event_count": shared_event_count,
            },
        )
        resources = self._resource_owner(
            stack,
            {
                "files": private_files,
                "file_sources": retained_files,
                "rmf_sources": retained_rmfs,
                "shared_rmf_file": shared_rmf_file,
                "shared_rmf_source": shared_source,
            },
            capability_count,
        )
        scheduled = self._schedule(job, resources, self._execute_batch_load_job)
        logger.info("Submitted batch load job %s for %d files", job.id, len(files))
        return scheduled

    def submit_url_load_job(
        self,
        url: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
        notes: Optional[str] = None,
        rmf_grant: str | None = None,
    ) -> Job:
        """Retain any local RMF while keeping the URL out of public job state."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        if (rmf_file is None) != (rmf_grant is None):
            raise ValueError("rmf_file and rmf_grant must be provided together")

        capability_count = int(rmf_file is not None)
        self._reserve_submission(capability_count)
        stack = ExitStack()
        try:
            rmf_source = (
                self._pin_read(stack, rmf_file, rmf_grant)
                if rmf_file is not None
                else None
            )
        except Exception:
            stack.close()
            self._release_submission(capability_count)
            raise

        job = Job(
            type=JobType.LOAD_FROM_URL,
            display_name=f"Remote load {name}",
            params={
                "name": name,
                "fmt": fmt,
                "additional_columns": additional_columns,
                "high_precision": high_precision,
                "skip_checks": skip_checks,
                "notes": notes,
            },
        )
        resources = self._resource_owner(
            stack,
            {
                "url": url,
                "rmf_file": rmf_file,
                "rmf_source": rmf_source,
            },
            capability_count,
        )
        scheduled = self._schedule(job, resources, self._execute_url_load_job)
        logger.info("Submitted remote load job %s", job.id)
        return scheduled

    # =========================================================================
    # Job Execution
    # =========================================================================

    def _execute_load_job(self, job: Job) -> None:
        """Execute a single file job using only private pinned resources."""
        if not self._start_job(job):
            return
        try:
            params = job.params
            private = self._private_resources(job.id)
            if not self._update_running_job(job, 0.1, "Loading selected event file..."):
                return

            if params.get("use_partial_loading"):
                if params.get("partial_mode") == "time_range":
                    result = self._data_service.load_event_list_by_time_range(
                        file_path=private["file_path"],
                        name=params["name"],
                        start_time=params["time_range_start"],
                        end_time=params["time_range_end"],
                        fmt=params["fmt"],
                        notes=params.get("notes"),
                        _file_source=private["file_source"],
                        _cancellation_check=lambda: job.status == JobStatus.CANCELLED,
                    )
                else:
                    result = self._data_service.load_event_list_by_event_count(
                        file_path=private["file_path"],
                        name=params["name"],
                        start_index=params.get("event_start_index") or 0,
                        count=params.get("event_count") or 10000,
                        fmt=params["fmt"],
                        notes=params.get("notes"),
                        _file_source=private["file_source"],
                        _cancellation_check=lambda: job.status == JobStatus.CANCELLED,
                    )
            else:
                result = self._data_service.load_event_list(
                    file_path=private["file_path"],
                    name=params["name"],
                    fmt=params["fmt"],
                    rmf_file=private.get("rmf_file"),
                    additional_columns=params.get("additional_columns"),
                    high_precision=params.get("high_precision", False),
                    skip_checks=params.get("skip_checks", False),
                    notes=params.get("notes"),
                    _file_source=private["file_source"],
                    _rmf_source=private.get("rmf_source"),
                    _cancellation_check=lambda: job.status == JobStatus.CANCELLED,
                )

            if result.get("success"):
                if self._complete_running_job(job, result.get("data")):
                    logger.info("Local load job %s completed", job.id)
            else:
                if self._fail_active_job(
                    job, "The selected event file could not be loaded"
                ):
                    logger.error("Local load job %s failed", job.id)
        except Exception as error:
            self._fail_active_job(job, "The selected event file could not be loaded")
            logger.error(
                "Local load job %s failed with %s", job.id, type(error).__name__
            )

    def _execute_batch_load_job(self, job: Job) -> None:
        """Execute a batch sequentially so cancellation and shared RMF reads are safe."""
        if not self._start_job(job):
            return
        try:
            params = job.params
            private = self._private_resources(job.id)
            files = private["files"]
            total = len(files)
            successful = []
            failed = []

            for index, file_config in enumerate(files):
                name = file_config["name"]
                if not self._update_running_job(
                    job,
                    index / total,
                    f"Loading {index + 1}/{total}: {name}",
                    completed_items=index,
                ):
                    return

                if params.get("use_same_settings"):
                    fmt = params.get("shared_fmt", "ogip")
                    rmf_file = private.get("shared_rmf_file")
                    columns = params.get("shared_additional_columns")
                    high_precision = params.get("shared_high_precision", False)
                    skip_checks = params.get("shared_skip_checks", False)
                    use_partial = params.get("shared_use_partial_loading", False)
                    partial_mode = params.get("shared_partial_mode", "time_range")
                    range_start = params.get("shared_time_range_start")
                    range_end = params.get("shared_time_range_end")
                    event_start = params.get("shared_event_start_index")
                    event_count = params.get("shared_event_count")
                else:
                    fmt = file_config.get("fmt", "ogip")
                    rmf_file = file_config.get("rmf_file")
                    columns = file_config.get("additional_columns")
                    high_precision = file_config.get("high_precision", False)
                    skip_checks = file_config.get("skip_checks", False)
                    use_partial = file_config.get("use_partial_loading", False)
                    partial_mode = file_config.get("partial_mode", "time_range")
                    range_start = file_config.get("time_range_start")
                    range_end = file_config.get("time_range_end")
                    event_start = file_config.get("event_start_index")
                    event_count = file_config.get("event_count")
                notes = file_config.get("notes")

                try:
                    if use_partial and partial_mode == "time_range":
                        result = self._data_service.load_event_list_by_time_range(
                            file_path=file_config["file_path"],
                            name=name,
                            start_time=range_start,
                            end_time=range_end,
                            fmt=fmt,
                            notes=notes,
                            _file_source=private["file_sources"][index],
                            _cancellation_check=lambda: job.status
                            == JobStatus.CANCELLED,
                        )
                    elif use_partial:
                        result = self._data_service.load_event_list_by_event_count(
                            file_path=file_config["file_path"],
                            name=name,
                            start_index=event_start or 0,
                            count=event_count or 10000,
                            fmt=fmt,
                            notes=notes,
                            _file_source=private["file_sources"][index],
                            _cancellation_check=lambda: job.status
                            == JobStatus.CANCELLED,
                        )
                    else:
                        result = self._data_service.load_event_list(
                            file_path=file_config["file_path"],
                            name=name,
                            fmt=fmt,
                            rmf_file=rmf_file,
                            additional_columns=columns,
                            high_precision=high_precision,
                            skip_checks=skip_checks,
                            notes=notes,
                            _file_source=private["file_sources"][index],
                            _rmf_source=private["rmf_sources"][index],
                            _cancellation_check=lambda: job.status
                            == JobStatus.CANCELLED,
                        )
                    if result.get("success"):
                        successful.append({"name": name, "data": result.get("data")})
                    else:
                        failed.append(
                            {
                                "name": name,
                                "error": "The selected file could not be loaded",
                            }
                        )
                except Exception as error:
                    failed.append(
                        {
                            "name": name,
                            "error": "The selected file could not be loaded",
                        }
                    )
                    logger.error(
                        "Batch job %s item failed with %s",
                        job.id,
                        type(error).__name__,
                    )

            if not self._update_running_job(
                job, 1.0, "Complete", completed_items=total
            ):
                return
            result = {
                "successful": successful,
                "failed": failed,
                "success_count": len(successful),
                "failure_count": len(failed),
                "total_files": total,
            }
            if not successful and failed:
                self._fail_active_job(job, f"All {total} selected files failed to load")
            else:
                self._complete_running_job(job, result)
            logger.info(
                "Batch job %s finished with %d/%d successful",
                job.id,
                len(successful),
                total,
            )
        except Exception as error:
            self._fail_active_job(job, "The selected batch could not be loaded")
            logger.error("Batch job %s failed with %s", job.id, type(error).__name__)

    def _execute_url_load_job(self, job: Job) -> None:
        """Execute a private bounded remote-source job."""
        if not self._start_job(job):
            return
        try:
            params = job.params
            private = self._private_resources(job.id)
            if not self._update_running_job(
                job, 0.1, "Downloading selected remote source..."
            ):
                return
            result = self._data_service.load_event_list_from_url(
                url=private["url"],
                name=params["name"],
                fmt=params["fmt"],
                rmf_file=private.get("rmf_file"),
                additional_columns=params.get("additional_columns"),
                high_precision=params.get("high_precision", False),
                skip_checks=params.get("skip_checks", False),
                notes=params.get("notes"),
                _rmf_source=private.get("rmf_source"),
                _cancellation_check=lambda: job.status == JobStatus.CANCELLED,
            )
            if result.get("success"):
                if self._complete_running_job(job, result.get("data")):
                    logger.info("Remote load job %s completed", job.id)
            else:
                if self._fail_active_job(
                    job, "The remote event source could not be loaded"
                ):
                    logger.error("Remote load job %s failed", job.id)
        except Exception as error:
            self._fail_active_job(job, "The remote event source could not be loaded")
            logger.error(
                "Remote load job %s failed with %s", job.id, type(error).__name__
            )

    def _on_job_complete(self, job_id: str, future: Future) -> None:
        """Callback when a job future completes."""
        with self._lock:
            self._futures.pop(job_id, None)
            resource = self._resources.pop(job_id, None)
        if resource is not None:
            resource.close()

        if future.cancelled():
            return

        # Handle any unexpected exceptions from the future
        try:
            future.result()  # Will re-raise any exception
        except Exception as error:
            job = self.get_job(job_id)
            if job and job.is_active:
                self._fail_active_job(job, "The background job failed unexpectedly")
                logger.error("Job %s future raised %s", job_id, type(error).__name__)

    # =========================================================================
    # SSE Streaming
    # =========================================================================

    def _broadcast_update(self, event_type: str, job: Job) -> None:
        """Broadcast a job update to all SSE connections."""
        update = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "job": job.to_dict(),
        }

        try:
            self._update_queue.put_nowait(update)
        except queue.Full:
            # Queue full, drop oldest and try again
            try:
                self._update_queue.get_nowait()
                self._update_queue.put_nowait(update)
            except queue.Empty:
                pass

    async def stream_updates(
        self,
        heartbeat_interval: float = 30.0,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Async generator that yields job updates for SSE streaming.

        Includes periodic heartbeat events to keep the connection alive.

        Args:
            heartbeat_interval: Seconds between heartbeat events

        Yields:
            Job update dictionaries ready for JSON serialization
        """
        self._active_connections += 1
        last_heartbeat = asyncio.get_event_loop().time()

        # First, send current state of all active jobs
        active_jobs = self.get_active_jobs()
        if active_jobs:
            yield {
                "type": "initial_state",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "jobs": [job.to_dict() for job in active_jobs],
            }

        try:
            while True:
                # Check for updates in the queue
                try:
                    update = self._update_queue.get_nowait()
                    yield update
                    last_heartbeat = asyncio.get_event_loop().time()
                except queue.Empty:
                    # No updates, check if we need a heartbeat
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat >= heartbeat_interval:
                        yield {
                            "type": "heartbeat",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        last_heartbeat = current_time

                # Small sleep to yield control
                await asyncio.sleep(0.1)

        finally:
            self._active_connections -= 1

    @property
    def active_connections(self) -> int:
        """Get the number of active SSE connections."""
        return self._active_connections


# Global singleton instance (initialized in main.py lifespan)
job_manager: Optional[JobManager] = None
