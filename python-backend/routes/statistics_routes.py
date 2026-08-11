"""Typed API routes for the Statistical Functions utility workbench."""

# FastAPI dependencies are intentionally declared by calling Depends in
# endpoint defaults, which is the framework's standard injection pattern.
# ruff: noqa: B008

from __future__ import annotations

import asyncio
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from services.statistics_service import MAX_COUNT_PARAMETER, StatisticsService

router = APIRouter()

Probability = Annotated[float, Field(strict=True, gt=0.0, lt=1.0)]
ClosedProbability = Annotated[float, Field(strict=True, ge=0.0, le=1.0)]
LogProbability = Annotated[float, Field(strict=True, lt=0.0)]
NonnegativeStatistic = Annotated[float, Field(strict=True, ge=0.0)]
PdmStatistic = Annotated[float, Field(strict=True, ge=0.0, le=1.0)]
PositiveCount = Annotated[int, Field(strict=True, ge=1, le=MAX_COUNT_PARAMETER)]
FoldPhaseBins = Annotated[int, Field(strict=True, ge=3, le=MAX_COUNT_PARAMETER)]
PdmPhaseBins = Annotated[int, Field(strict=True, ge=2, le=MAX_COUNT_PARAMETER)]
PdmSamples = Annotated[int, Field(strict=True, ge=3, le=MAX_COUNT_PARAMETER)]


class StrictRequest(BaseModel):
    """Reject unknown, non-finite, or coercion-dependent request values."""

    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        strict=True,
    )


class ServiceResponse(BaseModel):
    """Standard response envelope shared by backend services."""

    success: bool
    data: dict[str, Any] | None
    message: str
    error: str | None


class GaussianRequest(StrictRequest):
    probability: Probability | None = None
    log_probability: LogProbability | None = None
    sidedness: Literal["one-sided", "two-sided"] = "one-sided"

    @model_validator(mode="after")
    def require_exactly_one_probability(self) -> GaussianRequest:
        if (self.probability is None) == (self.log_probability is None):
            raise ValueError("Provide exactly one of probability or log_probability")
        return self


class TrialRequest(StrictRequest):
    direction: Literal["single-to-multi", "multi-to-single"]
    probability: ClosedProbability
    n_trials: PositiveCount

    @model_validator(mode="after")
    def inverse_probability_must_be_below_one(self) -> "TrialRequest":
        if self.direction == "multi-to-single" and self.probability == 1.0:
            raise ValueError(
                "probability must be less than 1 for multi-to-single conversion"
            )
        return self


class PdsEvaluateRequest(StrictRequest):
    power: NonnegativeStatistic
    n_trials: PositiveCount = 1
    n_summed_spectra: PositiveCount = 1
    n_rebin: PositiveCount = 1


class PdsDetectionRequest(StrictRequest):
    false_alarm_probability: Probability
    n_trials: PositiveCount = 1
    n_summed_spectra: PositiveCount = 1
    n_rebin: PositiveCount = 1


class Z2EvaluateRequest(StrictRequest):
    z2: NonnegativeStatistic
    harmonics: PositiveCount = 2
    n_trials: PositiveCount = 1
    n_summed_spectra: PositiveCount = 1


class Z2DetectionRequest(StrictRequest):
    false_alarm_probability: Probability
    harmonics: PositiveCount = 2
    n_trials: PositiveCount = 1
    n_summed_spectra: PositiveCount = 1


class FoldEvaluateRequest(StrictRequest):
    statistic: NonnegativeStatistic
    n_phase_bins: FoldPhaseBins
    n_trials: PositiveCount = 1


class FoldDetectionRequest(StrictRequest):
    false_alarm_probability: Probability
    n_phase_bins: FoldPhaseBins
    n_trials: PositiveCount = 1


class PdmBaseRequest(StrictRequest):
    n_samples: PdmSamples
    n_phase_bins: PdmPhaseBins
    n_trials: PositiveCount = 1

    @model_validator(mode="after")
    def samples_must_exceed_bins(self) -> PdmBaseRequest:
        if self.n_samples <= self.n_phase_bins:
            raise ValueError("n_samples must be greater than n_phase_bins")
        return self


class PdmEvaluateRequest(PdmBaseRequest):
    statistic: PdmStatistic


class PdmDetectionRequest(PdmBaseRequest):
    false_alarm_probability: Probability


def get_statistics_service(request: Request) -> StatisticsService:
    """Build the stateless service with the application's shared dependencies."""
    return StatisticsService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


@router.post("/gaussian", response_model=ServiceResponse)
async def gaussian_significance(
    request: GaussianRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Convert a one- or two-sided probability to Gaussian sigma."""
    return await asyncio.to_thread(
        service.gaussian_significance,
        probability=request.probability,
        log_probability=request.log_probability,
        sidedness=request.sidedness,
    )


@router.post("/trials", response_model=ServiceResponse)
async def convert_trials(
    request: TrialRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Convert between single-trial and overall independent-trial probability."""
    return await asyncio.to_thread(
        service.convert_trials,
        direction=request.direction,
        probability=request.probability,
        n_trials=request.n_trials,
    )


@router.post("/pds/evaluate", response_model=ServiceResponse)
async def evaluate_pds(
    request: PdsEvaluateRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Evaluate PDS false-alarm probability and natural-log probability."""
    return await asyncio.to_thread(
        service.evaluate_pds,
        power=request.power,
        n_trials=request.n_trials,
        n_summed_spectra=request.n_summed_spectra,
        n_rebin=request.n_rebin,
    )


@router.post("/pds/detection", response_model=ServiceResponse)
async def detect_pds(
    request: PdsDetectionRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Calculate a PDS threshold at an overall false-alarm probability."""
    return await asyncio.to_thread(
        service.detect_pds,
        false_alarm_probability=request.false_alarm_probability,
        n_trials=request.n_trials,
        n_summed_spectra=request.n_summed_spectra,
        n_rebin=request.n_rebin,
    )


@router.post("/z2/evaluate", response_model=ServiceResponse)
async def evaluate_z2(
    request: Z2EvaluateRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Evaluate Z-squared-n false-alarm and natural-log probabilities."""
    return await asyncio.to_thread(
        service.evaluate_z2,
        z2=request.z2,
        harmonics=request.harmonics,
        n_trials=request.n_trials,
        n_summed_spectra=request.n_summed_spectra,
    )


@router.post("/z2/detection", response_model=ServiceResponse)
async def detect_z2(
    request: Z2DetectionRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Calculate a Z-squared-n threshold at an overall false-alarm rate."""
    return await asyncio.to_thread(
        service.detect_z2,
        false_alarm_probability=request.false_alarm_probability,
        harmonics=request.harmonics,
        n_trials=request.n_trials,
        n_summed_spectra=request.n_summed_spectra,
    )


@router.post("/fold/evaluate", response_model=ServiceResponse)
async def evaluate_fold(
    request: FoldEvaluateRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Evaluate epoch-folding false-alarm and natural-log probabilities."""
    return await asyncio.to_thread(
        service.evaluate_fold,
        statistic=request.statistic,
        n_phase_bins=request.n_phase_bins,
        n_trials=request.n_trials,
    )


@router.post("/fold/detection", response_model=ServiceResponse)
async def detect_fold(
    request: FoldDetectionRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Calculate an epoch-folding threshold at an overall false-alarm rate."""
    return await asyncio.to_thread(
        service.detect_fold,
        false_alarm_probability=request.false_alarm_probability,
        n_phase_bins=request.n_phase_bins,
        n_trials=request.n_trials,
    )


@router.post("/pdm/evaluate", response_model=ServiceResponse)
async def evaluate_pdm(
    request: PdmEvaluateRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Evaluate lower-tail phase-dispersion probability and log probability."""
    return await asyncio.to_thread(
        service.evaluate_pdm,
        statistic=request.statistic,
        n_samples=request.n_samples,
        n_phase_bins=request.n_phase_bins,
        n_trials=request.n_trials,
    )


@router.post("/pdm/detection", response_model=ServiceResponse)
async def detect_pdm(
    request: PdmDetectionRequest,
    service: StatisticsService = Depends(get_statistics_service),
) -> dict[str, Any]:
    """Calculate a lower-tail PDM threshold at an overall false-alarm rate."""
    return await asyncio.to_thread(
        service.detect_pdm,
        false_alarm_probability=request.false_alarm_probability,
        n_samples=request.n_samples,
        n_phase_bins=request.n_phase_bins,
        n_trials=request.n_trials,
    )
