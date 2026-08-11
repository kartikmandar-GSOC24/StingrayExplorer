"""
Data service for EventList operations.

Handles loading, saving, and managing event lists.
Includes lazy loading support for large files.
"""

import asyncio
import gzip
import os
import re
import tempfile
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, BinaryIO, Dict, Generator, List, Optional

import numpy as np
import psutil
from astropy.io import fits
from stingray import EventList
from stingray.io import FITSTimeseriesReader

try:
    import h5py
except ImportError:  # Optional format support must not prevent app startup.
    h5py = None

from models.event_formats import (
    require_batch_input_formats,
    require_input_event_format,
)

from .base_service import BaseService
from .remote_source import (
    GENERAL_HTTPS_POLICY,
    RemoteSourceCancelled,
    RemoteSourceClient,
    RemoteSourceError,
)
from .utility_helpers import (
    MAX_FITS_INSPECT_BYTES,
    MAX_RMF_BYTES,
    GrantedReadFile,
    open_verified_read_grant,
    validate_derived_name,
)


SPOOL_MEMORY_LIMIT = 64 * 1024**2
REMOTE_EVENT_LIMIT = MAX_FITS_INSPECT_BYTES
COPY_CHUNK_SIZE = 1024 * 1024
MAX_PUBLIC_SCIENTIFIC_WARNINGS = 32
MAX_PUBLIC_WARNING_CHARS = 4096
_PRIVATE_LOCATOR = re.compile(
    r"(?:[A-Za-z][A-Za-z0-9+.-]*://|stingray-input-|"
    r"(?:^|[\s'\"(<])(?:/[^\s'\"<>]+|[A-Za-z]:[\\/]|\\\\))"
)


def _to_python_float(val):
    """Convert numpy numeric types to Python float for JSON serialization."""
    if val is None:
        return None
    try:
        # Handle numpy scalars (including longdouble/float128)
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_python_float_list(arr):
    """Convert numpy array to list of Python floats for JSON serialization."""
    if arr is None:
        return None
    try:
        # Convert each element explicitly to handle longdouble
        return [float(x) for x in arr]
    except (TypeError, ValueError):
        return arr.tolist() if hasattr(arr, "tolist") else list(arr)


def _safe_scientific_warning(captured_warning: Any) -> str | None:
    """Keep useful bounded warnings while dropping locator-bearing details."""
    if issubclass(captured_warning.category, ResourceWarning):
        return None
    text = str(captured_warning.message)[:MAX_PUBLIC_WARNING_CHARS]
    if _PRIVATE_LOCATOR.search(text):
        return f"{captured_warning.category.__name__} details were omitted"
    return text


@contextmanager
def _open_granted_source(
    file_path: str,
    file_grant: str | None,
    pinned_source: GrantedReadFile | None,
) -> Generator[GrantedReadFile, None, None]:
    """Yield an already pinned source or verify and pin a native grant now."""
    if pinned_source is not None:
        yield pinned_source
        return
    if not file_grant:
        raise PermissionError("A native read grant is required for the selected file")
    source_context = open_verified_read_grant(file_path, file_grant)
    try:
        source = source_context.__enter__()
    except Exception:
        # Native open failures can contain the selected pathname.  Keep that
        # capability out of API responses and framework exception logs.
        raise PermissionError(
            "The selected file could not be verified; select it again"
        ) from None

    body_failed = False
    try:
        yield source
    except BaseException:
        body_failed = True
        raise
    finally:
        try:
            source_context.__exit__(None, None, None)
        except Exception:
            if not body_failed:
                raise OSError("The selected input could not be closed safely") from None


@contextmanager
def _spooled_copy(
    source: GrantedReadFile,
    *,
    max_bytes: int,
    cancellation_check=None,
) -> Generator[BinaryIO, None, None]:
    """Copy one pinned input into a bounded anonymous application-owned file."""
    if source.size_bytes < 0 or source.size_bytes > max_bytes:
        raise ValueError(f"Selected input exceeds the {max_bytes}-byte safety cap")
    before = os.fstat(source.stream.fileno())
    if before.st_size != source.size_bytes:
        raise OSError("Selected input changed before it could be retained")
    with tempfile.SpooledTemporaryFile(
        max_size=SPOOL_MEMORY_LIMIT, mode="w+b"
    ) as spool:
        source.stream.seek(0)
        copied = 0
        while True:
            _raise_if_cancelled(cancellation_check)
            chunk = source.stream.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            copied += len(chunk)
            if copied > max_bytes:
                raise ValueError(
                    f"Selected input exceeds the {max_bytes}-byte safety cap"
                )
            spool.write(chunk)
        if copied != source.size_bytes:
            raise OSError("Selected input changed while it was being retained")
        after = os.fstat(source.stream.fileno())
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if after_identity != before_identity:
            raise OSError("Selected input changed while it was being retained")
        _raise_if_cancelled(cancellation_check)
        spool.seek(0)
        yield spool


def _rewind(stream: BinaryIO | None) -> None:
    if stream is not None:
        stream.seek(0)


def _raise_if_cancelled(cancellation_check) -> None:
    if cancellation_check is not None and cancellation_check():
        raise InterruptedError("The data operation was cancelled")


@contextmanager
def _decoded_event_stream(
    stream: BinaryIO,
    *,
    fmt: str,
    cancellation_check=None,
) -> Generator[BinaryIO, None, None]:
    """Decode gzip OGIP input into another capped anonymous spool."""
    _rewind(stream)
    magic = stream.read(2)
    _rewind(stream)
    if fmt not in {"ogip", "fits"} or magic != b"\x1f\x8b":
        yield stream
        return

    with gzip.GzipFile(fileobj=stream, mode="rb") as compressed:
        with tempfile.SpooledTemporaryFile(
            max_size=SPOOL_MEMORY_LIMIT, mode="w+b"
        ) as decoded:
            copied = 0
            while True:
                _raise_if_cancelled(cancellation_check)
                chunk = compressed.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_FITS_INSPECT_BYTES:
                    raise ValueError(
                        "Decompressed event input exceeds the scientific input cap"
                    )
                decoded.write(chunk)
            decoded.seek(0)
            _raise_if_cancelled(cancellation_check)
            yield decoded


@contextmanager
def _cloned_stream(
    stream: BinaryIO, *, cancellation_check=None
) -> Generator[BinaryIO, None, None]:
    """Give a reader that closes file objects its own bounded anonymous clone."""
    with tempfile.SpooledTemporaryFile(
        max_size=SPOOL_MEMORY_LIMIT, mode="w+b"
    ) as clone:
        _rewind(stream)
        copied = 0
        while True:
            _raise_if_cancelled(cancellation_check)
            chunk = stream.read(COPY_CHUNK_SIZE)
            if not chunk:
                break
            copied += len(chunk)
            if copied > MAX_FITS_INSPECT_BYTES:
                raise ValueError("Event input exceeds the scientific input cap")
            clone.write(chunk)
        _rewind(stream)
        clone.seek(0)
        _raise_if_cancelled(cancellation_check)
        yield clone


@contextmanager
def _scientific_reader_source(
    stream: BinaryIO,
    *,
    fmt: str,
    cancellation_check=None,
) -> Generator[BinaryIO | str, None, None]:
    """Adapt a retained stream for third-party readers that reopen by name.

    Astropy table/HDF5 readers consume file objects safely. Stingray's OGIP
    reader reopens its input multiple times, so it receives a private 0700
    directory snapshot rather than the originally selected pathname.
    """
    if fmt not in {"ogip", "fits"}:
        _rewind(stream)
        yield stream
        return

    with tempfile.TemporaryDirectory(prefix="stingray-input-") as directory:
        snapshot = Path(directory) / "events.evt"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(snapshot, flags, 0o600)
        try:
            _rewind(stream)
            copied = 0
            while True:
                _raise_if_cancelled(cancellation_check)
                chunk = stream.read(COPY_CHUNK_SIZE)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > MAX_FITS_INSPECT_BYTES:
                    raise ValueError("Event input exceeds the scientific input cap")
                remaining = memoryview(chunk)
                while remaining:
                    written = os.write(descriptor, remaining)
                    if written <= 0:
                        raise OSError("Could not retain the selected event input")
                    remaining = remaining[written:]
            os.fsync(descriptor)
            _raise_if_cancelled(cancellation_check)
        finally:
            os.close(descriptor)
        yield str(snapshot)


class DataService(BaseService):
    """
    Service for EventList data operations.

    Handles loading, saving, and managing event lists without any UI dependencies.
    """

    def _fix_inverted_gti(self, event_list: EventList) -> bool:
        """
        Fix inverted GTI intervals in an EventList (in-place).

        When Stingray loads unsorted data without a GTI extension, it sets
        GTI to [time[0], time[-1]] which can have start > stop for unsorted times.
        This causes Stingray's internal check_gtis to fail on later operations.

        This method sorts each GTI interval to ensure start <= stop.

        Args:
            event_list: The EventList to fix (modified in-place)

        Returns:
            True if any GTI was fixed, False otherwise
        """
        if event_list.gti is None or len(event_list.gti) == 0:
            return False

        fixed_any = False
        fixed_gti = []
        for g in event_list.gti:
            start, stop = g[0], g[1]
            if stop < start:
                # Swap to fix inverted interval
                fixed_gti.append([stop, start])
                fixed_any = True
            else:
                fixed_gti.append([start, stop])

        if fixed_any:
            event_list.gti = np.array(fixed_gti)

        return fixed_any

    def _validate_gti(self, event_list: EventList) -> List[str]:
        """
        Validate GTI (Good Time Intervals) for an EventList.

        Checks for:
        - Empty or missing GTI
        - Invalid GTI intervals (stop <= start)
        - Events falling outside GTI boundaries

        Args:
            event_list: The EventList to validate

        Returns:
            List of warning messages (empty if no issues found)
        """
        warnings: List[str] = []

        # Check 1: Empty or missing GTI
        if event_list.gti is None or len(event_list.gti) == 0:
            warnings.append(
                "GTI is empty or missing - no valid observation intervals defined"
            )
            return warnings  # Can't do further checks without GTI

        # Check 2: Invalid GTI intervals (stop <= start)
        invalid_intervals = []
        for i, (start, stop) in enumerate(event_list.gti):
            if stop <= start:
                invalid_intervals.append(i)
        if invalid_intervals:
            warnings.append(
                f"Found {len(invalid_intervals)} invalid GTI interval(s) where stop <= start "
                f"(indices: {invalid_intervals[:5]}{'...' if len(invalid_intervals) > 5 else ''})"
            )

        # Check 3: Events outside GTI boundaries
        if event_list.time is not None and len(event_list.time) > 0:
            times = event_list.time
            gti = event_list.gti

            # Check if each event falls within at least one GTI
            inside_gti = np.zeros(len(times), dtype=bool)
            for start, stop in gti:
                inside_gti |= (times >= start) & (times <= stop)

            events_outside = np.sum(~inside_gti)
            if events_outside > 0:
                total_events = len(times)
                percent_outside = (events_outside / total_events) * 100
                warnings.append(
                    f"{events_outside} events ({percent_outside:.2f}%) fall outside GTI boundaries"
                )

        return warnings

    def _validate_data_quality(self, event_list: EventList) -> List[Dict[str, Any]]:
        """
        Validate data quality beyond GTI checks.

        Performs comprehensive validation including:
        - NaN values in time/energy arrays
        - Time ordering (monotonically increasing)
        - Negative energy/PI values

        Args:
            event_list: The EventList to validate

        Returns:
            List of all validation check results with type, status, severity, message, and details
        """
        validations: List[Dict[str, Any]] = []

        # Check 1: NaN in time array
        if event_list.time is not None and len(event_list.time) > 0:
            nan_count = int(np.sum(np.isnan(event_list.time)))
            validations.append(
                {
                    "type": "nan_time",
                    "name": "Time Array NaN Check",
                    "description": "Check for NaN (Not a Number) values in time array",
                    "status": "fail" if nan_count > 0 else "pass",
                    "severity": "error" if nan_count > 0 else "pass",
                    "message": f"Found {nan_count} NaN values"
                    if nan_count > 0
                    else "No NaN values found",
                    "count": nan_count,
                    "total": len(event_list.time),
                }
            )

            # Check 2: Time ordering (monotonically increasing)
            time_diffs = np.diff(event_list.time)
            disorder_count = int(np.sum(time_diffs < 0))
            validations.append(
                {
                    "type": "time_ordering",
                    "name": "Time Ordering Check",
                    "description": "Check if time values are monotonically increasing",
                    "status": "fail" if disorder_count > 0 else "pass",
                    "severity": "warning" if disorder_count > 0 else "pass",
                    "message": f"Found {disorder_count} time inversions (not monotonically increasing)"
                    if disorder_count > 0
                    else "Time values are monotonically increasing",
                    "count": disorder_count,
                    "total": len(event_list.time) - 1,
                }
            )
        else:
            validations.append(
                {
                    "type": "nan_time",
                    "name": "Time Array NaN Check",
                    "description": "Check for NaN values in time array",
                    "status": "skip",
                    "severity": "skip",
                    "message": "No time data available",
                    "count": 0,
                    "total": 0,
                }
            )
            validations.append(
                {
                    "type": "time_ordering",
                    "name": "Time Ordering Check",
                    "description": "Check if time values are monotonically increasing",
                    "status": "skip",
                    "severity": "skip",
                    "message": "No time data available",
                    "count": 0,
                    "total": 0,
                }
            )

        # Check 3: NaN in energy array
        if event_list.energy is not None and len(event_list.energy) > 0:
            nan_energy = int(np.sum(np.isnan(event_list.energy)))
            validations.append(
                {
                    "type": "nan_energy",
                    "name": "Energy Array NaN Check",
                    "description": "Check for NaN values in energy array",
                    "status": "fail" if nan_energy > 0 else "pass",
                    "severity": "error" if nan_energy > 0 else "pass",
                    "message": f"Found {nan_energy} NaN values"
                    if nan_energy > 0
                    else "No NaN values found",
                    "count": nan_energy,
                    "total": len(event_list.energy),
                }
            )

            # Check 4: Negative energy values
            neg_energy = int(np.sum(event_list.energy < 0))
            validations.append(
                {
                    "type": "negative_energy",
                    "name": "Negative Energy Check",
                    "description": "Check for negative energy values (physically invalid)",
                    "status": "fail" if neg_energy > 0 else "pass",
                    "severity": "error" if neg_energy > 0 else "pass",
                    "message": f"Found {neg_energy} negative energy values"
                    if neg_energy > 0
                    else "All energy values are non-negative",
                    "count": neg_energy,
                    "total": len(event_list.energy),
                }
            )
        else:
            validations.append(
                {
                    "type": "nan_energy",
                    "name": "Energy Array NaN Check",
                    "description": "Check for NaN values in energy array",
                    "status": "skip",
                    "severity": "skip",
                    "message": "No energy data available",
                    "count": 0,
                    "total": 0,
                }
            )
            validations.append(
                {
                    "type": "negative_energy",
                    "name": "Negative Energy Check",
                    "description": "Check for negative energy values",
                    "status": "skip",
                    "severity": "skip",
                    "message": "No energy data available",
                    "count": 0,
                    "total": 0,
                }
            )

        # Check 5: Negative PI values
        if event_list.pi is not None and len(event_list.pi) > 0:
            neg_pi = int(np.sum(event_list.pi < 0))
            validations.append(
                {
                    "type": "negative_pi",
                    "name": "Negative PI Check",
                    "description": "Check for negative PI (Pulse Invariant) channel values",
                    "status": "fail" if neg_pi > 0 else "pass",
                    "severity": "error" if neg_pi > 0 else "pass",
                    "message": f"Found {neg_pi} negative PI values"
                    if neg_pi > 0
                    else "All PI values are non-negative",
                    "count": neg_pi,
                    "total": len(event_list.pi),
                }
            )
        else:
            validations.append(
                {
                    "type": "negative_pi",
                    "name": "Negative PI Check",
                    "description": "Check for negative PI channel values",
                    "status": "skip",
                    "severity": "skip",
                    "message": "No PI data available",
                    "count": 0,
                    "total": 0,
                }
            )

        # Check 6: GTI validity (start < stop for all intervals)
        if event_list.gti is not None and len(event_list.gti) > 0:
            invalid_gti = sum(1 for g in event_list.gti if g[1] <= g[0])
            validations.append(
                {
                    "type": "gti_validity",
                    "name": "GTI Interval Check",
                    "description": "Check that all GTI intervals have valid start < stop times",
                    "status": "fail" if invalid_gti > 0 else "pass",
                    "severity": "error" if invalid_gti > 0 else "pass",
                    "message": f"Found {invalid_gti} invalid GTI intervals (stop <= start)"
                    if invalid_gti > 0
                    else "All GTI intervals are valid",
                    "count": invalid_gti,
                    "total": len(event_list.gti),
                }
            )
        else:
            validations.append(
                {
                    "type": "gti_validity",
                    "name": "GTI Interval Check",
                    "description": "Check that all GTI intervals have valid start < stop times",
                    "status": "skip",
                    "severity": "skip",
                    "message": "No GTI data available",
                    "count": 0,
                    "total": 0,
                }
            )

        return validations

    def _parse_fits_header_string(self, header_str: str) -> Dict[str, str]:
        """
        Parse a FITS header string into a dictionary.

        FITS headers have 80-character lines with format:
        KEYWORD = value / comment
        or
        KEYWORD = 'string value' / comment

        Args:
            header_str: Raw FITS header string

        Returns:
            Dictionary of keyword -> value mappings
        """
        parsed: Dict[str, str] = {}

        # Split into 80-character cards (FITS standard)
        # Some headers may be newline-separated instead
        if "\n" in header_str:
            lines = header_str.split("\n")
        else:
            # Split into 80-char chunks
            lines = [header_str[i : i + 80] for i in range(0, len(header_str), 80)]

        for line in lines:
            if not line or len(line) < 8:
                continue

            # Skip COMMENT, HISTORY, and END cards
            keyword = line[:8].strip()
            if not keyword or keyword in ("COMMENT", "HISTORY", "END", ""):
                continue

            # Check for value indicator '='
            if len(line) > 9 and line[8] == "=":
                value_part = line[9:].strip()

                # Handle quoted string values
                if value_part.startswith("'"):
                    # Find closing quote (may contain escaped quotes '')
                    end_quote = 1
                    while end_quote < len(value_part):
                        if value_part[end_quote] == "'":
                            if (
                                end_quote + 1 < len(value_part)
                                and value_part[end_quote + 1] == "'"
                            ):
                                end_quote += 2  # Skip escaped quote
                            else:
                                break
                        else:
                            end_quote += 1
                    value = value_part[1:end_quote].replace("''", "'").strip()
                else:
                    # Numeric or boolean value - take until comment marker
                    if "/" in value_part:
                        value = value_part.split("/")[0].strip()
                    else:
                        value = value_part.strip()

                    # Handle boolean
                    if value == "T":
                        value = "True"
                    elif value == "F":
                        value = "False"

                if value:
                    parsed[keyword] = value

        return parsed

    def _extract_fits_header(self, event_list: EventList) -> Dict[str, Any]:
        """
        Extract key FITS header information from an EventList.

        Extracts commonly used header keywords including:
        - Object name, observation ID
        - RA/Dec coordinates
        - Exposure, ontime, livetime
        - Observation dates
        - Creator software

        Args:
            event_list: The EventList to extract headers from

        Returns:
            Dictionary containing extracted header information
        """
        header_info: Dict[str, Any] = {}
        raw_header = getattr(event_list, "header", None)

        if raw_header is None:
            return header_info

        # Parse string headers into a dictionary first
        header_dict: Dict[str, str] = {}
        if isinstance(raw_header, str):
            header_dict = self._parse_fits_header_string(raw_header)
        elif isinstance(raw_header, dict):
            header_dict = {str(k): str(v) for k, v in raw_header.items()}
        elif hasattr(raw_header, "get"):
            # Handle astropy Header-like objects - convert to dict
            try:
                for key in raw_header.keys():
                    if key and key.strip() and key not in ("COMMENT", "HISTORY", ""):
                        val = raw_header.get(key)
                        if val is not None:
                            header_dict[str(key)] = str(val)
            except Exception:
                pass

        if not header_dict:
            return header_info

        # Define key headers to extract with output key and type conversion
        key_headers = [
            ("OBJECT", "object", str),
            ("OBS_ID", "obs_id", str),
            ("RA_NOM", "ra_nom", float),
            ("DEC_NOM", "dec_nom", float),
            ("RA_OBJ", "ra_obj", float),
            ("DEC_OBJ", "dec_obj", float),
            ("EXPOSURE", "exposure", float),
            ("ONTIME", "ontime", float),
            ("LIVETIME", "livetime", float),
            ("DATE-OBS", "date_obs", str),
            ("DATE-END", "date_end", str),
            ("TSTART", "tstart", float),
            ("TSTOP", "tstop", float),
            ("CREATOR", "creator", str),
            ("TELESCOP", "telescop", str),
            ("INSTRUME", "instrume", str),
            ("DATAMODE", "datamode", str),
            ("OBSERVER", "observer", str),
        ]

        for fits_key, output_key, type_func in key_headers:
            if fits_key in header_dict:
                value = header_dict[fits_key]
                try:
                    if type_func is float:
                        header_info[output_key] = _to_python_float(float(value))
                    else:
                        header_info[output_key] = type_func(value)
                except (ValueError, TypeError):
                    header_info[output_key] = str(value)

        # Include full raw header
        raw_header_dict = {}
        for k, v in header_dict.items():
            try:
                raw_header_dict[str(k)] = str(v)
            except Exception:
                pass
        if raw_header_dict:
            header_info["raw_header"] = raw_header_dict

        return header_info

    def _detect_fits_file_type(self, file_stream: BinaryIO | str) -> Dict[str, Any]:
        """
        Detect the type of a FITS file by reading its headers.

        This pre-check prevents cryptic Stingray errors when users try to load
        Light Curve files as Event Lists (or other type mismatches).

        Returns:
            Dictionary with:
            - file_type: 'event_list', 'light_curve', 'spectrum', 'unknown'
            - details: Dict with HDUCLAS1, EXTNAME, columns found
            - is_event_list: bool
            - error_message: str or None (user-friendly message if not event list)
        """
        result: Dict[str, Any] = {
            "file_type": "unknown",
            "details": {},
            "is_event_list": False,
            "error_message": None,
        }

        try:
            if not isinstance(file_stream, str):
                _rewind(file_stream)
            with fits.open(file_stream, memmap=False) as hdulist:
                for hdu in hdulist:
                    if hdu.name in ["PRIMARY", ""]:
                        continue

                    header = hdu.header
                    extname = header.get("EXTNAME", "").upper()
                    hduclas1 = header.get("HDUCLAS1", "").upper()

                    result["details"] = {
                        "extname": extname,
                        "hduclas1": hduclas1,
                        "extension_name": hdu.name,
                    }

                    # Check for Light Curve
                    if "LIGHT" in hduclas1 or extname == "RATE":
                        result["file_type"] = "light_curve"
                        result["is_event_list"] = False
                        result["error_message"] = (
                            f"This is a Light Curve file (HDUCLAS1='{hduclas1}', "
                            f"EXTNAME='{extname}'). "
                            f"Use the Light Curve analysis tools instead of Event List loading."
                        )
                        return result

                    # Check for Event List
                    if extname == "EVENTS" or hduclas1 == "EVENTS":
                        result["file_type"] = "event_list"
                        result["is_event_list"] = True
                        return result

                    # Check for Spectrum
                    if "SPECTRUM" in hduclas1 or extname == "SPECTRUM":
                        result["file_type"] = "spectrum"
                        result["is_event_list"] = False
                        result["error_message"] = (
                            f"This is a Spectrum file (HDUCLAS1='{hduclas1}'). "
                            f"Use spectral analysis tools instead of Event List loading."
                        )
                        return result

            # If we get here, couldn't determine type - allow attempt
            result["file_type"] = "unknown"
            result["is_event_list"] = True  # Allow unknown files to attempt loading

        except Exception as e:
            # If we can't read headers, let the normal loading handle errors
            result["file_type"] = "unknown"
            result["is_event_list"] = True
            result["details"]["error"] = type(e).__name__

        return result

    def load_event_list(
        self,
        file_path: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
        notes: Optional[str] = None,
        file_grant: str | None = None,
        rmf_grant: Optional[str] = None,
        *,
        _file_source: GrantedReadFile | None = None,
        _rmf_source: GrantedReadFile | None = None,
        _cancellation_check=None,
    ) -> Dict[str, Any]:
        """Verify native grants and load only from retained anonymous streams."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        if (rmf_file is None) != (rmf_grant is None) and _rmf_source is None:
            raise ValueError("rmf_file and rmf_grant must be provided together")
        with ExitStack() as stack:
            selected = stack.enter_context(
                _open_granted_source(file_path, file_grant, _file_source)
            )
            retained_stream = stack.enter_context(
                _spooled_copy(
                    selected,
                    max_bytes=MAX_FITS_INSPECT_BYTES,
                    cancellation_check=_cancellation_check,
                )
            )
            event_stream = stack.enter_context(
                _decoded_event_stream(
                    retained_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            rmf_stream = None
            if rmf_file is not None or _rmf_source is not None:
                rmf_selected = stack.enter_context(
                    _open_granted_source(
                        rmf_file or "<retained RMF>", rmf_grant, _rmf_source
                    )
                )
                rmf_stream = stack.enter_context(
                    _spooled_copy(
                        rmf_selected,
                        max_bytes=MAX_RMF_BYTES,
                        cancellation_check=_cancellation_check,
                    )
                )
            return self._load_event_list_from_stream(
                event_stream=event_stream,
                source_name=Path(file_path).name,
                name=name,
                fmt=fmt,
                rmf_stream=rmf_stream,
                additional_columns=additional_columns,
                high_precision=high_precision,
                skip_checks=skip_checks,
                notes=notes,
                cancellation_check=_cancellation_check,
            )

    def _load_event_list_from_stream(
        self,
        event_stream: BinaryIO,
        source_name: str,
        name: str,
        fmt: str,
        rmf_stream: BinaryIO | None,
        additional_columns: Optional[List[str]],
        high_precision: bool,
        skip_checks: bool,
        notes: Optional[str],
        cancellation_check=None,
    ) -> Dict[str, Any]:
        """
        Load an EventList from a file.

        Args:
            file_path: Path to the event file
            name: Name to assign to the loaded event list
            fmt: File format (ogip, hdf5, hea, etc.)
            rmf_file: Optional path to RMF file
            additional_columns: Optional list of additional columns to read
            high_precision: Use numpy.float128 for time array (pulsar timing)
            skip_checks: Skip time ordering and GTI validation (performance)
            notes: Optional user notes/comments about this data

        Returns:
            Result dictionary with the EventList data
        """
        try:
            # Validate the name doesn't already exist
            if self.state.has_event_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"An event list with the name '{name}' already exists.",
                    error=None,
                )

            # Auto-detect format from file extension if not explicitly specified differently
            file_ext = os.path.splitext(source_name)[1].lower()
            if file_ext in [".hdf5", ".h5"]:
                fmt = "hdf5"
            elif file_ext in [".ecsv"]:
                fmt = "ascii.ecsv"
            # Otherwise use the provided fmt (default: ogip for FITS files)

            # Detect file type before attempting to load (for FITS files)
            is_fits = fmt in ("ogip", "fits")
            if is_fits:
                with _cloned_stream(
                    event_stream, cancellation_check=cancellation_check
                ) as detection_stream:
                    file_type_info = self._detect_fits_file_type(detection_stream)
                if not file_type_info["is_event_list"]:
                    return self.create_result(
                        success=False,
                        data=None,
                        message=f"Cannot load '{name}' as Event List: "
                        f"{file_type_info['error_message']}",
                        error=f"File type: {file_type_info['file_type']}",
                    )

            # Capture Stingray/library warnings during loading
            stingray_warnings: List[str] = []
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")  # Catch all warnings

                # Load the event list using Stingray
                _rewind(rmf_stream)
                with _scientific_reader_source(
                    event_stream,
                    fmt=fmt,
                    cancellation_check=cancellation_check,
                ) as reader_source:
                    if fmt == "hdf5":
                        if h5py is None:
                            raise RuntimeError("HDF5 support is unavailable")
                        with h5py.File(reader_source, "r") as hdf5_source:
                            event_list = EventList.read(hdf5_source, fmt=fmt)
                    else:
                        event_list = EventList.read(
                            reader_source,
                            fmt=fmt,
                            rmf_file=rmf_stream,
                            additional_columns=additional_columns,
                            high_precision=high_precision,
                            skip_checks=skip_checks,
                        )

                # Collect warning messages
                for w in caught_warnings:
                    safe_warning = _safe_scientific_warning(w)
                    if safe_warning is not None:
                        stingray_warnings.append(safe_warning)
                    if len(stingray_warnings) >= MAX_PUBLIC_SCIENTIFIC_WARNINGS:
                        break

            # Fix inverted GTI intervals (common with unsorted data)
            # This must be done before storing, as Stingray's check_gtis
            # will fail on later operations if GTI has start > stop
            gti_was_fixed = self._fix_inverted_gti(event_list)
            if gti_was_fixed:
                stingray_warnings.append(
                    "GTI intervals were inverted (start > stop) and have been automatically fixed. "
                    "This typically occurs with unsorted event data."
                )

            # Store user notes on the event list object
            if notes:
                event_list.notes = notes

            # Add to state manager
            _raise_if_cancelled(cancellation_check)
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)

            # Run comprehensive data quality validation
            validation_issues = self._validate_data_quality(event_list)

            # Prepare serializable summary (use helper for numpy type conversion)
            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max()),
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
                "stingray_warnings": stingray_warnings if stingray_warnings else None,
                "validation_issues": validation_issues if validation_issues else None,
                "notes": notes if notes else None,
            }

            # Build message with warnings if present
            message = f"EventList '{name}' loaded successfully ({len(event_list.time)} events)"
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"
            if stingray_warnings:
                message += f" [Stingray warnings: {len(stingray_warnings)}]"
            if validation_issues:
                error_count = sum(
                    1 for v in validation_issues if v["severity"] == "error"
                )
                warn_count = sum(
                    1 for v in validation_issues if v["severity"] == "warning"
                )
                if error_count > 0:
                    message += f" [Data errors: {error_count}]"
                if warn_count > 0:
                    message += f" [Data warnings: {warn_count}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected event file could not be read",
                error="event_read_failed",
            )

    def load_event_list_from_url(
        self,
        url: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        rmf_grant: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
        notes: Optional[str] = None,
        *,
        _rmf_source: GrantedReadFile | None = None,
        _cancellation_check=None,
    ) -> Dict[str, Any]:
        """Fetch one bounded HTTPS source and load it from an anonymous spool."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        if (rmf_file is None) != (rmf_grant is None) and _rmf_source is None:
            raise ValueError("rmf_file and rmf_grant must be provided together")
        with ExitStack() as stack:
            retained_rmf = _rmf_source
            if retained_rmf is None and rmf_file is not None:
                retained_rmf = stack.enter_context(
                    _open_granted_source(rmf_file, rmf_grant, None)
                )
            return asyncio.run(
                self._load_event_list_from_url_async(
                    url=url,
                    name=name,
                    fmt=fmt,
                    rmf_file=rmf_file,
                    rmf_grant=rmf_grant,
                    additional_columns=additional_columns,
                    high_precision=high_precision,
                    skip_checks=skip_checks,
                    notes=notes,
                    rmf_source=retained_rmf,
                    cancellation_check=_cancellation_check,
                )
            )

    async def _load_event_list_from_url_async(
        self,
        *,
        url: str,
        name: str,
        fmt: str,
        rmf_file: str | None,
        rmf_grant: str | None,
        additional_columns: List[str] | None,
        high_precision: bool,
        skip_checks: bool,
        notes: str | None,
        rmf_source: GrantedReadFile | None,
        cancellation_check,
    ) -> Dict[str, Any]:
        if self.state.has_event_data(name):
            return self.create_result(
                success=False,
                data=None,
                message=f"An event list with the name '{name}' already exists.",
                error=None,
            )

        client = RemoteSourceClient(GENERAL_HTTPS_POLICY)
        try:
            with tempfile.SpooledTemporaryFile(
                max_size=SPOOL_MEMORY_LIMIT, mode="w+b"
            ) as event_stream:
                async with client.stream(
                    url,
                    max_bytes=REMOTE_EVENT_LIMIT,
                    cancellation_check=cancellation_check,
                ) as remote_stream:
                    async for chunk in remote_stream.aiter_bytes():
                        event_stream.write(chunk)
                event_stream.seek(0)
                return await asyncio.to_thread(
                    self._load_remote_stream,
                    event_stream,
                    name,
                    fmt,
                    rmf_file,
                    rmf_grant,
                    additional_columns,
                    high_precision,
                    skip_checks,
                    notes,
                    rmf_source,
                    cancellation_check,
                )
        except RemoteSourceCancelled:
            return self.create_result(
                success=False,
                data=None,
                message="Remote load was cancelled",
                error="cancelled",
            )
        except RemoteSourceError as error:
            return self.create_result(
                success=False,
                data=None,
                message="The selected remote event source could not be retrieved",
                error=type(error).__name__,
            )
        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected remote event source could not be read",
                error="remote_event_read_failed",
            )

    def _load_remote_stream(
        self,
        event_stream: BinaryIO,
        name: str,
        fmt: str,
        rmf_file: str | None,
        rmf_grant: str | None,
        additional_columns: List[str] | None,
        high_precision: bool,
        skip_checks: bool,
        notes: str | None,
        rmf_source: GrantedReadFile | None,
        cancellation_check=None,
    ) -> Dict[str, Any]:
        if (rmf_file is None) != (rmf_grant is None) and rmf_source is None:
            raise ValueError("rmf_file and rmf_grant must be provided together")
        with ExitStack() as stack:
            rmf_stream = None
            if rmf_file is not None or rmf_source is not None:
                selected = stack.enter_context(
                    _open_granted_source(
                        rmf_file or "<retained RMF>", rmf_grant, rmf_source
                    )
                )
                rmf_stream = stack.enter_context(
                    _spooled_copy(
                        selected,
                        max_bytes=MAX_RMF_BYTES,
                        cancellation_check=cancellation_check,
                    )
                )
            decoded_stream = stack.enter_context(
                _decoded_event_stream(
                    event_stream,
                    fmt=fmt,
                    cancellation_check=cancellation_check,
                )
            )
            result = self._load_event_list_from_stream(
                event_stream=decoded_stream,
                source_name=(
                    "remote.hdf5"
                    if fmt == "hdf5"
                    else "remote.ecsv"
                    if fmt == "ascii.ecsv"
                    else "remote.evt"
                ),
                name=name,
                fmt=fmt,
                rmf_stream=rmf_stream,
                additional_columns=additional_columns,
                high_precision=high_precision,
                skip_checks=skip_checks,
                notes=notes,
                cancellation_check=cancellation_check,
            )
            if result.get("success"):
                result["message"] = f"EventList '{name}' loaded successfully from URL"
            return result

    async def load_event_list_from_url_stream(
        self,
        url: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        rmf_grant: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
        notes: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream bounded remote progress without exposing the selected URL."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        if self.state.has_event_data(name):
            yield {
                "type": "error",
                "error": f"An event list with the name '{name}' already exists.",
            }
            return

        cancellation_signal = threading.Event()
        client = RemoteSourceClient(GENERAL_HTTPS_POLICY)
        try:
            with ExitStack() as stack:
                if (rmf_file is None) != (rmf_grant is None):
                    raise ValueError("rmf_file and rmf_grant must be provided together")
                retained_rmf = None
                if rmf_file is not None:
                    retained_rmf = stack.enter_context(
                        _open_granted_source(rmf_file, rmf_grant, None)
                    )
                event_stream = stack.enter_context(
                    tempfile.SpooledTemporaryFile(
                        max_size=SPOOL_MEMORY_LIMIT, mode="w+b"
                    )
                )
                async with client.stream(
                    url,
                    max_bytes=REMOTE_EVENT_LIMIT,
                    cancellation_check=cancellation_signal.is_set,
                ) as remote_stream:
                    total_bytes = remote_stream.info.content_length or 0
                    async for chunk in remote_stream.aiter_bytes():
                        event_stream.write(chunk)
                        downloaded = remote_stream.bytes_read
                        percent = (
                            downloaded / total_bytes * 100 if total_bytes > 0 else 0
                        )
                        yield {
                            "type": "progress",
                            "bytes_downloaded": downloaded,
                            "total_bytes": total_bytes,
                            "percent": round(percent, 1),
                        }
                        await asyncio.sleep(0)

                yield {
                    "type": "processing",
                    "message": "Download complete, loading event list...",
                }
                event_stream.seek(0)
                processing_task = asyncio.create_task(
                    asyncio.to_thread(
                        self._load_remote_stream,
                        event_stream,
                        name,
                        fmt,
                        rmf_file,
                        rmf_grant,
                        additional_columns,
                        high_precision,
                        skip_checks,
                        notes,
                        retained_rmf,
                        cancellation_signal.is_set,
                    )
                )
                try:
                    result = await asyncio.shield(processing_task)
                except asyncio.CancelledError:
                    # to_thread workers are not cancelled with their awaiting
                    # task. Signal the worker and drain it before ExitStack
                    # closes the pinned RMF and anonymous event snapshot.
                    cancellation_signal.set()
                    while not processing_task.done():
                        try:
                            await asyncio.shield(processing_task)
                        except asyncio.CancelledError:
                            # Repeated disconnect/cancel signals must not break
                            # ownership before the non-cancellable thread exits.
                            continue
                    try:
                        processing_task.result()
                    except BaseException:
                        pass
                    raise
                if result.get("success"):
                    yield {
                        "type": "complete",
                        "data": result.get("data"),
                        "message": result.get("message"),
                    }
                else:
                    yield {
                        "type": "error",
                        "error": result.get("message") or "Remote load failed",
                    }
        except RemoteSourceCancelled:
            yield {"type": "error", "error": "Remote load was cancelled"}
        except RemoteSourceError:
            yield {
                "type": "error",
                "error": "The selected remote event source could not be retrieved",
            }
        except asyncio.CancelledError:
            raise
        except Exception:
            yield {
                "type": "error",
                "error": "Error loading the selected remote event list",
            }
        finally:
            cancellation_signal.set()

    def delete_event_list(self, name: str) -> Dict[str, Any]:
        """Delete an EventList from state."""
        try:
            if not self.state.has_event_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"No event list found with name '{name}'",
                    error=None,
                )

            self.state.remove_event_data(name)

            return self.create_result(
                success=True,
                data={"name": name},
                message=f"EventList '{name}' deleted successfully",
            )

        except Exception as e:
            return self.handle_error(e, "Deleting event list", name=name)

    def get_event_list_info(self, name: str) -> Dict[str, Any]:
        """
        Get information about an EventList.

        Args:
            name: Name of the event list

        Returns:
            Result dictionary with event list information
        """
        try:
            if not self.state.has_event_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"No event list found with name '{name}'",
                    error=None,
                )

            event_list = self.state.get_event_data(name)

            # Basic info - use helper functions for numpy type conversion
            duration = _to_python_float(event_list.time.max() - event_list.time.min())
            info = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max()),
                ],
                "duration": duration,
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "mjdref": _to_python_float(event_list.mjdref),
            }

            # GTI details
            if event_list.gti is not None and len(event_list.gti) > 0:
                info["gti_list"] = [
                    [_to_python_float(g[0]), _to_python_float(g[1])]
                    for g in event_list.gti
                ]
                info["total_gti_time"] = _to_python_float(
                    sum(g[1] - g[0] for g in event_list.gti)
                )

            # Energy/PI range
            if event_list.energy is not None:
                info["energy_range"] = [
                    _to_python_float(event_list.energy.min()),
                    _to_python_float(event_list.energy.max()),
                ]
            if event_list.pi is not None:
                info["pi_range"] = [int(event_list.pi.min()), int(event_list.pi.max())]

            # Mission metadata (if available)
            if hasattr(event_list, "mission") and event_list.mission:
                info["mission"] = str(event_list.mission)
            if hasattr(event_list, "instr") and event_list.instr:
                info["instrument"] = str(event_list.instr)

            # Time statistics
            if len(event_list.time) > 1:
                # Sort times to get accurate time differences
                sorted_times = np.sort(event_list.time)
                time_diffs = sorted_times[1:] - sorted_times[:-1]
                info["mean_count_rate"] = (
                    _to_python_float(len(event_list.time) / duration)
                    if duration and duration > 0
                    else 0
                )
                info["min_time_diff"] = _to_python_float(time_diffs.min())
                info["max_time_diff"] = _to_python_float(time_diffs.max())
                info["mean_time_diff"] = _to_python_float(np.mean(time_diffs))
                info["median_time_diff"] = _to_python_float(np.median(time_diffs))
                info["std_time_diff"] = _to_python_float(np.std(time_diffs))

            # Per-GTI rates
            if event_list.gti is not None and len(event_list.gti) > 0:
                per_gti_rates = []
                for start, stop in event_list.gti:
                    mask = (event_list.time >= start) & (event_list.time <= stop)
                    gti_events = int(np.sum(mask))
                    gti_duration = float(stop - start)
                    rate = gti_events / gti_duration if gti_duration > 0 else 0
                    per_gti_rates.append(
                        {
                            "start": _to_python_float(start),
                            "stop": _to_python_float(stop),
                            "events": gti_events,
                            "duration": _to_python_float(gti_duration),
                            "rate": _to_python_float(rate),
                        }
                    )
                info["per_gti_rates"] = per_gti_rates

            # Notes
            info["notes"] = getattr(event_list, "notes", None) or None

            return self.create_result(
                success=True,
                data=info,
                message=f"EventList '{name}' info retrieved",
            )

        except Exception as e:
            return self.handle_error(e, "Getting event list info", name=name)

    def list_event_lists(self) -> Dict[str, Any]:
        """List all loaded EventLists."""
        try:
            event_data = self.state.get_event_data()

            summaries = []
            for name, event_list in event_data:
                summaries.append(
                    {
                        "name": name,
                        "n_events": len(event_list.time),
                        "time_range": [
                            _to_python_float(event_list.time.min()),
                            _to_python_float(event_list.time.max()),
                        ],
                        "has_energy": event_list.energy is not None,
                        "has_pi": event_list.pi is not None,
                        "gti_count": len(event_list.gti)
                        if event_list.gti is not None
                        else 0,
                    }
                )

            return self.create_result(
                success=True,
                data=summaries,
                message=f"Found {len(summaries)} event list(s)",
            )

        except Exception as e:
            return self.handle_error(e, "Listing event lists")

    def check_file_size(
        self,
        file_path: str,
        file_grant: str | None = None,
        *,
        _file_source: GrantedReadFile | None = None,
        _cancellation_check=None,
    ) -> Dict[str, Any]:
        """Check file size and provide loading recommendations based on available RAM."""
        try:
            with _open_granted_source(file_path, file_grant, _file_source) as selected:
                file_size = selected.size_bytes
                file_size_mb = file_size / (1024**2)
                file_size_gb = file_size / (1024**3)

            # Get memory info first - we need this for smart recommendations
            memory_info = self._get_memory_info()
            available_ram_mb = memory_info["available_mb"]

            # Estimate memory needed to load the EventList
            # FITS files typically expand to ~3x file size in memory
            estimated_memory_mb = self._estimate_memory_usage(file_size, "fits") / (
                1024**2
            )

            # Calculate what percentage of available RAM this would use
            ram_usage_percent = (
                (estimated_memory_mb / available_ram_mb) * 100
                if available_ram_mb > 0
                else 100
            )

            # Determine risk level based on RAM usage percentage
            # This is smarter than just file size - adapts to user's system
            if ram_usage_percent > 80:
                risk_level = "critical"  # Would use >80% of available RAM
            elif ram_usage_percent > 50:
                risk_level = "risky"  # Would use >50% of available RAM
            elif ram_usage_percent > 30:
                risk_level = "caution"  # Would use >30% of available RAM
            else:
                risk_level = "safe"  # Would use <30% of available RAM

            # Recommend lazy loading if it would use more than 30% of available RAM
            recommend_lazy = ram_usage_percent > 30

            return self.create_result(
                success=True,
                data={
                    "file_size_bytes": file_size,
                    "file_size_mb": file_size_mb,
                    "file_size_gb": file_size_gb,
                    "risk_level": risk_level,
                    "recommend_lazy": recommend_lazy,
                    "estimated_memory_mb": estimated_memory_mb,
                    "ram_usage_percent": round(ram_usage_percent, 1),
                    "memory_info": memory_info,
                },
                message=f"File size: {file_size_mb:.2f} MB, Est. RAM usage: {ram_usage_percent:.1f}% of available",
            )

        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected file size could not be checked",
                error="file_size_check_failed",
            )

    def clear_all_event_lists(self) -> Dict[str, Any]:
        """Clear all loaded event lists from memory."""
        try:
            count = self.state.clear_event_data()

            return self.create_result(
                success=True,
                data={"count": count},
                message=f"Cleared {count} event list(s) from memory",
            )

        except Exception as e:
            return self.handle_error(e, "Clearing all event lists")

    def _get_memory_info(self) -> Dict[str, Any]:
        """Get current system memory information."""
        vm = psutil.virtual_memory()
        process = psutil.Process()
        return {
            "total_mb": vm.total / (1024**2),
            "available_mb": vm.available / (1024**2),
            "used_mb": vm.used / (1024**2),
            "percent": vm.percent,
            "process_mb": process.memory_info().rss / (1024**2),
        }

    def _estimate_memory_usage(self, file_size: int, fmt: str = "fits") -> int:
        """
        Estimate memory needed to load file into EventList.

        Based on Stingray's official benchmarks:
        - FITS event file: ~3x file size
        - HDF5: ~2x file size
        """
        fmt = require_input_event_format(fmt)
        multipliers = {
            "fits": 3,
            "ogip": 3,
            "hdf5": 2,
        }
        multiplier = multipliers.get(fmt, 3)
        return int(file_size * multiplier)

    def _can_load_safely(
        self,
        file_size: int,
        safety_margin: float = 0.5,
        fmt: str = "fits",
    ) -> bool:
        """Check if file can be safely loaded into memory."""
        fmt = require_input_event_format(fmt)
        available_ram = psutil.virtual_memory().available
        needed_ram = self._estimate_memory_usage(file_size, fmt)
        safe_limit = available_ram * safety_margin
        return needed_ram < safe_limit

    def get_event_list_full_preview(
        self, name: str, time_limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get full preview of an EventList with all attributes.

        Args:
            name: Name of the event list
            time_limit: Number of time entries to show in preview

        Returns:
            Result dictionary with comprehensive preview data
        """
        try:
            if not self.state.has_event_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"No event list found with name '{name}'",
                    error=None,
                )

            event_list = self.state.get_event_data(name)

            # Build comprehensive preview
            # Use helper functions to convert numpy types (including longdouble) to Python types
            preview = {
                "name": name,
                # Core data - use explicit float conversion for longdouble support
                "times_preview": _to_python_float_list(event_list.time[:time_limit]),
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max()),
                ],
                "duration": _to_python_float(
                    event_list.time.max() - event_list.time.min()
                ),
                # Energy data
                "has_energy": event_list.energy is not None,
                "energy_preview": (
                    _to_python_float_list(event_list.energy[:time_limit])
                    if event_list.energy is not None
                    else None
                ),
                "energy_range": (
                    [
                        _to_python_float(event_list.energy.min()),
                        _to_python_float(event_list.energy.max()),
                    ]
                    if event_list.energy is not None
                    else None
                ),
                # PI data
                "has_pi": event_list.pi is not None,
                "pi_preview": (
                    [int(x) for x in event_list.pi[:time_limit]]
                    if event_list.pi is not None
                    else None
                ),
                "pi_range": (
                    [int(event_list.pi.min()), int(event_list.pi.max())]
                    if event_list.pi is not None
                    else None
                ),
                # GTI data - sort each interval to handle inverted GTIs from unsorted data
                # When Stingray loads unsorted data without a GTI extension, it sets
                # GTI to [time[0], time[-1]] which can have start > stop for unsorted times
                "gti_count": 0,  # Will be set below
                "gti_list": None,  # Will be set below
                "total_gti_time": None,  # Will be set below
                # Reference time - mjdref is often numpy.longdouble
                "mjdref": _to_python_float(event_list.mjdref),
                # Metadata (if available) - convert to string to be safe
                "mission": str(getattr(event_list, "mission", None))
                if getattr(event_list, "mission", None)
                else None,
                "instrument": str(getattr(event_list, "instr", None))
                if getattr(event_list, "instr", None)
                else None,
                "detector_id": (
                    str(getattr(event_list, "detector_id", None))
                    if hasattr(event_list, "detector_id")
                    and event_list.detector_id is not None
                    else None
                ),
                "ephem": str(getattr(event_list, "ephem", None))
                if getattr(event_list, "ephem", None)
                else None,
                "timeref": str(getattr(event_list, "timeref", None))
                if getattr(event_list, "timeref", None)
                else None,
                "timesys": str(getattr(event_list, "timesys", None))
                if getattr(event_list, "timesys", None)
                else None,
                # Statistics
                "mean_count_rate": None,
                "min_time_diff": None,
                "max_time_diff": None,
            }

            # Process GTI data - sort each interval to handle inverted GTIs from unsorted data
            # When Stingray loads unsorted data without a GTI extension, it sets
            # GTI to [time[0], time[-1]] which can have start > stop for unsorted times
            valid_gti = None
            if event_list.gti is not None and len(event_list.gti) > 0:
                # Sort each GTI interval to ensure [start, stop] order (start <= stop)
                valid_gti = [
                    [
                        _to_python_float(min(g[0], g[1])),
                        _to_python_float(max(g[0], g[1])),
                    ]
                    for g in event_list.gti
                ]
            preview["gti_count"] = len(valid_gti) if valid_gti else 0
            preview["gti_list"] = valid_gti
            preview["total_gti_time"] = (
                _to_python_float(sum(g[1] - g[0] for g in valid_gti))
                if valid_gti
                else None
            )

            # Calculate time statistics
            duration = preview["duration"]
            if duration and duration > 0:
                preview["mean_count_rate"] = _to_python_float(
                    len(event_list.time) / duration
                )

            if len(event_list.time) > 1:
                sorted_times = np.sort(event_list.time)
                time_diffs = sorted_times[1:] - sorted_times[:-1]
                preview["min_time_diff"] = _to_python_float(time_diffs.min())
                preview["max_time_diff"] = _to_python_float(time_diffs.max())
                preview["mean_time_diff"] = _to_python_float(time_diffs.mean())
                # Enhanced time statistics
                preview["median_time_diff"] = _to_python_float(np.median(time_diffs))
                preview["std_time_diff"] = _to_python_float(np.std(time_diffs))

            # Per-GTI rates - use the validated/sorted GTI intervals
            if valid_gti:
                per_gti_rates = []
                for gti_entry in valid_gti:
                    start, stop = gti_entry[0], gti_entry[1]
                    mask = (event_list.time >= start) & (event_list.time <= stop)
                    gti_events = int(np.sum(mask))
                    gti_duration = float(stop - start)
                    rate = gti_events / gti_duration if gti_duration > 0 else 0
                    per_gti_rates.append(
                        {
                            "start": _to_python_float(start),
                            "stop": _to_python_float(stop),
                            "events": gti_events,
                            "duration": _to_python_float(gti_duration),
                            "rate": _to_python_float(rate),
                        }
                    )
                preview["per_gti_rates"] = per_gti_rates

            # Check for additional columns
            additional_cols = []
            for attr in dir(event_list):
                if not attr.startswith("_") and attr not in [
                    "time",
                    "energy",
                    "pi",
                    "gti",
                    "mjdref",
                    "mission",
                    "instr",
                    "detector_id",
                    "ephem",
                    "timeref",
                    "timesys",
                    "header",
                    "notes",
                    "ncounts",
                    "dt",
                    "n",
                ]:
                    val = getattr(event_list, attr, None)
                    if isinstance(val, np.ndarray) and len(val) == len(event_list.time):
                        additional_cols.append(attr)
            preview["additional_columns"] = additional_cols

            # User notes
            preview["notes"] = getattr(event_list, "notes", None) or None

            # Data quality validation
            validation_issues = self._validate_data_quality(event_list)
            preview["validation_issues"] = (
                validation_issues if validation_issues else None
            )

            # FITS header information
            header_info = self._extract_fits_header(event_list)
            preview["header_info"] = header_info if header_info else None

            return self.create_result(
                success=True,
                data=preview,
                message=f"Full preview for '{name}' retrieved",
            )

        except Exception as e:
            return self.handle_error(e, "Getting event list full preview", name=name)

    # =========================================================================
    # PARTIAL LOADING METHODS
    # These methods use FITSTimeseriesReader to load only a portion of the file
    # =========================================================================
    #
    # TODO: Implement true chunk-based lazy loading for streaming analysis
    #
    # FITSTimeseriesReader supports genuine lazy/streaming I/O via:
    # - reader.split_by_number_of_samples(N) -> Generator yielding N-event chunks
    # - reader.filter_at_time_intervals(intervals) -> Generator for time ranges
    # - reader.apply_gti_lists(gti_lists) -> Generator for GTI-based splits
    #
    # This would allow processing huge files without loading them fully:
    #   for chunk in reader.split_by_number_of_samples(100000):
    #       ps = AveragedPowerspectrum(chunk, segment_size=128)
    #       # Aggregate results...
    #
    # Implementation would require:
    # 1. Store FITSTimeseriesReader objects in StateManager (not just EventLists)
    # 2. Create generator-based iteration endpoints
    # 3. Implement chunked analysis methods (works well with Averaged* classes)
    #
    # Note: Only "averaged" analysis methods (AveragedPowerspectrum, etc.) benefit
    # from chunking. Single-FFT methods need all data at once.
    # =========================================================================

    def load_event_list_by_time_range(
        self,
        file_path: str,
        name: str,
        start_time: float,
        end_time: float,
        fmt: str = "ogip",
        notes: Optional[str] = None,
        file_grant: str | None = None,
        *,
        _file_source: GrantedReadFile | None = None,
        _cancellation_check=None,
    ) -> Dict[str, Any]:
        """Load a time slice after retaining the exact granted input."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        with ExitStack() as stack:
            selected = stack.enter_context(
                _open_granted_source(file_path, file_grant, _file_source)
            )
            retained_event_stream = stack.enter_context(
                _spooled_copy(
                    selected,
                    max_bytes=MAX_FITS_INSPECT_BYTES,
                    cancellation_check=_cancellation_check,
                )
            )
            retained_times_stream = stack.enter_context(
                _spooled_copy(
                    selected,
                    max_bytes=MAX_FITS_INSPECT_BYTES,
                    cancellation_check=_cancellation_check,
                )
            )
            event_stream = stack.enter_context(
                _decoded_event_stream(
                    retained_event_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            times_stream = stack.enter_context(
                _decoded_event_stream(
                    retained_times_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            event_source = stack.enter_context(
                _scientific_reader_source(
                    event_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            times_source = stack.enter_context(
                _scientific_reader_source(
                    times_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            return self._load_event_list_by_time_range_from_stream(
                event_source,
                times_source,
                name,
                start_time,
                end_time,
                fmt,
                notes,
                _cancellation_check,
            )

    def _load_event_list_by_time_range_from_stream(
        self,
        event_stream: BinaryIO | str,
        times_stream: BinaryIO | str,
        name: str,
        start_time: float,
        end_time: float,
        fmt: str,
        notes: Optional[str],
        cancellation_check=None,
    ) -> Dict[str, Any]:
        """
        Load events within a specific time range using true lazy loading.

        Uses FITSTimeseriesReader.filter_at_time_intervals() to load only
        events within the specified time window without reading the entire file.

        Args:
            file_path: Path to the FITS event file
            name: Name to assign to the loaded event list
            start_time: Start time (in seconds from file start or absolute)
            end_time: End time (in seconds from file start or absolute)
            fmt: File format (only FITS formats supported for lazy loading)
            notes: Optional user notes/comments about this data

        Returns:
            Result dictionary with the filtered EventList
        """
        try:
            # Validate the name doesn't already exist
            if self.state.has_event_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"An event list with the name '{name}' already exists.",
                    error=None,
                )

            # Check format - only FITS supports true lazy loading
            is_fits = fmt in ("ogip", "fits")
            if not is_fits:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"True lazy loading only supports FITS formats. Got: {fmt}",
                    error="Unsupported format for lazy loading",
                )

            # Detect file type before attempting to load
            if isinstance(event_stream, str):
                file_type_info = self._detect_fits_file_type(event_stream)
            else:
                with _cloned_stream(
                    event_stream, cancellation_check=cancellation_check
                ) as detection_stream:
                    file_type_info = self._detect_fits_file_type(detection_stream)
            if not file_type_info["is_event_list"]:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Cannot load '{name}' as Event List: "
                    f"{file_type_info['error_message']}",
                    error=f"File type: {file_type_info['file_type']}",
                )

            # Create the reader
            if not isinstance(event_stream, str):
                _rewind(event_stream)
            reader = FITSTimeseriesReader(
                event_stream, output_class=EventList, data_kind="events"
            )

            # Get file metadata
            original_gti = reader.gti
            mjdref = getattr(reader, "mjdref", 0.0)
            mission = getattr(reader, "mission", None)
            instr = getattr(reader, "instr", None)

            # Get total event count for reporting
            if not isinstance(times_stream, str):
                _rewind(times_stream)
            times_reader = FITSTimeseriesReader(times_stream, data_kind="times")
            total_events = len(times_reader[:])

            # Calculate absolute times if relative times are provided
            # If start_time is small (< 1000), treat as relative to GTI start
            if original_gti is not None and len(original_gti) > 0:
                gti_start = float(original_gti[0, 0])
                gti_end = float(original_gti[-1, 1])
                total_duration = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))

                # If times look relative (small values), convert to absolute
                if start_time < 1000 and end_time < 1000:
                    abs_start = gti_start + start_time
                    abs_end = gti_start + end_time
                else:
                    abs_start = start_time
                    abs_end = end_time

                # Clamp to valid range
                abs_start = max(abs_start, gti_start)
                abs_end = min(abs_end, gti_end)
            else:
                abs_start = start_time
                abs_end = end_time
                total_duration = 0.0

            if abs_start >= abs_end:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Invalid time range: start ({abs_start}) >= end ({abs_end})",
                    error="Invalid time range",
                )

            # Use filter_at_time_intervals to get events in the time range
            # This returns a generator - we get the first (and only) result
            time_intervals = [[abs_start, abs_end]]
            event_list = None

            for filtered_events in reader.filter_at_time_intervals(time_intervals):
                event_list = filtered_events
                break  # Only one interval

            if event_list is None or len(event_list.time) == 0:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"No events found in time range [{start_time}, {end_time}]",
                    error="Empty time range",
                )

            # Set metadata that might not be transferred
            event_list.mjdref = _to_python_float(mjdref) or 0.0
            if mission:
                event_list.mission = mission
            if instr:
                event_list.instr = instr

            # Store user notes on the event list object
            if notes:
                event_list.notes = notes

            # Fix inverted GTI intervals (common with unsorted data)
            gti_was_fixed = self._fix_inverted_gti(event_list)

            # Add to state manager
            _raise_if_cancelled(cancellation_check)
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)
            if gti_was_fixed:
                gti_warnings.insert(
                    0, "GTI intervals were inverted and automatically fixed."
                )

            # Run comprehensive data quality validation
            validation_issues = self._validate_data_quality(event_list)

            # Calculate loaded duration
            loaded_duration = abs_end - abs_start

            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max()),
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
                "validation_issues": validation_issues if validation_issues else None,
                "notes": notes if notes else None,
                "lazy_loading_info": {
                    "method": "time_range",
                    "requested_range": [start_time, end_time],
                    "actual_range": [abs_start, abs_end],
                    "loaded_duration": loaded_duration,
                    "total_file_duration": total_duration,
                    "total_file_events": total_events,
                    "events_loaded_percent": (len(event_list.time) / total_events * 100)
                    if total_events > 0
                    else 0,
                },
            }

            message = (
                f"Lazy loaded '{name}': {len(event_list.time)} events "
                f"({summary['lazy_loading_info']['events_loaded_percent']:.1f}% of file) "
                f"from time range [{start_time:.1f}s - {end_time:.1f}s]"
            )
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"
            if validation_issues:
                error_count = sum(
                    1 for v in validation_issues if v["severity"] == "error"
                )
                warn_count = sum(
                    1 for v in validation_issues if v["severity"] == "warning"
                )
                if error_count > 0:
                    message += f" [Data errors: {error_count}]"
                if warn_count > 0:
                    message += f" [Data warnings: {warn_count}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected event time range could not be read",
                error="event_range_read_failed",
            )

    def load_event_list_by_event_count(
        self,
        file_path: str,
        name: str,
        start_index: int = 0,
        count: int = 10000,
        fmt: str = "ogip",
        notes: Optional[str] = None,
        file_grant: str | None = None,
        *,
        _file_source: GrantedReadFile | None = None,
        _cancellation_check=None,
    ) -> Dict[str, Any]:
        """Load an event slice after retaining the exact granted input."""
        fmt = require_input_event_format(fmt)
        name_error = validate_derived_name(name)
        if name_error:
            raise ValueError(name_error)
        with ExitStack() as stack:
            selected = stack.enter_context(
                _open_granted_source(file_path, file_grant, _file_source)
            )
            retained_event_stream = stack.enter_context(
                _spooled_copy(
                    selected,
                    max_bytes=MAX_FITS_INSPECT_BYTES,
                    cancellation_check=_cancellation_check,
                )
            )
            retained_times_stream = stack.enter_context(
                _spooled_copy(
                    selected,
                    max_bytes=MAX_FITS_INSPECT_BYTES,
                    cancellation_check=_cancellation_check,
                )
            )
            event_stream = stack.enter_context(
                _decoded_event_stream(
                    retained_event_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            times_stream = stack.enter_context(
                _decoded_event_stream(
                    retained_times_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            event_source = stack.enter_context(
                _scientific_reader_source(
                    event_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            times_source = stack.enter_context(
                _scientific_reader_source(
                    times_stream,
                    fmt=fmt,
                    cancellation_check=_cancellation_check,
                )
            )
            return self._load_event_list_by_event_count_from_stream(
                event_source,
                times_source,
                name,
                start_index,
                count,
                fmt,
                notes,
                _cancellation_check,
            )

    def _load_event_list_by_event_count_from_stream(
        self,
        event_stream: BinaryIO | str,
        times_stream: BinaryIO | str,
        name: str,
        start_index: int,
        count: int,
        fmt: str,
        notes: Optional[str],
        cancellation_check=None,
    ) -> Dict[str, Any]:
        """
        Load a specific number of events using true lazy loading.

        Uses FITSTimeseriesReader slicing to load only the requested events
        without reading the entire file into memory.

        Args:
            file_path: Path to the FITS event file
            name: Name to assign to the loaded event list
            start_index: Starting event index (0-based)
            count: Number of events to load
            fmt: File format (only FITS formats supported for lazy loading)
            notes: Optional user notes/comments about this data

        Returns:
            Result dictionary with the sliced EventList
        """
        try:
            # Validate the name doesn't already exist
            if self.state.has_event_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"An event list with the name '{name}' already exists.",
                    error=None,
                )

            # Check format
            is_fits = fmt in ("ogip", "fits")
            if not is_fits:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"True lazy loading only supports FITS formats. Got: {fmt}",
                    error="Unsupported format for lazy loading",
                )

            # Detect file type before attempting to load
            if isinstance(event_stream, str):
                file_type_info = self._detect_fits_file_type(event_stream)
            else:
                with _cloned_stream(
                    event_stream, cancellation_check=cancellation_check
                ) as detection_stream:
                    file_type_info = self._detect_fits_file_type(detection_stream)
            if not file_type_info["is_event_list"]:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Cannot load '{name}' as Event List: "
                    f"{file_type_info['error_message']}",
                    error=f"File type: {file_type_info['file_type']}",
                )

            # Create the reader
            if not isinstance(event_stream, str):
                _rewind(event_stream)
            reader = FITSTimeseriesReader(
                event_stream, output_class=EventList, data_kind="events"
            )

            # Get file metadata
            original_gti = reader.gti
            mjdref = getattr(reader, "mjdref", 0.0)
            mission = getattr(reader, "mission", None)
            instr = getattr(reader, "instr", None)

            # Get total event count
            if not isinstance(times_stream, str):
                _rewind(times_stream)
            times_reader = FITSTimeseriesReader(times_stream, data_kind="times")
            all_times = times_reader[:]
            total_events = len(all_times)

            if original_gti is not None and len(original_gti) > 0:
                total_duration = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))
            else:
                total_duration = (
                    float(all_times.max() - all_times.min())
                    if total_events > 0
                    else 0.0
                )

            # Validate indices
            if start_index < 0:
                start_index = 0
            if start_index >= total_events:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Start index {start_index} exceeds total events {total_events}",
                    error="Invalid start index",
                )

            end_index = min(start_index + count, total_events)
            actual_count = end_index - start_index

            # Use slice to load only requested events
            event_list = reader[start_index:end_index]

            if event_list is None or len(event_list.time) == 0:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"No events found in range [{start_index}:{end_index}]",
                    error="Empty event range",
                )

            # Set metadata that might not be transferred
            event_list.mjdref = _to_python_float(mjdref) or 0.0
            if mission:
                event_list.mission = mission
            if instr:
                event_list.instr = instr

            # Store user notes on the event list object
            if notes:
                event_list.notes = notes

            # Fix inverted GTI intervals (common with unsorted data)
            gti_was_fixed = self._fix_inverted_gti(event_list)

            # Add to state manager
            _raise_if_cancelled(cancellation_check)
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)
            if gti_was_fixed:
                gti_warnings.insert(
                    0, "GTI intervals were inverted and automatically fixed."
                )

            # Run comprehensive data quality validation
            validation_issues = self._validate_data_quality(event_list)

            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max()),
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
                "validation_issues": validation_issues if validation_issues else None,
                "notes": notes if notes else None,
                "lazy_loading_info": {
                    "method": "event_count",
                    "start_index": start_index,
                    "end_index": end_index,
                    "events_requested": count,
                    "events_loaded": actual_count,
                    "total_file_events": total_events,
                    "total_file_duration": total_duration,
                    "events_loaded_percent": (actual_count / total_events * 100)
                    if total_events > 0
                    else 0,
                },
            }

            message = (
                f"Lazy loaded '{name}': {actual_count} events "
                f"({summary['lazy_loading_info']['events_loaded_percent']:.1f}% of file) "
                f"from indices [{start_index}:{end_index}]"
            )
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"
            if validation_issues:
                error_count = sum(
                    1 for v in validation_issues if v["severity"] == "error"
                )
                warn_count = sum(
                    1 for v in validation_issues if v["severity"] == "warning"
                )
                if error_count > 0:
                    message += f" [Data errors: {error_count}]"
                if warn_count > 0:
                    message += f" [Data warnings: {warn_count}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected event range could not be read",
                error="event_count_read_failed",
            )

    def get_file_metadata(
        self,
        file_path: str,
        fmt: str = "ogip",
        file_grant: str | None = None,
        *,
        _file_source: GrantedReadFile | None = None,
    ) -> Dict[str, Any]:
        """Inspect metadata only through the exact granted input."""
        fmt = require_input_event_format(fmt)
        with ExitStack() as stack:
            selected = stack.enter_context(
                _open_granted_source(file_path, file_grant, _file_source)
            )
            retained_stream = stack.enter_context(
                _spooled_copy(selected, max_bytes=MAX_FITS_INSPECT_BYTES)
            )
            stream = stack.enter_context(
                _decoded_event_stream(retained_stream, fmt=fmt)
            )
            return self._get_file_metadata_from_stream(stream, selected.size_bytes, fmt)

    def _get_file_metadata_from_stream(
        self,
        file_stream: BinaryIO,
        file_size: int,
        fmt: str,
    ) -> Dict[str, Any]:
        """
        Get metadata from a FITS file without loading the full data.

        Uses FITSTimeseriesReader to efficiently read only metadata:
        - Total event count
        - Time range
        - GTI information
        - Mission/instrument info
        - Available columns

        This is useful for previewing large files before deciding
        what portion to load.

        Args:
            file_path: Path to the FITS event file
            fmt: File format

        Returns:
            Result dictionary with file metadata
        """
        try:
            # Check format
            is_fits = fmt in ("ogip", "fits")
            if not is_fits:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Metadata preview only supports FITS formats. Got: {fmt}",
                    error="Unsupported format",
                )

            file_size_mb = file_size / (1024**2)
            file_size_gb = file_size / (1024**3)

            # Read metadata directly from FITS headers - NO full data loading!
            # This is much faster than using FITSTimeseriesReader for large files
            total_events = 0
            time_min = None
            time_max = None
            available_columns = []
            mjdref = 0.0
            mission = None
            instr = None
            original_gti = None

            _rewind(file_stream)
            with fits.open(file_stream, memmap=False) as hdulist:
                # Find the EVENTS or EVT extension
                events_hdu = None
                for hdu in hdulist:
                    if hdu.name.upper() in ["EVENTS", "EVT"]:
                        events_hdu = hdu
                        break

                if events_hdu is not None:
                    # Get row count from header (NAXIS2) - no data loading!
                    total_events = events_hdu.header.get("NAXIS2", 0)
                    available_columns = [col.name for col in events_hdu.columns]

                    # Get MJDREF from header
                    mjdref = events_hdu.header.get("MJDREF", 0.0)
                    if mjdref == 0.0:
                        # Some files split MJDREF into integer and fractional parts
                        mjdrefi = events_hdu.header.get("MJDREFI", 0)
                        mjdreff = events_hdu.header.get("MJDREFF", 0.0)
                        mjdref = mjdrefi + mjdreff

                    # Get mission/instrument from header
                    mission = events_hdu.header.get(
                        "TELESCOP", None
                    ) or events_hdu.header.get("MISSION", None)
                    instr = events_hdu.header.get("INSTRUME", None)

                    # Get time range from header keywords if available (fast!)
                    tstart = events_hdu.header.get("TSTART", None)
                    tstop = events_hdu.header.get("TSTOP", None)

                    if tstart is not None and tstop is not None:
                        time_min = float(tstart)
                        time_max = float(tstop)
                    elif total_events > 0:
                        # Fallback: read only first and last few rows (much faster than full load)
                        time_col = events_hdu.data["TIME"]
                        time_min = float(time_col[0])
                        time_max = float(time_col[-1])

                # Read GTI extension (usually small, OK to load fully)
                gti_hdu = None
                for hdu in hdulist:
                    if hdu.name.upper() in ["GTI", "STDGTI"]:
                        gti_hdu = hdu
                        break

                if gti_hdu is not None and gti_hdu.data is not None:
                    start_col = (
                        gti_hdu.data["START"]
                        if "START" in gti_hdu.columns.names
                        else None
                    )
                    stop_col = (
                        gti_hdu.data["STOP"]
                        if "STOP" in gti_hdu.columns.names
                        else None
                    )
                    if start_col is not None and stop_col is not None:
                        original_gti = np.column_stack([start_col, stop_col])

            # Calculate duration
            duration = (
                (time_max - time_min)
                if (time_min is not None and time_max is not None)
                else 0.0
            )

            # GTI info
            gti_count = len(original_gti) if original_gti is not None else 0
            total_gti_time = None
            if original_gti is not None and len(original_gti) > 0:
                total_gti_time = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))

            # Determine risk level for loading
            if file_size_gb > 10:
                risk_level = "critical"
            elif file_size_gb > 5:
                risk_level = "risky"
            elif file_size_gb > 1:
                risk_level = "caution"
            else:
                risk_level = "safe"

            metadata = {
                "file_size_mb": file_size_mb,
                "file_size_gb": file_size_gb,
                "risk_level": risk_level,
                "total_events": total_events,
                "time_range": [time_min, time_max],
                "duration": duration,
                "gti_count": gti_count,
                "total_gti_time": total_gti_time,
                "gti_list": (
                    [
                        [_to_python_float(g[0]), _to_python_float(g[1])]
                        for g in original_gti
                    ]
                    if original_gti is not None
                    else None
                ),
                "mjdref": _to_python_float(mjdref),
                "mission": mission,
                "instrument": instr,
                "available_columns": available_columns,
                "recommended_loading": self._recommend_loading_strategy(
                    total_events, file_size_gb, risk_level
                ),
            }

            return self.create_result(
                success=True,
                data=metadata,
                message=f"Metadata retrieved: {total_events} events, {file_size_mb:.1f} MB, {gti_count} GTI",
            )

        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected file metadata could not be read",
                error="metadata_read_failed",
            )

    def _recommend_loading_strategy(
        self,
        total_events: int,
        file_size_gb: float,
        risk_level: str,
    ) -> Dict[str, Any]:
        """
        Recommend a loading strategy based on file characteristics.

        Returns recommendations for how to load the file efficiently.

        Strategies:
        - 'full': Safe to load the entire file
        - 'time_range': Use partial loading by time range
        - 'event_count': Use partial loading by event count (for very large files)
        """
        recommendations = {
            "can_load_full": risk_level in ["safe"],
            "recommend_lazy": risk_level in ["caution", "risky", "critical"],
            "suggested_chunk_size": None,
            "suggested_time_chunk": None,
            "strategy": "full",
        }

        if risk_level == "critical":
            # Very large file (>10GB) - must use partial loading
            recommendations["strategy"] = "event_count"
            recommendations["suggested_chunk_size"] = min(
                100000, max(1000, total_events // 10)
            )
            recommendations["suggested_time_chunk"] = 100.0  # seconds
        elif risk_level == "risky":
            # Large file (5-10GB) - strongly recommend partial loading
            recommendations["strategy"] = "time_range"
            recommendations["suggested_chunk_size"] = min(
                500000, max(10000, total_events // 5)
            )
            recommendations["suggested_time_chunk"] = 500.0
        elif risk_level == "caution":
            # Medium file (1-5GB) - partial loading recommended
            recommendations["strategy"] = "time_range"
            recommendations["suggested_chunk_size"] = min(
                1000000, max(50000, total_events // 2)
            )
            recommendations["suggested_time_chunk"] = 1000.0
        else:
            # Small file (<1GB) - safe to load fully
            recommendations["strategy"] = "full"

        return recommendations

    # =========================================================================
    # BATCH LOADING METHODS
    # Load multiple files in parallel using ThreadPoolExecutor
    # =========================================================================

    def _get_risk_level(self, ram_percent: float) -> str:
        """Determine risk level based on RAM usage percentage."""
        if ram_percent > 80:
            return "critical"
        elif ram_percent > 50:
            return "risky"
        elif ram_percent > 30:
            return "caution"
        else:
            return "safe"

    def check_batch_file_size(
        self,
        files: List[Dict[str, str]],
        *,
        _file_sources: List[GrantedReadFile] | None = None,
    ) -> Dict[str, Any]:
        """Check a bounded batch after atomically pinning every selected input."""
        try:
            with ExitStack() as stack:
                sources: List[GrantedReadFile] = []
                for index, item in enumerate(files):
                    retained = (
                        _file_sources[index] if _file_sources is not None else None
                    )
                    sources.append(
                        stack.enter_context(
                            _open_granted_source(
                                item["file_path"],
                                item.get("file_grant"),
                                retained,
                            )
                        )
                    )

                memory_info = self._get_memory_info()
                available_ram_mb = memory_info["available_mb"]
                files_info = []
                total_size_mb = 0.0
                total_estimated_ram_mb = 0.0

                for item, source in zip(files, sources):
                    size_bytes = source.size_bytes
                    size_mb = size_bytes / (1024**2)
                    suffix = source.path.suffix.lower()
                    fmt = (
                        "fits"
                        if suffix in {".fits", ".fit", ".fts", ".evt", ".gz"}
                        else "hdf5"
                        if suffix in {".hdf5", ".h5"}
                        else "fits"
                    )
                    estimated_ram_mb = self._estimate_memory_usage(size_bytes, fmt) / (
                        1024**2
                    )
                    ram_percent = (
                        estimated_ram_mb / available_ram_mb * 100
                        if available_ram_mb > 0
                        else 100
                    )
                    files_info.append(
                        {
                            "file_name": source.path.name,
                            "size_mb": round(size_mb, 1),
                            "estimated_ram_mb": round(estimated_ram_mb, 1),
                            "ram_percent": round(ram_percent, 1),
                            "risk_level": self._get_risk_level(ram_percent),
                        }
                    )
                    total_size_mb += size_mb
                    total_estimated_ram_mb += estimated_ram_mb

                total_ram_percent = (
                    total_estimated_ram_mb / available_ram_mb * 100
                    if available_ram_mb > 0
                    else 100
                )
                return self.create_result(
                    success=True,
                    data={
                        "files": files_info,
                        "total": {
                            "size_mb": round(total_size_mb, 1),
                            "estimated_ram_mb": round(total_estimated_ram_mb, 1),
                            "ram_percent": round(total_ram_percent, 1),
                            "risk_level": self._get_risk_level(total_ram_percent),
                        },
                        "available_ram_mb": round(available_ram_mb, 1),
                        "file_count": len(files),
                        "recommend_partial_loading": total_ram_percent > 30,
                    },
                    message=(
                        f"Checked {len(files)} files: {total_size_mb:.1f} MB total, "
                        f"~{total_ram_percent:.0f}% of available RAM"
                    ),
                )
        except Exception:
            return self.create_result(
                success=False,
                data=None,
                message="The selected batch sizes could not be checked",
                error="batch_size_check_failed",
            )

    def load_batch_event_lists(
        self,
        files: List[Dict[str, Any]],
        use_same_settings: bool = True,
        shared_fmt: str = "ogip",
        shared_rmf_file: Optional[str] = None,
        shared_rmf_grant: Optional[str] = None,
        shared_additional_columns: Optional[List[str]] = None,
        shared_high_precision: bool = False,
        shared_skip_checks: bool = False,
        shared_use_partial_loading: bool = False,
        shared_partial_mode: str = "time_range",
        shared_time_range_start: Optional[float] = None,
        shared_time_range_end: Optional[float] = None,
        shared_event_start_index: Optional[int] = None,
        shared_event_count: Optional[int] = None,
        max_workers: Optional[int] = None,
        *,
        _file_sources: List[GrantedReadFile] | None = None,
        _rmf_sources: List[GrantedReadFile | None] | None = None,
        _shared_rmf_source: GrantedReadFile | None = None,
        _cancellation_check=None,
    ) -> Dict[str, Any]:
        """Pin an entire batch before loading and never reopen selected paths."""
        files, shared_fmt = require_batch_input_formats(files, shared_fmt)
        for item in files:
            name_error = validate_derived_name(item.get("name", ""))
            if name_error:
                raise ValueError(name_error)
        start_time = time.time()
        if not files:
            return self.create_result(
                success=False, message="No files provided for batch loading"
            )

        names = [item.get("name", "") for item in files]
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        if duplicate_names:
            return self.create_result(
                success=False, message=f"Duplicate names in request: {duplicate_names}"
            )
        existing_names = [
            name for name in names if name and self.state.has_event_data(name)
        ]
        if existing_names:
            return self.create_result(
                success=False, message=f"Names already exist in state: {existing_names}"
            )
        if (shared_rmf_file is None) != (shared_rmf_grant is None) and (
            _shared_rmf_source is None
        ):
            raise ValueError(
                "shared_rmf_file and shared_rmf_grant must be provided together"
            )

        with ExitStack() as stack:
            retained_files: List[GrantedReadFile] = []
            retained_rmfs: List[GrantedReadFile | None] = []
            for index, item in enumerate(files):
                private_source = (
                    _file_sources[index] if _file_sources is not None else None
                )
                retained_files.append(
                    stack.enter_context(
                        _open_granted_source(
                            item["file_path"],
                            item.get("file_grant"),
                            private_source,
                        )
                    )
                )

            shared_source = None
            if shared_rmf_file is not None or _shared_rmf_source is not None:
                shared_source = stack.enter_context(
                    _open_granted_source(
                        shared_rmf_file or "<retained RMF>",
                        shared_rmf_grant,
                        _shared_rmf_source,
                    )
                )

            for index, item in enumerate(files):
                private_rmf = _rmf_sources[index] if _rmf_sources is not None else None
                if use_same_settings:
                    retained_rmfs.append(shared_source)
                    continue
                rmf_path = item.get("rmf_file")
                rmf_grant = item.get("rmf_grant")
                if (rmf_path is None) != (rmf_grant is None) and private_rmf is None:
                    raise ValueError("rmf_file and rmf_grant must be provided together")
                if rmf_path is None and private_rmf is None:
                    retained_rmfs.append(None)
                else:
                    retained_rmfs.append(
                        stack.enter_context(
                            _open_granted_source(
                                rmf_path or "<retained RMF>",
                                rmf_grant,
                                private_rmf,
                            )
                        )
                    )

            def load_single(index: int) -> Dict[str, Any]:
                item = files[index]
                name = item["name"]
                if use_same_settings:
                    fmt = shared_fmt
                    rmf_path = shared_rmf_file
                    columns = shared_additional_columns
                    high_precision = shared_high_precision
                    skip_checks = shared_skip_checks
                    use_partial = shared_use_partial_loading
                    partial_mode = shared_partial_mode
                    range_start = shared_time_range_start
                    range_end = shared_time_range_end
                    event_start = shared_event_start_index
                    event_count = shared_event_count
                    notes = None
                else:
                    fmt = item.get("fmt", "ogip")
                    rmf_path = item.get("rmf_file")
                    columns = item.get("additional_columns")
                    high_precision = bool(item.get("high_precision", False))
                    skip_checks = bool(item.get("skip_checks", False))
                    use_partial = bool(item.get("use_partial_loading", False))
                    partial_mode = item.get("partial_mode", "time_range")
                    range_start = item.get("time_range_start")
                    range_end = item.get("time_range_end")
                    event_start = item.get("event_start_index")
                    event_count = item.get("event_count")
                    notes = item.get("notes")

                try:
                    if use_partial and partial_mode == "time_range":
                        if range_start is None or range_end is None:
                            raise ValueError(
                                "Partial time-range loading requires both endpoints"
                            )
                        result = self.load_event_list_by_time_range(
                            item["file_path"],
                            name,
                            range_start,
                            range_end,
                            fmt,
                            notes,
                            _file_source=retained_files[index],
                            _cancellation_check=_cancellation_check,
                        )
                    elif use_partial:
                        result = self.load_event_list_by_event_count(
                            item["file_path"],
                            name,
                            event_start or 0,
                            event_count or 10000,
                            fmt,
                            notes,
                            _file_source=retained_files[index],
                            _cancellation_check=_cancellation_check,
                        )
                    else:
                        result = self.load_event_list(
                            item["file_path"],
                            name,
                            fmt=fmt,
                            rmf_file=rmf_path,
                            additional_columns=columns,
                            high_precision=high_precision,
                            skip_checks=skip_checks,
                            notes=notes,
                            _file_source=retained_files[index],
                            _rmf_source=retained_rmfs[index],
                            _cancellation_check=_cancellation_check,
                        )
                    return {
                        "success": bool(result.get("success")),
                        "name": name,
                        "data": result.get("data"),
                        "message": result.get("message"),
                        "error": result.get("error") or result.get("message"),
                    }
                except Exception:
                    return {
                        "success": False,
                        "name": name,
                        "error": "The selected file could not be loaded",
                    }

            worker_count = max_workers or min(os.cpu_count() or 4, len(files), 8)
            worker_count = max(1, min(worker_count, len(files), 8))
            # One shared seekable RMF stream must never be consumed concurrently.
            if shared_source is not None:
                worker_count = 1

            successful: List[Dict[str, Any]] = []
            failed: List[Dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                _raise_if_cancelled(_cancellation_check)
                futures = {
                    executor.submit(load_single, index): index
                    for index in range(len(files))
                }
                for future in as_completed(futures):
                    _raise_if_cancelled(_cancellation_check)
                    result = future.result()
                    if result["success"]:
                        successful.append(
                            {
                                "name": result["name"],
                                "data": result.get("data"),
                                "message": result.get("message"),
                            }
                        )
                    else:
                        failed.append(
                            {
                                "name": result["name"],
                                "error": result.get("error") or "Unknown error",
                            }
                        )

            total_time_ms = (time.time() - start_time) * 1000
            total_events = sum(
                item.get("data", {}).get("n_events", 0) if item.get("data") else 0
                for item in successful
            )
            return self.create_result(
                success=not failed,
                data={
                    "successful": successful,
                    "failed": failed,
                    "summary": {
                        "total_files": len(files),
                        "success_count": len(successful),
                        "failure_count": len(failed),
                        "total_events_loaded": total_events,
                        "total_time_ms": round(total_time_ms, 1),
                        "workers_used": worker_count,
                    },
                },
                message=(
                    f"Loaded {len(successful)}/{len(files)} files "
                    f"({total_events:,} total events) in {total_time_ms:.0f}ms"
                ),
            )

    async def load_batch_event_lists_stream(
        self,
        files: List[Dict[str, Any]],
        use_same_settings: bool = True,
        shared_fmt: str = "ogip",
        shared_rmf_file: Optional[str] = None,
        shared_rmf_grant: Optional[str] = None,
        shared_additional_columns: Optional[List[str]] = None,
        shared_high_precision: bool = False,
        shared_skip_checks: bool = False,
        shared_use_partial_loading: bool = False,
        shared_partial_mode: str = "time_range",
        shared_time_range_start: Optional[float] = None,
        shared_time_range_end: Optional[float] = None,
        shared_event_start_index: Optional[int] = None,
        shared_event_count: Optional[int] = None,
        max_workers: Optional[int] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Return the legacy SSE envelope backed by the secure batch loader."""
        # Format policy is an admission decision, not a runtime SSE failure.
        # Preserve fail-fast behavior before any worker or native I/O exists.
        files, shared_fmt = require_batch_input_formats(files, shared_fmt)
        cancellation_signal = threading.Event()
        worker = asyncio.create_task(
            asyncio.to_thread(
                self.load_batch_event_lists,
                files,
                use_same_settings,
                shared_fmt,
                shared_rmf_file,
                shared_rmf_grant,
                shared_additional_columns,
                shared_high_precision,
                shared_skip_checks,
                shared_use_partial_loading,
                shared_partial_mode,
                shared_time_range_start,
                shared_time_range_end,
                shared_event_start_index,
                shared_event_count,
                max_workers,
                _cancellation_check=cancellation_signal.is_set,
            )
        )
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancellation_signal.set()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
            try:
                worker.result()
            except BaseException:
                pass
            raise
        except Exception:
            yield {
                "type": "error",
                "error": "The selected batch could not be admitted or loaded",
            }
            return
        finally:
            cancellation_signal.set()
        if result.get("data") is None:
            yield {
                "type": "error",
                "error": result.get("message") or "Batch load failed",
            }
            return

        data = result["data"]
        completed = 0
        for item in [*data["successful"], *data["failed"]]:
            completed += 1
            success = "data" in item
            event = {
                "type": "file_complete",
                "name": item["name"],
                "success": success,
                "completed": completed,
                "total": len(files),
            }
            if success:
                event["data"] = item.get("data")
            else:
                event["error"] = item.get("error", "Unknown error")
            yield event
            await asyncio.sleep(0)

        summary = data["summary"]
        yield {
            "type": "complete",
            "total_time_ms": summary["total_time_ms"],
            "success_count": summary["success_count"],
            "failure_count": summary["failure_count"],
            "total_events": summary["total_events_loaded"],
            "workers_used": summary["workers_used"],
        }
