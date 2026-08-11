"""FastAPI routes for the Utilities GTI workbench."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from services.gti_service import GTIService
from services.utility_helpers import MAX_GTI_ROWS
from routes.utility_models import UtilityResponse

router = APIRouter()

TimeReference = Literal["absolute_mission_time", "relative_seconds"]
SetOperation = Literal["intersection", "union", "append"]
GtiRow = Annotated[list[float], Field(min_length=2, max_length=2)]


def get_gti_service(request: Request) -> GTIService:
    """Build a request-scoped service around the shared, thread-safe state."""
    return GTIService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


GTIServiceDependency = Annotated[GTIService, Depends(get_gti_service)]


class _RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class InspectRequest(_RequestModel):
    event_list_name: str = Field(min_length=1)


class ValidateRequest(_RequestModel):
    gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)
    time_reference: TimeReference = "absolute_mission_time"


class SetOperationRequest(_RequestModel):
    left_gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)
    right_gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)
    operation: SetOperation
    time_reference: TimeReference = "absolute_mission_time"


class BadTimeIntervalsRequest(_RequestModel):
    gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)
    start_time: float
    stop_time: float
    time_reference: TimeReference = "absolute_mission_time"


class MaskPreviewRequest(_RequestModel):
    event_list_name: str = Field(min_length=1)
    gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)


class MaskSaveRequest(MaskPreviewRequest):
    destination_name: str = Field(min_length=1, max_length=64)


class FixedSegmentsRequest(_RequestModel):
    gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)
    segment_size: float
    time_reference: TimeReference = "absolute_mission_time"


class ExposureSegmentsRequest(_RequestModel):
    gtis: list[GtiRow] = Field(max_length=MAX_GTI_ROWS)
    exposure_per_chunk: float
    new_interval_if_gti_sep: float | None = None
    time_reference: TimeReference = "absolute_mission_time"


@router.post("/inspect", response_model=UtilityResponse)
async def inspect(
    request: InspectRequest,
    service: GTIServiceDependency,
):
    """Inspect the effective GTIs on one loaded EventList."""
    return await asyncio.to_thread(service.inspect, request.event_list_name)


@router.post("/validate", response_model=UtilityResponse)
async def validate(
    request: ValidateRequest,
    service: GTIServiceDependency,
):
    """Validate manually entered GTIs without normalizing them."""
    return await asyncio.to_thread(
        service.validate,
        gtis=request.gtis,
        time_reference=request.time_reference,
    )


@router.post("/set-operation", response_model=UtilityResponse)
async def set_operation(
    request: SetOperationRequest,
    service: GTIServiceDependency,
):
    """Intersect, union, or append two valid GTI sets."""
    return await asyncio.to_thread(
        service.set_operation,
        left_gtis=request.left_gtis,
        right_gtis=request.right_gtis,
        operation=request.operation,
        time_reference=request.time_reference,
    )


@router.post("/bad-time-intervals", response_model=UtilityResponse)
async def bad_time_intervals(
    request: BadTimeIntervalsRequest,
    service: GTIServiceDependency,
):
    """Generate bad-time intervals inside an explicit observation range."""
    return await asyncio.to_thread(
        service.bad_time_intervals,
        gtis=request.gtis,
        start_time=request.start_time,
        stop_time=request.stop_time,
        time_reference=request.time_reference,
    )


@router.post("/mask/preview", response_model=UtilityResponse)
async def mask_preview(
    request: MaskPreviewRequest,
    service: GTIServiceDependency,
):
    """Preview retained/rejected events without changing state."""
    return await asyncio.to_thread(
        service.mask_preview,
        event_list_name=request.event_list_name,
        gtis=request.gtis,
    )


@router.post("/mask/save", response_model=UtilityResponse)
async def mask_save(
    request: MaskSaveRequest,
    service: GTIServiceDependency,
):
    """Save a GTI-filtered copy under a unique destination name."""
    return await asyncio.to_thread(
        service.save_masked,
        event_list_name=request.event_list_name,
        gtis=request.gtis,
        destination_name=request.destination_name,
    )


@router.post("/segment/fixed", response_model=UtilityResponse)
async def fixed_segments(
    request: FixedSegmentsRequest,
    service: GTIServiceDependency,
):
    """Generate fixed-duration segments fully contained within GTIs."""
    return await asyncio.to_thread(
        service.fixed_segments,
        gtis=request.gtis,
        segment_size=request.segment_size,
        time_reference=request.time_reference,
    )


@router.post("/segment/exposure", response_model=UtilityResponse)
async def exposure_segments(
    request: ExposureSegmentsRequest,
    service: GTIServiceDependency,
):
    """Split GTIs into approximate-exposure chunk groups."""
    return await asyncio.to_thread(
        service.split_by_exposure,
        gtis=request.gtis,
        exposure_per_chunk=request.exposure_per_chunk,
        new_interval_if_gti_sep=request.new_interval_if_gti_sep,
        time_reference=request.time_reference,
    )
