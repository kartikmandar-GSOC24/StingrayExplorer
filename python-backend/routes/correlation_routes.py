"""
API routes for correlation operations.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.
"""

import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from services.correlation_service import CorrelationService

router = APIRouter()


def get_correlation_service(request: Request) -> CorrelationService:
    """Get CorrelationService instance from app state."""
    return CorrelationService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


# Request Models
class AutoCorrelationRequest(BaseModel):
    event_list_name: str
    dt: float
    mode: str = "same"
    norm: str = "none"


class CrossCorrelationRequest(BaseModel):
    event_list_1_name: str
    event_list_2_name: str
    dt: float
    mode: str = "same"
    norm: str = "none"


# Routes
@router.post("/auto-correlation")
async def auto_correlation(
    request: AutoCorrelationRequest,
    service: CorrelationService = Depends(get_correlation_service),
):
    """Auto-correlate an EventList's light curve with itself."""
    return await asyncio.to_thread(
        service.auto_correlation,
        event_list_name=request.event_list_name,
        dt=request.dt,
        mode=request.mode,
        norm=request.norm,
    )


@router.post("/cross-correlation")
async def cross_correlation(
    request: CrossCorrelationRequest,
    service: CorrelationService = Depends(get_correlation_service),
):
    """Cross-correlate two EventLists binned onto a shared time grid."""
    return await asyncio.to_thread(
        service.cross_correlation,
        event_list_1_name=request.event_list_1_name,
        event_list_2_name=request.event_list_2_name,
        dt=request.dt,
        mode=request.mode,
        norm=request.norm,
    )
