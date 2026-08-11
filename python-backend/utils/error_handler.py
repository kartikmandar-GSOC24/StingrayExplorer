"""
Error handling utilities for Stingray Explorer.
"""

import traceback
from typing import Any, Dict, Optional, Tuple


class ErrorHandler:
    """
    Centralized error handling for Stingray Explorer backend.

    Provides consistent error formatting and user-friendly messages.
    """

    # Mapping of common exception types to user-friendly messages
    ERROR_MESSAGES: Dict[type, str] = {
        FileNotFoundError: "The specified file could not be found",
        PermissionError: "Permission denied when accessing the file",
        ValueError: "Invalid value provided",
        TypeError: "Invalid data type",
        MemoryError: "Operation requires more memory than available",
        IOError: "Error reading or writing data",
        KeyError: "Required data field not found",
    }

    @classmethod
    def handle_error(
        cls,
        exception: Exception,
        context: str = "",
        include_traceback: bool = False,
        **context_data: Any,
    ) -> Tuple[str, str]:
        """
        Handle an exception and return user-friendly and technical messages.

        Args:
            exception: The exception that occurred
            context: Description of the operation that failed
            include_traceback: Whether to include full traceback in technical message
            **context_data: Additional context data to include

        Returns:
            Tuple of (user_friendly_message, technical_message)

        Example:
            >>> try:
            ...     data = load_file(path)
            ... except Exception as e:
            ...     user_msg, tech_msg = ErrorHandler.handle_error(
            ...         e, context="Loading file", file_path=path
            ...     )
        """
        # Get exception type and message
        exc_type = type(exception)
        exc_message = str(exception)

        # Create user-friendly message
        base_message = cls.ERROR_MESSAGES.get(
            exc_type, f"An error occurred: {exc_type.__name__}"
        )

        if context:
            user_message = f"{context}: {base_message}"
        else:
            user_message = base_message

        if exc_message and exc_message != str(exc_type):
            user_message = f"{user_message}. {exc_message}"

        # Create technical message
        tech_parts = [
            f"Exception: {exc_type.__name__}",
            f"Message: {exc_message}",
        ]

        if context:
            tech_parts.append(f"Context: {context}")

        if context_data:
            context_str = ", ".join(f"{k}={v}" for k, v in context_data.items())
            tech_parts.append(f"Data: {context_str}")

        if include_traceback:
            tech_parts.append(f"Traceback:\n{traceback.format_exc()}")

        technical_message = " | ".join(tech_parts)

        return user_message, technical_message

    @classmethod
    def format_validation_error(
        cls, field: str, expected: str, received: Any
    ) -> Tuple[str, str]:
        """
        Format a validation error message.

        Args:
            field: The field that failed validation
            expected: Description of expected value
            received: The actual value received

        Returns:
            Tuple of (user_friendly_message, technical_message)
        """
        user_message = f"Invalid {field}: expected {expected}, got {type(received).__name__}"
        technical_message = f"Validation error: {field}={received!r}, expected {expected}"

        return user_message, technical_message

    @classmethod
    def create_error_response(
        cls,
        exception: Exception,
        context: str = "",
        **context_data: Any,
    ) -> Dict[str, Any]:
        """
        Create a standardized error response dictionary.

        Args:
            exception: The exception that occurred
            context: Description of the operation that failed
            **context_data: Additional context data

        Returns:
            Error response dictionary
        """
        user_msg, tech_msg = cls.handle_error(
            exception, context=context, **context_data
        )

        return {
            "success": False,
            "data": None,
            "message": user_msg,
            "error": tech_msg,
            "error_type": type(exception).__name__,
        }
