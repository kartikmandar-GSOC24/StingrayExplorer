"""
Stingray Explorer Python Backend

FastAPI server providing REST API endpoints for X-ray timing analysis
using the Stingray library.
"""

import logging
import os
import secrets
import signal
import socket
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from routes import (
    archive_routes,
    correlation_routes,
    data_routes,
    deadtime_routes,
    export_routes,
    gti_routes,
    io_utility_routes,
    job_routes,
    lightcurve_routes,
    log_routes,
    misc_routes,
    mission_io_routes,
    spectrum_routes,
    statistics_routes,
    timing_routes,
    varenergy_routes,
)
from services.state_manager import StateManager
from services.data_service import DataService
from services.job_manager import JobManager
from utils.performance_monitor import PerformanceMonitor
from utils.log_stream import log_stream_manager

MAX_REQUEST_BODY_BYTES = 8 * 1024**2
MAX_SERIALIZED_VALIDATION_ERRORS = 50
MAX_VALIDATION_MESSAGE_CHARS = 512
MAX_VALIDATION_LOCATION_PARTS = 16
BACKEND_SESSION_ENV = "STINGRAY_BACKEND_SESSION_SECRET"
BACKEND_SESSION_HEADER = "x-stingray-session"
MIN_BACKEND_SESSION_SECRET_BYTES = 32
ALLOWED_RENDERER_ORIGINS = ("http://localhost:5173", "null")
ALLOWED_CORS_METHODS = ("GET", "POST", "DELETE", "OPTIONS")
ALLOWED_CORS_HEADERS = ("Accept", "Content-Type", "X-Stingray-Session")


def _scope_header_values(scope: Scope, header_name: bytes) -> list[bytes]:
    """Return every value for one ASGI header without hiding duplicates."""

    return [
        value for name, value in scope.get("headers", []) if name.lower() == header_name
    ]


class BackendSessionMiddleware:
    """Authenticate every state-bearing loopback request before route execution."""

    def __init__(self, app: ASGIApp, session_secret: str | None) -> None:
        self.app = app
        encoded = session_secret.encode("utf-8") if session_secret else b""
        self.session_secret = (
            encoded if len(encoded) >= MIN_BACKEND_SESSION_SECRET_BYTES else None
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        origin_values = _scope_header_values(scope, b"origin")
        if len(origin_values) > 1:
            await self._reject(scope, receive, send, 403, "Origin is not allowed")
            return
        if origin_values:
            try:
                origin = origin_values[0].decode("ascii")
            except UnicodeDecodeError:
                origin = ""
            if origin not in ALLOWED_RENDERER_ORIGINS:
                await self._reject(scope, receive, send, 403, "Origin is not allowed")
                return

        # A health probe is intentionally public, but contains no application state.
        if scope.get("path") == "/health":
            await self.app(scope, receive, send)
            return

        # Browser preflights cannot carry the per-launch credential. The outer
        # CORSMiddleware validates the requested origin, method, and headers and
        # terminates genuine preflights before they reach this middleware.
        if scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        if self.session_secret is None:
            await self._reject(
                scope,
                receive,
                send,
                503,
                "Backend session authentication is not configured",
            )
            return

        credential_values = _scope_header_values(
            scope, BACKEND_SESSION_HEADER.encode("ascii")
        )
        authenticated = len(credential_values) == 1 and secrets.compare_digest(
            credential_values[0], self.session_secret
        )
        if not authenticated:
            await self._reject(
                scope, receive, send, 401, "Backend session authentication required"
            )
            return

        await self.app(scope, receive, send)

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse(status_code=status_code, content={"detail": detail})
        await response(scope, receive, send)


class RequestBodyLimitMiddleware:
    """Reject oversized HTTP bodies even when Content-Length is absent or false."""

    def __init__(self, app: ASGIApp, max_body_size: int) -> None:
        self.app = app
        self.max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                declared_size = int(value)
            except ValueError:
                # The server normally rejects malformed Content-Length values.
                # Counting the received bytes is still safe if one reaches here.
                continue
            if declared_size > self.max_body_size:
                await self._send_too_large(scope, receive, send)
                return

        buffered_messages: list[Message] = []
        received_size = 0
        while True:
            message = await receive()
            buffered_messages.append(message)
            if message["type"] == "http.disconnect":
                break
            if message["type"] != "http.request":
                continue

            received_size += len(message.get("body", b""))
            if received_size > self.max_body_size:
                await self._send_too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        message_index = 0

        async def replay_receive() -> Message:
            nonlocal message_index
            if message_index < len(buffered_messages):
                message = buffered_messages[message_index]
                message_index += 1
                return message
            # Streaming responses keep listening for a real client disconnect
            # after the request body has been consumed.  Fabricating one here
            # would cancel their response producer before it can finish.
            return await receive()

        await self.app(scope, replay_receive, send)

    async def _send_too_large(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit_mib = self.max_body_size // 1024**2
        response = JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {limit_mib} MiB limit"},
        )
        await response(scope, receive, send)


def _bounded_validation_errors(exception: RequestValidationError) -> list[dict]:
    """Return useful validation details without reflecting attacker-sized input."""

    errors = exception.errors()
    result: list[dict] = []
    for error in errors[:MAX_SERIALIZED_VALIDATION_ERRORS]:
        location = []
        for part in error.get("loc", ())[:MAX_VALIDATION_LOCATION_PARTS]:
            if isinstance(part, int):
                location.append(part)
            else:
                location.append(str(part)[:MAX_VALIDATION_MESSAGE_CHARS])
        result.append(
            {
                "type": str(error.get("type", "value_error"))[
                    :MAX_VALIDATION_MESSAGE_CHARS
                ],
                "loc": location,
                "msg": str(error.get("msg", "Invalid value"))[
                    :MAX_VALIDATION_MESSAGE_CHARS
                ],
                "input": None,
            }
        )

    omitted = len(errors) - len(result)
    if omitted:
        result.append(
            {
                "type": "validation_errors_omitted",
                "loc": ["body"],
                "msg": f"{omitted} additional validation error(s) omitted",
                "input": None,
            }
        )
    return result


# Filter to suppress /api/status access logs (polled every 2s, would flood logs)
class StatusEndpointFilter(logging.Filter):
    """Filter out /api/status requests from uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/api/status" not in record.getMessage()


# Global instances
state_manager: StateManager = None
performance_monitor: PerformanceMonitor = None
data_service: DataService = None
job_manager: JobManager = None


def find_free_port(start_port: int = 8765, max_attempts: int = 100) -> int:
    """Find a free port starting from start_port."""
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError(
        f"Could not find a free port in range {start_port}-{start_port + max_attempts}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup/shutdown events."""
    global state_manager, performance_monitor, data_service, job_manager

    # Startup
    print("Starting Stingray Explorer Backend...")
    state_manager = StateManager()
    performance_monitor = PerformanceMonitor()
    data_service = DataService(state_manager, performance_monitor)
    job_manager = JobManager(state_manager, data_service, max_workers=4)

    # Store in app state for access in routes
    app.state.state_manager = state_manager
    app.state.performance_monitor = performance_monitor
    app.state.data_service = data_service
    app.state.job_manager = job_manager

    # Install log streaming to capture Python logs and warnings
    log_stream_manager.install(log_level=logging.DEBUG)

    print("Backend initialized successfully")
    yield

    # Shutdown
    print("Shutting down Stingray Explorer Backend...")
    # Shutdown job manager
    if job_manager:
        job_manager.shutdown()
    # Uninstall log streaming
    log_stream_manager.uninstall()


def create_app(*, session_secret: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    resolved_session_secret = (
        session_secret
        if session_secret is not None
        else os.environ.get(BACKEND_SESSION_ENV)
    )
    app = FastAPI(
        title="Stingray Explorer API",
        description="REST API for X-ray timing analysis using the Stingray library",
        version="1.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestBodyLimitMiddleware, max_body_size=MAX_REQUEST_BODY_BYTES)
    app.add_middleware(BackendSessionMiddleware, session_secret=resolved_session_secret)

    # The renderer is either the fixed development origin or an authenticated
    # packaged file origin (serialized by Chromium as "null"). CORS is only a
    # browser response policy; BackendSessionMiddleware remains the auth boundary.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(ALLOWED_RENDERER_ORIGINS),
        allow_credentials=False,
        allow_methods=list(ALLOWED_CORS_METHODS),
        allow_headers=list(ALLOWED_CORS_HEADERS),
    )

    @app.exception_handler(RequestValidationError)
    async def json_safe_validation_error(
        _request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        """Serialize bounded strict JSON without reflecting the rejected payload."""
        return JSONResponse(
            status_code=422,
            content={"detail": _bounded_validation_errors(exception)},
        )

    # Register routes
    app.include_router(data_routes.router, prefix="/api/data", tags=["Data"])
    app.include_router(
        lightcurve_routes.router, prefix="/api/lightcurve", tags=["Lightcurve"]
    )
    app.include_router(
        spectrum_routes.router, prefix="/api/spectrum", tags=["Spectrum"]
    )
    app.include_router(timing_routes.router, prefix="/api/timing", tags=["Timing"])
    app.include_router(export_routes.router, prefix="/api/export", tags=["Export"])
    app.include_router(log_routes.router, prefix="/api/logs", tags=["Logs"])
    app.include_router(archive_routes.router, prefix="/api/archive", tags=["Archive"])
    app.include_router(job_routes.router, prefix="/api/jobs", tags=["Jobs"])
    app.include_router(
        correlation_routes.router, prefix="/api/correlation", tags=["Correlation"]
    )
    app.include_router(
        varenergy_routes.router, prefix="/api/varenergy", tags=["VarEnergy"]
    )
    app.include_router(
        deadtime_routes.router, prefix="/api/deadtime", tags=["Deadtime"]
    )
    app.include_router(
        statistics_routes.router,
        prefix="/api/utilities/statistics",
        tags=["Utilities - Statistics"],
    )
    app.include_router(
        gti_routes.router,
        prefix="/api/utilities/gti",
        tags=["Utilities - GTI"],
    )
    app.include_router(
        io_utility_routes.router,
        prefix="/api/utilities/io",
        tags=["Utilities - General I/O"],
    )
    app.include_router(
        mission_io_routes.router,
        prefix="/api/utilities/mission-io",
        tags=["Utilities - Mission I/O"],
    )
    app.include_router(
        misc_routes.router,
        prefix="/api/utilities/misc",
        tags=["Utilities - Miscellaneous"],
    )

    @app.get("/")
    async def root():
        """Root endpoint - health check."""
        return {"status": "ok", "message": "Stingray Explorer API is running"}

    @app.get("/health")
    async def health_check():
        """Health check endpoint for Electron to verify backend is ready."""
        return {"status": "healthy", "service": "stingray-explorer-backend"}

    @app.get("/api/status")
    async def get_status():
        """Get current application status including process-specific resources."""
        backend_resources = None

        if performance_monitor:
            mem_info = performance_monitor.get_memory_usage()
            cpu_info = performance_monitor.get_cpu_usage()

            backend_resources = {
                # Process-specific metrics (Python backend only)
                "memory_mb": mem_info.get("process_mb", 0),
                "memory_percent": mem_info.get("process_percent", 0),
                "cpu_percent": cpu_info.get("process_percent", 0),
                # System totals (for reference and percentage calculations)
                "system_memory_total_mb": mem_info.get("system_total_gb", 0) * 1024,
                "system_memory_available_mb": mem_info.get("system_available_gb", 0)
                * 1024,
                "system_cpu_count": cpu_info.get("cpu_count", 1),
            }

        return {
            "event_lists_loaded": len(state_manager.get_event_data())
            if state_manager
            else 0,
            "lightcurves_loaded": len(state_manager.get_lightcurve_data())
            if state_manager
            else 0,
            "backend_resources": backend_resources,
        }

    @app.post("/api/shutdown")
    async def shutdown():
        """Shutdown the backend server."""
        import asyncio
        import os

        async def shutdown_server():
            await asyncio.sleep(0.5)  # Give time for response to be sent
            os._exit(0)

        asyncio.create_task(shutdown_server())
        return {"status": "shutting_down"}

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn

    # Suppress /api/status access logs to avoid log flooding during polling
    logging.getLogger("uvicorn.access").addFilter(StatusEndpointFilter())

    # Get port from environment or command line, or find a free one
    requested_port = os.environ.get("PORT") or (
        sys.argv[1] if len(sys.argv) > 1 else None
    )

    if requested_port:
        port = int(requested_port)
    else:
        port = find_free_port(8765)

    # Print port so parent process can read it
    print(f"BACKEND_PORT:{port}", flush=True)

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}, shutting down...")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=port,
        reload=False,
        log_level="info",
    )
