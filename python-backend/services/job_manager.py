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
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from models.job import Job, JobStatus, JobType

logger = logging.getLogger(__name__)

# Maximum number of completed jobs to retain
MAX_COMPLETED_JOBS = 100


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
            max_workers=max_workers,
            thread_name_prefix="job_worker"
        )

        # Futures for tracking running jobs
        self._futures: Dict[str, Future] = {}

        # SSE update queue for broadcasting job updates
        self._update_queue: queue.Queue[Dict[str, Any]] = queue.Queue(maxsize=1000)

        # Active SSE connections counter
        self._active_connections = 0

        logger.info(f"JobManager initialized with {max_workers} workers")

    def shutdown(self) -> None:
        """Shutdown the job manager and its thread pool."""
        logger.info("Shutting down JobManager...")
        self._executor.shutdown(wait=False)
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

            if job.status != JobStatus.PENDING:
                return False

            # Cancel the future if it exists
            future = self._futures.get(job_id)
            if future and not future.done():
                future.cancel()

            job.cancel()
            self._broadcast_update("job_cancelled", job)
            logger.info(f"Cancelled job {job_id}")
            return True

    def clear_completed_jobs(self) -> int:
        """
        Remove all completed/failed/cancelled jobs.

        Returns:
            Number of jobs removed
        """
        with self._lock:
            to_remove = [
                job_id for job_id, job in self._jobs.items()
                if job.is_finished
            ]

            for job_id in to_remove:
                del self._jobs[job_id]
                self._futures.pop(job_id, None)

            logger.info(f"Cleared {len(to_remove)} completed jobs")
            return len(to_remove)

    def _cleanup_old_jobs(self) -> None:
        """Remove oldest completed jobs if exceeding limit."""
        with self._lock:
            finished_jobs = [
                (job_id, job) for job_id, job in self._jobs.items()
                if job.is_finished
            ]

            if len(finished_jobs) <= MAX_COMPLETED_JOBS:
                return

            # Sort by completed_at (oldest first)
            finished_jobs.sort(key=lambda x: x[1].completed_at or "")

            # Remove oldest jobs exceeding limit
            to_remove = len(finished_jobs) - MAX_COMPLETED_JOBS
            for job_id, _ in finished_jobs[:to_remove]:
                del self._jobs[job_id]
                self._futures.pop(job_id, None)

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
    ) -> Job:
        """
        Submit a single file load job.

        Returns immediately with the job object. The actual loading
        happens asynchronously in the thread pool.

        Args:
            file_path: Path to the file to load
            name: Name for the loaded event list
            ... other load parameters ...

        Returns:
            The created Job object
        """
        # Create display name from filename
        import os
        display_name = os.path.basename(file_path)

        job = Job(
            type=JobType.LOAD_EVENT_LIST,
            display_name=display_name,
            params={
                "file_path": file_path,
                "name": name,
                "fmt": fmt,
                "rmf_file": rmf_file,
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

        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_old_jobs()

        # Submit to thread pool
        future = self._executor.submit(self._execute_load_job, job)
        future.add_done_callback(lambda f: self._on_job_complete(job.id, f))

        with self._lock:
            self._futures[job.id] = future

        self._broadcast_update("job_created", job)
        logger.info(f"Submitted load job {job.id} for {file_path}")

        return job

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
    ) -> Job:
        """
        Submit a batch file load job.

        Args:
            files: List of file configs with file_path, name, and optional settings
            ... shared settings ...

        Returns:
            The created Job object
        """
        display_name = f"Batch load ({len(files)} files)"

        job = Job(
            type=JobType.LOAD_BATCH,
            display_name=display_name,
            total_items=len(files),
            params={
                "files": files,
                "use_same_settings": use_same_settings,
                "shared_fmt": shared_fmt,
                "shared_rmf_file": shared_rmf_file,
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

        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_old_jobs()

        # Submit to thread pool
        future = self._executor.submit(self._execute_batch_load_job, job)
        future.add_done_callback(lambda f: self._on_job_complete(job.id, f))

        with self._lock:
            self._futures[job.id] = future

        self._broadcast_update("job_created", job)
        logger.info(f"Submitted batch load job {job.id} for {len(files)} files")

        return job

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
    ) -> Job:
        """
        Submit a URL download and load job.

        Args:
            url: URL to download
            name: Name for the loaded event list
            ... other load parameters ...

        Returns:
            The created Job object
        """
        # Extract filename from URL for display
        import os
        from urllib.parse import urlparse
        parsed = urlparse(url)
        display_name = os.path.basename(parsed.path) or "URL download"

        job = Job(
            type=JobType.LOAD_FROM_URL,
            display_name=display_name,
            params={
                "url": url,
                "name": name,
                "fmt": fmt,
                "rmf_file": rmf_file,
                "additional_columns": additional_columns,
                "high_precision": high_precision,
                "skip_checks": skip_checks,
                "notes": notes,
            },
        )

        with self._lock:
            self._jobs[job.id] = job
            self._cleanup_old_jobs()

        # Submit to thread pool
        future = self._executor.submit(self._execute_url_load_job, job)
        future.add_done_callback(lambda f: self._on_job_complete(job.id, f))

        with self._lock:
            self._futures[job.id] = future

        self._broadcast_update("job_created", job)
        logger.info(f"Submitted URL load job {job.id} for {url}")

        return job

    # =========================================================================
    # Job Execution
    # =========================================================================

    def _execute_load_job(self, job: Job) -> None:
        """Execute a single file load job in a worker thread."""
        job.start()
        self._broadcast_update("job_started", job)

        try:
            params = job.params
            job.update_progress(0.1, f"Loading {job.display_name}...")
            self._broadcast_update("job_progress", job)

            # Determine loading method
            if params.get("use_partial_loading"):
                if params.get("partial_mode") == "time_range":
                    result = self._data_service.load_event_list_by_time_range(
                        file_path=params["file_path"],
                        name=params["name"],
                        start_time=params["time_range_start"],
                        end_time=params["time_range_end"],
                        fmt=params["fmt"],
                        notes=params.get("notes"),
                    )
                else:  # event_count
                    result = self._data_service.load_event_list_by_event_count(
                        file_path=params["file_path"],
                        name=params["name"],
                        start_index=params.get("event_start_index", 0),
                        count=params.get("event_count", 10000),
                        fmt=params["fmt"],
                        notes=params.get("notes"),
                    )
            else:
                result = self._data_service.load_event_list(
                    file_path=params["file_path"],
                    name=params["name"],
                    fmt=params["fmt"],
                    rmf_file=params.get("rmf_file"),
                    additional_columns=params.get("additional_columns"),
                    high_precision=params.get("high_precision", False),
                    skip_checks=params.get("skip_checks", False),
                    notes=params.get("notes"),
                )

            if result.get("success"):
                job.complete(result.get("data"))
                self._broadcast_update("job_completed", job)
                logger.info(f"Job {job.id} completed successfully")
            else:
                error_msg = result.get("message") or result.get("error") or "Unknown error"
                job.fail(error_msg)
                self._broadcast_update("job_failed", job)
                logger.error(f"Job {job.id} failed: {error_msg}")

        except Exception as e:
            error_msg = str(e)
            job.fail(error_msg)
            self._broadcast_update("job_failed", job)
            logger.exception(f"Job {job.id} failed with exception")

    def _execute_batch_load_job(self, job: Job) -> None:
        """Execute a batch load job in a worker thread."""
        job.start()
        self._broadcast_update("job_started", job)

        try:
            params = job.params
            files = params["files"]
            total = len(files)

            successful = []
            failed = []

            for i, file_config in enumerate(files):
                if job.status == JobStatus.CANCELLED:
                    break

                file_path = file_config["file_path"]
                name = file_config["name"]

                # Update progress
                progress = (i / total)
                job.update_progress(
                    progress,
                    f"Loading {i + 1}/{total}: {name}",
                    completed_items=i,
                )
                self._broadcast_update("job_progress", job)

                # Determine settings (per-file or shared)
                if params.get("use_same_settings"):
                    fmt = params.get("shared_fmt", "ogip")
                    rmf_file = params.get("shared_rmf_file")
                    additional_columns = params.get("shared_additional_columns")
                    high_precision = params.get("shared_high_precision", False)
                    skip_checks = params.get("shared_skip_checks", False)
                    use_partial = params.get("shared_use_partial_loading", False)
                    partial_mode = params.get("shared_partial_mode", "time_range")
                    time_start = params.get("shared_time_range_start")
                    time_end = params.get("shared_time_range_end")
                    event_start = params.get("shared_event_start_index")
                    event_cnt = params.get("shared_event_count")
                else:
                    fmt = file_config.get("fmt", "ogip")
                    rmf_file = file_config.get("rmf_file")
                    additional_columns = file_config.get("additional_columns")
                    high_precision = file_config.get("high_precision", False)
                    skip_checks = file_config.get("skip_checks", False)
                    use_partial = file_config.get("use_partial_loading", False)
                    partial_mode = file_config.get("partial_mode", "time_range")
                    time_start = file_config.get("time_range_start")
                    time_end = file_config.get("time_range_end")
                    event_start = file_config.get("event_start_index")
                    event_cnt = file_config.get("event_count")

                notes = file_config.get("notes")

                try:
                    # Load the file
                    if use_partial:
                        if partial_mode == "time_range":
                            result = self._data_service.load_event_list_by_time_range(
                                file_path=file_path,
                                name=name,
                                start_time=time_start,
                                end_time=time_end,
                                fmt=fmt,
                                notes=notes,
                            )
                        else:
                            result = self._data_service.load_event_list_by_event_count(
                                file_path=file_path,
                                name=name,
                                start_index=event_start or 0,
                                count=event_cnt or 10000,
                                fmt=fmt,
                                notes=notes,
                            )
                    else:
                        result = self._data_service.load_event_list(
                            file_path=file_path,
                            name=name,
                            fmt=fmt,
                            rmf_file=rmf_file,
                            additional_columns=additional_columns,
                            high_precision=high_precision,
                            skip_checks=skip_checks,
                            notes=notes,
                        )

                    if result.get("success"):
                        successful.append({
                            "name": name,
                            "file_path": file_path,
                            "data": result.get("data"),
                        })
                    else:
                        error_msg = result.get("message") or result.get("error") or "Unknown error"
                        failed.append({
                            "name": name,
                            "file_path": file_path,
                            "error": error_msg,
                        })

                except Exception as e:
                    failed.append({
                        "name": name,
                        "file_path": file_path,
                        "error": str(e),
                    })

            # Final update
            job.update_progress(1.0, "Complete", completed_items=total)

            if len(failed) == 0:
                job.complete({
                    "successful": successful,
                    "failed": failed,
                    "success_count": len(successful),
                    "failure_count": len(failed),
                    "total_files": total,
                })
                self._broadcast_update("job_completed", job)
                logger.info(f"Batch job {job.id} completed: {len(successful)}/{total} files")
            elif len(successful) == 0:
                job.fail(f"All {total} files failed to load")
                self._broadcast_update("job_failed", job)
                logger.error(f"Batch job {job.id} failed: all files failed")
            else:
                # Partial success
                job.complete({
                    "successful": successful,
                    "failed": failed,
                    "success_count": len(successful),
                    "failure_count": len(failed),
                    "total_files": total,
                })
                self._broadcast_update("job_completed", job)
                logger.warning(
                    f"Batch job {job.id} partial success: "
                    f"{len(successful)}/{total} files loaded"
                )

        except Exception as e:
            job.fail(str(e))
            self._broadcast_update("job_failed", job)
            logger.exception(f"Batch job {job.id} failed with exception")

    def _execute_url_load_job(self, job: Job) -> None:
        """Execute a URL download and load job in a worker thread."""
        job.start()
        self._broadcast_update("job_started", job)

        try:
            params = job.params
            url = params["url"]

            job.update_progress(0.1, "Downloading...")
            self._broadcast_update("job_progress", job)

            # Use the synchronous URL loading method
            result = self._data_service.load_event_list_from_url(
                url=url,
                name=params["name"],
                fmt=params["fmt"],
                rmf_file=params.get("rmf_file"),
                additional_columns=params.get("additional_columns"),
                high_precision=params.get("high_precision", False),
                skip_checks=params.get("skip_checks", False),
            )

            if result.get("success"):
                job.complete(result.get("data"))
                self._broadcast_update("job_completed", job)
                logger.info(f"URL job {job.id} completed successfully")
            else:
                error_msg = result.get("message") or result.get("error") or "Unknown error"
                job.fail(error_msg)
                self._broadcast_update("job_failed", job)
                logger.error(f"URL job {job.id} failed: {error_msg}")

        except Exception as e:
            job.fail(str(e))
            self._broadcast_update("job_failed", job)
            logger.exception(f"URL job {job.id} failed with exception")

    def _on_job_complete(self, job_id: str, future: Future) -> None:
        """Callback when a job future completes."""
        with self._lock:
            self._futures.pop(job_id, None)

        # Handle any unexpected exceptions from the future
        try:
            future.result()  # Will re-raise any exception
        except Exception as e:
            job = self.get_job(job_id)
            if job and job.is_active:
                job.fail(f"Unexpected error: {e}")
                self._broadcast_update("job_failed", job)
                logger.exception(f"Job {job_id} future raised unexpected exception")

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
