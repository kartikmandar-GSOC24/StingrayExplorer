"""
Performance monitoring utilities for Stingray Explorer.
"""

import time
import psutil
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional


@dataclass
class OperationMetrics:
    """Metrics for a single operation."""

    name: str
    duration_ms: float
    memory_mb: float
    success: bool
    context: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


class PerformanceMonitor:
    """
    Monitor performance of operations in the Stingray Explorer backend.

    Tracks execution time, memory usage, and operation success rates.
    """

    def __init__(self, max_history: int = 100):
        """
        Initialize the performance monitor.

        Args:
            max_history: Maximum number of operations to keep in history
        """
        self.max_history = max_history
        self.history: List[OperationMetrics] = []
        self._process = psutil.Process()

    @contextmanager
    def track_operation(
        self, name: str, **context: Any
    ) -> Generator[None, None, None]:
        """
        Context manager to track an operation's performance.

        Args:
            name: Name of the operation
            **context: Additional context to log with the metrics

        Example:
            >>> with monitor.track_operation("load_file", file_path="/data/obs.evt"):
            ...     data = load_file("/data/obs.evt")
        """
        start_time = time.perf_counter()
        start_memory = self._get_memory_mb()
        success = True

        try:
            yield
        except Exception:
            success = False
            raise
        finally:
            end_time = time.perf_counter()
            end_memory = self._get_memory_mb()

            metrics = OperationMetrics(
                name=name,
                duration_ms=(end_time - start_time) * 1000,
                memory_mb=end_memory - start_memory,
                success=success,
                context=context,
            )

            self._add_to_history(metrics)

    def _get_memory_mb(self) -> float:
        """Get current memory usage in megabytes."""
        try:
            return self._process.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0

    def _add_to_history(self, metrics: OperationMetrics) -> None:
        """Add metrics to history, trimming if necessary."""
        self.history.append(metrics)
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

    def get_memory_usage(self) -> Dict[str, float]:
        """
        Get current memory usage information.

        Returns:
            Dictionary with memory usage metrics
        """
        try:
            memory_info = self._process.memory_info()
            virtual_memory = psutil.virtual_memory()

            return {
                "process_mb": memory_info.rss / (1024 * 1024),
                "process_percent": self._process.memory_percent(),
                "system_total_gb": virtual_memory.total / (1024**3),
                "system_available_gb": virtual_memory.available / (1024**3),
                "system_percent": virtual_memory.percent,
            }
        except Exception:
            return {}

    def get_cpu_usage(self) -> Dict[str, float]:
        """
        Get current CPU usage information.

        Returns:
            Dictionary with CPU usage metrics

        Note:
            Using interval=0.1 for cpu_percent() to get accurate readings.
            Without an interval, the first call returns 0.0 (psutil quirk).
        """
        try:
            return {
                "process_percent": self._process.cpu_percent(interval=0.1),
                "system_percent": psutil.cpu_percent(interval=None),
                "cpu_count": psutil.cpu_count(),
            }
        except Exception:
            return {}

    def get_recent_operations(self, count: int = 10) -> List[Dict[str, Any]]:
        """
        Get recent operation metrics.

        Args:
            count: Number of recent operations to return

        Returns:
            List of operation metrics dictionaries
        """
        recent = self.history[-count:] if self.history else []
        return [
            {
                "name": op.name,
                "duration_ms": op.duration_ms,
                "memory_mb": op.memory_mb,
                "success": op.success,
                "context": op.context,
                "timestamp": op.timestamp,
            }
            for op in recent
        ]

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get aggregate statistics from operation history.

        Returns:
            Dictionary with aggregate statistics
        """
        if not self.history:
            return {"total_operations": 0}

        durations = [op.duration_ms for op in self.history]
        successes = sum(1 for op in self.history if op.success)

        return {
            "total_operations": len(self.history),
            "success_rate": successes / len(self.history),
            "avg_duration_ms": sum(durations) / len(durations),
            "max_duration_ms": max(durations),
            "min_duration_ms": min(durations),
        }

    def clear_history(self) -> None:
        """Clear operation history."""
        self.history.clear()
