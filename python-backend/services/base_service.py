"""
Base service class for Stingray Explorer backend.

Provides common functionality for all services.
"""

from typing import Any, Dict, Optional

from .state_manager import StateManager
from utils.error_handler import ErrorHandler
from utils.performance_monitor import PerformanceMonitor


class BaseService:
    """
    Base class for all services in the Stingray Explorer backend.

    Provides:
    - Access to StateManager for data persistence
    - Access to ErrorHandler for consistent error handling
    - Standard result format for all service methods
    """

    def __init__(
        self,
        state_manager: StateManager,
        performance_monitor: Optional[PerformanceMonitor] = None,
    ):
        """
        Initialize the base service.

        Args:
            state_manager: The application state manager instance
            performance_monitor: Optional performance monitor instance
        """
        self.state = state_manager
        self.error_handler = ErrorHandler
        self.performance_monitor = performance_monitor

    def create_result(
        self,
        success: bool,
        data: Any = None,
        message: str = "",
        error: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Create a standardized result dictionary.

        All service methods should return results in this format.

        Args:
            success: Whether the operation succeeded
            data: The result data
            message: User-friendly message
            error: Technical error message
            **kwargs: Additional fields to include

        Returns:
            Standardized result dictionary
        """
        result: Dict[str, Any] = {
            "success": success,
            "data": data,
            "message": message,
            "error": error,
        }
        result.update(kwargs)
        return result

    def handle_error(
        self,
        exception: Exception,
        context: str,
        **context_data: Any,
    ) -> Dict[str, Any]:
        """
        Handle an exception and return a standardized error result.

        Args:
            exception: The exception that occurred
            context: Description of the operation that failed
            **context_data: Additional context data

        Returns:
            Error result dictionary
        """
        user_msg, tech_msg = self.error_handler.handle_error(
            exception, context=context, **context_data
        )

        return self.create_result(
            success=False,
            data=None,
            message=user_msg,
            error=tech_msg,
        )
