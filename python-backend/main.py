"""
Stingray Explorer Python Backend

FastAPI server providing REST API endpoints for X-ray timing analysis
using the Stingray library.
"""

import logging
import os
import signal
import socket
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import data_routes, lightcurve_routes, spectrum_routes, timing_routes, export_routes, log_routes, archive_routes, job_routes, correlation_routes, varenergy_routes, deadtime_routes
from services.state_manager import StateManager
from services.data_service import DataService
from services.job_manager import JobManager
from utils.performance_monitor import PerformanceMonitor
from utils.log_stream import log_stream_manager


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
    raise RuntimeError(f"Could not find a free port in range {start_port}-{start_port + max_attempts}")


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


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Stingray Explorer API",
        description="REST API for X-ray timing analysis using the Stingray library",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Configure CORS for Electron renderer
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # In production, restrict to electron app
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(data_routes.router, prefix="/api/data", tags=["Data"])
    app.include_router(lightcurve_routes.router, prefix="/api/lightcurve", tags=["Lightcurve"])
    app.include_router(spectrum_routes.router, prefix="/api/spectrum", tags=["Spectrum"])
    app.include_router(timing_routes.router, prefix="/api/timing", tags=["Timing"])
    app.include_router(export_routes.router, prefix="/api/export", tags=["Export"])
    app.include_router(log_routes.router, prefix="/api/logs", tags=["Logs"])
    app.include_router(archive_routes.router, prefix="/api/archive", tags=["Archive"])
    app.include_router(job_routes.router, prefix="/api/jobs", tags=["Jobs"])
    app.include_router(correlation_routes.router, prefix="/api/correlation", tags=["Correlation"])
    app.include_router(varenergy_routes.router, prefix="/api/varenergy", tags=["VarEnergy"])
    app.include_router(deadtime_routes.router, prefix="/api/deadtime", tags=["Deadtime"])

    @app.get("/")
    async def root():
        """Root endpoint - health check."""
        return {"status": "ok", "message": "Stingray Explorer API is running"}

    @app.get("/health")
    async def health_check():
        """Health check endpoint for Electron to verify backend is ready."""
        return {
            "status": "healthy",
            "version": "1.0.0",
            "state_manager": state_manager is not None,
        }

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
                "system_memory_available_mb": mem_info.get("system_available_gb", 0) * 1024,
                "system_cpu_count": cpu_info.get("cpu_count", 1),
            }

        return {
            "event_lists_loaded": len(state_manager.get_event_data()) if state_manager else 0,
            "lightcurves_loaded": len(state_manager.get_lightcurve_data()) if state_manager else 0,
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
    requested_port = os.environ.get("PORT") or (sys.argv[1] if len(sys.argv) > 1 else None)

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
