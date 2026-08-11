"""
API routes for dead-time correction operations.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from services.deadtime_service import DeadtimeService

router = APIRouter()


def get_deadtime_service(request: Request) -> DeadtimeService:
    """Get DeadtimeService instance from app state."""
    return DeadtimeService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


# Request Models
class PdsCorrectionRequest(BaseModel):
    # No `norm` field: deadtime_correct() assumes the Leahy white-noise level
    # of 2, so the service always builds the spectrum with norm="leahy".
    # No `paralyzable` field: stingray raises NotImplementedError for it.
    event_list_name: str
    dt: float
    segment_size: float
    dead_time: float
    background_rate: float = 0.0
    limit_k: int = 200


class FadCorrectionRequest(BaseModel):
    event_list_1_name: str
    event_list_2_name: str
    dt: float
    segment_size: float
    norm: str = "frac"
    smoothing_length: Optional[float] = None


# Routes
@router.post("/pds-correction")
async def pds_correction(
    request: PdsCorrectionRequest,
    service: DeadtimeService = Depends(get_deadtime_service),
):
    """Apply the model dead-time correction to an averaged power spectrum."""
    return await asyncio.to_thread(
        service.calculate_pds_correction,
        event_list_name=request.event_list_name,
        dt=request.dt,
        segment_size=request.segment_size,
        dead_time=request.dead_time,
        background_rate=request.background_rate,
        limit_k=request.limit_k,
    )


@router.post("/fad-correction")
async def fad_correction(
    request: FadCorrectionRequest,
    service: DeadtimeService = Depends(get_deadtime_service),
):
    """Apply the FAD dead-time correction using two independent detectors."""
    return await asyncio.to_thread(
        service.calculate_fad_correction,
        event_list_1_name=request.event_list_1_name,
        event_list_2_name=request.event_list_2_name,
        dt=request.dt,
        segment_size=request.segment_size,
        norm=request.norm,
        smoothing_length=request.smoothing_length,
    )
