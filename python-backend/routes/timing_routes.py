"""
API routes for timing analysis operations.
"""

import asyncio
from typing import Dict, Optional, Tuple

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from services.timing_service import TimingService

router = APIRouter()


def get_timing_service(request: Request) -> TimingService:
    """Get TimingService instance from app state."""
    return TimingService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


# Request Models
class CreateBispectrumRequest(BaseModel):
    event_list_name: str
    dt: float
    maxlag: int = 25
    scale: str = "unbiased"
    window: str = "uniform"
    output_name: Optional[str] = None


class CalculatePowerColorsRequest(BaseModel):
    event_list_name: str
    dt: float
    segment_size: float
    freq_ranges: Dict[str, Tuple[float, float]]
    output_name: Optional[str] = None


class CalculateTimeLagsRequest(BaseModel):
    event_list_1_name: str
    event_list_2_name: str
    dt: float
    segment_size: float
    freq_range: Optional[Tuple[float, float]] = None
    output_name: Optional[str] = None


class CalculateCoherenceRequest(BaseModel):
    event_list_1_name: str
    event_list_2_name: str
    dt: float
    segment_size: float
    output_name: Optional[str] = None


# Routes
@router.post("/bispectrum")
async def create_bispectrum(
    request: CreateBispectrumRequest,
    service: TimingService = Depends(get_timing_service),
):
    """Create a bispectrum from an EventList."""
    return await asyncio.to_thread(
        service.create_bispectrum,
        event_list_name=request.event_list_name,
        dt=request.dt,
        maxlag=request.maxlag,
        scale=request.scale,
        window=request.window,
        output_name=request.output_name,
    )


@router.post("/power-colors")
async def calculate_power_colors(
    request: CalculatePowerColorsRequest,
    service: TimingService = Depends(get_timing_service),
):
    """Calculate power colors from frequency bands."""
    return await asyncio.to_thread(
        service.calculate_power_colors,
        event_list_name=request.event_list_name,
        dt=request.dt,
        segment_size=request.segment_size,
        freq_ranges=request.freq_ranges,
        output_name=request.output_name,
    )


@router.post("/time-lags")
async def calculate_time_lags(
    request: CalculateTimeLagsRequest,
    service: TimingService = Depends(get_timing_service),
):
    """Calculate time lags between two event lists."""
    return await asyncio.to_thread(
        service.calculate_time_lags,
        event_list_1_name=request.event_list_1_name,
        event_list_2_name=request.event_list_2_name,
        dt=request.dt,
        segment_size=request.segment_size,
        freq_range=request.freq_range,
        output_name=request.output_name,
    )


@router.post("/coherence")
async def calculate_coherence(
    request: CalculateCoherenceRequest,
    service: TimingService = Depends(get_timing_service),
):
    """Calculate coherence between two event lists."""
    return await asyncio.to_thread(
        service.calculate_coherence,
        event_list_1_name=request.event_list_1_name,
        event_list_2_name=request.event_list_2_name,
        dt=request.dt,
        segment_size=request.segment_size,
        output_name=request.output_name,
    )
