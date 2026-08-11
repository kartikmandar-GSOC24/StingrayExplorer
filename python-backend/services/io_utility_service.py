"""Safe file inspection, RMF calibration, and tabular export utilities.

The existing data-ingestion service remains the only way to load arbitrary
files into application state.  This service only inspects explicitly selected
files, derives calibrated copies of loaded EventLists, and exports objects that
are already in state.
"""

from __future__ import annotations

import copy
import importlib
import json
import math
import os
from collections.abc import Iterable, Mapping, Sized
from contextlib import ExitStack
from decimal import Decimal, InvalidOperation
from itertools import islice
from numbers import Integral, Real
from typing import Any, BinaryIO

import numpy as np
from astropy import units as u
from astropy.io import fits
from astropy.table import Column, MaskedColumn, Table
from astropy.table import meta as astropy_table_meta
from astropy.table import serialize as astropy_table_serialize
from astropy.utils.data_info import serialize_context_as
from astropy.utils.masked import Masked
from stingray.io import high_precision_keyword_read, pi_to_energy, read_rmf

from .analysis_helpers import collect_warnings
from .base_service import BaseService
from .secure_publication import open_secure_publication
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
    operation_provenance,
    validate_derived_name,
    validate_file_size,
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
    "hdf5": ".hdf5",
}
EXPORT_OBJECT_TYPES = {"event_list", "lightcurve", "analysis_result"}

HDF5_SCHEMA = "stingray-explorer.hdf5.v1"
HDF5_GROUP_PATH = "stingray_explorer"
HDF5_TABLE_PATH = f"{HDF5_GROUP_PATH}/table"
HDF5_MANIFEST_PATH = f"{HDF5_GROUP_PATH}/column_manifest"
HDF5_ASTROPY_METADATA_PATH = f"{HDF5_TABLE_PATH}.__table_column_meta__"
HDF5_EXTENSION = ".hdf5"
HDF5_MANIFEST_MAX_BYTES = 2 * 1024**2
HDF5_UNAVAILABLE_REASON = (
    "HDF5 export requires the optional 'h5py' runtime dependency, which is not "
    "available."
)
HDF5_SUPPORTED_COLUMN_KINDS = {"b", "i", "u", "f", "U"}
HDF5_SUPPORTED_ITEM_SIZES = {
    "b": {1},
    "i": {1, 2, 4, 8},
    "u": {1, 2, 4, 8},
    "f": {2, 4, 8},
}
HDF5_VERIFICATION_CHECKS = [
    "schema_and_layout",
    "row_count",
    "ordered_columns",
    "logical_dtypes",
    "masks_and_values",
    "units",
    "column_metadata_and_fill_values",
    "object_metadata_gti_and_provenance",
]

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
ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE = "_stingray_hdf5_fill_reason"


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
    if value is None or isinstance(value, (bool, float, np.number)):
        return 32
    if type(value) is int:
        bit_length = abs(value).bit_length()
        decimal_bytes = 1 + (bit_length * 30_103) // 100_000
        if value < 0:
            decimal_bytes += 1
        return max(32, int(value.__sizeof__()), decimal_bytes)
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
    numbers and normalize ``None`` to a mask.  An unmasked NaN remains an
    unmasked NaN, so formats capable of representing masks can preserve the
    scientific distinction between missing and non-finite values.
    """
    source_is_masked = isinstance(value, (MaskedColumn, Masked)) or np.ma.isMaskedArray(
        value
    )
    masked_value = np.ma.asarray(value)
    array = np.asarray(masked_value.data)
    if array.ndim != 1 or array.dtype.kind != "O":
        if array.ndim == 1 and source_is_masked:
            return np.ma.array(
                array,
                mask=np.ma.getmaskarray(masked_value),
                copy=False,
            )
        return array

    normalized: list[float] = []
    mask = np.ma.getmaskarray(masked_value).copy()
    added_missing_mask = False
    for index, item in enumerate(array):
        if mask[index]:
            # A masked payload is scientifically absent.  Do not reject a
            # valid nullable numeric column merely because its hidden storage
            # uses an arbitrary object sentinel.
            normalized.append(float("nan"))
            continue
        if item is None:
            normalized.append(float("nan"))
            mask[index] = True
            added_missing_mask = True
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
    normalized_array = np.asarray(normalized, dtype=float)
    if source_is_masked or added_missing_mask:
        return np.ma.array(normalized_array, mask=mask, copy=False)
    return normalized_array


def _normalized_analysis_column(
    original: Any,
    normalized: np.ndarray,
    name: str,
) -> Column:
    """Build a normalized column without discarding masks or display metadata."""
    values = np.ma.asarray(normalized)
    data = np.asarray(values.data)
    masked = np.ma.isMaskedArray(normalized)
    source_is_masked = isinstance(
        original, (MaskedColumn, Masked)
    ) or np.ma.isMaskedArray(original)
    common = {
        "name": name,
        "unit": getattr(original, "unit", None),
        "format": getattr(original, "format", None),
        "description": getattr(original, "description", None),
        "meta": copy.deepcopy(getattr(original, "meta", {})),
        "copy": False,
    }
    if not masked:
        return Column(data, **common)

    fill_value = np.ma.default_fill_value(data)
    fill_reason: str | None = None
    if source_is_masked and hasattr(original, "fill_value"):
        try:
            fill_value = (
                np.asarray(getattr(original, "fill_value"), dtype=data.dtype)
                .reshape(())
                .item()
            )
        except (TypeError, ValueError, OverflowError):
            fill_reason = (
                f"HDF5 export cannot preserve column '{name}' custom fill value "
                "after nullable numeric normalization"
            )
    replacement = MaskedColumn(
        data,
        mask=np.ma.getmaskarray(values),
        fill_value=fill_value,
        **common,
    )
    if fill_reason is not None:
        setattr(replacement, ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE, fill_reason)
    return replacement


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
    for key in result:
        if not isinstance(key, str):
            raise ValueError(
                "Analysis result field names must be text; found a field name "
                f"of type {type(key).__name__}"
            )

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
            if isinstance(value, u.Quantity) and value.isscalar:
                estimated_bytes += value_bytes
                continue
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
        hdf5_fill_reasons: dict[str, str] = {}
        for name in table.colnames:
            original = table[name]
            array = _analysis_column_array(original, name)
            if np.asarray(original).dtype.kind == "O" and array.dtype.kind != "O":
                replacement = _normalized_analysis_column(original, array, name)
                fill_reason = getattr(
                    replacement, ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE, None
                )
                if fill_reason is not None:
                    hdf5_fill_reasons[name] = str(fill_reason)
                table.replace_column(
                    name,
                    replacement,
                )
        _reject_complex_columns(table)
        if hdf5_fill_reasons:
            setattr(
                table,
                ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE,
                hdf5_fill_reasons,
            )
        return table
    if not isinstance(result, dict):
        raise ValueError("Analysis result is not a tabular mapping")

    non_column_fields = _analysis_non_column_fields(result)
    reserved = ANALYSIS_RESERVED_FIELDS | non_column_fields
    columns: dict[str, Any] = {}
    hdf5_fill_reasons: dict[str, str] = {}
    metadata: dict[str, Any] = {}
    expected_length: int | None = None
    for key, value in result.items():
        if key in reserved:
            continue
        array = _analysis_column_array(value, str(key))
        if array.ndim == 0:
            if isinstance(value, u.Quantity) and value.isscalar:
                metadata[str(key)] = value.copy()
                continue
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
        normalized_column = _normalized_analysis_column(value, array, str(key))
        fill_reason = getattr(
            normalized_column, ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE, None
        )
        if fill_reason is not None:
            hdf5_fill_reasons[str(key)] = str(fill_reason)
        columns[str(key)] = normalized_column

    if expected_length is None or not columns:
        raise ValueError(
            "Analysis result does not contain exportable one-dimensional columns"
        )
    table = Table(columns)
    if hdf5_fill_reasons:
        setattr(
            table,
            ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE,
            hdf5_fill_reasons,
        )
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


def _gti_array_for_export(
    obj: Any, *, preserve_dtype: bool = False
) -> np.ndarray | None:
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
    return _normalize_gti_array(gti, preserve_dtype=preserve_dtype)


def _normalize_gti_array(gti: Any, *, preserve_dtype: bool = False) -> np.ndarray:
    """Validate and copy one explicit seconds-based GTI value."""
    array = np.asarray(gti)
    if not preserve_dtype:
        array = np.asarray(array, dtype=float)
    elif array.dtype.kind not in {"f", "i", "u"}:
        try:
            array = np.asarray(gti, dtype=np.longdouble)
        except (TypeError, ValueError, OverflowError) as exception:
            raise ValueError(
                "Loaded object GTIs must be numeric for export"
            ) from exception
    if array.size == 0:
        return np.empty(
            (0, 2),
            dtype=array.dtype if preserve_dtype else float,
        )
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
        row_count = _analysis_result_row_count(obj)
        if row_count > MAX_EXPORT_ROWS:
            return row_count
        _enforce_precopy_caps(
            obj,
            "Analysis result",
            max_rows=MAX_EXPORT_ROWS,
            max_columns=MAX_EXPORT_COLUMNS,
            max_cells=MAX_EXPORT_CELLS,
            max_bytes=MAX_EXPORT_ESTIMATED_BYTES,
        )
        return row_count
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


def _table_for_object(
    obj: Any,
    object_type: str,
    *,
    preserve_timing_precision: bool = False,
) -> Table:
    if object_type == "analysis_result":
        table = _analysis_table(obj)
        explicit_gti = None
    else:
        # Capture the backing GTI before to_astropy_table accesses the public
        # property and can synthesize/cache an implicit interval.
        explicit_gti = _gti_array_for_export(
            obj, preserve_dtype=preserve_timing_precision
        )
        table = obj.to_astropy_table()
        # Stingray declares its scientific scalar fields through meta_attrs(),
        # but Lightcurve.to_astropy_table() currently omits several of them.
        # Add every declared value that the public serializer left out so the
        # HDF5 semantic comparison sees the complete source projection.
        if preserve_timing_precision:
            for attribute in obj.meta_attrs():
                if attribute == "gti" or attribute in table.meta:
                    continue
                table.meta[attribute] = copy.deepcopy(getattr(obj, attribute))
        if object_type == "lightcurve":
            for attribute in obj.array_attrs():
                values = getattr(obj, attribute, None)
                if values is None or attribute in table.colnames:
                    continue
                array = (
                    np.ma.asarray(values)
                    if isinstance(values, Masked) or np.ma.isMaskedArray(values)
                    else np.asarray(values)
                )
                if array.ndim != 1 or len(array) != len(table):
                    raise ValueError(
                        f"Loaded Lightcurve {attribute} must be a one-dimensional "
                        "array aligned with time"
                    )
                table[attribute] = _normalized_analysis_column(values, array, attribute)
            dt = np.asarray(getattr(obj, "dt", None))
            if dt.ndim == 1:
                if len(dt) != len(table):
                    raise ValueError(
                        "Loaded Lightcurve per-bin dt must be aligned with time"
                    )
                table["dt"] = np.array(dt, copy=True)
        if preserve_timing_precision:
            # Preserve additional application provenance and other non-null
            # public scalar fields that Stingray does not declare through
            # meta_attrs().  Aligned scientific arrays are represented as
            # columns above or by Stingray's own table projection.
            for attribute, value in vars(obj).items():
                if (
                    attribute.startswith("_")
                    or attribute in table.colnames
                    or attribute in table.meta
                    or value is None
                ):
                    continue
                try:
                    aligned = np.ndim(value) >= 1 and len(value) == len(table)
                except TypeError:
                    aligned = False
                if aligned:
                    raise ValueError(
                        f"Loaded {object_type.replace('_', ' ')} field '{attribute}' "
                        "was not represented as a scientific column"
                    )
                table.meta[attribute] = copy.deepcopy(value)
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
            # A masked nullable value may use NaN only as its hidden storage.
            # Report non-finite values only when they are scientifically
            # present, not when the mask already declares them missing.
            nonfinite_count = int(np.count_nonzero(~finite & ~masked))
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


def _optional_hdf5_runtime() -> tuple[Any | None, str | None]:
    """Load h5py lazily so the rest of General I/O remains independently usable."""
    try:
        module = importlib.import_module("h5py")
    except Exception:
        return None, HDF5_UNAVAILABLE_REASON
    if not callable(getattr(module, "File", None)):
        return None, HDF5_UNAVAILABLE_REASON
    return module, None


def _hdf5_capability() -> dict[str, Any]:
    module, reason = _optional_hdf5_runtime()
    available = module is not None
    return {
        "supported": available,
        "notes": (
            "Versioned Stingray Explorer HDF5 table with a complete semantic "
            "reopen comparison before publication."
            if available
            else "Optional HDF5 runtime dependency is unavailable."
        ),
        "reason": reason,
        "extensions": [HDF5_EXTENSION],
        "dependency": {
            "name": "h5py",
            "available": available,
            "version": str(getattr(module, "__version__", "unknown"))
            if available
            else None,
        },
    }


def _hdf5_object_name_reason(object_name: str) -> str | None:
    if "\0" in object_name:
        return "HDF5 export does not support NUL characters in object names"
    try:
        object_name.encode("utf-8")
    except UnicodeEncodeError:
        return "HDF5 export requires object names that are valid UTF-8 text"
    return None


def _hdf5_dtype_reason(dtype: np.dtype[Any], column_name: str) -> str | None:
    kind = dtype.kind
    if kind not in HDF5_SUPPORTED_COLUMN_KINDS:
        return (
            f"HDF5 export does not support column '{column_name}' with logical "
            f"dtype {dtype}; supported logical kinds are boolean, integer, "
            "floating point, and ASCII Unicode text"
        )
    if kind == "U":
        if dtype.itemsize <= 0 or dtype.itemsize % np.dtype("U1").itemsize != 0:
            return (
                f"HDF5 export cannot represent column '{column_name}' with "
                f"logical dtype {dtype}"
            )
        return None
    if dtype.itemsize not in HDF5_SUPPORTED_ITEM_SIZES[kind]:
        return (
            f"HDF5 export does not support column '{column_name}' with logical "
            f"dtype {dtype}; its {dtype.itemsize}-byte width is unsupported"
        )
    return None


def _hdf5_metadata_reason(
    value: Any,
    location: str,
    active: set[int] | None = None,
) -> str | None:
    """Return why metadata is outside the explicitly verified HDF5 subset."""
    if active is None:
        active = set()
    if value is None or type(value) in {str, bool, int, float}:
        return None
    if isinstance(value, Masked) or np.ma.isMaskedArray(value):
        return f"HDF5 export does not support masked metadata at '{location}'"
    if isinstance(value, np.generic):
        return _hdf5_dtype_reason(np.asarray(value).dtype, location)
    if isinstance(value, u.UnitBase):
        return _hdf5_unit_reason(value, location)
    if isinstance(value, u.Quantity):
        if type(value) is not u.Quantity:
            return (
                f"HDF5 export does not support Quantity subclass "
                f"'{type(value).__name__}' at '{location}'"
            )
        quantity_dtype = np.asarray(value.value).dtype
        reason = _hdf5_dtype_reason(quantity_dtype, location)
        if reason is not None:
            return reason
        if quantity_dtype.kind in {"b", "i", "u"}:
            return (
                f"HDF5 export does not support integer or boolean Quantity "
                f"metadata at '{location}' because Astropy reopens it as "
                "floating point"
            )
        return _hdf5_unit_reason(value.unit, location)
    if type(value) is np.ndarray:
        return _hdf5_dtype_reason(value.dtype, location)
    if isinstance(value, np.ndarray):
        return (
            f"HDF5 export does not support ndarray subclass "
            f"'{type(value).__name__}' at '{location}'"
        )
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"HDF5 export does not support binary metadata at '{location}'"

    identity = id(value)
    if identity in active:
        return f"HDF5 export metadata at '{location}' contains a cycle"
    active.add(identity)
    try:
        if type(value) is dict:
            for key, item in value.items():
                if not isinstance(key, str):
                    return f"HDF5 export metadata at '{location}' has a non-text key"
                reason = _hdf5_metadata_reason(item, f"{location}.{key}", active)
                if reason is not None:
                    return reason
            return None
        if isinstance(value, Mapping):
            return (
                f"HDF5 export does not support metadata mapping subclass "
                f"'{type(value).__name__}' at '{location}'"
            )
        if type(value) in {list, tuple}:
            for index, item in enumerate(value):
                reason = _hdf5_metadata_reason(item, f"{location}[{index}]", active)
                if reason is not None:
                    return reason
            return None
        if isinstance(value, (list, tuple)):
            return (
                f"HDF5 export does not support metadata sequence subclass "
                f"'{type(value).__name__}' at '{location}'"
            )
    finally:
        active.remove(identity)
    return (
        f"HDF5 export does not support metadata value '{location}' of type "
        f"{type(value).__name__}"
    )


def _hdf5_unit_reason(unit: u.UnitBase, location: str) -> str | None:
    """Reject units the standalone reader cannot reconstruct exactly."""
    try:
        encoded = unit.to_string()
        decoded = u.Unit(encoded, parse_strict="raise")
    except Exception:
        return (
            f"HDF5 export cannot reopen the unit '{unit}' at '{location}' "
            "without an external custom-unit definition"
        )
    if decoded != unit:
        return f"HDF5 export cannot round-trip the unit at '{location}' exactly"
    return None


def _canonicalize_hdf5_metadata(value: Any) -> Any:
    """Normalize supported scalar types to Astropy's stable YAML representation."""
    if isinstance(value, np.generic):
        kind = np.asarray(value).dtype.kind
        if kind == "b":
            return bool(value)
        if kind in {"i", "u"}:
            return int(value)
        if kind == "f":
            return float(value)
        if kind == "U":
            return str(value)
    if isinstance(value, u.Quantity):
        if value.isscalar:
            scalar = _canonicalize_hdf5_metadata(np.asarray(value.value)[()])
            return u.Quantity(scalar, value.unit, copy=True)
        return value.copy()
    if type(value) is np.ndarray:
        return value.copy()
    if type(value) is dict:
        return {key: _canonicalize_hdf5_metadata(item) for key, item in value.items()}
    if type(value) is list:
        return [_canonicalize_hdf5_metadata(item) for item in value]
    if type(value) is tuple:
        return tuple(_canonicalize_hdf5_metadata(item) for item in value)
    return value


def _is_masked_column(column: Any) -> bool:
    return isinstance(column, MaskedColumn) or np.ma.isMaskedArray(column)


def _encode_hdf5_fill_value(value: Any, dtype: np.dtype[Any]) -> dict[str, Any]:
    """Encode one dtype-coerced scalar without losing non-finite float values."""
    scalar = np.asarray(value, dtype=dtype).reshape(()).item()
    if dtype.kind == "b":
        return {"kind": "bool", "value": bool(scalar)}
    if dtype.kind in {"i", "u"}:
        return {"kind": "integer", "value": str(int(scalar))}
    if dtype.kind == "f":
        converted = float(scalar)
        if math.isnan(converted):
            encoded = "nan"
        elif math.isinf(converted):
            encoded = "+inf" if converted > 0 else "-inf"
        else:
            encoded = converted.hex()
        return {"kind": "float", "value": encoded}
    if dtype.kind == "U":
        return {"kind": "unicode", "value": str(scalar)}
    raise ValueError(f"Cannot encode an HDF5 fill value for logical dtype {dtype}")


def _logical_dtype_from_manifest(entry: Mapping[str, Any]) -> np.dtype[Any]:
    kind = entry.get("dtype_kind")
    itemsize = entry.get("dtype_itemsize")
    if (
        not isinstance(kind, str)
        or not isinstance(itemsize, int)
        or isinstance(itemsize, bool)
    ):
        raise ValueError("HDF5 column manifest contains an invalid logical dtype")
    if kind == "b" and itemsize == 1:
        return np.dtype("?")
    if kind in {"i", "u", "f"} and itemsize in HDF5_SUPPORTED_ITEM_SIZES[kind]:
        return np.dtype(f"{kind}{itemsize}").newbyteorder("=")
    if kind == "U" and itemsize > 0 and itemsize % np.dtype("U1").itemsize == 0:
        return np.dtype(f"U{itemsize // np.dtype('U1').itemsize}")
    raise ValueError("HDF5 column manifest declares an unsupported logical dtype")


def _decode_hdf5_fill_value(
    encoded: Any, dtype: np.dtype[Any]
) -> np.generic | str | bool:
    if not isinstance(encoded, Mapping):
        raise ValueError("HDF5 column manifest contains an invalid fill value")
    kind = encoded.get("kind")
    value = encoded.get("value")
    if kind == "bool" and isinstance(value, bool):
        decoded: Any = value
    elif kind == "integer" and isinstance(value, str):
        decoded = int(value)
    elif kind == "float" and isinstance(value, str):
        if value == "nan":
            decoded = float("nan")
        elif value == "+inf":
            decoded = float("inf")
        elif value == "-inf":
            decoded = float("-inf")
        else:
            decoded = float.fromhex(value)
    elif kind == "unicode" and isinstance(value, str):
        decoded = value
    else:
        raise ValueError("HDF5 column manifest contains an invalid fill value")
    return np.asarray(decoded, dtype=dtype).reshape(()).item()


def _replace_table_column(
    table: Table,
    name: str,
    data: np.ndarray,
    *,
    masked: bool,
    mask: np.ndarray | None = None,
    fill_value: Any = None,
) -> None:
    original = table[name]
    common = {
        "name": name,
        "unit": getattr(original, "unit", None),
        "format": getattr(original, "format", None),
        "description": getattr(original, "description", None),
        "meta": copy.deepcopy(getattr(original, "meta", {})),
        "copy": False,
    }
    if masked:
        replacement = MaskedColumn(
            data,
            mask=mask,
            fill_value=fill_value,
            **common,
        )
    else:
        replacement = Column(data, **common)
    table.replace_column(name, replacement)


def _prepare_hdf5_table(table: Table) -> tuple[Table, list[dict[str, Any]]]:
    """Canonicalize endian representation and create an ordered schema manifest."""
    if "__serialized_columns__" in table.meta:
        raise ValueError(
            "HDF5 export does not support the reserved top-level metadata key "
            "'__serialized_columns__'"
        )
    metadata_reason = _hdf5_metadata_reason(table.meta, "metadata")
    if metadata_reason is not None:
        raise ValueError(metadata_reason)
    table_fill_reasons = getattr(table, ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE, {})
    if isinstance(table_fill_reasons, Mapping) and table_fill_reasons:
        first_name = next(iter(table_fill_reasons))
        raise ValueError(str(table_fill_reasons[first_name]))
    source_names = set(table.colnames)
    for name in table.colnames:
        if _is_masked_column(table[name]) and f"{name}.mask" in source_names:
            raise ValueError(
                f"HDF5 export cannot serialize masked column '{name}' because "
                f"column '{name}.mask' conflicts with its schema mask field"
            )
    for name in table.colnames:
        fill_reason = getattr(table[name], ANALYSIS_HDF5_FILL_REASON_ATTRIBUTE, None)
        if fill_reason is not None:
            raise ValueError(str(fill_reason))

    canonical = table.copy(copy_data=True)
    canonical.meta = _canonicalize_hdf5_metadata(canonical.meta)
    manifest: list[dict[str, Any]] = []
    for name in canonical.colnames:
        column = canonical[name]
        if not isinstance(column, Column):
            raise ValueError(
                f"HDF5 export does not support mixin column '{name}' of type "
                f"{type(column).__name__}"
            )
        if not isinstance(name, str) or not name:
            raise ValueError("HDF5 export requires non-empty text column names")
        if not name.isprintable():
            raise ValueError(
                f"HDF5 export does not support control characters in column "
                f"name {name!r}"
            )
        column_format = getattr(column, "format", None)
        if column_format is not None and not isinstance(column_format, str):
            raise ValueError(
                f"HDF5 export does not support callable or non-text format "
                f"metadata on column '{name}'"
            )
        description = getattr(column, "description", None)
        if description is not None and not isinstance(description, str):
            raise ValueError(
                f"HDF5 export does not support non-text description metadata "
                f"on column '{name}'"
            )
        values = np.ma.asarray(column)
        data = np.asarray(values.data)
        if data.ndim != 1:
            raise ValueError(f"HDF5 export requires one-dimensional column '{name}'")
        reason = _hdf5_dtype_reason(data.dtype, name)
        if reason is not None:
            raise ValueError(reason)
        if data.dtype.kind == "U" and any(
            not str(item).isascii() for item in data.flat
        ):
            raise ValueError(
                f"HDF5 export column '{name}' contains non-ASCII Unicode text; "
                "this schema only verifies fixed-width ASCII text losslessly"
            )

        dtype = data.dtype.newbyteorder("=")
        masked = _is_masked_column(column)
        mask = np.ma.getmaskarray(values) if masked else None
        fill_value = getattr(column, "fill_value", None) if masked else None
        if data.dtype.byteorder not in {"=", "|"}:
            data = data.astype(dtype, copy=True)
            _replace_table_column(
                canonical,
                name,
                data,
                masked=masked,
                mask=mask,
                fill_value=fill_value,
            )
            column = canonical[name]
            values = np.ma.asarray(column)
            data = np.asarray(values.data)

        column_meta_reason = _hdf5_metadata_reason(
            getattr(column, "meta", {}), f"columns.{name}.meta"
        )
        if column_meta_reason is not None:
            raise ValueError(column_meta_reason)
        column.meta = _canonicalize_hdf5_metadata(column.meta)
        column_unit = getattr(column, "unit", None)
        if column_unit is not None:
            unit_reason = _hdf5_unit_reason(column_unit, f"columns.{name}.unit")
            if unit_reason is not None:
                raise ValueError(unit_reason)
        entry: dict[str, Any] = {
            "name": name,
            "dtype_kind": data.dtype.kind,
            "dtype_itemsize": data.dtype.itemsize,
            "masked": masked,
            "unit": str(column_unit) if column_unit is not None else None,
        }
        if masked:
            entry["fill_value"] = _encode_hdf5_fill_value(column.fill_value, data.dtype)
            entry["mask_stored"] = bool(np.any(mask))
        manifest.append(entry)

    manifest_bytes = len(
        json.dumps(
            manifest,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    if manifest_bytes > HDF5_MANIFEST_MAX_BYTES:
        raise ValueError("HDF5 column manifest exceeds the 2 MiB schema cap")
    try:
        with serialize_context_as("hdf5"):
            serialized_table = astropy_table_serialize.represent_mixins_as_columns(
                canonical
            )
        yaml_lines = astropy_table_meta.get_yaml_from_table(serialized_table)
    except Exception as exception:
        raise ValueError(
            "HDF5 export metadata cannot be represented by the installed "
            "Astropy runtime"
        ) from exception
    if not isinstance(yaml_lines, list) or any(
        not isinstance(line, str) for line in yaml_lines
    ):
        raise ValueError("HDF5 export metadata serialization is invalid")
    yaml_width = max(
        (len(line.encode("utf-8")) for line in yaml_lines),
        default=0,
    )
    yaml_bytes = len(yaml_lines) * yaml_width
    table_bytes = sum(
        int(np.asarray(serialized_table[name]).nbytes)
        for name in serialized_table.colnames
    )
    estimated_bytes = table_bytes + yaml_bytes + manifest_bytes
    if estimated_bytes > MAX_EXPORT_ESTIMATED_BYTES:
        raise ValueError(
            f"HDF5 serialized table is estimated at least "
            f"{estimated_bytes / 1024**2:.1f} MiB; the export size cap is "
            f"{MAX_EXPORT_ESTIMATED_BYTES / 1024**2:.1f} MiB"
        )
    return canonical, manifest


def _hdf5_object_support_reason(
    obj: Any,
    object_type: str,
    object_name: str | None = None,
) -> str | None:
    """Check one bounded object without mutating application state."""
    if object_name is not None:
        name_reason = _hdf5_object_name_reason(object_name)
        if name_reason is not None:
            return name_reason
    try:
        # A shallow object copy keeps array allocation bounded while isolating
        # Stingray's lazy GTI/property caches from the catalog operation.
        table = _table_for_object(
            copy.copy(obj), object_type, preserve_timing_precision=True
        )
        _prepare_hdf5_table(table)
    except Exception as exception:
        return str(exception)
    return None


def _write_hdf5_table(
    stream: BinaryIO,
    h5py_module: Any,
    table: Table,
    manifest: list[dict[str, Any]],
    *,
    object_type: str,
    object_name: str,
) -> None:
    name_reason = _hdf5_object_name_reason(object_name)
    if name_reason is not None:
        raise ValueError(name_reason)
    manifest_json = json.dumps(
        manifest,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    manifest_encoded = manifest_json.encode("utf-8")
    if len(manifest_encoded) > HDF5_MANIFEST_MAX_BYTES:
        raise ValueError("HDF5 column manifest exceeds the 2 MiB schema cap")
    with h5py_module.File(stream, "w") as handle:
        table.write(
            handle,
            format="hdf5",
            path=HDF5_TABLE_PATH,
            serialize_meta=True,
        )
        group = handle[HDF5_GROUP_PATH]
        group.attrs["schema"] = HDF5_SCHEMA
        group.attrs["table_path"] = HDF5_TABLE_PATH
        group.attrs["object_type"] = object_type
        group.attrs["object_name"] = object_name
        group.attrs["row_count"] = len(table)
        handle.create_dataset(
            HDF5_MANIFEST_PATH,
            shape=(),
            dtype=f"S{max(1, len(manifest_encoded))}",
            data=np.bytes_(manifest_encoded),
        )
        handle.flush()


def _text_hdf5_attribute(value: Any, name: str) -> str:
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as exception:
            raise ValueError(f"HDF5 {name} attribute is not UTF-8") from exception
    if not isinstance(value, str):
        raise ValueError(f"HDF5 {name} attribute is invalid")
    return value


def _require_hdf5_hard_link(
    handle: Any,
    h5py_module: Any,
    path: str,
    label: str,
) -> None:
    link = handle.get(path, getlink=True)
    if not isinstance(link, h5py_module.HardLink):
        raise ValueError(f"HDF5 verification found a noncanonical {label} link")


def _require_self_contained_hdf5_dataset(dataset: Any, label: str) -> None:
    if bool(dataset.is_virtual) or bool(dataset.external):
        raise ValueError(
            f"HDF5 verification found a non-self-contained {label} dataset"
        )


def _validated_hdf5_manifest(
    manifest: Any,
) -> tuple[list[dict[str, Any]], list[tuple[str, np.dtype[Any]]]]:
    """Validate the bounded manifest before any table dataset is materialized."""
    if not isinstance(manifest, list):
        raise ValueError("HDF5 column manifest must be a list")
    if not manifest or len(manifest) > MAX_EXPORT_COLUMNS:
        raise ValueError(
            f"HDF5 column manifest must contain between 1 and "
            f"{MAX_EXPORT_COLUMNS:,} columns"
        )
    seen: set[str] = set()
    physical_fields: list[tuple[str, np.dtype[Any]]] = []
    for entry in manifest:
        if not isinstance(entry, dict):
            raise ValueError("HDF5 column manifest contains an invalid entry")
        masked = entry.get("masked")
        required_keys = {
            "name",
            "dtype_kind",
            "dtype_itemsize",
            "masked",
            "unit",
        }
        if masked is True:
            required_keys.update({"fill_value", "mask_stored"})
        if type(masked) is not bool or set(entry) != required_keys:
            raise ValueError("HDF5 column manifest contains an invalid entry")
        name = entry.get("name")
        if (
            not isinstance(name, str)
            or not name
            or not name.isprintable()
            or name in seen
        ):
            raise ValueError("HDF5 column manifest contains an invalid column name")
        seen.add(name)
        unit = entry.get("unit")
        if unit is not None and not isinstance(unit, str):
            raise ValueError("HDF5 column manifest contains an invalid unit")
        logical_dtype = _logical_dtype_from_manifest(entry)
        physical_fields.append((name, logical_dtype))
        if masked:
            # Validate the scalar now; the restored column uses the same decode.
            _decode_hdf5_fill_value(entry.get("fill_value"), logical_dtype)
            mask_stored = entry.get("mask_stored")
            if type(mask_stored) is not bool:
                raise ValueError("HDF5 column manifest contains an invalid entry")
            if mask_stored:
                physical_fields.append((f"{name}.mask", np.dtype("?")))
    return manifest, physical_fields


def _hdf5_dataset_logical_bytes(dataset: Any) -> int:
    return int(dataset.size) * int(dataset.dtype.itemsize)


def _validate_hdf5_table_storage(
    handle: Any,
    h5py_module: Any,
    *,
    row_count: int,
    manifest: list[dict[str, Any]],
    physical_fields: list[tuple[str, np.dtype[Any]]],
    manifest_bytes: int,
) -> None:
    """Bound and validate all datasets before Astropy allocates a Table."""
    _require_hdf5_hard_link(handle, h5py_module, HDF5_TABLE_PATH, "table dataset")
    table_dataset = handle[HDF5_TABLE_PATH]
    if not isinstance(table_dataset, h5py_module.Dataset):
        raise ValueError("HDF5 verification found an invalid table dataset")
    _require_self_contained_hdf5_dataset(table_dataset, "table")
    if len(table_dataset.shape) != 1 or int(table_dataset.shape[0]) != row_count:
        raise ValueError("HDF5 schema row count does not match the table dataset")
    if table_dataset.dtype.hasobject or table_dataset.dtype.metadata is not None:
        raise ValueError("HDF5 table dataset contains an unbounded variable dtype")
    actual_fields = table_dataset.dtype.names
    expected_names = tuple(name for name, _dtype in physical_fields)
    if actual_fields is None or tuple(actual_fields) != expected_names:
        raise ValueError("HDF5 table storage fields do not match the column manifest")
    expected_storage_fields: list[tuple[str, np.dtype[Any]]] = []
    for name, logical_dtype in physical_fields:
        field_dtype = table_dataset.dtype.fields[name][0]
        if field_dtype.hasobject or field_dtype.subdtype is not None:
            raise ValueError(
                f"HDF5 table storage field '{name}' has an unsupported dtype"
            )
        if logical_dtype.kind == "U":
            expected_kind = "S"
            expected_itemsize = logical_dtype.itemsize // np.dtype("U1").itemsize
            expected_storage_dtype = h5py_module.string_dtype(
                encoding="ascii",
                length=expected_itemsize,
            )
        else:
            expected_kind = logical_dtype.kind
            expected_itemsize = logical_dtype.itemsize
            expected_storage_dtype = logical_dtype.newbyteorder("=")
        expected_storage_fields.append((name, expected_storage_dtype))
        allowed_metadata = field_dtype.metadata is None or (
            expected_kind == "S" and field_dtype.metadata == {"h5py_encoding": "ascii"}
        )
        if (
            field_dtype.kind != expected_kind
            or field_dtype.itemsize != expected_itemsize
            or not allowed_metadata
        ):
            raise ValueError(
                f"HDF5 table storage field '{name}' does not match its logical dtype"
            )

    # High-level NumPy dtypes do not expose every HDF5 type property.  Compare
    # the complete low-level compound type against the exact packed type our
    # writer creates so padding, byte order, integer precision/offset/sign,
    # string padding/cset, and boolean enum semantics are all canonical.
    expected_storage_dtype = np.dtype(expected_storage_fields, align=False)
    actual_hdf_type = table_dataset.id.get_type()
    expected_hdf_type = h5py_module.h5t.py_create(
        expected_storage_dtype,
        logical=True,
    )
    try:
        if not actual_hdf_type.equal(expected_hdf_type):
            raise ValueError(
                "HDF5 table storage has a noncanonical compound layout or member type"
            )
    finally:
        expected_hdf_type.close()
        actual_hdf_type.close()

    cells = row_count * len(manifest)
    if cells > MAX_EXPORT_CELLS:
        raise ValueError(
            f"HDF5 table has {cells:,} cells; the export cell cap is "
            f"{MAX_EXPORT_CELLS:,}"
        )
    if HDF5_ASTROPY_METADATA_PATH not in handle:
        raise ValueError("HDF5 verification could not find Astropy table metadata")
    _require_hdf5_hard_link(
        handle,
        h5py_module,
        HDF5_ASTROPY_METADATA_PATH,
        "Astropy table metadata",
    )
    metadata_dataset = handle[HDF5_ASTROPY_METADATA_PATH]
    if not isinstance(metadata_dataset, h5py_module.Dataset):
        raise ValueError("HDF5 verification found invalid Astropy table metadata")
    _require_self_contained_hdf5_dataset(metadata_dataset, "Astropy table metadata")
    if (
        len(metadata_dataset.shape) != 1
        or int(metadata_dataset.size) <= 0
        or metadata_dataset.dtype.kind != "S"
        or metadata_dataset.dtype.itemsize <= 0
        or metadata_dataset.dtype.hasobject
    ):
        raise ValueError("HDF5 verification found invalid Astropy table metadata")
    metadata_bytes = _hdf5_dataset_logical_bytes(metadata_dataset)
    table_bytes = _hdf5_dataset_logical_bytes(table_dataset)
    estimated_bytes = manifest_bytes + metadata_bytes + table_bytes
    if estimated_bytes > MAX_EXPORT_ESTIMATED_BYTES:
        raise ValueError(
            f"HDF5 artifact is estimated at least "
            f"{estimated_bytes / 1024**2:.1f} MiB; the export size cap is "
            f"{MAX_EXPORT_ESTIMATED_BYTES / 1024**2:.1f} MiB"
        )


def _restore_hdf5_columns(table: Table, manifest: list[dict[str, Any]]) -> Table:
    if len(manifest) != len(table.colnames):
        raise ValueError("HDF5 column manifest length does not match the table")
    for index, entry in enumerate(manifest):
        if not isinstance(entry, dict):
            raise ValueError("HDF5 column manifest contains an invalid entry")
        name = entry.get("name")
        if not isinstance(name, str) or table.colnames[index] != name:
            raise ValueError("HDF5 column manifest order does not match the table")
        logical_dtype = _logical_dtype_from_manifest(entry)
        column = table[name]
        values = np.ma.asarray(column)
        data = np.asarray(values.data)
        masked = entry.get("masked")
        if not isinstance(masked, bool):
            raise ValueError("HDF5 column manifest has an invalid mask declaration")
        actual_masked = _is_masked_column(column)
        if actual_masked != masked:
            raise ValueError(f"HDF5 column '{name}' mask capability changed")
        declared_unit = entry.get("unit")
        actual_unit = (
            str(column.unit) if getattr(column, "unit", None) is not None else None
        )
        if actual_unit != declared_unit:
            raise ValueError(f"HDF5 column '{name}' unit manifest changed")

        if logical_dtype.kind == "U":
            character_count = logical_dtype.itemsize // np.dtype("U1").itemsize
            if data.dtype.kind == "S" and data.dtype.itemsize == character_count:
                try:
                    restored_data = data.astype(logical_dtype)
                except UnicodeDecodeError as exception:
                    raise ValueError(
                        f"HDF5 column '{name}' is not valid ASCII text"
                    ) from exception
            elif data.dtype == logical_dtype:
                restored_data = data
            else:
                raise ValueError(f"HDF5 column '{name}' logical dtype changed")
        else:
            if (
                data.dtype.kind != logical_dtype.kind
                or data.dtype.itemsize != logical_dtype.itemsize
            ):
                raise ValueError(f"HDF5 column '{name}' logical dtype changed")
            restored_data = (
                data.astype(logical_dtype, copy=True)
                if data.dtype.byteorder not in {"=", "|"}
                else data
            )

        fill_value = None
        if masked:
            fill_value = _decode_hdf5_fill_value(entry.get("fill_value"), logical_dtype)
        if restored_data is not data or masked:
            _replace_table_column(
                table,
                name,
                restored_data,
                masked=masked,
                mask=np.ma.getmaskarray(values) if masked else None,
                fill_value=fill_value,
            )
    return table


def _read_hdf5_table(
    stream: BinaryIO,
    h5py_module: Any,
    *,
    object_type: str,
    object_name: str,
) -> tuple[Table, list[dict[str, Any]]]:
    with h5py_module.File(stream, "r") as handle:
        if HDF5_GROUP_PATH not in handle:
            raise ValueError("HDF5 verification could not find the schema group")
        _require_hdf5_hard_link(handle, h5py_module, HDF5_GROUP_PATH, "schema group")
        group = handle[HDF5_GROUP_PATH]
        if not isinstance(group, h5py_module.Group):
            raise ValueError("HDF5 verification found an invalid schema group")
        schema = _text_hdf5_attribute(group.attrs.get("schema"), "schema")
        if schema != HDF5_SCHEMA:
            raise ValueError("HDF5 verification found an unexpected schema marker")
        table_path = _text_hdf5_attribute(group.attrs.get("table_path"), "table path")
        if table_path != HDF5_TABLE_PATH or HDF5_TABLE_PATH not in handle:
            raise ValueError("HDF5 verification found an unexpected table path")
        stored_type = _text_hdf5_attribute(
            group.attrs.get("object_type"), "object type"
        )
        stored_name = _text_hdf5_attribute(
            group.attrs.get("object_name"), "object name"
        )
        if stored_type != object_type or stored_name != object_name:
            raise ValueError("HDF5 verification found unexpected object identity")
        row_count = group.attrs.get("row_count")
        if not isinstance(row_count, (int, np.integer)) or isinstance(
            row_count, (bool, np.bool_)
        ):
            raise ValueError("HDF5 verification found an invalid row count")
        row_count = int(row_count)
        if row_count < 0 or row_count > MAX_EXPORT_ROWS:
            raise ValueError(
                f"HDF5 table row count exceeds the export cap of {MAX_EXPORT_ROWS:,}"
            )
        if HDF5_MANIFEST_PATH not in handle:
            raise ValueError("HDF5 verification could not find the column manifest")
        _require_hdf5_hard_link(
            handle, h5py_module, HDF5_MANIFEST_PATH, "column manifest"
        )
        manifest_dataset = handle[HDF5_MANIFEST_PATH]
        if not isinstance(manifest_dataset, h5py_module.Dataset):
            raise ValueError("HDF5 verification found an invalid column manifest")
        if (
            manifest_dataset.shape != ()
            or manifest_dataset.dtype.kind != "S"
            or manifest_dataset.dtype.itemsize <= 0
            or manifest_dataset.dtype.itemsize > HDF5_MANIFEST_MAX_BYTES
            or manifest_dataset.dtype.hasobject
        ):
            raise ValueError(
                "HDF5 column manifest storage exceeds or violates the 2 MiB schema cap"
            )
        _require_self_contained_hdf5_dataset(manifest_dataset, "column manifest")
        manifest_bytes = int(manifest_dataset.dtype.itemsize)
        manifest_text = _text_hdf5_attribute(manifest_dataset[()], "column manifest")
        if len(manifest_text.encode("utf-8")) > HDF5_MANIFEST_MAX_BYTES:
            raise ValueError("HDF5 column manifest exceeds the 2 MiB schema cap")
        try:
            manifest = json.loads(manifest_text)
        except json.JSONDecodeError as exception:
            raise ValueError("HDF5 column manifest is invalid JSON") from exception
        manifest, physical_fields = _validated_hdf5_manifest(manifest)
        _validate_hdf5_table_storage(
            handle,
            h5py_module,
            row_count=row_count,
            manifest=manifest,
            physical_fields=physical_fields,
            manifest_bytes=manifest_bytes,
        )
        reopened = Table.read(
            handle,
            format="hdf5",
            path=HDF5_TABLE_PATH,
        )
        if len(reopened) != row_count:
            raise ValueError("HDF5 schema row count does not match the table")
    return _restore_hdf5_columns(reopened, manifest), manifest


def _semantic_array_equal(expected: np.ndarray, actual: np.ndarray) -> bool:
    if expected.shape != actual.shape:
        return False
    if expected.dtype.kind == "f" and actual.dtype.kind == "f":
        return bool(np.array_equal(expected, actual, equal_nan=True))
    return bool(np.array_equal(expected, actual))


def _assert_hdf5_semantic_equal(expected: Any, actual: Any, location: str) -> None:
    if isinstance(expected, u.Quantity):
        if not isinstance(actual, u.Quantity) or expected.unit != actual.unit:
            raise ValueError(f"HDF5 verification changed {location} units")
        _assert_hdf5_semantic_equal(expected.value, actual.value, location)
        return
    if isinstance(expected, u.UnitBase):
        if not isinstance(actual, u.UnitBase) or expected != actual:
            raise ValueError(f"HDF5 verification changed {location}")
        return
    if isinstance(expected, np.ndarray):
        if not isinstance(actual, np.ndarray):
            raise ValueError(f"HDF5 verification changed {location} type")
        if (
            expected.dtype.kind != actual.dtype.kind
            or expected.dtype.itemsize != actual.dtype.itemsize
        ):
            raise ValueError(f"HDF5 verification changed {location} dtype")
        if not _semantic_array_equal(expected, actual):
            raise ValueError(f"HDF5 verification changed {location} values")
        return
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping) or set(expected) != set(actual):
            raise ValueError(f"HDF5 verification changed {location} keys")
        for key in expected:
            _assert_hdf5_semantic_equal(expected[key], actual[key], f"{location}.{key}")
        return
    if isinstance(expected, (list, tuple)):
        if not isinstance(actual, type(expected)) or len(expected) != len(actual):
            raise ValueError(f"HDF5 verification changed {location} sequence")
        for index, (expected_item, actual_item) in enumerate(
            zip(expected, actual, strict=True)
        ):
            _assert_hdf5_semantic_equal(
                expected_item, actual_item, f"{location}[{index}]"
            )
        return
    if isinstance(expected, np.generic):
        if isinstance(expected, np.floating):
            expected = float(expected)
        else:
            expected = expected.item()
    if isinstance(actual, np.generic):
        if isinstance(actual, np.floating):
            actual = float(actual)
        else:
            actual = actual.item()
    if isinstance(expected, bool) or isinstance(actual, bool):
        if type(expected) is not type(actual) or expected != actual:
            raise ValueError(f"HDF5 verification changed {location}")
        return
    if isinstance(expected, float) and isinstance(actual, (int, float)):
        if math.isnan(expected) and isinstance(actual, float) and math.isnan(actual):
            return
        if expected == actual:
            return
        raise ValueError(f"HDF5 verification changed {location}")
    if expected != actual:
        raise ValueError(f"HDF5 verification changed {location}")


def _verify_hdf5_table(expected: Table, actual: Table) -> list[str]:
    if len(expected) != len(actual):
        raise ValueError("HDF5 semantic verification changed the row count")
    if expected.colnames != actual.colnames:
        raise ValueError("HDF5 semantic verification changed the column order")
    for name in expected.colnames:
        expected_column = expected[name]
        actual_column = actual[name]
        expected_values = np.ma.asarray(expected_column)
        actual_values = np.ma.asarray(actual_column)
        expected_data = np.asarray(expected_values.data)
        actual_data = np.asarray(actual_values.data)
        if (
            expected_data.dtype.kind != actual_data.dtype.kind
            or expected_data.dtype.itemsize != actual_data.dtype.itemsize
        ):
            raise ValueError(
                f"HDF5 semantic verification changed column '{name}' logical dtype"
            )
        if _is_masked_column(expected_column) != _is_masked_column(actual_column):
            raise ValueError(
                f"HDF5 semantic verification changed column '{name}' mask capability"
            )
        expected_mask = np.ma.getmaskarray(expected_values)
        actual_mask = np.ma.getmaskarray(actual_values)
        if not np.array_equal(expected_mask, actual_mask):
            raise ValueError(
                f"HDF5 semantic verification changed column '{name}' masks"
            )
        # Masked payload bytes are deliberately non-scientific and serializers
        # may normalize them.  The mask and fill semantics are checked
        # separately; compare values only where the column says they exist.
        if not _semantic_array_equal(
            expected_data[~expected_mask], actual_data[~actual_mask]
        ):
            raise ValueError(
                f"HDF5 semantic verification changed column '{name}' values"
            )
        expected_unit = getattr(expected_column, "unit", None)
        actual_unit = getattr(actual_column, "unit", None)
        if expected_unit != actual_unit:
            raise ValueError(
                f"HDF5 semantic verification changed column '{name}' units"
            )
        for attribute in ("description", "format", "meta"):
            _assert_hdf5_semantic_equal(
                getattr(expected_column, attribute, None),
                getattr(actual_column, attribute, None),
                f"column '{name}' {attribute}",
            )
        if _is_masked_column(expected_column):
            _assert_hdf5_semantic_equal(
                np.asarray(expected_column.fill_value, dtype=expected_data.dtype),
                np.asarray(actual_column.fill_value, dtype=actual_data.dtype),
                f"column '{name}' fill value",
            )
    _assert_hdf5_semantic_equal(
        dict(expected.meta), dict(actual.meta), "table metadata"
    )
    return list(HDF5_VERIFICATION_CHECKS)


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
    def _format_capabilities(
        object_type: str,
        hdf5_capability: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
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
            "hdf5": copy.deepcopy(hdf5_capability or _hdf5_capability()),
        }
        if object_type in {"event_list", "lightcurve"}:
            common["fits"]["notes"] += (
                " A separate GTI extension is included when available."
            )
        return common

    def list_exportable_objects(self) -> dict[str, Any]:
        try:
            hdf5_capability = _hdf5_capability()
            enabled_formats = ["csv", "ecsv", "json", "fits"]
            if hdf5_capability["supported"]:
                enabled_formats.append("hdf5")
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
                    formats = list(enabled_formats) if reason is None else []
                    format_reasons: dict[str, str] = {}
                    if reason is None:
                        if hdf5_capability["supported"]:
                            hdf5_reason = _hdf5_object_support_reason(
                                obj, object_type, name
                            )
                        else:
                            hdf5_reason = hdf5_capability["reason"]
                        if hdf5_reason is not None:
                            format_reasons["hdf5"] = hdf5_reason
                            if "hdf5" in formats:
                                formats.remove("hdf5")
                    objects.append(
                        {
                            "object_type": object_type,
                            "name": name,
                            "row_count": row_count,
                            "exportable": reason is None,
                            "formats": formats,
                            "format_reasons": format_reasons,
                            "reason": reason,
                        }
                    )

            matrix = {
                object_type: self._format_capabilities(object_type, hdf5_capability)
                for object_type in sorted(EXPORT_OBJECT_TYPES)
            }
            excluded_formats = {
                "pickle": "Unsafe deserialization format; intentionally unsupported."
            }
            if not hdf5_capability["supported"]:
                excluded_formats["hdf5"] = hdf5_capability["reason"]
            data = {
                "objects": objects,
                "capability_matrix": matrix,
                "format_allowlist": enabled_formats,
                "excluded_formats": excluded_formats,
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
        warning_messages: list[str] = []
        try:
            publication = context_stack.enter_context(
                open_secure_publication(
                    destination_path,
                    destination_grant,
                )
            )
            path = publication.path
            destination_name = publication.filename
            if destination_name in {"", ".", ".."} or os.sep in destination_name:
                raise ValueError("The selected destination filename is invalid")
            if os.altsep is not None and os.altsep in destination_name:
                raise ValueError("The selected destination filename is invalid")

            publication.revalidate("The selected destination path changed")
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
            h5py_module = None
            if requested_format == "hdf5":
                h5py_module, hdf5_reason = _optional_hdf5_runtime()
                if h5py_module is None:
                    raise RuntimeError(hdf5_reason or HDF5_UNAVAILABLE_REASON)
                name_reason = _hdf5_object_name_reason(object_name)
                if name_reason is not None:
                    raise ValueError(name_reason)
            publication.assert_destination_available()
            obj = self._copy_export_object(object_type, object_name)
            row_count = _object_row_count(obj, object_type)
            if row_count > MAX_EXPORT_ROWS:
                raise ValueError(
                    f"Object has {row_count:,} rows; the export cap is {MAX_EXPORT_ROWS:,}"
                )
            table = _table_for_object(
                obj,
                object_type,
                preserve_timing_precision=requested_format == "hdf5",
            )
            if len(table) != row_count:
                raise ValueError(
                    "Export table row count does not match the loaded object"
                )
            hdf5_manifest: list[dict[str, Any]] | None = None
            if requested_format == "hdf5":
                table, hdf5_manifest = _prepare_hdf5_table(table)

            # Write and verify in a private same-directory staging area.  The
            # platform adapter exposes the user-visible destination only after
            # verification, using an exclusive no-replacement publication.
            publication.reserve_staging(expected_extension)
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

            if requested_format == "hdf5":
                mode = "w+b"
            elif requested_format == "fits":
                mode = "wb"
            else:
                mode = "w"
            with publication.open_writer(
                mode,
                encoding=None if "b" in mode else "utf-8",
            ) as stream:
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
                    elif requested_format == "hdf5":
                        assert h5py_module is not None
                        assert hdf5_manifest is not None
                        _write_hdf5_table(
                            stream,
                            h5py_module,
                            table,
                            hdf5_manifest,
                            object_type=object_type,
                            object_name=object_name,
                        )
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

            # Astropy's ASCII registry expects a binary-readable file object;
            # JSON's standard decoder expects text.
            read_mode = "r" if requested_format == "json" else "rb"
            hdf5_checks: list[str] | None = None
            with publication.open_reader(
                read_mode,
                encoding=None if read_mode == "rb" else "utf-8",
            ) as reopened_stream:
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
                elif requested_format == "hdf5":
                    assert h5py_module is not None
                    assert hdf5_manifest is not None
                    reopened, reopened_manifest = _read_hdf5_table(
                        reopened_stream,
                        h5py_module,
                        object_type=object_type,
                        object_name=object_name,
                    )
                    _assert_hdf5_semantic_equal(
                        hdf5_manifest,
                        reopened_manifest,
                        "HDF5 column manifest",
                    )
                    hdf5_checks = _verify_hdf5_table(table, reopened)
                    reopened_rows = len(reopened)
                else:
                    reopened_json = json.load(reopened_stream)
                    if reopened_json.get("schema") != "stingray-explorer.tabular.v1":
                        raise ValueError("JSON verification found an unexpected schema")
                    reopened_rows = int(reopened_json.get("row_count", -1))
            if reopened_rows != row_count:
                raise ValueError(
                    f"Reopened artifact has {reopened_rows:,} rows; expected {row_count:,}"
                )

            byte_size = publication.verified_size()

            # Publish the already verified artifact through the platform's
            # single-operation, exclusive no-replacement primitive.
            warning_messages.extend(publication.publish())
            provenance_parameters = {
                "format": requested_format,
                "destination_path": str(path),
                "exclusive_non_overwrite": True,
                "reopen_verified": True,
            }
            if requested_format == "hdf5":
                provenance_parameters["schema"] = HDF5_SCHEMA
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
                    parameters=provenance_parameters,
                ),
            }
            if requested_format == "hdf5":
                assert h5py_module is not None
                assert hdf5_checks is not None
                data["verification"] = {
                    "schema": HDF5_SCHEMA,
                    "table_path": HDF5_TABLE_PATH,
                    "semantic_round_trip": True,
                    "checks": hdf5_checks,
                    "h5py_version": str(getattr(h5py_module, "__version__", "unknown")),
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
            context_stack.close()
