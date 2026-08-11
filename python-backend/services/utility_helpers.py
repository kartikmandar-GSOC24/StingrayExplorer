"""Shared validation, provenance, preview, and file-grant helpers for Utilities."""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import stat
import time
from collections.abc import Generator, Iterable, Mapping, Sized
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from itertools import islice
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
import stingray

MAX_ARRAY_INPUT = 100_000
MAX_MATRIX_CELLS = 200_000
MAX_GTI_ROWS = 10_000
MAX_EXACT_OUTPUT = 100_000
MAX_PLOT_POINTS = 5_000
MAX_EXPORT_ROWS = 2_000_000
MAX_STATE_SNAPSHOT_CELLS = 2_000_000
MAX_STATE_SNAPSHOT_BYTES = 256 * 1024**2
MAX_FITS_INSPECT_BYTES = 8 * 1024**3
MAX_RMF_BYTES = 512 * 1024**2

DERIVED_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
FILE_GRANT_SECRET_ENV = "STINGRAY_FILE_GRANT_SECRET"
FILE_GRANT_MAX_FUTURE_SECONDS = 15 * 60
MAX_JSON_SAFE_WARNING_GROUPS = 32
SECURE_DIR_FD_OPERATIONS_SUPPORTED = all(
    operation in os.supports_dir_fd
    for operation in (os.open, os.mkdir, os.stat, os.unlink, os.rmdir, os.link)
)


@dataclass(frozen=True)
class GrantedReadFile:
    """An identity-verified file held open for the whole scientific read."""

    path: Path
    stream: BinaryIO
    size_bytes: int


@dataclass(frozen=True)
class GrantedWriteDestination:
    """A destination whose selected parent directory is held open and pinned."""

    path: Path
    parent_descriptor: int
    filename: str


@contextmanager
def duplicate_binary_stream(stream: BinaryIO) -> Generator[BinaryIO, None, None]:
    """Yield an independently closable descriptor for a pinned input file."""
    descriptor = os.dup(stream.fileno())
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as duplicate:
            descriptor = -1
            duplicate.seek(0)
            yield duplicate
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def validate_derived_name(name: str) -> str | None:
    """Return an actionable error for an invalid derived-object name."""
    if name != name.strip():
        return "Destination name must not start or end with whitespace"
    if not DERIVED_NAME_RE.fullmatch(name):
        return (
            "Destination name must be 1-64 characters, start with a letter or "
            "digit, and contain only letters, digits, spaces, '.', '_' or '-'"
        )
    return None


def validate_finite_array(
    values: Iterable[Any],
    *,
    label: str,
    min_size: int = 1,
    max_size: int = MAX_ARRAY_INPUT,
) -> tuple[np.ndarray | None, str | None]:
    """Convert a one-dimensional numeric input after bounded finite checks."""
    if isinstance(values, (bool, np.bool_)):
        return None, f"{label} must contain real numbers, not booleans"
    if isinstance(values, (str, bytes, bytearray, memoryview)):
        return None, f"{label} must be a one-dimensional array, not text"
    if isinstance(values, Mapping):
        return None, f"{label} must be a one-dimensional array, not a mapping"

    materialized: Any
    if type(values) is np.ndarray:
        if values.ndim != 1:
            return None, f"{label} must be a one-dimensional array"
        if values.size < min_size:
            return None, f"{label} must contain at least {min_size} value(s)"
        if values.size > max_size:
            return None, (
                f"{label} contains {values.size:,} values; the cap is {max_size:,}"
            )
        materialized = values
    elif type(values) in (list, tuple):
        value_count = len(values)
        if value_count < min_size:
            return None, f"{label} must contain at least {min_size} value(s)"
        if value_count > max_size:
            return None, (
                f"{label} contains {value_count:,} values; the cap is {max_size:,}"
            )
        materialized = values
    else:
        # Array-like inputs often expose their dimensions without requiring a
        # conversion.  Use those hints before touching an iterator so an
        # oversized request cannot force an unbounded temporary allocation.
        shape = getattr(values, "shape", None)
        if shape is not None:
            try:
                dimensions = tuple(shape)
            except TypeError:
                dimensions = ()
            if len(dimensions) != 1:
                return None, f"{label} must be a one-dimensional array"
            if (
                isinstance(dimensions[0], (int, np.integer))
                and int(dimensions[0]) > max_size
            ):
                return None, (
                    f"{label} contains {int(dimensions[0]):,} values; the cap is "
                    f"{max_size:,}"
                )

        hinted_size = getattr(values, "size", None)
        if isinstance(hinted_size, (int, np.integer)):
            if hinted_size < min_size:
                return None, f"{label} must contain at least {min_size} value(s)"
            if hinted_size > max_size:
                return None, (
                    f"{label} contains {hinted_size:,} values; the cap is {max_size:,}"
                )

        if isinstance(values, Sized):
            try:
                hinted_length = len(values)
            except (TypeError, ValueError, OverflowError):
                hinted_length = None
            if hinted_length is not None:
                if hinted_length < min_size:
                    return None, f"{label} must contain at least {min_size} value(s)"
                if hinted_length > max_size:
                    return None, (
                        f"{label} contains {hinted_length:,} values; the cap is "
                        f"{max_size:,}"
                    )

        try:
            materialized = list(islice(iter(values), max_size + 1))
        except (TypeError, ValueError) as exc:
            return None, f"{label} must contain only numeric values ({exc})"
        if len(materialized) > max_size:
            return None, (
                f"{label} contains at least {len(materialized):,} values; the cap is "
                f"{max_size:,}"
            )

    if isinstance(materialized, (list, tuple)):
        if any(isinstance(item, (bool, np.bool_)) for item in materialized):
            return None, f"{label} must contain real numbers, not booleans"
        if any(
            isinstance(item, (complex, np.complexfloating)) for item in materialized
        ):
            return None, f"{label} must contain real numbers, not complex values"
        if any(
            isinstance(item, (str, bytes, bytearray, memoryview))
            for item in materialized
        ):
            return None, f"{label} must contain real numbers, not text values"
        if any(isinstance(item, Mapping) for item in materialized):
            return None, f"{label} must contain real numbers, not mappings"
        # Nested iterables are already known not to satisfy the 1-D contract.
        # Reject them before NumPy can duplicate all of their cells in an
        # object array merely to discover the extra dimension.
        if any(
            isinstance(item, Iterable)
            and not isinstance(item, (str, bytes, bytearray, memoryview))
            for item in materialized
        ):
            return None, f"{label} must be a one-dimensional array"

    try:
        object_array = np.asarray(materialized, dtype=object)
        if any(isinstance(item, (bool, np.bool_)) for item in object_array.flat):
            return None, f"{label} must contain real numbers, not booleans"
        if any(
            isinstance(item, (complex, np.complexfloating))
            for item in object_array.flat
        ):
            return None, f"{label} must contain real numbers, not complex values"
        if any(
            isinstance(item, (str, bytes, bytearray, memoryview))
            for item in object_array.flat
        ):
            return None, f"{label} must contain real numbers, not text values"
        if any(isinstance(item, Mapping) for item in object_array.flat):
            return None, f"{label} must contain real numbers, not mappings"
        array = np.asarray(materialized, dtype=float)
    except (TypeError, ValueError) as exc:
        return None, f"{label} must contain only numeric values ({exc})"
    if array.ndim != 1:
        return None, f"{label} must be a one-dimensional array"
    if array.size < min_size:
        return None, f"{label} must contain at least {min_size} value(s)"
    if array.size > max_size:
        return None, f"{label} contains {array.size:,} values; the cap is {max_size:,}"
    bad = np.flatnonzero(~np.isfinite(array))
    if bad.size:
        index = int(bad[0])
        return None, f"{label}[{index}] must be finite"
    return array, None


def finite_or_none(value: Any, warnings: list[str], label: str) -> float | None:
    """Convert a numeric scalar to JSON-safe float, warning on non-finite output."""
    try:
        result = float(np.asarray(value).reshape(()))
    except (TypeError, ValueError):
        warnings.append(f"{label} could not be represented as a scalar and was omitted")
        return None
    if math.isfinite(result):
        return result
    warnings.append(f"{label} is non-finite and is represented as null")
    return None


class _JsonWarningCollector:
    """Aggregate repeated conversion warnings without retaining one per value."""

    def __init__(self) -> None:
        self.issues: dict[tuple[str, str], tuple[int, str]] = {}
        self.omitted_values = 0

    def add(self, kind: str, group: str, representative: str) -> None:
        key = (kind, group)
        if key in self.issues:
            count, first = self.issues[key]
            self.issues[key] = (count + 1, first)
        elif len(self.issues) < MAX_JSON_SAFE_WARNING_GROUPS:
            self.issues[key] = (1, representative)
        else:
            self.omitted_values += 1

    def flush(self, warnings: list[str]) -> None:
        for (kind, group), (count, representative) in self.issues.items():
            if kind == "nonfinite":
                warning = (
                    f"{representative} is non-finite and is represented as null"
                    if count == 1
                    else f"{group} contains {count:,} non-finite values represented as "
                    f"null; first at {representative}"
                )
            else:
                warning = (
                    f"{representative} is complex and cannot be represented in this "
                    "real-valued result"
                    if count == 1
                    else f"{group} contains {count:,} complex values that cannot be "
                    f"represented in this real-valued result; first at {representative}"
                )
            if warning not in warnings:
                warnings.append(warning)
        if self.omitted_values:
            warnings.append(
                f"{self.omitted_values:,} additional JSON-sanitizing issue(s) were "
                "omitted from warnings"
            )


def _json_safe(
    value: Any,
    collector: _JsonWarningCollector,
    label: str,
    sequence_group: str | None = None,
) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Decimal):
        if value.is_finite():
            converted = float(value)
            if math.isfinite(converted):
                return converted
        collector.add("nonfinite", sequence_group or label, label)
        return None
    if isinstance(value, dict):
        return {
            str(key): _json_safe(
                item,
                collector,
                f"{label}.{key}",
                sequence_group,
            )
            for key, item in value.items()
        }
    if isinstance(value, np.ndarray) and value.ndim == 0:
        return _json_safe(value.item(), collector, label, sequence_group)
    if isinstance(value, (list, tuple, np.ndarray)):
        group = sequence_group or label
        return [
            _json_safe(item, collector, f"{label}[{index}]", group)
            for index, item in enumerate(value)
        ]
    if isinstance(value, (complex, np.complexfloating)):
        collector.add("complex", sequence_group or label, label)
        return None
    if isinstance(value, (float, np.floating, np.integer)):
        result = float(value)
        if math.isfinite(result):
            return int(value) if isinstance(value, np.integer) else result
        collector.add("nonfinite", sequence_group or label, label)
        return None
    if hasattr(value, "tolist"):
        return _json_safe(value.tolist(), collector, label, sequence_group)
    return str(value)


def json_safe(value: Any, warnings: list[str], label: str = "result") -> Any:
    """Recursively convert scientific values to strict JSON with bounded warnings."""
    collector = _JsonWarningCollector()
    converted = _json_safe(value, collector, label)
    collector.flush(warnings)
    return converted


def bounded_plot_preview(
    *arrays: Iterable[Any], max_points: int = MAX_PLOT_POINTS
) -> dict[str, Any]:
    """Return aligned decimated plot arrays without changing exact result arrays."""
    if max_points < 1:
        raise ValueError("max_points must be a positive integer")
    converted = [np.asarray(array) for array in arrays]
    if not converted:
        return {"arrays": [], "stride": 1, "source_points": 0}
    size = len(converted[0])
    if any(len(array) != size for array in converted):
        raise ValueError("Plot preview arrays must have the same length")
    stride = max(1, math.ceil(size / max_points))
    return {
        "arrays": [array[::stride].tolist() for array in converted],
        "stride": stride,
        "source_points": size,
    }


def operation_provenance(
    operation: str,
    *,
    input_source: Any,
    parameters: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    """Create the common provenance block returned by every Utility operation."""
    return {
        "operation": operation,
        "input_source": input_source,
        "parameters": parameters,
        "stingray_version": stingray.__version__,
        **extra,
    }


def _canonical_path(file_path: str, *, must_exist: bool) -> Path:
    if not isinstance(file_path, str) or not file_path or "\x00" in file_path:
        raise ValueError(
            "A non-empty file path selected through the native dialog is required"
        )
    candidate = Path(file_path).expanduser()
    if must_exist:
        resolved = candidate.resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("The selected input path is not a regular file")
        return resolved

    if candidate.name in {"", ".", ".."}:
        raise ValueError("The selected destination filename is invalid")
    parent = candidate.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("The selected destination directory does not exist")
    return parent / candidate.name


def verify_file_grant(
    file_path: str,
    grant: str,
    *,
    access: str,
    must_exist: bool,
) -> Path:
    """Verify an Electron-issued HMAC grant for exactly one selected path.

    The renderer receives the selected absolute path and a short-lived token,
    but never receives the session secret shared by Electron main and FastAPI.
    It therefore cannot substitute an adjacent or manually typed path.
    """
    if access not in {"read", "write"}:
        raise ValueError("Invalid file-grant access mode")
    secret = os.environ.get(FILE_GRANT_SECRET_ENV, "")
    if not secret:
        raise PermissionError(
            "Native file grants are unavailable because the backend was not launched by Electron"
        )
    try:
        parts = grant.split(".")
        expires = int(parts[0])
        if len(parts) != 4:
            raise ValueError
        granted_device = int(parts[1])
        granted_inode = int(parts[2])
        supplied_digest = parts[3]
    except (AttributeError, TypeError, ValueError, IndexError) as exc:
        raise PermissionError("The native file selection grant is malformed") from exc

    now = int(time.time())
    if expires < now:
        raise PermissionError(
            "The native file selection grant has expired; select the file again"
        )
    if expires > now + FILE_GRANT_MAX_FUTURE_SECONDS:
        raise PermissionError("The native file selection grant expiry is invalid")

    resolved = _canonical_path(file_path, must_exist=must_exist)
    identity_suffix = f"\0{granted_device}\0{granted_inode}"
    message = f"{access}\0{expires}\0{resolved}{identity_suffix}".encode()
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_digest, expected):
        raise PermissionError("The path does not match the native file selection grant")
    identity_path = resolved if access == "read" else resolved.parent
    current = identity_path.stat()
    if access == "read":
        if not stat.S_ISREG(current.st_mode):
            raise PermissionError("The selected input is no longer a regular file")
        changed_message = (
            "The selected input file identity changed; select the file again"
        )
    else:
        if not stat.S_ISDIR(current.st_mode):
            raise PermissionError("The selected destination directory is unavailable")
        changed_message = (
            "The selected destination directory identity changed; choose it again"
        )
    if (current.st_dev, current.st_ino) != (granted_device, granted_inode):
        raise PermissionError(changed_message)
    return resolved


@contextmanager
def open_verified_read_grant(
    file_path: str,
    grant: str,
) -> Generator[GrantedReadFile, None, None]:
    """Open one granted file and pin all later reads to its verified inode.

    The native grant includes the device/inode observed by Electron main.  We
    re-check that identity on the descriptor itself and keep the descriptor
    open, so replacing the pathname after validation cannot redirect Astropy
    or Stingray to a different file.
    """
    path = verify_file_grant(
        file_path,
        grant,
        access="read",
        must_exist=True,
    )
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        # Re-parse only the authenticated identity fields. verify_file_grant
        # already validated their shape, expiry, and signature.
        parts = grant.split(".")
        granted_identity = (int(parts[1]), int(parts[2]))
        if not stat.S_ISREG(opened.st_mode):
            raise PermissionError("The selected input is no longer a regular file")
        if (opened.st_dev, opened.st_ino) != granted_identity:
            raise PermissionError(
                "The selected input file identity changed; select the file again"
            )
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            descriptor = -1
            yield GrantedReadFile(
                path=path,
                stream=stream,
                size_bytes=opened.st_size,
            )
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def open_verified_write_grant(
    file_path: str,
    grant: str,
) -> Generator[GrantedWriteDestination, None, None]:
    """Pin the identity-verified destination directory for an export.

    Export mutations must use ``parent_descriptor`` and relative names.  This
    prevents an ancestor rename/replacement after grant validation from
    redirecting writes or cleanup into a different directory.
    """
    if not SECURE_DIR_FD_OPERATIONS_SUPPORTED:
        raise PermissionError(
            "Secure native exports are unavailable on this platform because "
            "directory-relative file operations are unsupported"
        )
    path = verify_file_grant(
        file_path,
        grant,
        access="write",
        must_exist=False,
    )
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path.parent, flags)
    try:
        opened = os.fstat(descriptor)
        parts = grant.split(".")
        granted_identity = (int(parts[1]), int(parts[2]))
        if not stat.S_ISDIR(opened.st_mode):
            raise PermissionError("The selected destination directory is unavailable")
        if (opened.st_dev, opened.st_ino) != granted_identity:
            raise PermissionError(
                "The selected destination directory identity changed; choose it again"
            )
        yield GrantedWriteDestination(
            path=path,
            parent_descriptor=descriptor,
            filename=path.name,
        )
    finally:
        os.close(descriptor)


def assert_new_destination(path: Path) -> None:
    """Reject existing destinations; Utility exports never overwrite silently."""
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"Destination already exists: {path}")


def validate_file_size(path: Path | BinaryIO, maximum: int, label: str) -> int:
    """Return selected file size after an explicit cap check."""
    size = (
        os.fstat(path.fileno()).st_size
        if hasattr(path, "fileno")
        else path.stat().st_size
    )
    if size > maximum:
        raise ValueError(
            f"{label} is {size / 1024**2:.1f} MiB; the supported cap is {maximum / 1024**2:.1f} MiB"
        )
    return size
