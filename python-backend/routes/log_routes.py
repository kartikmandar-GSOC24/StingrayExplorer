"""
API routes for real-time log streaming via Server-Sent Events (SSE).
"""

import json
import logging
import warnings

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from utils.log_stream import log_stream_manager

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/stream")
async def stream_logs(request: Request) -> StreamingResponse:
    """
    Stream log messages via Server-Sent Events (SSE).

    This endpoint provides real-time streaming of Python logging output
    and warnings to the frontend. Logs are delivered as JSON objects
    in the SSE data field.

    Event Format:
        Log event:
        {
            "type": "log",
            "timestamp": "2024-01-15T10:30:00.123Z",
            "level": "warn",
            "source": "python",
            "logger": "stingray.events",
            "message": "No GTI found, using whole time range"
        }

        Heartbeat (every 30s of inactivity):
        {
            "type": "heartbeat",
            "timestamp": "2024-01-15T10:30:30.000Z"
        }

    Returns:
        StreamingResponse with SSE content type
    """

    async def event_generator():
        """Generate SSE events from the log stream."""
        async for log_entry in log_stream_manager.stream_logs():
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Format as SSE data event
            yield f"data: {json.dumps(log_entry)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering if behind proxy
        },
    )


@router.get("/status")
async def get_log_status() -> dict:
    """
    Get the status of the log streaming system.

    Returns:
        Dictionary with status information:
        - installed: Whether log streaming is active
        - active_connections: Number of connected SSE clients
        - queue_size: Number of buffered log entries
    """
    return {
        "success": True,
        "data": {
            "installed": log_stream_manager.is_installed,
            "active_connections": log_stream_manager.active_connections,
            "queue_size": log_stream_manager.queue_size,
        },
        "message": "Log stream status retrieved",
        "error": None,
    }


@router.post("/test")
async def test_log_generation() -> dict:
    """
    Generate test log messages at various levels for testing the SSE stream.

    This endpoint is for development/testing purposes only.
    """
    logger.debug("This is a DEBUG test message")
    logger.info("This is an INFO test message")
    logger.warning("This is a WARNING test message")
    logger.error("This is an ERROR test message")

    # Also test warning capture
    warnings.warn("This is a test warning from Python warnings module", UserWarning)

    return {
        "success": True,
        "data": None,
        "message": "Test logs generated (debug, info, warning, error, and a Python warning)",
        "error": None,
    }
