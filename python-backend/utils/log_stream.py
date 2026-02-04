"""
Log streaming utilities for real-time log delivery via SSE.

This module captures Python logging output and warnings, then streams them
to connected frontend clients through Server-Sent Events (SSE).
"""

import asyncio
import logging
import queue
import warnings
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Optional

# Loggers to skip (reduce noise)
SKIP_LOGGERS = frozenset({
    "uvicorn.access",
    "uvicorn.error",
})


class StreamingLogHandler(logging.Handler):
    """
    Custom logging handler that pushes log records to a queue for SSE streaming.

    Maps Python log levels to frontend-compatible levels:
    - DEBUG -> debug
    - INFO -> info
    - WARNING -> warn
    - ERROR/CRITICAL -> error
    """

    LEVEL_MAP = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warn",
        logging.ERROR: "error",
        logging.CRITICAL: "error",
    }

    def __init__(self, log_queue: "queue.Queue[dict[str, Any]]") -> None:
        """
        Initialize the handler with a queue for log entries.

        Args:
            log_queue: Thread-safe queue to push log entries to
        """
        super().__init__()
        self._queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record by pushing it to the queue.

        Args:
            record: The log record to emit
        """
        # Skip noisy loggers
        if record.name in SKIP_LOGGERS:
            return

        try:
            # Map level to frontend-compatible string
            level = self.LEVEL_MAP.get(record.levelno, "info")

            # Format the message
            message = self.format(record)

            # Create log entry
            log_entry = {
                "type": "log",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": level,
                "source": "python",
                "logger": record.name,
                "message": message,
            }

            # Non-blocking put (drop if queue is full)
            try:
                self._queue.put_nowait(log_entry)
            except queue.Full:
                # Queue full, drop oldest entry and try again
                try:
                    self._queue.get_nowait()
                    self._queue.put_nowait(log_entry)
                except queue.Empty:
                    pass

        except Exception:
            # Don't let logging errors crash the app
            self.handleError(record)


class LogStreamManager:
    """
    Manages log streaming infrastructure for SSE delivery.

    Captures Python logging output and warnings, buffering them in a queue
    for delivery to connected SSE clients. Supports multiple concurrent
    connections and handles cleanup on shutdown.
    """

    def __init__(self, max_queue_size: int = 1000) -> None:
        """
        Initialize the log stream manager.

        Args:
            max_queue_size: Maximum number of log entries to buffer
        """
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=max_queue_size)
        self._handler: Optional[StreamingLogHandler] = None
        self._original_showwarning: Optional[Callable[..., None]] = None
        self._installed = False
        self._active_connections = 0

    def install(self, log_level: int = logging.DEBUG) -> None:
        """
        Install the log handler and warning capture.

        Args:
            log_level: Minimum log level to capture (default: DEBUG)
        """
        if self._installed:
            return

        # Create and configure handler
        self._handler = StreamingLogHandler(self._queue)
        self._handler.setLevel(log_level)

        # Set formatter
        formatter = logging.Formatter("%(message)s")
        self._handler.setFormatter(formatter)

        # Add to root logger
        root_logger = logging.getLogger()
        root_logger.addHandler(self._handler)

        # Capture warnings
        self._original_showwarning = warnings.showwarning
        warnings.showwarning = self._capture_warning

        self._installed = True
        logging.getLogger(__name__).info("Log streaming installed")

    def uninstall(self) -> None:
        """Remove the log handler and restore original warning handling."""
        if not self._installed:
            return

        # Remove handler from root logger
        if self._handler:
            root_logger = logging.getLogger()
            root_logger.removeHandler(self._handler)
            self._handler = None

        # Restore original showwarning
        if self._original_showwarning:
            warnings.showwarning = self._original_showwarning
            self._original_showwarning = None

        # Clear the queue
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

        self._installed = False
        logging.getLogger(__name__).info("Log streaming uninstalled")

    def _capture_warning(
        self,
        message: Warning | str,
        category: type[Warning],
        filename: str,
        lineno: int,
        file: Any = None,
        line: str | None = None,
    ) -> None:
        """
        Capture warnings and route them to the log stream.

        Args:
            message: The warning message
            category: The warning category class
            filename: The file where the warning occurred
            lineno: The line number
            file: File to write to (ignored, we capture it)
            line: Source code line (optional)
        """
        # Format warning message
        warning_msg = f"{category.__name__}: {message}"
        if filename and lineno:
            warning_msg = f"{filename}:{lineno}: {warning_msg}"

        # Create log entry
        log_entry = {
            "type": "log",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": "warn",
            "source": "python",
            "logger": f"warnings.{category.__name__}",
            "message": warning_msg,
        }

        # Push to queue
        try:
            self._queue.put_nowait(log_entry)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(log_entry)
            except queue.Empty:
                pass

        # Also call original handler if it exists (for console output)
        if self._original_showwarning:
            self._original_showwarning(message, category, filename, lineno, file, line)

    async def stream_logs(
        self,
        heartbeat_interval: float = 30.0,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Async generator that yields log entries for SSE streaming.

        Includes periodic heartbeat events to keep the connection alive.

        Args:
            heartbeat_interval: Seconds between heartbeat events (default: 30)

        Yields:
            Log entry dictionaries ready for JSON serialization
        """
        self._active_connections += 1
        last_heartbeat = asyncio.get_event_loop().time()

        try:
            while True:
                # Check for log entries in the queue
                try:
                    log_entry = self._queue.get_nowait()
                    yield log_entry
                    last_heartbeat = asyncio.get_event_loop().time()
                except queue.Empty:
                    # No logs available, check if we need a heartbeat
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_heartbeat >= heartbeat_interval:
                        yield {
                            "type": "heartbeat",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        last_heartbeat = current_time

                # Small sleep to yield control and not spin
                await asyncio.sleep(0.1)

        finally:
            self._active_connections -= 1

    @property
    def is_installed(self) -> bool:
        """Check if log streaming is currently installed."""
        return self._installed

    @property
    def active_connections(self) -> int:
        """Get the number of active SSE connections."""
        return self._active_connections

    @property
    def queue_size(self) -> int:
        """Get the current queue size."""
        return self._queue.qsize()


# Global singleton instance
log_stream_manager = LogStreamManager()
