"""FastAPI routes for General I/O Utilities."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from services.io_utility_service import IOUtilityService
from routes.utility_models import UtilityResponse

router = APIRouter()


def get_io_utility_service(request: Request) -> IOUtilityService:
    """Create an I/O Utilities service over the application StateManager."""
    return IOUtilityService(
        state_manager=request.app.state.state_manager,
        performance_monitor=getattr(request.app.state, "performance_monitor", None),
    )


class GrantedInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    file_path: str = Field(min_length=1, max_length=4_096)
    file_grant: str = Field(min_length=1, max_length=512)


class RmfInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    rmf_path: str = Field(min_length=1, max_length=4_096)
    rmf_grant: str = Field(min_length=1, max_length=512)


class ConvertPiRequest(RmfInputRequest):
    pi_values: list[int] = Field(min_length=1, max_length=100_000)


class ConvertEventListRequest(RmfInputRequest):
    # Source names originate in the existing ingestion/state subsystem, which
    # has no length cap.  Do not make a valid selectable object unusable here;
    # the global request-body cap still bounds the HTTP payload.
    event_list_name: str = Field(min_length=1)
    save_as: str | None = Field(default=None, max_length=64)


class ExportObjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, strict=True)

    object_type: Literal["event_list", "lightcurve", "analysis_result"]
    object_name: str = Field(min_length=1)
    format: Literal["csv", "ecsv", "json", "fits", "hdf5"]
    destination_path: str = Field(min_length=1, max_length=4_096)
    destination_grant: str = Field(min_length=1, max_length=512)


@router.post("/inspect-file", response_model=UtilityResponse)
async def inspect_file(
    request: GrantedInputRequest,
    service: IOUtilityService = Depends(get_io_utility_service),
):
    """Inspect one exact native-selected file without loading FITS data arrays."""
    return await asyncio.to_thread(
        service.inspect_file,
        file_path=request.file_path,
        file_grant=request.file_grant,
    )


@router.post("/inspect-rmf", response_model=UtilityResponse)
async def inspect_rmf(
    request: RmfInputRequest,
    service: IOUtilityService = Depends(get_io_utility_service),
):
    """Inspect and validate the EBOUNDS portion of one selected RMF."""
    return await asyncio.to_thread(
        service.inspect_rmf,
        rmf_path=request.rmf_path,
        rmf_grant=request.rmf_grant,
    )


@router.post("/convert-pi", response_model=UtilityResponse)
async def convert_pi(
    request: ConvertPiRequest,
    service: IOUtilityService = Depends(get_io_utility_service),
):
    """Convert pasted PI channels with exact RMF EBOUNDS coverage."""
    return await asyncio.to_thread(
        service.convert_pi_values,
        pi_values=request.pi_values,
        rmf_path=request.rmf_path,
        rmf_grant=request.rmf_grant,
    )


@router.post("/convert-event-list", response_model=UtilityResponse)
async def convert_event_list(
    request: ConvertEventListRequest,
    service: IOUtilityService = Depends(get_io_utility_service),
):
    """Preview or explicitly save a calibrated copy of a loaded EventList."""
    return await asyncio.to_thread(
        service.convert_event_list,
        event_list_name=request.event_list_name,
        rmf_path=request.rmf_path,
        rmf_grant=request.rmf_grant,
        save_as=request.save_as,
    )


@router.get("/exportable-objects", response_model=UtilityResponse)
async def list_exportable_objects(
    service: IOUtilityService = Depends(get_io_utility_service),
):
    """List loaded objects and their tested safe export combinations."""
    return await asyncio.to_thread(service.list_exportable_objects)


@router.post("/export", response_model=UtilityResponse)
async def export_object(
    request: ExportObjectRequest,
    service: IOUtilityService = Depends(get_io_utility_service),
):
    """Exclusively create and reopen-verify one selected export destination."""
    return await asyncio.to_thread(
        service.export_object,
        object_type=request.object_type,
        object_name=request.object_name,
        export_format=request.format,
        destination_path=request.destination_path,
        destination_grant=request.destination_grant,
    )
