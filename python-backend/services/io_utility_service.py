"""Safe file inspection, RMF calibration, and tabular export utilities.

The existing data-ingestion service remains the only way to load arbitrary
files into application state.  This service only inspects explicitly selected
files, derives calibrated copies of loaded EventLists, and exports objects that
are already in state.
"""

from __future__ import annotations

import json
import math
import os
import secrets
import stat
from collections.abc import Iterable, Mapping, Sized
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
from itertools import islice
from numbers import Integral, Real
from pathlib import Path
from typing import Any, BinaryIO

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.table import Table
from stingray.io import high_precision_keyword_read, pi_to_energy, read_rmf

from .analysis_helpers import collect_warnings
from .base_service import BaseService
from .state_manager import _enforce_precopy_caps
from .utility_helpers import (
    MAX_ARRAY_INPUT,
    MAX_EXPORT_ROWS,
    MAX_FITS_INSPECT_BYTES,
    MAX_RMF_BYTES,
    bounded_plot_preview,
    duplicate_binary_stream,
    json_safe,
    open_verified_read_grant,
    open_verified_write_grant,
    operation_provenance,
    validate_derived_name,
    validate_file_size,
    verify_file_grant,
)

MAX_INSPECT_HDUS = 512
MAX_COLUMNS_PER_HDU = 1_024
MAX_RMF_ROWS = 1_000_000
MAX_RMF_PI_WORK = 20_000_000
MAX_EXACT_CHANNEL = 2**53 - 1
MAX_EVENT_PREVIEW_ROWS = 500
MAX_EXPORT_COLUMNS = 1_024
MAX_EXPORT_CELLS = 20_000_000
MAX_EXPORT_ESTIMATED_BYTES = 512 * 1024**2

FITS_EXTENSIONS = {".fits", ".fit", ".fts", ".evt", ".rmf", ".rsp"}
EXPORT_EXTENSIONS = {
    "csv": ".csv",
    "ecsv": ".ecsv",
    "json": ".json",
    "fits": ".fits",
}
EXPORT_OBJECT_TYPES = {"event_list", "lightcurve", "analysis_result"}

TIMING_KEYWORDS = (
    "MJDREF",
    "MJDREFI",
    "MJDREFF",
    "MJD-OBS",
    "MJD-END",
    "TIMESYS",
    "TIMEREF",
    "TREFPOS",
    "TIMEUNIT",
    "TIMEZERO",
    "TIMEZERI",
    "TIMEZERF",
    "TSTART",
    "TSTARTI",
    "TSTARTF",
    "TSTOP",
    "TSTOPI",
    "TSTOPF",
    "TIMEDEL",
    "TIMEPIXR",
    "DATE-OBS",
    "DATE-END",
    "CLOCKAPP",
)

NUMERIC_TIMING_KEYWORDS = {
    "MJDREF",
    "MJDREFI",
    "MJDREFF",
    "MJD-OBS",
    "MJD-END",
    "TIMEZERO",
    "TIMEZERI",
    "TIMEZERF",
    "TSTART",
    "TSTARTI",
    "TSTARTF",
    "TSTOP",
    "TSTOPI",
    "TSTOPF",
    "TIMEDEL",
    "TIMEPIXR",
}

SPLIT_HIGH_PRECISION_TIMING_KEYWORDS = {
    "TSTART": ("TSTARTI", "TSTARTF"),
    "TSTOP": ("TSTOPI", "TSTOPF"),
    # high_precision_keyword_read truncates an eight-character keyword before
    # adding I/F so the FITS-compatible split spelling is TIMEZERI/TIMEZERF.
    "TIMEZERO": ("TIMEZERI", "TIMEZERF"),
}

ANALYSIS_RESERVED_FIELDS = {"warnings", "provenance", "parameters", "metadata"}


def _display_fits_value(value: Any) -> Any:
    """Return one FITS scalar without introducing non-JSON numeric values."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating, np.integer)):
        converted = float(value)
        return converted if math.isfinite(converted) else str(value)
    return str(value)


def _raw_decimal_card_value(header: fits.Header, keyword: str) -> str:
    """Return the numeric value field from the original 80-byte FITS card.

    Astropy normally exposes FITS numeric cards as binary64 values.  The card
    image still retains the decimal token that was actually written, which is
    important for split MJD reference epochs that intentionally carry more
    digits than binary64 can round-trip.
    """
    card = header.cards[keyword]
    image = card.image[:80]
    if image[8:10] != "= ":
        return str(card.value)
    value_field = image[10:].split("/", 1)[0].strip()
    if value_field.startswith("'"):
        return str(card.value)
    # FITS permits Fortran-style D exponents, while Decimal accepts E.
    return value_field.replace("D", "E").replace("d", "e")


def _decimal_mjdref(header: fits.Header) -> dict[str, Any] | None:
    """Read MJDREF with Stingray and retain the original FITS components.

    ``high_precision_keyword_read`` is the installed public Stingray helper.
    Its numeric precision is platform-dependent, so the API also returns an
    exact decimal sum constructed from the original FITS card text.
    """
    has_direct = "MJDREF" in header
    has_integer = "MJDREFI" in header
    has_fraction = "MJDREFF" in header
    if not has_direct and has_integer != has_fraction:
        raise ValueError("MJDREFI/MJDREFF split reference is incomplete")

    stingray_value = high_precision_keyword_read(header, "MJDREF")
    if stingray_value is None:
        return None

    components: dict[str, str] = {}
    try:
        if "MJDREF" in header:
            components["MJDREF"] = _raw_decimal_card_value(header, "MJDREF")
            exact = Decimal(components["MJDREF"])
        else:
            components["MJDREFI"] = _raw_decimal_card_value(header, "MJDREFI")
            components["MJDREFF"] = _raw_decimal_card_value(header, "MJDREFF")
            exact = Decimal(components["MJDREFI"]) + Decimal(components["MJDREFF"])
    except (InvalidOperation, KeyError, TypeError, ValueError):
        exact = Decimal(str(stingray_value))

    if not exact.is_finite() or not np.isfinite(np.longdouble(stingray_value)):
        raise ValueError("MJDREF is non-finite")

    return {
        "decimal": format(exact, "f"),
        "stingray_value": np.format_float_positional(
            np.longdouble(stingray_value), unique=True, trim="-"
        ),
        "source_keywords": components,
    }


def _timing_metadata(
    header: fits.Header, warning_messages: list[str], hdu_label: str
) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    invalid_timing = False
    for keyword in TIMING_KEYWORDS:
        if keyword not in header:
            continue
        value = header[keyword]
        if keyword in NUMERIC_TIMING_KEYWORDS:
            try:
                decimal_value = Decimal(str(value).strip())
            except (InvalidOperation, TypeError, ValueError):
                raw[keyword] = None
                invalid_timing = True
                warning_messages.append(
                    f"{hdu_label} timing keyword {keyword} is not numeric and is "
                    "represented as null."
                )
                continue
            else:
                if not decimal_value.is_finite():
                    raw[keyword] = None
                    invalid_timing = True
                    warning_messages.append(
                        f"{hdu_label} timing keyword {keyword} is non-finite and is "
                        "represented as null."
                    )
                    continue
                if keyword == "TIMEDEL" and decimal_value <= 0:
                    raw[keyword] = None
                    invalid_timing = True
                    warning_messages.append(
                        f"{hdu_label} timing keyword TIMEDEL must be greater than zero "
                        "and is represented as null."
                    )
                    continue
                if keyword == "TIMEPIXR" and not Decimal(0) <= decimal_value <= Decimal(
                    1
                ):
                    raw[keyword] = None
                    invalid_timing = True
                    warning_messages.append(
                        f"{hdu_label} timing keyword TIMEPIXR must be between 0 and 1 "
                        "and is represented as null."
                    )
                    continue
        raw[keyword] = _display_fits_value(value)

    high_precision: dict[str, dict[str, Any]] = {}
    for keyword, (
        integer_keyword,
        fraction_keyword,
    ) in SPLIT_HIGH_PRECISION_TIMING_KEYWORDS.items():
        has_direct = keyword in header
        has_integer = integer_keyword in header
        has_fraction = fraction_keyword in header
        if not has_direct and not has_integer and not has_fraction:
            continue
        if not has_direct and has_integer != has_fraction:
            raw[keyword] = None
            invalid_timing = True
            warning_messages.append(
                f"{hdu_label} split timing keyword {keyword} is incomplete; both "
                f"{integer_keyword} and {fraction_keyword} are required."
            )
            continue

        source_keywords: dict[str, str] = {}
        try:
            if has_direct:
                source_keywords[keyword] = _raw_decimal_card_value(header, keyword)
                exact = Decimal(source_keywords[keyword])
            else:
                source_keywords[integer_keyword] = _raw_decimal_card_value(
                    header, integer_keyword
                )
                source_keywords[fraction_keyword] = _raw_decimal_card_value(
                    header, fraction_keyword
                )
                exact = Decimal(source_keywords[integer_keyword]) + Decimal(
                    source_keywords[fraction_keyword]
                )
            stingray_value = high_precision_keyword_read(header, keyword)
            if (
                stingray_value is None
                or not exact.is_finite()
                or not np.isfinite(np.longdouble(stingray_value))
            ):
                raise ValueError("non-finite split timing value")
        except (InvalidOperation, TypeError, ValueError):
            raw[keyword] = None
            invalid_timing = True
            warning_messages.append(
                f"{hdu_label} timing keyword {keyword} is invalid or non-finite and "
                "is represented as null."
            )
            continue

        high_precision[keyword] = {
            "decimal": format(exact, "f"),
            "stingray_value": np.format_float_positional(
                np.longdouble(stingray_value), unique=True, trim="-"
            ),
            "source_keywords": source_keywords,
        }
        if not has_direct:
            raw[keyword] = _display_fits_value(np.longdouble(stingray_value))

        if has_direct and has_integer and has_fraction:
            try:
                split = Decimal(
                    _raw_decimal_card_value(header, integer_keyword)
                ) + Decimal(_raw_decimal_card_value(header, fraction_keyword))
            except (InvalidOperation, TypeError, ValueError):
                split = exact
            if split.is_finite() and split != exact:
                warning_messages.append(
                    f"{hdu_label} declares conflicting {keyword} and "
                    f"{integer_keyword}/{fraction_keyword} values; the direct "
                    f"{keyword} value was used."
                )

    split_conflict = False
    if all(keyword in header for keyword in ("MJDREF", "MJDREFI", "MJDREFF")):
        try:
            direct = Decimal(_raw_decimal_card_value(header, "MJDREF"))
            split = Decimal(_raw_decimal_card_value(header, "MJDREFI")) + Decimal(
                _raw_decimal_card_value(header, "MJDREFF")
            )
            split_conflict = (
                direct.is_finite() and split.is_finite() and direct != split
            )
        except (InvalidOperation, TypeError, ValueError):
            pass
        if split_conflict:
            warning_messages.append(
                f"{hdu_label} declares conflicting MJDREF and MJDREFI/MJDREFF values; "
                "the direct MJDREF value was used."
            )

    try:
        mjdref = _decimal_mjdref(header)
    except (InvalidOperation, TypeError, ValueError):
        mjdref = None
        status = "invalid"
        note = "MJDREF is invalid or non-finite and was not interpreted."
        warning_messages.append(f"{hdu_label} MJDREF is invalid or non-finite.")
    else:
        status = "available" if mjdref is not None else "missing"
        note = (
            "MJDREF is preserved as an exact decimal assembled from its original "
            "FITS card or MJDREFI/MJDREFF components."
            if mjdref is not None
            else "No MJDREF or MJDREFI/MJDREFF time-reference keyword is present in this HDU."
        )
        if split_conflict:
            note += " Conflicting split reference cards are present."
    if invalid_timing and status != "invalid":
        status = "invalid"
        note += " One or more timing keywords are invalid and were represented as null."
    return {
        "mjdref": mjdref,
        "status": status,
        "note": note,
        "keywords": raw,
        "high_precision_keywords": high_precision,
    }


def _hdu_kind(hdu: fits.hdu.base.ExtensionHDU | fits.PrimaryHDU) -> str:
    if isinstance(hdu, fits.BinTableHDU):
        return "binary_table"
    if isinstance(hdu, fits.TableHDU):
        return "ascii_table"
    if isinstance(hdu, fits.PrimaryHDU):
        return "primary"
    if isinstance(hdu, (fits.ImageHDU, fits.CompImageHDU)):
        return "image"
    return type(hdu).__name__


def _inspect_fits(stream: BinaryIO) -> tuple[list[dict[str, Any]], list[str], str]:
    """Inspect FITS headers without touching table/image data arrays."""
    warning_messages: list[str] = [
        "FITS DATASUM/CHECKSUM values were not verified during header-only inspection."
    ]
    with collect_warnings(warning_messages):
        with (
            duplicate_binary_stream(stream) as fits_stream,
            fits.open(
                fits_stream,
                mode="readonly",
                memmap=True,
                lazy_load_hdus=True,
                # checksum=True can force DATASUM reads of large HDUs, defeating
                # this inspector's deliberate header-only boundary.
                checksum=False,
            ) as hdul,
        ):
            if len(hdul) > MAX_INSPECT_HDUS:
                raise ValueError(
                    f"FITS file has {len(hdul):,} HDUs; the inspection cap is {MAX_INSPECT_HDUS:,}"
                )

            summaries: list[dict[str, Any]] = []
            detected_type = "fits"
            for index, hdu in enumerate(hdul):
                header = hdu.header
                kind = _hdu_kind(hdu)
                columns: list[dict[str, Any]] = []
                if isinstance(hdu, (fits.BinTableHDU, fits.TableHDU)):
                    column_count = int(header.get("TFIELDS", 0) or 0)
                    if column_count > MAX_COLUMNS_PER_HDU:
                        raise ValueError(
                            f"HDU {index} has {column_count:,} columns; the inspection cap is "
                            f"{MAX_COLUMNS_PER_HDU:,}"
                        )
                    columns = [
                        {
                            "name": column.name,
                            "format": str(column.format),
                            "unit": str(column.unit) if column.unit else None,
                        }
                        for column in hdu.columns
                    ]

                axes = [
                    int(header[f"NAXIS{axis}"])
                    for axis in range(1, int(header.get("NAXIS", 0) or 0) + 1)
                ]
                row_count = (
                    int(header.get("NAXIS2", 0) or 0)
                    if isinstance(hdu, (fits.BinTableHDU, fits.TableHDU))
                    else None
                )
                name = str(header.get("EXTNAME", hdu.name or "PRIMARY"))
                column_names = {column["name"].upper() for column in columns}
                if name.upper() == "EBOUNDS" and {"CHANNEL", "E_MIN", "E_MAX"}.issubset(
                    column_names
                ):
                    detected_type = "rmf"

                summaries.append(
                    {
                        "index": index,
                        "name": name,
                        "type": kind,
                        "row_count": row_count,
                        "dimensions": axes,
                        "columns": columns,
                        "timing": _timing_metadata(
                            header, warning_messages, f"HDU {index} ({name})"
                        ),
                    }
                )

            mjdrefs = {
                Decimal(summary["timing"]["mjdref"]["decimal"])
                for summary in summaries
                if summary["timing"]["mjdref"] is not None
            }
            if len(mjdrefs) > 1:
                warning_messages.append(
                    "Different HDUs declare different MJDREF values; the file's time "
                    "reference is ambiguous and must be interpreted per HDU."
                )
    return summaries, warning_messages, detected_type


def _energy_unit_scales(
    ebounds: fits.BinTableHDU,
) -> tuple[tuple[float, float] | None, list[str]]:
    """Validate EBOUNDS units and return per-column conversions to keV."""
    warnings_out: list[str] = []
    units: list[str | None] = []
    for name in ("E_MIN", "E_MAX"):
        unit = ebounds.columns[name].unit
        units.append(str(unit).strip() if unit else None)
    scales: list[float | None] = []
    for name, unit_text in zip(("E_MIN", "E_MAX"), units, strict=True):
        if unit_text is None:
            scales.append(None)
            continue
        try:
            parsed_unit = u.Unit(unit_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"RMF {name} unit '{unit_text}' is not a recognized physical unit"
            ) from exc
        if not parsed_unit.is_equivalent(u.keV):
            raise ValueError(
                f"RMF {name} unit '{unit_text}' is not energy-equivalent and cannot "
                "be calibrated to keV"
            )
        scale = float(parsed_unit.to(u.keV))
        if not math.isfinite(scale) or scale <= 0:
            raise ValueError(f"RMF {name} unit '{unit_text}' has an invalid keV scale")
        scales.append(scale)
    if scales[0] is None or scales[1] is None:
        warnings_out.append(
            "E_MIN/E_MAX units are missing; calibrated energy conversion is disabled."
        )
        return None, warnings_out
    scale_min, scale_max = scales
    if not math.isclose(scale_min, scale_max, rel_tol=0.0, abs_tol=0.0):
        warnings_out.append(
            f"E_MIN and E_MAX use different energy units ({units[0]} and {units[1]}); "
            "each bound was independently normalized to keV."
        )
    return (scale_min, scale_max), warnings_out


def _load_valid_rmf(
    stream: BinaryIO, *, require_energy_unit: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray, str | None, list[str]]:
    """Load a bounded EBOUNDS table through public Stingray I/O and validate it."""
    validate_file_size(stream, MAX_RMF_BYTES, "RMF file")
    with (
        duplicate_binary_stream(stream) as fits_stream,
        fits.open(
            fits_stream,
            mode="readonly",
            memmap=True,
            lazy_load_hdus=True,
            # Only inspect NAXIS2/columns before the allocation cap.  The public
            # read_rmf call below reopens with checksum=True after that cap passes.
            checksum=False,
        ) as hdul,
    ):
        matches = [hdu for hdu in hdul if hdu.name.upper() == "EBOUNDS"]
        if len(matches) != 1:
            raise ValueError(
                "RMF must contain exactly one EBOUNDS binary-table extension"
            )
        ebounds = matches[0]
        if not isinstance(ebounds, fits.BinTableHDU):
            raise ValueError("EBOUNDS must be a FITS binary table")
        row_count = int(ebounds.header.get("NAXIS2", 0) or 0)
        if row_count < 1:
            raise ValueError("RMF EBOUNDS contains no channel rows")
        if row_count > MAX_RMF_ROWS:
            raise ValueError(
                f"RMF EBOUNDS has {row_count:,} rows; the supported cap is {MAX_RMF_ROWS:,}"
            )
        names = {name.upper() for name in (ebounds.columns.names or [])}
        missing = sorted({"CHANNEL", "E_MIN", "E_MAX"} - names)
        if missing:
            raise ValueError(
                f"RMF EBOUNDS is missing required column(s): {', '.join(missing)}"
            )
        energy_scales, warnings_out = _energy_unit_scales(ebounds)

    # Public Stingray 2.2.10 API.  It opens with memmap=False, which is why the
    # NAXIS2 allocation cap is checked from the lazy header before this call.
    with collect_warnings(warnings_out):
        with duplicate_binary_stream(stream) as rmf_stream:
            channels_raw, e_min_raw, e_max_raw = read_rmf(rmf_stream)
    if any("verification failed" in message.lower() for message in warnings_out):
        raise ValueError("RMF FITS checksum or DATASUM verification failed")
    channels_array = np.asarray(channels_raw)
    e_min = np.asarray(e_min_raw, dtype=float)
    e_max = np.asarray(e_max_raw, dtype=float)

    if energy_scales is not None:
        with np.errstate(over="ignore", invalid="ignore"):
            e_min = e_min * energy_scales[0]
            e_max = e_max * energy_scales[1]

    if any(array.ndim != 1 for array in (channels_array, e_min, e_max)):
        raise ValueError("RMF EBOUNDS columns must be one-dimensional")
    if not (len(channels_array) == len(e_min) == len(e_max) == row_count):
        raise ValueError("RMF EBOUNDS columns have inconsistent lengths")
    for array, label in ((e_min, "E_MIN"), (e_max, "E_MAX")):
        bad = np.flatnonzero(~np.isfinite(array))
        if bad.size:
            raise ValueError(f"RMF {label}[{int(bad[0])}] must be finite")
    if channels_array.dtype.kind not in {"i", "u"}:
        raise ValueError("RMF CHANNEL values must use an integer FITS column")
    if channels_array.dtype.kind == "i" and np.any(channels_array < 0):
        raise ValueError("RMF CHANNEL values must be non-negative integers")
    too_large = np.flatnonzero(channels_array > MAX_EXACT_CHANNEL)
    if too_large.size:
        index = int(too_large[0])
        raise ValueError(
            f"RMF CHANNEL[{index}] exceeds the exact JSON/JavaScript integer cap "
            f"of {MAX_EXACT_CHANNEL:,}"
        )
    channels = channels_array.astype(np.int64, copy=False)
    unique, counts = np.unique(channels, return_counts=True)
    duplicated = unique[counts > 1]
    if duplicated.size:
        raise ValueError(f"RMF CHANNEL contains duplicate value {int(duplicated[0])}")
    negative_bounds = np.flatnonzero((e_min < 0) | (e_max <= 0))
    if negative_bounds.size:
        raise ValueError(
            f"RMF energy bounds row {int(negative_bounds[0])} must be non-negative "
            "photon energies with E_MAX > 0"
        )
    invalid_bounds = np.flatnonzero(e_min >= e_max)
    if invalid_bounds.size:
        index = int(invalid_bounds[0])
        raise ValueError(f"RMF energy bounds row {index} must satisfy E_MIN < E_MAX")
    if require_energy_unit and energy_scales is None:
        raise ValueError(warnings_out[0])
    energy_unit = "keV" if energy_scales is not None else None
    return channels, e_min, e_max, energy_unit, warnings_out


def _validate_pi_values(values: Any, *, maximum: int) -> np.ndarray:
    if isinstance(values, (bool, np.bool_)):
        raise ValueError("PI values must be a one-dimensional array, not a boolean")
    if isinstance(values, (str, bytes, bytearray, memoryview)):
        raise ValueError("PI values must be a one-dimensional array, not text")
    if isinstance(values, Mapping):
        raise ValueError("PI values must be a one-dimensional array, not a mapping")

    if isinstance(values, np.ndarray):
        if values.ndim != 1:
            raise ValueError("PI values must be a one-dimensional array")
        if values.size > maximum:
            raise ValueError(
                f"PI values contains {values.size:,} values; the cap is {maximum:,}"
            )
        materialized: Any = values
    elif isinstance(values, (list, tuple)):
        if len(values) > maximum:
            raise ValueError(
                f"PI values contains {len(values):,} values; the cap is {maximum:,}"
            )
        materialized = values
    else:
        shape = getattr(values, "shape", None)
        if shape is not None:
            try:
                dimensions = tuple(shape)
            except TypeError:
                dimensions = ()
            if len(dimensions) != 1:
                raise ValueError("PI values must be a one-dimensional array")
            if (
                isinstance(dimensions[0], (int, np.integer))
                and int(dimensions[0]) > maximum
            ):
                raise ValueError(
                    f"PI values contains {int(dimensions[0]):,} values; the cap is "
                    f"{maximum:,}"
                )
        if isinstance(values, Sized):
            try:
                hinted_length = len(values)
            except (TypeError, ValueError, OverflowError):
                hinted_length = None
            if hinted_length is not None and hinted_length > maximum:
                raise ValueError(
                    f"PI values contains {hinted_length:,} values; the cap is "
                    f"{maximum:,}"
                )
        try:
            materialized = list(islice(iter(values), maximum + 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"PI values must contain only numeric values ({exc})"
            ) from exc
        if len(materialized) > maximum:
            raise ValueError(
                f"PI values contains at least {len(materialized):,} values; the cap is "
                f"{maximum:,}"
            )

    if len(materialized) < 1:
        raise ValueError("PI values must contain at least 1 value(s)")
    if any(
        isinstance(item, Iterable)
        and not isinstance(item, (str, bytes, bytearray, memoryview))
        for item in materialized
    ):
        raise ValueError("PI values must be a one-dimensional array")

    exact = np.empty(len(materialized), dtype=np.int64)
    for index, item in enumerate(materialized):
        if isinstance(item, (bool, np.bool_)):
            raise ValueError("PI values must contain integer channels, not booleans")
        if isinstance(item, Integral):
            integer = int(item)
        elif isinstance(item, Real):
            numeric = float(item)
            if not math.isfinite(numeric):
                raise ValueError(f"PI values[{index}] must be finite")
            if not numeric.is_integer():
                raise ValueError(f"PI values[{index}] must be an integer channel")
            integer = int(numeric)
        else:
            raise ValueError(f"PI values[{index}] must be an integer channel")
        if integer < 0:
            raise ValueError(f"PI values[{index}] must be non-negative")
        if integer > MAX_EXACT_CHANNEL:
            raise ValueError(
                f"PI values[{index}] exceeds the exact JSON/JavaScript integer cap "
                f"of {MAX_EXACT_CHANNEL:,}"
            )
        exact[index] = integer
    return exact


def _energy_midpoints(e_min: np.ndarray, e_max: np.ndarray) -> np.ndarray:
    """Compute finite midpoints without overflowing ``e_min + e_max``."""
    midpoints = e_min / 2.0 + e_max / 2.0
    bad = np.flatnonzero(~np.isfinite(midpoints))
    if bad.size:
        raise ValueError(
            f"RMF energy midpoint at row {int(bad[0])} is not finite after keV conversion"
        )
    return midpoints


def _calibrate_pi(
    pi_values: Any,
    rmf_stream: BinaryIO,
    *,
    maximum: int,
) -> tuple[np.ndarray, np.ndarray, str, list[str]]:
    pis = _validate_pi_values(pi_values, maximum=maximum)
    channels, e_min, e_max, unit, warnings_out = _load_valid_rmf(
        rmf_stream, require_energy_unit=True
    )
    unique_pis, inverse = np.unique(pis, return_inverse=True)
    covered_unique = np.isin(unique_pis, channels)
    covered = covered_unique[inverse]
    if not np.all(covered):
        missing = np.unique(pis[~covered])
        shown = ", ".join(str(int(value)) for value in missing[:10])
        suffix = " ..." if missing.size > 10 else ""
        raise ValueError(
            "Every PI value must have an exact RMF EBOUNDS channel match; missing "
            f"channel(s): {shown}{suffix}"
        )

    work = len(channels) * len(unique_pis)
    if work > MAX_RMF_PI_WORK:
        raise ValueError(
            "RMF conversion would require "
            f"{work:,} channel comparisons ({len(channels):,} RMF channels x "
            f"{len(unique_pis):,} unique PI values); the work cap is "
            f"{MAX_RMF_PI_WORK:,}"
        )

    # Public Stingray call, after defending against its silent zero-for-miss
    # behavior, malformed EBOUNDS inputs, and O(channels * PI) implementation.
    # Supplying only unique PI values avoids repeating upstream comparisons for
    # duplicate event channels.
    with collect_warnings(warnings_out):
        with duplicate_binary_stream(rmf_stream) as upstream_stream:
            upstream_unique = np.asarray(
                pi_to_energy(unique_pis, upstream_stream), dtype=float
            )
    if upstream_unique.shape != unique_pis.shape:
        raise ValueError("Stingray returned an unexpected calibrated-energy shape")
    bad = np.flatnonzero(~np.isfinite(upstream_unique))
    if bad.size:
        warnings_out.append(
            "Stingray's raw-unit midpoint calculation produced a non-finite value; "
            "the returned calibration uses overflow-safe, unit-normalized RMF bounds."
        )

    # Stingray 2.2.10 ignores TUNITn and returns the numeric midpoint in the
    # source units.  Use the already validated, per-bound keV values so mixed
    # but energy-equivalent E_MIN/E_MAX units remain scientifically meaningful.
    midpoints = _energy_midpoints(e_min, e_max)
    channel_to_energy = {
        int(channel): float(midpoint)
        for channel, midpoint in zip(channels, midpoints, strict=True)
    }
    unique_energies = np.asarray(
        [channel_to_energy[int(pi)] for pi in unique_pis], dtype=float
    )
    energies = unique_energies[inverse]
    assert unit is not None
    return pis, energies, unit, warnings_out


def _estimated_value_bytes(
    value: Any, limit: int, active: set[int] | None = None
) -> int:
    """Estimate serialized size while counting every repeated reference.

    Shared values are expanded once per occurrence by JSON/ECSV/FITS metadata
    serialization, so they must be charged once per occurrence here as well.
    Only references on the active recursion path are special: those are cycles
    and cannot be represented by the supported export formats.
    """
    if active is None:
        active = set()
    if value is None or isinstance(value, (bool, int, float, np.number)):
        return 32
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if isinstance(value, np.ndarray) and value.dtype.kind != "O":
        return int(value.nbytes)
    identity = id(value)
    if identity in active:
        raise ValueError(
            "Analysis result metadata contains a cycle and cannot be serialized safely"
        )
    active.add(identity)
    try:
        total = 0
        if isinstance(value, dict):
            iterable = value.items()
            for key, item in iterable:
                total += _estimated_value_bytes(key, limit - total, active)
                total += _estimated_value_bytes(item, limit - total, active)
                if total > limit:
                    return total
            return total
        if isinstance(value, np.ndarray):
            # Object arrays store pointers in ``nbytes``; their referenced
            # values are what serializers actually expand.
            total = int(value.nbytes)
            iterable = value.flat
        elif isinstance(value, (list, tuple)):
            iterable = value
        else:
            return len(str(value).encode("utf-8"))
        for item in iterable:
            total += _estimated_value_bytes(item, limit - total, active)
            if total > limit:
                return total
        return total
    finally:
        active.remove(identity)


def _analysis_non_column_fields(result: dict[str, Any]) -> set[str]:
    """Return explicitly declared top-level metadata fields."""
    source_metadata = result.get("metadata")
    if source_metadata is None:
        return set()
    if not isinstance(source_metadata, dict):
        raise ValueError("Analysis result metadata must be a mapping for export")
    declared = source_metadata.get("non_column_fields", [])
    if declared is None:
        return set()
    if not isinstance(declared, (list, tuple)) or any(
        not isinstance(name, str) or not name for name in declared
    ):
        raise ValueError(
            "Analysis result metadata.non_column_fields must be a list of field names"
        )
    fields = set(declared)
    reserved = fields & ANALYSIS_RESERVED_FIELDS
    if reserved:
        raise ValueError(
            "Analysis result metadata.non_column_fields cannot include reserved field "
            f"'{sorted(reserved)[0]}'"
        )
    missing = fields - result.keys()
    if missing:
        raise ValueError(
            "Analysis result metadata.non_column_fields references unknown field "
            f"'{sorted(missing)[0]}'"
        )
    return fields


def _analysis_column_array(value: Any, key: str) -> np.ndarray:
    """Return a supported one-dimensional array for one analysis column.

    Timing estimators legitimately produce nullable floating-point sequences.
    NumPy otherwise turns those into object arrays, indistinguishable from
    nested arbitrary Python values.  Accept exactly ``None`` plus real scalar
    numbers and normalize missing entries to NaN; every other object value
    remains rejected.
    """
    array = np.asarray(value)
    if array.ndim != 1 or array.dtype.kind != "O":
        return array

    normalized: list[float] = []
    for item in array:
        if item is None:
            normalized.append(float("nan"))
            continue
        if isinstance(item, (bool, np.bool_)) or not isinstance(item, Real):
            raise ValueError(
                f"Analysis result column '{key}' contains nested or object values and "
                "cannot be losslessly represented by the supported export formats"
            )
        if isinstance(item, Integral) and abs(int(item)) > MAX_EXACT_CHANNEL:
            raise ValueError(
                f"Analysis result column '{key}' contains an integer that cannot be "
                "represented exactly by the nullable numeric export encoding"
            )
        normalized.append(float(item))
    return np.asarray(normalized, dtype=float)


def _validate_analysis_dtype(array: np.ndarray, key: str) -> None:
    """Reject dtypes that any advertised export format cannot encode."""
    if array.dtype.kind == "c":
        raise ValueError(
            f"Analysis result column '{key}' is complex; export separate real and "
            "imaginary columns for a lossless representation"
        )
    if array.dtype.kind in {"M", "m", "S", "V"}:
        raise ValueError(
            f"Analysis result column '{key}' uses {array.dtype}, which is not "
            "losslessly supported by every enabled export format"
        )
    if array.dtype.kind == "U" and any(not str(item).isascii() for item in array.flat):
        raise ValueError(
            f"Analysis result column '{key}' contains non-ASCII Unicode text, which "
            "is not losslessly supported by every enabled export format"
        )
    if array.dtype.kind == "O":
        raise ValueError(
            f"Analysis result column '{key}' contains nested or object values and "
            "cannot be losslessly represented by the supported export formats"
        )


def _validate_analysis_allocation(
    row_count: int, column_count: int, estimated_bytes: int
) -> None:
    if column_count > MAX_EXPORT_COLUMNS:
        raise ValueError(
            f"Analysis result has {column_count:,} columns; the export column cap is "
            f"{MAX_EXPORT_COLUMNS:,}"
        )
    cells = row_count * column_count
    if cells > MAX_EXPORT_CELLS:
        raise ValueError(
            f"Analysis result has {cells:,} cells; the export cell cap is "
            f"{MAX_EXPORT_CELLS:,}"
        )
    if estimated_bytes > MAX_EXPORT_ESTIMATED_BYTES:
        raise ValueError(
            f"Analysis result is estimated at {estimated_bytes / 1024**2:.1f} MiB; "
            "the export estimated-size cap is "
            f"{MAX_EXPORT_ESTIMATED_BYTES / 1024**2:.1f} MiB"
        )


def _analysis_result_row_count(result: Any) -> int:
    """Validate tabular shape and return rows before copying/building a Table."""
    if isinstance(result, Table):
        row_count = len(result)
        if row_count <= MAX_EXPORT_ROWS:
            _validate_analysis_allocation(row_count, len(result.colnames), 0)
            estimated_bytes = sum(
                int(np.asarray(result[name]).nbytes) for name in result.colnames
            ) + _estimated_value_bytes(dict(result.meta), MAX_EXPORT_ESTIMATED_BYTES)
            _validate_analysis_allocation(
                row_count, len(result.colnames), estimated_bytes
            )
            for name in result.colnames:
                array = _analysis_column_array(result[name], name)
                if array.ndim != 1:
                    raise ValueError(
                        f"Analysis result column '{name}' has {array.ndim} dimensions "
                        "and cannot be losslessly represented as one tabular column"
                    )
                _validate_analysis_dtype(array, name)
        return row_count
    if not isinstance(result, dict):
        raise ValueError("Analysis result is not a tabular mapping")

    non_column_fields = _analysis_non_column_fields(result)
    reserved = ANALYSIS_RESERVED_FIELDS | non_column_fields
    expected_length: int | None = None
    column_names: set[str] = set()
    estimated_bytes = _estimated_value_bytes(
        {key: result[key] for key in reserved if key in result},
        MAX_EXPORT_ESTIMATED_BYTES,
    )
    for key, value in result.items():
        if key in reserved:
            continue
        if isinstance(value, dict):
            raise ValueError(
                f"Analysis result field '{key}' is nested or non-tabular and cannot be "
                "losslessly represented by the supported export formats"
            )
        try:
            raw_length = None if isinstance(value, (str, bytes)) else len(value)
        except TypeError:
            raw_length = None
        if raw_length is not None and raw_length > MAX_EXPORT_ROWS:
            return raw_length

        value_bytes = _estimated_value_bytes(
            value, MAX_EXPORT_ESTIMATED_BYTES - estimated_bytes
        )
        if estimated_bytes + value_bytes > MAX_EXPORT_ESTIMATED_BYTES:
            _validate_analysis_allocation(
                raw_length or expected_length or 0,
                len(column_names) + 1,
                estimated_bytes + value_bytes,
            )

        array = _analysis_column_array(value, str(key))
        if array.ndim == 0:
            scalar = array.item()
            if isinstance(scalar, (complex, np.complexfloating)):
                raise ValueError(
                    f"Analysis result scalar '{key}' is complex; export explicit real "
                    "and imaginary values instead"
                )
            if scalar is None or isinstance(scalar, (str, bool, int, float)):
                estimated_bytes += _estimated_value_bytes(
                    scalar, MAX_EXPORT_ESTIMATED_BYTES - estimated_bytes
                )
                continue
            raise ValueError(
                f"Analysis result field '{key}' is nested or non-tabular and cannot be "
                "losslessly represented by the supported export formats"
            )
        if array.ndim != 1:
            raise ValueError(
                f"Analysis result field '{key}' has {array.ndim} dimensions and cannot "
                "be losslessly represented as one tabular column"
            )
        _validate_analysis_dtype(array, str(key))
        if expected_length is None:
            expected_length = len(array)
        elif len(array) != expected_length:
            raise ValueError(
                "Analysis result contains one-dimensional columns with different lengths"
            )
        column_names.add(str(key))
        estimated_bytes += max(value_bytes, int(array.nbytes))
        _validate_analysis_allocation(
            expected_length, len(column_names), estimated_bytes
        )

    if expected_length is None:
        raise ValueError(
            "Analysis result does not contain exportable one-dimensional columns"
        )
    source_metadata = result.get("metadata")
    if source_metadata is not None:
        assert isinstance(source_metadata, dict)
        units = source_metadata.get("units", {})
        if units is not None:
            if not isinstance(units, dict):
                raise ValueError("Analysis result metadata.units must be a mapping")
            for column_name, unit_label in units.items():
                if column_name not in column_names:
                    raise ValueError(
                        f"Analysis result metadata.units references unknown column "
                        f"'{column_name}'"
                    )
                try:
                    u.Unit(unit_label)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Analysis result column '{column_name}' has invalid unit "
                        f"'{unit_label}'"
                    ) from exc
    provenance = result.get("provenance")
    if provenance is not None and not isinstance(provenance, dict):
        raise ValueError("Analysis result provenance must be a mapping for export")
    _validate_analysis_allocation(expected_length, len(column_names), estimated_bytes)
    return expected_length


def _analysis_table(result: Any) -> Table:
    row_count = _analysis_result_row_count(result)
    if row_count > MAX_EXPORT_ROWS:
        raise ValueError(
            f"Analysis result has {row_count:,} rows; the export cap is "
            f"{MAX_EXPORT_ROWS:,}"
        )
    if isinstance(result, Table):
        table = result.copy(copy_data=True)
        for name in table.colnames:
            original = table[name]
            array = _analysis_column_array(original, name)
            if np.asarray(original).dtype.kind == "O" and array.dtype.kind != "O":
                replacement = np.ma.array(
                    array,
                    mask=np.ma.getmaskarray(np.ma.asarray(original)),
                    copy=False,
                )
                table.replace_column(name, replacement)
                if getattr(original, "unit", None) is not None:
                    table[name].unit = original.unit
        _reject_complex_columns(table)
        return table
    if not isinstance(result, dict):
        raise ValueError("Analysis result is not a tabular mapping")

    non_column_fields = _analysis_non_column_fields(result)
    reserved = ANALYSIS_RESERVED_FIELDS | non_column_fields
    columns: dict[str, np.ndarray] = {}
    metadata: dict[str, Any] = {}
    expected_length: int | None = None
    for key, value in result.items():
        if key in reserved:
            continue
        array = _analysis_column_array(value, str(key))
        if array.ndim == 0:
            scalar = array.item()
            if isinstance(scalar, (complex, np.complexfloating)):
                raise ValueError(
                    f"Analysis result scalar '{key}' is complex; export explicit real "
                    "and imaginary values instead"
                )
            if scalar is None or isinstance(scalar, (str, bool, int, float)):
                metadata[str(key)] = scalar
                continue
            raise ValueError(
                f"Analysis result field '{key}' is nested or non-tabular and cannot be "
                "losslessly represented by the supported export formats"
            )
        if array.ndim != 1:
            raise ValueError(
                f"Analysis result field '{key}' has {array.ndim} dimensions and cannot "
                "be losslessly represented as one tabular column"
            )
        _validate_analysis_dtype(array, str(key))
        if expected_length is None:
            expected_length = len(array)
        elif len(array) != expected_length:
            raise ValueError(
                "Analysis result contains one-dimensional columns with different lengths"
            )
        columns[str(key)] = value if getattr(value, "unit", None) is not None else array

    if expected_length is None or not columns:
        raise ValueError(
            "Analysis result does not contain exportable one-dimensional columns"
        )
    table = Table(columns)
    table.meta.update(metadata)
    for key in ANALYSIS_RESERVED_FIELDS:
        if key in result:
            table.meta[key] = result[key]
    for key in non_column_fields:
        table.meta[key] = result[key]

    source_metadata = result.get("metadata")
    if source_metadata is not None:
        if not isinstance(source_metadata, dict):
            raise ValueError("Analysis result metadata must be a mapping for export")
        units = source_metadata.get("units", {})
        if units is not None:
            if not isinstance(units, dict):
                raise ValueError("Analysis result metadata.units must be a mapping")
            for column_name, unit_label in units.items():
                if column_name not in table.colnames:
                    raise ValueError(
                        f"Analysis result metadata.units references unknown column "
                        f"'{column_name}'"
                    )
                try:
                    declared_unit = u.Unit(unit_label)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"Analysis result column '{column_name}' has invalid unit "
                        f"'{unit_label}'"
                    ) from exc
                existing_unit = table[column_name].unit
                if existing_unit is not None:
                    if not existing_unit.is_equivalent(declared_unit):
                        raise ValueError(
                            f"Analysis result column '{column_name}' unit "
                            f"'{existing_unit}' conflicts with metadata unit "
                            f"'{declared_unit}'"
                        )
                    table[column_name].convert_unit_to(declared_unit)
                else:
                    table[column_name].unit = declared_unit
    return table


def _reject_complex_columns(table: Table) -> None:
    """Fail closed on columns unsupported by every enabled export format."""
    for name in table.colnames:
        values = np.asarray(table[name])
        if values.ndim != 1:
            raise ValueError(
                f"Analysis result column '{name}' has {values.ndim} dimensions and "
                "cannot be losslessly represented as one tabular column"
            )
        _validate_analysis_dtype(values, name)


def _gti_array_for_export(obj: Any) -> np.ndarray | None:
    """Return only explicitly stored GTIs, including a zero-row GTI.

    Stingray's public ``gti`` property synthesizes and caches ``[time[0],
    time[-1]]`` when ``_gti`` is ``None``.  Export must not turn that implicit
    convenience interval into source data, so inspect the backing value first.
    """
    try:
        gti = obj._gti
    except AttributeError:
        gti = getattr(obj, "gti", None)
    if gti is None:
        return None
    return _normalize_gti_array(gti)


def _normalize_gti_array(gti: Any) -> np.ndarray:
    """Validate and copy one explicit seconds-based GTI value."""
    array = np.asarray(gti, dtype=float)
    if array.size == 0:
        return np.empty((0, 2), dtype=float)
    if array.ndim != 2 or array.shape[1] != 2:
        raise ValueError("Loaded object GTIs must have shape (n, 2) for export")
    bad = np.argwhere(~np.isfinite(array))
    if bad.size:
        row, column = (int(value) for value in bad[0])
        raise ValueError(f"Loaded object GTI[{row}, {column}] must be finite")
    return np.array(array, copy=True)


def _apply_known_units(
    table: Table,
    object_type: str,
    obj: Any,
    explicit_gti: np.ndarray | None,
) -> None:
    """Restore units that Stingray's ``to_astropy_table`` currently omits."""
    known_units: dict[str, u.UnitBase] = {}
    if object_type in {"event_list", "lightcurve"}:
        known_units["time"] = u.s
    if object_type == "event_list":
        known_units["energy"] = u.keV
    elif object_type == "lightcurve":
        known_units.update(
            {
                "counts": u.ct,
                "counts_err": u.ct,
                "countrate": u.ct / u.s,
                "countrate_err": u.ct / u.s,
                "bin_lo": u.s,
                "bin_hi": u.s,
                "dt": u.s,
                "bg_counts": u.ct,
                "bg_ratio": u.dimensionless_unscaled,
                "frac_exp": u.dimensionless_unscaled,
            }
        )

    for name in table.colnames:
        unit = known_units.get(name.lower())
        if unit is not None and getattr(table[name], "unit", None) is None:
            table[name].unit = unit

    if object_type in {"event_list", "lightcurve"}:
        table.meta.setdefault("time_unit", "s")
        dt = getattr(obj, "dt", None)
        if dt is not None:
            table.meta.setdefault("dt_unit", "s")
        if explicit_gti is not None:
            table.meta["gti"] = explicit_gti
            table.meta["gti_time_unit"] = "s"
            table.meta["gti_status"] = "present"
        else:
            table.meta.pop("gti", None)
            table.meta.pop("gti_time_unit", None)
            table.meta["gti_status"] = "missing"
    if object_type == "event_list" and "energy" in {
        name.lower() for name in table.colnames
    }:
        table.meta.setdefault("energy_unit", "keV")
    if object_type == "lightcurve":
        table.meta.setdefault("count_unit", "ct")
    rmf_provenance = getattr(obj, "rmf_conversion_provenance", None)
    if rmf_provenance is not None:
        if not isinstance(rmf_provenance, dict):
            raise ValueError("RMF conversion provenance must be a mapping for export")
        table.meta["rmf_conversion_provenance"] = rmf_provenance


def _object_row_count(obj: Any, object_type: str) -> int:
    if object_type == "event_list":
        values = getattr(obj, "time", None)
    elif object_type == "lightcurve":
        values = getattr(obj, "time", None)
    else:
        return _analysis_result_row_count(obj)
    if values is None:
        raise ValueError(f"Loaded {object_type.replace('_', ' ')} has no time array")
    _enforce_precopy_caps(
        obj,
        f"Loaded {object_type.replace('_', ' ')}",
        max_rows=MAX_EXPORT_ROWS,
        max_columns=MAX_EXPORT_COLUMNS,
        max_cells=MAX_EXPORT_CELLS,
        max_bytes=MAX_EXPORT_ESTIMATED_BYTES,
    )
    array = np.asarray(values)
    if array.ndim != 1:
        raise ValueError(
            f"Loaded {object_type.replace('_', ' ')} time must be one-dimensional"
        )
    row_count = len(array)
    return row_count


def _table_for_object(obj: Any, object_type: str) -> Table:
    if object_type == "analysis_result":
        table = _analysis_table(obj)
        explicit_gti = None
    else:
        # Capture the backing GTI before to_astropy_table accesses the public
        # property and can synthesize/cache an implicit interval.
        explicit_gti = _gti_array_for_export(obj)
        table = obj.to_astropy_table()
        if object_type == "lightcurve":
            for attribute in obj.array_attrs():
                values = getattr(obj, attribute, None)
                if values is None or attribute in table.colnames:
                    continue
                array = np.asarray(values)
                if array.ndim != 1 or len(array) != len(table):
                    raise ValueError(
                        f"Loaded Lightcurve {attribute} must be a one-dimensional "
                        "array aligned with time"
                    )
                table[attribute] = np.array(array, copy=True)
            dt = np.asarray(getattr(obj, "dt", None))
            if dt.ndim == 1:
                if len(dt) != len(table):
                    raise ValueError(
                        "Loaded Lightcurve per-bin dt must be aligned with time"
                    )
                table["dt"] = np.array(dt, copy=True)
    if not table.colnames:
        raise ValueError("Loaded object has no exportable columns")
    _reject_complex_columns(table)
    _apply_known_units(table, object_type, obj, explicit_gti)
    return table


def _fits_hdul_for_table(
    table: Table, object_type: str, obj: Any, warnings_out: list[str]
) -> fits.HDUList:
    """Build a generic, explicitly non-OGIP FITS table export."""
    primary = fits.PrimaryHDU()
    primary.header["CREATOR"] = "Stingray Explorer"
    extension_name = "EVENTS" if object_type == "event_list" else "DATA"
    # FITS headers cannot represent ndarray/dict metadata such as GTIs and
    # provenance.  Build the data HDU from columns only, then preserve GTIs in
    # their own extension below.  This also prevents Astropy from silently
    # dropping metadata while emitting process-global warnings.
    fits_table = table.copy(copy_data=True)
    fits_table.meta.clear()
    data_hdu = fits.table_to_hdu(fits_table)
    data_hdu.name = extension_name
    data_hdu.header["HDUCLASS"] = "STINGRAY"
    data_hdu.header["HDUCLAS1"] = "GENERIC"
    mjdref = getattr(obj, "mjdref", None)
    if mjdref is not None and np.isfinite(float(mjdref)):
        mjd_decimal = Decimal(str(mjdref))
        mjd_integer = int(mjd_decimal)
        # The single keyword keeps Stingray's explicit ``fmt='fits'`` generic
        # reader useful; the split cards retain the source components for
        # FITS-aware consumers.
        data_hdu.header["MJDREF"] = float(mjd_decimal)
        data_hdu.header["MJDREFI"] = mjd_integer
        data_hdu.header["MJDREFF"] = float(mjd_decimal - Decimal(mjd_integer))
    dt = getattr(obj, "dt", None)
    if dt is not None and np.asarray(dt).ndim == 0 and np.isfinite(float(dt)):
        data_hdu.header["TIMEDEL"] = float(dt)
    if any(name.lower() == "time" for name in table.colnames):
        data_hdu.header["TIMEUNIT"] = "s"
    data_hdu.header.add_history(
        "Generic Stingray/Astropy table export; this file is not an OGIP event product."
    )

    hdus: list[fits.hdu.base.ExtensionHDU | fits.PrimaryHDU] = [primary, data_hdu]
    if object_type in {"event_list", "lightcurve"}:
        if table.meta.get("gti_status") == "present":
            gti_array = _normalize_gti_array(table.meta["gti"])
            gti_table = Table(
                {
                    "START": u.Quantity(gti_array[:, 0], u.s),
                    "STOP": u.Quantity(gti_array[:, 1], u.s),
                }
            )
            gti_hdu = fits.table_to_hdu(gti_table)
            gti_hdu.name = "GTI"
            gti_hdu.header["HDUCLASS"] = "STINGRAY"
            gti_hdu.header["HDUCLAS1"] = "GTI"
            gti_hdu.header["TIMEUNIT"] = "s"
            for keyword in ("MJDREF", "MJDREFI", "MJDREFF"):
                if keyword in data_hdu.header:
                    gti_hdu.header[keyword] = data_hdu.header[keyword]
            hdus.append(gti_hdu)
    if table.meta:
        safe_metadata = json_safe(dict(table.meta), warnings_out, "metadata")
        encoded_metadata = json.dumps(
            safe_metadata,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        metadata_hdu = fits.BinTableHDU.from_columns(
            [
                fits.Column(
                    name="JSON",
                    format=f"{max(1, len(encoded_metadata))}A",
                    array=np.asarray([encoded_metadata]),
                )
            ],
            name="METADATA",
        )
        metadata_hdu.header["HDUCLASS"] = "STINGRAY"
        metadata_hdu.header["HDUCLAS1"] = "METADATA"
        metadata_hdu.header["SCHEMA"] = "stingray-explorer.metadata.v1"
        hdus.append(metadata_hdu)
    return fits.HDUList(hdus)


def _json_export_payload(
    table: Table,
    *,
    object_type: str,
    object_name: str,
    warnings_out: list[str],
) -> dict[str, Any]:
    columns: dict[str, Any] = {}
    for name in table.colnames:
        masked_values = np.ma.asarray(table[name])
        values = np.asarray(masked_values.data)
        masked = np.ma.getmaskarray(masked_values)
        masked_count = int(np.count_nonzero(masked))
        if masked_count:
            warnings_out.append(
                f"columns.{name} contains {masked_count:,} masked value(s); they are "
                "represented as null."
            )
        if values.dtype.kind == "f":
            finite = np.isfinite(values)
            nonfinite_count = int(np.count_nonzero(~finite))
            if nonfinite_count:
                warnings_out.append(
                    f"columns.{name} contains {nonfinite_count:,} non-finite value(s); "
                    "they are represented as null."
                )
            if nonfinite_count or masked_count:
                columns[name] = [
                    float(value) if is_finite and not is_masked else None
                    for value, is_finite, is_masked in zip(
                        values, finite, masked, strict=True
                    )
                ]
                continue
        safe_values = json_safe(values, warnings_out, f"columns.{name}")
        if masked_count:
            safe_values = [
                None if is_masked else value
                for value, is_masked in zip(safe_values, masked, strict=True)
            ]
        columns[name] = safe_values
    return {
        "schema": "stingray-explorer.tabular.v1",
        "object_type": object_type,
        "object_name": object_name,
        "row_count": len(table),
        "columns": columns,
        "column_units": {
            name: (
                str(table[name].unit)
                if getattr(table[name], "unit", None) is not None
                else None
            )
            for name in table.colnames
        },
        "metadata": json_safe(dict(table.meta), warnings_out, "metadata"),
    }


def _unlink_owned_entry(
    directory_descriptor: int, name: str, identity: tuple[int, int]
) -> None:
    """Remove only the exact regular entry reserved by this operation."""
    try:
        current = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == identity:
        os.unlink(name, dir_fd=directory_descriptor)


def _assert_new_destination_at(
    parent_descriptor: int, filename: str, display_path: Path
) -> None:
    """Reject an existing entry relative to the pinned selected directory."""
    try:
        os.stat(filename, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return
    raise FileExistsError(f"Destination already exists: {display_path}")


def _rmdir_owned_entry(
    parent_descriptor: int, name: str, identity: tuple[int, int]
) -> bool:
    """Remove a staging directory only while its pinned identity still matches."""
    try:
        current = os.stat(
            name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return True
    if not stat.S_ISDIR(current.st_mode):
        return False
    if (current.st_dev, current.st_ino) != identity:
        return False
    os.rmdir(name, dir_fd=parent_descriptor)
    return True


class IOUtilityService(BaseService):
    """General I/O Utilities service with exact native-file grant checks."""

    def inspect_file(self, file_path: str, file_grant: str) -> dict[str, Any]:
        try:
            with open_verified_read_grant(file_path, file_grant) as granted:
                path = granted.path
                size = validate_file_size(
                    granted.stream, MAX_FITS_INSPECT_BYTES, "Selected file"
                )
                suffix = path.suffix.lower()
                granted.stream.seek(0)
                stream = granted.stream
                magic = stream.read(30)
                looks_like_fits = magic.startswith(b"SIMPLE  =")

                base_data: dict[str, Any] = {
                    "path": str(path),
                    "filename": path.name,
                    "extension": suffix or None,
                    "size_bytes": size,
                    "supported": False,
                    "detected_type": "unknown",
                    "hdus": [],
                    "warnings": [],
                }
                if suffix not in FITS_EXTENSIONS and not looks_like_fits:
                    base_data["warnings"] = [
                        "This inspector currently supports FITS-family files only; use Data "
                        "Ingestion for loading other tabular files."
                    ]
                    base_data["provenance"] = operation_provenance(
                        "inspect_file",
                        input_source={"kind": "native_file", "path": str(path)},
                        parameters={"header_only": True},
                    )
                    return self.create_result(
                        success=True,
                        data=base_data,
                        message=f"'{path.name}' is not a supported inspection format",
                        warnings=base_data["warnings"],
                    )

                hdus, warning_messages, detected_type = _inspect_fits(granted.stream)
                base_data.update(
                    {
                        "supported": True,
                        "detected_type": detected_type,
                        "hdus": hdus,
                        "warnings": warning_messages,
                        "provenance": operation_provenance(
                            "inspect_file",
                            input_source={"kind": "native_file", "path": str(path)},
                            parameters={"header_only": True, "lazy_data": True},
                        ),
                    }
                )
                return self.create_result(
                    success=True,
                    data=base_data,
                    message=f"Inspected {len(hdus)} FITS HDU(s) in '{path.name}'",
                    warnings=warning_messages,
                )
        except Exception as exception:
            return self.handle_error(
                exception, "Inspecting selected file", file=file_path
            )

    def inspect_rmf(self, rmf_path: str, rmf_grant: str) -> dict[str, Any]:
        try:
            with open_verified_read_grant(rmf_path, rmf_grant) as granted:
                path = granted.path
                file_size = granted.size_bytes
                channels, e_min, e_max, unit, warning_messages = _load_valid_rmf(
                    granted.stream, require_energy_unit=False
                )
            midpoints = _energy_midpoints(e_min, e_max)
            order = np.argsort(channels)
            sorted_channels = channels[order]
            gaps = np.diff(sorted_channels) != 1
            if np.any(gaps):
                warning_messages.append(
                    "RMF channels are not contiguous; conversion remains available only for "
                    "exact listed channel values."
                )
            preview_count = min(len(channels), MAX_EVENT_PREVIEW_ROWS)
            rows = [
                {
                    "channel": int(channels[index]),
                    "energy_min": float(e_min[index]),
                    "energy_max": float(e_max[index]),
                    "energy_midpoint": float(midpoints[index]),
                }
                for index in range(preview_count)
            ]
            data = {
                "path": str(path),
                "filename": path.name,
                "size_bytes": file_size,
                "channel_count": len(channels),
                "channel_min": int(np.min(channels)),
                "channel_max": int(np.max(channels)),
                "energy_min": float(np.min(e_min)),
                "energy_max": float(np.max(e_max)),
                "energy_unit": unit,
                "conversion_supported": unit is not None,
                "contiguous_channels": not bool(np.any(gaps)),
                "preview_rows": rows,
                "preview_truncated": preview_count < len(channels),
                "warnings": warning_messages,
                "provenance": operation_provenance(
                    "inspect_rmf",
                    input_source={"kind": "native_rmf", "path": str(path)},
                    parameters={"ebounds_only": True},
                    calibrated=True,
                ),
            }
            return self.create_result(
                success=True,
                data=data,
                message=f"Inspected {len(channels):,} RMF channel(s)",
                warnings=warning_messages,
            )
        except Exception as exception:
            return self.handle_error(exception, "Inspecting RMF", file=rmf_path)

    def convert_pi_values(
        self,
        pi_values: Any,
        rmf_path: str,
        rmf_grant: str,
    ) -> dict[str, Any]:
        try:
            with open_verified_read_grant(rmf_path, rmf_grant) as granted:
                path = granted.path
                pis, energies, unit, warning_messages = _calibrate_pi(
                    pi_values, granted.stream, maximum=MAX_ARRAY_INPUT
                )
            rows = [
                {"index": index, "pi": int(pi), "energy": float(energy)}
                for index, (pi, energy) in enumerate(zip(pis, energies, strict=True))
            ]
            data = {
                "rows": rows,
                "count": len(rows),
                "energy_unit": unit,
                "plot": bounded_plot_preview(pis, energies),
                "warnings": warning_messages,
                "provenance": operation_provenance(
                    "rmf_pi_to_energy",
                    input_source={"kind": "pasted_pi", "count": len(pis)},
                    parameters={"rmf_path": str(path)},
                    calibrated=True,
                    energy_unit=unit,
                ),
            }
            return self.create_result(
                success=True,
                data=data,
                message=f"Converted {len(pis):,} PI value(s) to calibrated energy",
                warnings=warning_messages,
            )
        except Exception as exception:
            return self.handle_error(
                exception, "Converting PI values with RMF", file=rmf_path
            )

    def convert_event_list(
        self,
        event_list_name: str,
        rmf_path: str,
        rmf_grant: str,
        save_as: str | None = None,
    ) -> dict[str, Any]:
        try:
            with open_verified_read_grant(rmf_path, rmf_grant) as granted:
                path = granted.path
                if save_as is not None:
                    name_error = validate_derived_name(save_as)
                    if name_error:
                        raise ValueError(name_error)
                source = self.state.copy_event_data(
                    event_list_name,
                    max_events=MAX_EXPORT_ROWS,
                    max_columns=MAX_EXPORT_COLUMNS,
                    max_cells=MAX_EXPORT_CELLS,
                    max_bytes=MAX_EXPORT_ESTIMATED_BYTES,
                )
                if source is None:
                    raise ValueError(f"EventList '{event_list_name}' not found")
                source_pi = getattr(source, "pi", None)
                if source_pi is None:
                    raise ValueError(
                        f"EventList '{event_list_name}' has no PI channel data"
                    )
                if getattr(source, "time", None) is None or len(source.time) != len(
                    source_pi
                ):
                    raise ValueError(
                        "EventList PI and time arrays must have the same length"
                    )

                pis, energies, unit, warning_messages = _calibrate_pi(
                    source_pi, granted.stream, maximum=MAX_EXPORT_ROWS
                )
            # ``source`` is already a StateManager deep copy.  Only this
            # detached object receives energy/provenance attributes.
            # The deep copy already contains the source PI array byte-for-byte;
            # keep it untouched (including dtype) and add only calibrated energy.
            source.energy = np.array(energies, copy=True)
            provenance = operation_provenance(
                "rmf_event_list_pi_to_energy",
                input_source={"kind": "loaded_event_list", "name": event_list_name},
                parameters={"rmf_path": str(path), "save_as": save_as},
                calibrated=True,
                energy_unit=unit,
            )
            source.rmf_conversion_provenance = provenance

            saved = False
            if save_as is not None:
                if not self.state.add_event_data_if_absent(save_as, source):
                    raise ValueError(f"EventList name '{save_as}' already exists")
                saved = True

            preview_count = min(len(pis), MAX_EVENT_PREVIEW_ROWS)
            preview_rows = [
                {
                    "index": index,
                    "pi": int(pis[index]),
                    "energy": float(energies[index]),
                }
                for index in range(preview_count)
            ]
            data = {
                "source_name": event_list_name,
                "saved": saved,
                "saved_name": save_as if saved else None,
                "event_count": len(pis),
                "energy_unit": unit,
                "preview_rows": preview_rows,
                "preview_truncated": preview_count < len(pis),
                "plot": bounded_plot_preview(pis, energies),
                "pi_preserved": True,
                "warnings": warning_messages,
                "provenance": provenance,
            }
            action = f"saved as '{save_as}'" if saved else "previewed without saving"
            return self.create_result(
                success=True,
                data=data,
                message=f"Calibrated {len(pis):,} EventList PI value(s); {action}",
                warnings=warning_messages,
            )
        except Exception as exception:
            return self.handle_error(
                exception,
                "Converting EventList PI with RMF",
                event_list=event_list_name,
                file=rmf_path,
            )

    @staticmethod
    def _format_capabilities(object_type: str) -> dict[str, dict[str, Any]]:
        common = {
            "csv": {
                "supported": True,
                "notes": (
                    "Tabular values only; column units, metadata, and GTIs are not "
                    "preserved."
                ),
            },
            "ecsv": {
                "supported": True,
                "notes": "Astropy ECSV table with serializable metadata.",
            },
            "json": {
                "supported": True,
                "notes": "Strict JSON tabular envelope; non-finite values become null with warnings.",
            },
            "fits": {
                "supported": True,
                "notes": "Generic FITS binary table, not an OGIP/HEASoft event product.",
            },
        }
        if object_type in {"event_list", "lightcurve"}:
            common["fits"]["notes"] += (
                " A separate GTI extension is included when available."
            )
        return common

    def list_exportable_objects(self) -> dict[str, Any]:
        try:
            objects: list[dict[str, Any]] = []
            sources = (
                ("event_list", self.state.get_event_data()),
                ("lightcurve", self.state.get_lightcurve_data()),
                ("analysis_result", self.state.get_analysis_result()),
            )
            for object_type, entries in sources:
                for name, obj in entries:
                    reason: str | None = None
                    try:
                        row_count = _object_row_count(obj, object_type)
                        if row_count > MAX_EXPORT_ROWS:
                            reason = (
                                f"Object has {row_count:,} rows; the export cap is "
                                f"{MAX_EXPORT_ROWS:,}"
                            )
                    except Exception as exception:
                        row_count = None
                        reason = str(exception)
                    objects.append(
                        {
                            "object_type": object_type,
                            "name": name,
                            "row_count": row_count,
                            "exportable": reason is None,
                            "formats": list(EXPORT_EXTENSIONS)
                            if reason is None
                            else [],
                            "reason": reason,
                        }
                    )

            matrix = {
                object_type: self._format_capabilities(object_type)
                for object_type in sorted(EXPORT_OBJECT_TYPES)
            }
            data = {
                "objects": objects,
                "capability_matrix": matrix,
                "format_allowlist": list(EXPORT_EXTENSIONS),
                "excluded_formats": {
                    "pickle": "Unsafe deserialization format; intentionally unsupported.",
                    "hdf5": "Not enabled because this Utilities export path has not verified every object round trip.",
                },
                "row_cap": MAX_EXPORT_ROWS,
                "provenance": operation_provenance(
                    "list_exportable_objects",
                    input_source={"kind": "application_state"},
                    parameters={},
                ),
            }
            return self.create_result(
                success=True,
                data=data,
                message=f"Found {sum(item['exportable'] for item in objects)} exportable object(s)",
            )
        except Exception as exception:
            return self.handle_error(exception, "Listing exportable objects")

    def _copy_export_object(self, object_type: str, object_name: str) -> Any:
        if object_type == "event_list":
            result = self.state.copy_event_data(
                object_name,
                max_events=MAX_EXPORT_ROWS,
                max_columns=MAX_EXPORT_COLUMNS,
                max_cells=MAX_EXPORT_CELLS,
                max_bytes=MAX_EXPORT_ESTIMATED_BYTES,
            )
        elif object_type == "lightcurve":
            result = self.state.copy_lightcurve_data(
                object_name,
                max_points=MAX_EXPORT_ROWS,
                max_columns=MAX_EXPORT_COLUMNS,
                max_cells=MAX_EXPORT_CELLS,
                max_bytes=MAX_EXPORT_ESTIMATED_BYTES,
            )
        elif object_type == "analysis_result":
            result = self.state.copy_analysis_result(
                object_name,
                max_rows=MAX_EXPORT_ROWS,
                max_columns=MAX_EXPORT_COLUMNS,
                max_cells=MAX_EXPORT_CELLS,
                max_bytes=MAX_EXPORT_ESTIMATED_BYTES,
            )
        else:
            raise ValueError(
                "object_type must be one of: event_list, lightcurve, analysis_result"
            )
        if result is None:
            label = object_type.replace("_", " ").title()
            raise ValueError(f"{label} '{object_name}' not found")
        return result

    def export_object(
        self,
        object_type: str,
        object_name: str,
        export_format: str,
        destination_path: str,
        destination_grant: str,
    ) -> dict[str, Any]:
        context_stack = ExitStack()
        parent_descriptor = -1
        staging_descriptor = -1
        staging_name: str | None = None
        staging_identity: tuple[int, int] | None = None
        artifact_name: str | None = None
        reserved_identity: tuple[int, int] | None = None
        warning_messages: list[str] = []
        try:
            destination = context_stack.enter_context(
                open_verified_write_grant(
                    destination_path,
                    destination_grant,
                )
            )
            path = destination.path
            parent_descriptor = destination.parent_descriptor
            destination_name = destination.filename
            if destination_name in {"", ".", ".."} or os.sep in destination_name:
                raise ValueError("The selected destination filename is invalid")
            if os.altsep is not None and os.altsep in destination_name:
                raise ValueError("The selected destination filename is invalid")

            verified_path = verify_file_grant(
                destination_path,
                destination_grant,
                access="write",
                must_exist=False,
            )
            if verified_path != path:
                raise PermissionError("The selected destination path changed")
            requested_format = export_format.lower().strip()
            if requested_format not in EXPORT_EXTENSIONS:
                raise ValueError(
                    "format must be one of: " + ", ".join(EXPORT_EXTENSIONS)
                )
            expected_extension = EXPORT_EXTENSIONS[requested_format]
            if path.suffix.lower() != expected_extension:
                raise ValueError(
                    f"{requested_format.upper()} export requires the exact "
                    f"'{expected_extension}' filename extension"
                )
            _assert_new_destination_at(parent_descriptor, destination_name, path)
            obj = self._copy_export_object(object_type, object_name)
            row_count = _object_row_count(obj, object_type)
            if row_count > MAX_EXPORT_ROWS:
                raise ValueError(
                    f"Object has {row_count:,} rows; the export cap is {MAX_EXPORT_ROWS:,}"
                )
            table = _table_for_object(obj, object_type)
            if len(table) != row_count:
                raise ValueError(
                    "Export table row count does not match the loaded object"
                )

            # Write and verify in a private same-directory staging area.  The
            # user-visible destination is published only after verification by
            # an atomic hard link that cannot overwrite an existing path.
            for _ in range(10):
                candidate_name = f".stingray-export-{secrets.token_hex(16)}"
                try:
                    os.mkdir(
                        candidate_name,
                        0o700,
                        dir_fd=parent_descriptor,
                    )
                except FileExistsError:
                    continue
                staging_name = candidate_name
                break
            else:
                raise FileExistsError("Could not reserve a private export staging area")

            directory_flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                directory_flags |= os.O_CLOEXEC
            if hasattr(os, "O_DIRECTORY"):
                directory_flags |= os.O_DIRECTORY
            if hasattr(os, "O_NOFOLLOW"):
                directory_flags |= os.O_NOFOLLOW
            staging_descriptor = os.open(
                staging_name,
                directory_flags,
                dir_fd=parent_descriptor,
            )
            staging_stat = os.fstat(staging_descriptor)
            if not stat.S_ISDIR(staging_stat.st_mode):
                raise PermissionError("The private export staging area was replaced")
            staging_identity = (staging_stat.st_dev, staging_stat.st_ino)

            artifact_name = f"artifact{expected_extension}"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(
                artifact_name,
                flags,
                0o600,
                dir_fd=staging_descriptor,
            )
            try:
                reserved_stat = os.fstat(descriptor)
            except Exception:
                os.close(descriptor)
                raise
            reserved_identity = (reserved_stat.st_dev, reserved_stat.st_ino)
            if (
                object_type in {"event_list", "lightcurve"}
                and table.meta.get("gti_status") == "missing"
            ):
                warning_messages.append(
                    "The source has no explicit GTI; no GTI was synthesized for export."
                )
            if requested_format == "csv":
                warning_messages.append(
                    "CSV stores tabular values only; column units, object metadata, and "
                    "GTIs are not preserved."
                )
            elif requested_format == "fits":
                warning_messages.append(
                    "FITS output is a generic binary-table export, not an OGIP/HEASoft "
                    "event product, and may not preserve every object metadata field."
                )

            mode = "wb" if requested_format == "fits" else "w"
            try:
                output_stream = os.fdopen(
                    descriptor, mode, encoding=None if mode == "wb" else "utf-8"
                )
            except Exception:
                os.close(descriptor)
                raise
            with output_stream as stream:
                with collect_warnings(warning_messages):
                    if requested_format == "csv":
                        table.write(stream, format="ascii.csv", overwrite=False)
                    elif requested_format == "ecsv":
                        table.write(stream, format="ascii.ecsv", overwrite=False)
                    elif requested_format == "fits":
                        with _fits_hdul_for_table(
                            table, object_type, obj, warning_messages
                        ) as hdul:
                            hdul.writeto(stream, checksum=True)
                    else:
                        payload = _json_export_payload(
                            table,
                            object_type=object_type,
                            object_name=object_name,
                            warnings_out=warning_messages,
                        )
                        json.dump(
                            payload,
                            stream,
                            allow_nan=False,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                stream.flush()
                os.fsync(stream.fileno())

            verified_path = verify_file_grant(
                destination_path,
                destination_grant,
                access="write",
                must_exist=False,
            )
            if verified_path != path:
                raise PermissionError(
                    "Written artifact path changed during verification"
                )
            before_reopen = os.stat(
                artifact_name,
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(before_reopen.st_mode)
                or (before_reopen.st_dev, before_reopen.st_ino) != reserved_identity
            ):
                raise PermissionError(
                    "Export destination was replaced before verification"
                )

            read_flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                read_flags |= os.O_NOFOLLOW
            read_descriptor = os.open(
                artifact_name,
                read_flags,
                dir_fd=staging_descriptor,
            )
            try:
                read_stat = os.fstat(read_descriptor)
            except Exception:
                os.close(read_descriptor)
                raise
            if (read_stat.st_dev, read_stat.st_ino) != reserved_identity:
                os.close(read_descriptor)
                raise PermissionError(
                    "Export destination was replaced before verification"
                )

            # Astropy's ASCII registry expects a binary-readable file object;
            # JSON's standard decoder expects text.
            read_mode = "r" if requested_format == "json" else "rb"
            try:
                reopened_file = os.fdopen(
                    read_descriptor,
                    read_mode,
                    encoding=None if read_mode == "rb" else "utf-8",
                )
            except Exception:
                os.close(read_descriptor)
                raise
            with reopened_file as reopened_stream:
                if requested_format in {"csv", "ecsv"}:
                    reopened = Table.read(
                        reopened_stream,
                        format=(
                            "ascii.csv" if requested_format == "csv" else "ascii.ecsv"
                        ),
                    )
                    reopened_rows = len(reopened)
                elif requested_format == "fits":
                    with fits.open(
                        reopened_stream, checksum=True, memmap=False
                    ) as hdul:
                        hdul.verify("exception")
                        for hdu in hdul:
                            if (
                                "CHECKSUM" not in hdu.header
                                or hdu.verify_checksum() != 1
                            ):
                                raise ValueError("FITS CHECKSUM verification failed")
                            if "DATASUM" not in hdu.header or hdu.verify_datasum() != 1:
                                raise ValueError("FITS DATASUM verification failed")
                        reopened_rows = int(hdul[1].header.get("NAXIS2", 0) or 0)
                        if object_type in {"event_list", "lightcurve"}:
                            if table.meta.get("gti_status") == "present":
                                expected_gti = _normalize_gti_array(table.meta["gti"])
                                if "GTI" not in hdul:
                                    raise ValueError(
                                        "FITS verification could not find the GTI extension"
                                    )
                                actual_gti_rows = int(
                                    hdul["GTI"].header.get("NAXIS2", -1)
                                )
                                if actual_gti_rows != len(expected_gti):
                                    raise ValueError(
                                        "FITS GTI verification found an unexpected row count"
                                    )
                        if table.meta and "METADATA" not in hdul:
                            raise ValueError(
                                "FITS verification could not find object metadata"
                            )
                else:
                    reopened_json = json.load(reopened_stream)
                    if reopened_json.get("schema") != "stingray-explorer.tabular.v1":
                        raise ValueError("JSON verification found an unexpected schema")
                    reopened_rows = int(reopened_json.get("row_count", -1))
            if reopened_rows != row_count:
                raise ValueError(
                    f"Reopened artifact has {reopened_rows:,} rows; expected {row_count:,}"
                )

            final_stat = os.stat(
                artifact_name,
                dir_fd=staging_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(final_stat.st_mode)
                or (final_stat.st_dev, final_stat.st_ino) != reserved_identity
            ):
                raise PermissionError(
                    "Export destination was replaced during verification"
                )
            byte_size = final_stat.st_size
            if byte_size < 1:
                raise ValueError("Written artifact is empty")

            # `link` publishes the already verified inode atomically and fails
            # if a destination appeared after the initial non-overwrite check.
            verified_path = verify_file_grant(
                destination_path,
                destination_grant,
                access="write",
                must_exist=False,
            )
            if verified_path != path:
                raise PermissionError("The selected destination path changed")
            try:
                os.link(
                    artifact_name,
                    destination_name,
                    src_dir_fd=staging_descriptor,
                    dst_dir_fd=parent_descriptor,
                    follow_symlinks=False,
                )
            except FileExistsError as exc:
                raise FileExistsError(f"Destination already exists: {path}") from exc
            published_stat = os.stat(
                destination_name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(published_stat.st_mode)
                or (published_stat.st_dev, published_stat.st_ino) != reserved_identity
            ):
                raise PermissionError(
                    "Export destination changed during atomic publication"
                )

            # Cleanup touches only the random private staging path, never the
            # user-visible destination.  If its identity changed, retain it
            # and report a warning instead of deleting an unrelated file.
            try:
                _unlink_owned_entry(
                    staging_descriptor,
                    artifact_name,
                    reserved_identity,
                )
                os.close(staging_descriptor)
                staging_descriptor = -1
                if not _rmdir_owned_entry(
                    parent_descriptor,
                    staging_name,
                    staging_identity,
                ):
                    raise OSError("private staging directory identity changed")
            except OSError as cleanup_error:
                warning_messages.append(
                    "Export succeeded, but its private staging artifact could not be "
                    f"removed safely ({cleanup_error})."
                )
            artifact_name = None
            reserved_identity = None
            staging_name = None
            staging_identity = None
            data = {
                "path": str(path),
                "bytes": byte_size,
                "format": requested_format,
                "row_count": row_count,
                "object_type": object_type,
                "object_name": object_name,
                "verified": True,
                "warnings": warning_messages,
                "provenance": operation_provenance(
                    "export_loaded_object",
                    input_source={"kind": object_type, "name": object_name},
                    parameters={
                        "format": requested_format,
                        "destination_path": str(path),
                        "exclusive_non_overwrite": True,
                        "reopen_verified": True,
                    },
                ),
            }
            return self.create_result(
                success=True,
                data=data,
                message=f"Exported {row_count:,} row(s) to '{path.name}'",
                warnings=warning_messages,
            )
        except Exception as exception:
            return self.handle_error(
                exception,
                "Exporting loaded object",
                object_type=object_type,
                object_name=object_name,
                destination=destination_path,
            )
        finally:
            if (
                staging_descriptor >= 0
                and artifact_name is not None
                and reserved_identity is not None
            ):
                try:
                    _unlink_owned_entry(
                        staging_descriptor,
                        artifact_name,
                        reserved_identity,
                    )
                except OSError:
                    pass
            if staging_descriptor >= 0:
                try:
                    os.close(staging_descriptor)
                except OSError:
                    pass
            if (
                staging_name is not None
                and staging_identity is not None
                and parent_descriptor >= 0
            ):
                try:
                    _rmdir_owned_entry(
                        parent_descriptor,
                        staging_name,
                        staging_identity,
                    )
                except OSError:
                    # Never broaden cleanup or delete an unexpected entry.
                    pass
            context_stack.close()
