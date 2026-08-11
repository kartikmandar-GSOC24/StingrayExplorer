"""FastAPI routes for the curated Miscellaneous Utilities workbench."""

from __future__ import annotations

import asyncio
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from services.misc_service import MiscService
from services.utility_helpers import MAX_ARRAY_INPUT, MAX_EXACT_OUTPUT, MAX_MATRIX_CELLS
from routes.utility_models import UtilityResponse

router = APIRouter()

NumericArray = Annotated[list[StrictFloat], Field(max_length=MAX_ARRAY_INPUT)]
MatrixRow = Annotated[list[StrictFloat], Field(max_length=MAX_MATRIX_CELLS)]
SampleMatrix = Annotated[list[MatrixRow], Field(max_length=MAX_MATRIX_CELLS)]
OutputMean = Annotated[list[StrictFloat], Field(max_length=MAX_EXACT_OUTPUT)]


def get_misc_service(request: Request) -> MiscService:
    """Build a request-scoped service over the application's shared state."""

    return MiscService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


class UtilityRequest(BaseModel):
    """Strict base model: renderer payloads may not smuggle unused fields."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)


class LinearRebinRequest(UtilityRequest):
    x: NumericArray
    y: NumericArray
    dx_new: StrictFloat
    y_error: Optional[NumericArray] = None
    method: Literal["sum", "mean"] = "sum"
    dx: Optional[StrictFloat] = None


class LogarithmicRebinRequest(UtilityRequest):
    x: NumericArray
    y: NumericArray
    factor: StrictFloat
    y_error: Optional[NumericArray] = None
    dx: Optional[StrictFloat] = None


class BaselineRequest(UtilityRequest):
    x: NumericArray
    y: NumericArray
    lam: StrictFloat = 1e11
    asymmetry: StrictFloat = 0.001
    iterations: StrictInt = 10
    offset_correction: StrictBool = False


class WindowRequest(UtilityRequest):
    n_samples: StrictInt
    window_type: StrictStr = "uniform"


class OptimalBinTimeRequest(UtilityRequest):
    fft_length: StrictFloat
    proposed_bin_time: StrictFloat


class NearestPowerOfTwoRequest(UtilityRequest):
    value: StrictInt


class SegmentSizeRequest(UtilityRequest):
    segment_size: StrictFloat
    dt: StrictFloat
    tolerance: StrictFloat = 0.01


class PoissonErrorRequest(UtilityRequest):
    counts: NumericArray


class StandardErrorRequest(UtilityRequest):
    samples: SampleMatrix
    mean: Optional[OutputMean] = None


class EqualCountEnergyRangesRequest(UtilityRequest):
    n_ranges: StrictInt
    energies: Optional[NumericArray] = None
    event_list_name: Optional[StrictStr] = None
    energy_min: Optional[StrictFloat] = None
    energy_max: Optional[StrictFloat] = None
    energy_unit: StrictStr = "keV"


@router.get("/capabilities", response_model=UtilityResponse)
async def capabilities(service: MiscService = Depends(get_misc_service)):
    """Report exact installed window types, defaults and allocation caps."""

    return await asyncio.to_thread(service.capabilities)


@router.post("/rebin/linear", response_model=UtilityResponse)
async def linear_rebin(
    request: LinearRebinRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Linearly rebin values with optional standard uncertainties."""

    return await asyncio.to_thread(
        service.linear_rebin,
        request.x,
        request.y,
        request.dx_new,
        y_error=request.y_error,
        method=request.method,
        dx=request.dx,
    )


@router.post("/rebin/logarithmic", response_model=UtilityResponse)
async def logarithmic_rebin(
    request: LogarithmicRebinRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Logarithmically rebin values using Stingray's mean-only helper."""

    return await asyncio.to_thread(
        service.logarithmic_rebin,
        request.x,
        request.y,
        request.factor,
        y_error=request.y_error,
        dx=request.dx,
    )


@router.post("/baseline", response_model=UtilityResponse)
async def estimate_baseline(
    request: BaselineRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Estimate and remove an asymmetric least-squares baseline."""

    return await asyncio.to_thread(
        service.estimate_baseline,
        request.x,
        request.y,
        lam=request.lam,
        asymmetry=request.asymmetry,
        iterations=request.iterations,
        offset_correction=request.offset_correction,
    )


@router.post("/window", response_model=UtilityResponse)
async def generate_window(
    request: WindowRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Generate one installed Stingray analysis window."""

    return await asyncio.to_thread(
        service.generate_window,
        request.n_samples,
        request.window_type,
    )


@router.post("/sampling/optimal-bin-time", response_model=UtilityResponse)
async def calculate_optimal_bin_time(
    request: OptimalBinTimeRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Find a nearby bin time yielding a power-of-two FFT sample count."""

    return await asyncio.to_thread(
        service.calculate_optimal_bin_time,
        request.fft_length,
        request.proposed_bin_time,
    )


@router.post("/sampling/nearest-power-of-two", response_model=UtilityResponse)
async def calculate_nearest_power_of_two(
    request: NearestPowerOfTwoRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Find Stingray's nearest integral power of two."""

    return await asyncio.to_thread(
        service.calculate_nearest_power_of_two, request.value
    )


@router.post("/sampling/segment-size", response_model=UtilityResponse)
async def adjust_segment_size(
    request: SegmentSizeRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Adjust a segment size to an integer number of samples."""

    return await asyncio.to_thread(
        service.adjust_segment_size,
        request.segment_size,
        request.dt,
        tolerance=request.tolerance,
    )


@router.post("/errors/poisson", response_model=UtilityResponse)
async def poisson_errors(
    request: PoissonErrorRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Calculate one-sigma symmetrized frequentist Poisson errors."""

    return await asyncio.to_thread(service.poisson_errors, request.counts)


@router.post("/errors/standard", response_model=UtilityResponse)
async def standard_error(
    request: StandardErrorRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Calculate column-wise standard errors for a sample matrix."""

    return await asyncio.to_thread(
        service.standard_error,
        request.samples,
        mean=request.mean,
    )


@router.post("/energy-ranges", response_model=UtilityResponse)
async def equal_count_ranges(
    request: EqualCountEnergyRangesRequest,
    service: MiscService = Depends(get_misc_service),
):
    """Create equal-count energy ranges from pasted or loaded EventList data."""

    return await asyncio.to_thread(
        service.equal_count_ranges,
        n_ranges=request.n_ranges,
        energies=request.energies,
        event_list_name=request.event_list_name,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        energy_unit=request.energy_unit,
    )


__all__ = [
    "BaselineRequest",
    "EqualCountEnergyRangesRequest",
    "LinearRebinRequest",
    "LogarithmicRebinRequest",
    "NearestPowerOfTwoRequest",
    "OptimalBinTimeRequest",
    "PoissonErrorRequest",
    "SegmentSizeRequest",
    "StandardErrorRequest",
    "WindowRequest",
    "get_misc_service",
    "router",
]
