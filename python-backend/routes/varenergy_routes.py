"""
API routes for var-energy spectrum operations.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.
"""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from services.varenergy_service import VarEnergyService

router = APIRouter()


def get_varenergy_service(request: Request) -> VarEnergyService:
    """Get VarEnergyService instance from app state."""
    return VarEnergyService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


class RmsSpectrumRequest(BaseModel):
    # No reference band: stingray's RmsSpectrum ignores ref_band for a single
    # event list, so exposing one would be a control that does nothing.
    event_list_name: str
    bin_time: float
    segment_size: float
    freq_min: float
    freq_max: float
    energy_min: float
    energy_max: float
    n_bands: int = 5
    log_bands: bool = False
    norm: str = "frac"


class LagSpectrumRequest(BaseModel):
    event_list_name: str
    bin_time: float
    segment_size: float
    freq_min: float
    freq_max: float
    energy_min: float
    energy_max: float
    n_bands: int = 5
    log_bands: bool = False
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None


class ExcessVarianceRequest(BaseModel):
    # No frequency range and no segment_size: stingray's
    # ExcessVarianceSpectrum never reads freq_interval and ignores
    # segment_size entirely.
    event_list_name: str
    bin_time: float
    energy_min: float
    energy_max: float
    n_bands: int = 5
    log_bands: bool = False
    normalization: str = "fvar"


class VariableEnergySpectrumRequest(BaseModel):
    event_list_name: str
    bin_time: float
    segment_size: float
    freq_min: float
    freq_max: float
    energy_min: float
    energy_max: float
    n_bands: int = 5
    log_bands: bool = False
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None


class CovarianceSpectrumRequest(BaseModel):
    # Unsegmented page: the single segment spans the longest good-time
    # interval, so there is no segment_size field here.
    event_list_name: str
    bin_time: float
    freq_min: float
    freq_max: float
    energy_min: float
    energy_max: float
    n_bands: int = 5
    log_bands: bool = False
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None
    norm: str = "abs"


class AvgCovarianceSpectrumRequest(BaseModel):
    event_list_name: str
    bin_time: float
    segment_size: float
    freq_min: float
    freq_max: float
    energy_min: float
    energy_max: float
    n_bands: int = 5
    log_bands: bool = False
    ref_min: Optional[float] = None
    ref_max: Optional[float] = None
    norm: str = "abs"


@router.post("/rms-spectrum")
async def rms_spectrum(
    request: RmsSpectrumRequest,
    service: VarEnergyService = Depends(get_varenergy_service),
):
    """Compute the rms spectrum as a function of energy."""
    return await asyncio.to_thread(
        service.rms_spectrum,
        event_list_name=request.event_list_name,
        bin_time=request.bin_time,
        segment_size=request.segment_size,
        freq_min=request.freq_min,
        freq_max=request.freq_max,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        n_bands=request.n_bands,
        log_bands=request.log_bands,
        norm=request.norm,
    )


@router.post("/lag-spectrum")
async def lag_spectrum(
    request: LagSpectrumRequest,
    service: VarEnergyService = Depends(get_varenergy_service),
):
    """Compute the time-lag spectrum as a function of energy."""
    return await asyncio.to_thread(
        service.lag_spectrum,
        event_list_name=request.event_list_name,
        bin_time=request.bin_time,
        segment_size=request.segment_size,
        freq_min=request.freq_min,
        freq_max=request.freq_max,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        n_bands=request.n_bands,
        log_bands=request.log_bands,
        ref_min=request.ref_min,
        ref_max=request.ref_max,
    )


@router.post("/excess-variance")
async def excess_variance(
    request: ExcessVarianceRequest,
    service: VarEnergyService = Depends(get_varenergy_service),
):
    """Compute the excess-variance spectrum as a function of energy."""
    return await asyncio.to_thread(
        service.excess_variance_spectrum,
        event_list_name=request.event_list_name,
        bin_time=request.bin_time,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        n_bands=request.n_bands,
        log_bands=request.log_bands,
        normalization=request.normalization,
    )


@router.post("/variable-energy-spectrum")
async def variable_energy_spectrum(
    request: VariableEnergySpectrumRequest,
    service: VarEnergyService = Depends(get_varenergy_service),
):
    """Compute counts, fractional rms and lag spectra in one pass."""
    return await asyncio.to_thread(
        service.variable_energy_spectrum,
        event_list_name=request.event_list_name,
        bin_time=request.bin_time,
        segment_size=request.segment_size,
        freq_min=request.freq_min,
        freq_max=request.freq_max,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        n_bands=request.n_bands,
        log_bands=request.log_bands,
        ref_min=request.ref_min,
        ref_max=request.ref_max,
    )


@router.post("/covariance-spectrum")
async def covariance_spectrum(
    request: CovarianceSpectrumRequest,
    service: VarEnergyService = Depends(get_varenergy_service),
):
    """Compute the covariance spectrum over the whole observation."""
    return await asyncio.to_thread(
        service.covariance_spectrum,
        event_list_name=request.event_list_name,
        bin_time=request.bin_time,
        freq_min=request.freq_min,
        freq_max=request.freq_max,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        n_bands=request.n_bands,
        log_bands=request.log_bands,
        ref_min=request.ref_min,
        ref_max=request.ref_max,
        norm=request.norm,
    )


@router.post("/avg-covariance-spectrum")
async def avg_covariance_spectrum(
    request: AvgCovarianceSpectrumRequest,
    service: VarEnergyService = Depends(get_varenergy_service),
):
    """Compute the segment-averaged covariance spectrum."""
    return await asyncio.to_thread(
        service.avg_covariance_spectrum,
        event_list_name=request.event_list_name,
        bin_time=request.bin_time,
        segment_size=request.segment_size,
        freq_min=request.freq_min,
        freq_max=request.freq_max,
        energy_min=request.energy_min,
        energy_max=request.energy_max,
        n_bands=request.n_bands,
        log_bands=request.log_bands,
        ref_min=request.ref_min,
        ref_max=request.ref_max,
        norm=request.norm,
    )
