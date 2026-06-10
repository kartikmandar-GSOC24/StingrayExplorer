"""
API routes for Lightcurve operations.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from services.lightcurve_service import DEFAULT_MAX_PLOT_POINTS, LightcurveService

router = APIRouter()


def get_lightcurve_service(request: Request) -> LightcurveService:
    """Get LightcurveService instance from app state."""
    return LightcurveService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


# Request Models
class CreateLightcurveFromEventListRequest(BaseModel):
    event_list_name: str
    dt: float
    output_name: str
    gti: Optional[List[List[float]]] = None
    max_points: Optional[int] = Field(default=DEFAULT_MAX_PLOT_POINTS, ge=0)


class CreateLightcurveFromArraysRequest(BaseModel):
    times: List[float]
    counts: List[float]
    dt: float
    output_name: str


class RebinLightcurveRequest(BaseModel):
    name: str
    rebin_factor: float
    output_name: str
    max_points: Optional[int] = Field(default=DEFAULT_MAX_PLOT_POINTS, ge=0)


# Routes
@router.post("/from-event-list")
async def create_lightcurve_from_event_list(
    request: CreateLightcurveFromEventListRequest,
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Create a Lightcurve from an EventList."""
    return service.create_lightcurve_from_event_list(
        event_list_name=request.event_list_name,
        dt=request.dt,
        output_name=request.output_name,
        gti=request.gti,
        max_points=request.max_points,
    )


@router.post("/from-arrays")
async def create_lightcurve_from_arrays(
    request: CreateLightcurveFromArraysRequest,
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Create a Lightcurve from time and count arrays."""
    return service.create_lightcurve_from_arrays(
        times=request.times,
        counts=request.counts,
        dt=request.dt,
        output_name=request.output_name,
    )


@router.post("/rebin")
async def rebin_lightcurve(
    request: RebinLightcurveRequest,
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Rebin a lightcurve."""
    return service.rebin_lightcurve(
        name=request.name,
        rebin_factor=request.rebin_factor,
        output_name=request.output_name,
        max_points=request.max_points,
    )


@router.get("/{name}")
async def get_lightcurve_data(
    name: str,
    max_points: int = Query(default=DEFAULT_MAX_PLOT_POINTS, ge=0),
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Get lightcurve data for plotting."""
    return service.get_lightcurve_data(name, max_points=max_points)


@router.get("/")
async def list_lightcurves(
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """List all loaded lightcurves."""
    return service.list_lightcurves()


@router.delete("/{name}")
async def delete_lightcurve(
    name: str,
    service: LightcurveService = Depends(get_lightcurve_service),
):
    """Delete a lightcurve from state."""
    return service.delete_lightcurve(name)
