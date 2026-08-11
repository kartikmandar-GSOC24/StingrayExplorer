"""Main-process-only native file-grant issuance.

This route is deliberately absent from OpenAPI and unavailable to renderer
requests. Electron main authenticates with both the backend session secret and
a distinct issuer secret that is never exposed through the renderer bridge.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from services.utility_helpers import (
    issue_file_grant,
    validated_file_grant_secret,
)

GRANT_ISSUER_HEADER = "x-stingray-grant-issuer"

router = APIRouter()


class FileGrantIssueRequest(BaseModel):
    """One exact path selected by Electron's native dialog."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=4_096)
    access: Literal["read", "write"]


class FileGrantIssueResponse(BaseModel):
    """Canonical selected path and its opaque, short-lived grant."""

    model_config = ConfigDict(extra="forbid", strict=True)

    path: str = Field(min_length=1, max_length=4_096)
    grant: str = Field(min_length=1, max_length=512)
    expires_at: int


def require_main_grant_issuer(request: Request) -> str:
    """Authenticate Electron main independently from the renderer session."""
    if any(
        name.lower() == b"origin" for name, _value in request.scope.get("headers", [])
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Browser-origin requests cannot issue native file grants",
        )

    configured = getattr(request.app.state, "_file_grant_secret", None)
    configured_bytes = validated_file_grant_secret(configured)
    if configured_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Native file-grant issuance is not configured",
        )

    supplied_values = [
        value
        for name, value in request.scope.get("headers", [])
        if name.lower() == GRANT_ISSUER_HEADER.encode("ascii")
    ]
    authenticated = len(supplied_values) == 1 and secrets.compare_digest(
        supplied_values[0], configured_bytes
    )
    if not authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Native file-grant issuer authentication required",
        )
    return configured


@router.post(
    "/file-grants/issue",
    response_model=FileGrantIssueResponse,
    include_in_schema=False,
)
async def issue_native_file_grant(
    request: FileGrantIssueRequest,
    response: Response,
    issuer_secret: str = Depends(require_main_grant_issuer),
) -> FileGrantIssueResponse:
    """Issue one grant using Python's canonical path and filesystem identity."""
    response.headers["Cache-Control"] = "no-store"
    try:
        issued = await asyncio.to_thread(
            issue_file_grant,
            request.path,
            access=request.access,
            secret=issuer_secret,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Native file-grant issuance is not configured",
        ) from exc
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected path is not eligible for the requested access",
        ) from exc

    return FileGrantIssueResponse(
        path=str(issued.path),
        grant=issued.grant,
        expires_at=issued.expires_at,
    )
