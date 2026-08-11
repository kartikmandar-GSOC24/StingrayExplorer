"""Shared typed response envelope for Utilities routes."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class UtilityResponse(BaseModel):
    """Document and enforce the service envelope exposed by every Utility API."""

    model_config = ConfigDict(extra="allow")

    success: bool
    data: Any | None
    message: str
    error: str | None
    warnings: list[str] | None = None
