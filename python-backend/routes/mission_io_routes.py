"""FastAPI routes for Mission-Specific I/O Utilities."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.mission_io_service import MissionIOService
from services.utility_helpers import MAX_ARRAY_INPUT
from routes.utility_models import UtilityResponse


router = APIRouter()


def get_mission_io_service(request: Request) -> MissionIOService:
    """Build a request-scoped service over the shared application state."""
    return MissionIOService(
        state_manager=request.app.state.state_manager,
        performance_monitor=request.app.state.performance_monitor,
    )


class MissionInfoRequest(BaseModel):
    """Select a runtime mission mapping, optionally specialized by setup."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    mission: str = Field(min_length=1, max_length=128)
    instrument: Optional[str] = Field(default=None, min_length=1, max_length=128)
    mode: Optional[str] = Field(default=None, min_length=1, max_length=256)


class MissionIdentifyRequest(BaseModel):
    """Select exactly one loaded or Electron-granted FITS source."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    event_list_name: Optional[str] = Field(default=None, min_length=1)
    file_path: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    file_grant: Optional[str] = Field(default=None, min_length=1, max_length=512)
    mission_override: Optional[str] = Field(default=None, min_length=1, max_length=128)
    instrument_override: Optional[str] = Field(
        default=None, min_length=1, max_length=128
    )
    mode_override: Optional[str] = Field(default=None, min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_source(self) -> "MissionIdentifyRequest":
        if (self.event_list_name is None) == (self.file_path is None):
            raise ValueError(
                "Select exactly one source: event_list_name or file_path with file_grant"
            )
        if self.file_path is not None and self.file_grant is None:
            raise ValueError("file_grant is required with file_path")
        if self.event_list_name is not None and self.file_grant is not None:
            raise ValueError("file_grant is only valid with file_path")
        return self


class RoughPiConversionRequest(BaseModel):
    """Request an explicitly approximate public mission conversion."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    pi_values: Optional[list[float]] = Field(
        default=None,
        min_length=1,
        max_length=MAX_ARRAY_INPUT,
    )
    event_list_name: Optional[str] = Field(default=None, min_length=1)
    mission_override: Optional[str] = Field(default=None, min_length=1, max_length=128)
    instrument_override: Optional[str] = Field(
        default=None, min_length=1, max_length=128
    )
    mode_override: Optional[str] = Field(default=None, min_length=1, max_length=256)
    epoch_mjd: Optional[float] = None
    detector_ids: Optional[list[int]] = Field(
        default=None,
        min_length=1,
        max_length=MAX_ARRAY_INPUT,
    )
    save_as: Optional[str] = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source(self) -> "RoughPiConversionRequest":
        if (self.pi_values is None) == (self.event_list_name is None):
            raise ValueError("Provide exactly one of pi_values or event_list_name")
        if self.save_as is not None and self.event_list_name is None:
            raise ValueError("save_as is valid only for a loaded EventList source")
        return self


class MissionInterpretRequest(BaseModel):
    """Select one FITS file for supported read-only interpretation."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    file_path: str = Field(min_length=1, max_length=4096)
    file_grant: str = Field(min_length=1, max_length=512)
    mission_override: Optional[str] = Field(default=None, min_length=1, max_length=128)
    instrument_override: Optional[str] = Field(
        default=None, min_length=1, max_length=128
    )
    mode_override: Optional[str] = Field(default=None, min_length=1, max_length=256)


@router.get("/capabilities", response_model=UtilityResponse)
async def list_mission_capabilities(
    service: MissionIOService = Depends(get_mission_io_service),
):
    """List runtime xselect mappings and operation-specific capabilities."""
    return await asyncio.to_thread(service.list_capabilities)


@router.post("/info", response_model=UtilityResponse)
async def get_mission_info(
    request: MissionInfoRequest,
    service: MissionIOService = Depends(get_mission_io_service),
):
    """Read a runtime mission mapping for an instrument and observing mode."""
    return await asyncio.to_thread(
        service.get_mission_info,
        request.mission,
        instrument=request.instrument,
        mode=request.mode,
    )


@router.post("/identify", response_model=UtilityResponse)
async def identify_mission_source(
    request: MissionIdentifyRequest,
    service: MissionIOService = Depends(get_mission_io_service),
):
    """Identify mission metadata from a loaded EventList or granted FITS file."""
    return await asyncio.to_thread(
        service.identify_source,
        event_list_name=request.event_list_name,
        file_path=request.file_path,
        file_grant=request.file_grant,
        mission_override=request.mission_override,
        instrument_override=request.instrument_override,
        mode_override=request.mode_override,
    )


@router.post("/convert-pi", response_model=UtilityResponse)
async def convert_pi_to_energy(
    request: RoughPiConversionRequest,
    service: MissionIOService = Depends(get_mission_io_service),
):
    """Run a prominently labelled approximate PI-to-energy conversion."""
    return await asyncio.to_thread(
        service.convert_pi_to_energy,
        pi_values=request.pi_values,
        event_list_name=request.event_list_name,
        mission_override=request.mission_override,
        instrument_override=request.instrument_override,
        mode_override=request.mode_override,
        epoch_mjd=request.epoch_mjd,
        detector_ids=request.detector_ids,
        save_as=request.save_as,
    )


@router.post("/interpret", response_model=UtilityResponse)
async def interpret_mission_fits(
    request: MissionInterpretRequest,
    service: MissionIOService = Depends(get_mission_io_service),
):
    """Summarize supported interpretation on a bounded in-memory FITS copy."""
    return await asyncio.to_thread(
        service.interpret_selected_fits,
        file_path=request.file_path,
        file_grant=request.file_grant,
        mission_override=request.mission_override,
        instrument_override=request.instrument_override,
        mode_override=request.mode_override,
    )
