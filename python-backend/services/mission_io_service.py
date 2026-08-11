"""Mission-aware inspection and approximate PI conversion utilities.

The service deliberately keeps two calibration paths distinct:

* :func:`stingray.mission_support.get_rough_conversion_function` provides the
  approximate, mission-specific estimates exposed here.
* RMF-based calibration is the precise path and belongs to General I/O.

No selected FITS path is opened until its Electron-issued file grant has been
verified.  Mission-specific FITS interpretation is run on an in-memory copy
and is summarized without changing the source file.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, BinaryIO, Optional

import numpy as np
from astropy.io import fits
from stingray.io import get_key_from_mission_info
from stingray.mission_support import (
    get_rough_conversion_function,
    mission_specific_event_interpretation,
    read_mission_info,
)

from services.base_service import BaseService
from services.utility_helpers import (
    MAX_ARRAY_INPUT,
    MAX_EXPORT_ROWS,
    MAX_FITS_INSPECT_BYTES,
    MAX_STATE_SNAPSHOT_BYTES,
    MAX_STATE_SNAPSHOT_CELLS,
    duplicate_binary_stream,
    json_safe,
    open_verified_read_grant,
    operation_provenance,
    validate_derived_name,
    validate_file_size,
    validate_finite_array,
)


PREVIEW_ROWS = 500
MAX_INTERPRET_FITS_BYTES = 256 * 1024**2
MAX_FITS_HDUS = 512
XTE_PCA_EPOCH_MJD_MIN_EXCLUSIVE = 50_081.0
XTE_PCA_EPOCH_MJD_MAX_INCLUSIVE = 55_931.0
TIME_UNIT_SECONDS = {
    "s": 1.0,
    "sec": 1.0,
    "second": 1.0,
    "seconds": 1.0,
    "ms": 1e-3,
    "us": 1e-6,
    "ns": 1e-9,
    "min": 60.0,
    "minute": 60.0,
    "minutes": 60.0,
    "h": 3600.0,
    "hr": 3600.0,
    "hour": 3600.0,
    "hours": 3600.0,
    "d": 86400.0,
    "day": 86400.0,
    "days": 86400.0,
}
RAW_CARD_PREFIX = "__STINGRAY_EXPLORER_RAW_CARD__"

# These are naming aliases, not a hard-coded support list.  Capability rows
# continue to come from the runtime xselect database returned by Stingray.
MISSION_NAME_ALIASES = {
    "chandra": "axaf",
    "rxte": "xte",
    "xmm-newton": "xmm",
}

MAPPING_KEYS = {
    "event_hdu": "events",
    "gti_hdu": "gti",
    "time_column": "time",
    "energy_or_channel_column": "ecol",
    "detector_column": "ccol",
    "instrument_keyword": "instkey",
    "mode_keyword": "dmodekey",
}


def _clean_text(value: Any) -> Optional[str]:
    """Return a non-empty, stripped string or ``None``."""
    if value is None:
        return None
    result = str(value).strip()
    if not result or result.upper() == "NONE":
        return None
    return result


def _safe_float(value: Any) -> Optional[float]:
    """Return a finite scalar float or ``None``."""
    if isinstance(value, (bool, np.bool_)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _normalise_mapping_value(value: Any) -> Any:
    """Translate xselect's ``NONE`` sentinel and retain useful mappings."""
    if isinstance(value, str):
        return None if value.strip().upper() == "NONE" else value.strip()
    if isinstance(value, (list, tuple)):
        return [_normalise_mapping_value(item) for item in value]
    return value


def _runtime_choices(value: Any) -> list[str]:
    """Return non-empty runtime database choices without inventing delimiters."""
    normalized = _normalise_mapping_value(value)
    raw_values = normalized if isinstance(normalized, list) else [normalized]
    return [clean for item in raw_values if (clean := _clean_text(item)) is not None]


def _canonical_runtime_choice(requested: Any, available: Any) -> Optional[str]:
    """Resolve a user spelling to an exact runtime database choice."""
    clean = _clean_text(requested)
    if clean is None:
        return None
    for choice in _runtime_choices(available):
        if choice.casefold() == clean.casefold():
            return choice
    return None


def _header_to_mapping(raw_header: Any) -> dict[str, Any]:
    """Convert a supported EventList header representation to a mapping."""
    if raw_header is None:
        return {}
    if isinstance(raw_header, fits.Header):
        result: dict[str, Any] = {}
        for key in raw_header.keys():
            normalized_key = str(key).upper()
            if not key or normalized_key.strip() in {"COMMENT", "HISTORY"}:
                continue
            result[normalized_key] = raw_header.get(key)
            try:
                card_image = raw_header.cards[key].image
            except (KeyError, AttributeError):
                continue
            if len(card_image) >= 11 and card_image[8:10] == "= ":
                raw_value = card_image[10:].split("/", 1)[0].strip()
                if raw_value:
                    result[f"{RAW_CARD_PREFIX}{normalized_key}"] = raw_value
        return result
    if isinstance(raw_header, Mapping):
        return {str(key).upper(): value for key, value in raw_header.items()}
    if not isinstance(raw_header, str):
        return {}

    try:
        separator = "\n" if "\n" in raw_header else ""
        parsed = fits.Header.fromstring(raw_header, sep=separator)
        return _header_to_mapping(parsed)
    except Exception:
        # A malformed optional header must not make EventList identification
        # unusable.  The EventList's explicit metadata attributes can still be
        # reported, and the caller receives a missing-header warning.
        return {}


def _field(
    value: Any = None,
    *,
    raw_value: Any = None,
    source: Optional[str] = None,
    source_type: str = "missing",
    inferred: bool = False,
    override: bool = False,
) -> dict[str, Any]:
    """Build a source-labelled identification field."""
    clean_value = _clean_text(value)
    return {
        "value": clean_value,
        "raw_value": _clean_text(raw_value) if raw_value is not None else clean_value,
        "source": source,
        "source_type": source_type if clean_value is not None else "missing",
        "inferred": bool(inferred and clean_value is not None),
        "override": bool(override and clean_value is not None),
    }


class MissionIOService(BaseService):
    """Mission-specific read-only inspection and derived EventList operations."""

    def _failure(
        self, message: str, *, warnings: Optional[list[str]] = None
    ) -> dict[str, Any]:
        return self.create_result(
            success=False,
            data=None,
            message=message,
            error=None,
            warnings=warnings or [],
        )

    @staticmethod
    def _runtime_database() -> dict[str, tuple[str, dict[str, Any]]]:
        """Return case-folded, de-duplicated runtime xselect mappings."""
        raw_database = read_mission_info()
        if not isinstance(raw_database, dict):
            raise RuntimeError("Stingray returned an invalid mission database")

        database: dict[str, tuple[str, dict[str, Any]]] = {}
        for raw_name, raw_info in raw_database.items():
            name = _clean_text(raw_name)
            if name is None or not isinstance(raw_info, dict):
                continue
            # Stingray applies a few mission-specific database patches only
            # when a mission is requested explicitly (for example XTE's PCUID
            # column).  Use the all-mission call to discover names, then load
            # the public per-mission view for accurate mappings.
            selected_info = read_mission_info(name)
            if not isinstance(selected_info, dict):
                selected_info = raw_info
            key = name.casefold()
            current = database.get(key)
            # Prefer the all-uppercase spelling when xselect contains a
            # duplicate that differs only in case (Astro-E2 in 2.2.10).
            if current is None or (name.isupper() and not current[0].isupper()):
                database[key] = (name, selected_info)
        return database

    @staticmethod
    def _resolve_mission(
        value: Any,
        database: dict[str, tuple[str, dict[str, Any]]],
    ) -> tuple[Optional[str], Optional[dict[str, Any]], bool]:
        """Resolve a mission against the runtime database and naming aliases."""
        clean = _clean_text(value)
        if clean is None:
            return None, None, False
        key = clean.casefold()
        inferred = False
        if key not in database and key in MISSION_NAME_ALIASES:
            key = MISSION_NAME_ALIASES[key]
            inferred = True
        if key in database:
            canonical, info = database[key]
            return canonical, info, inferred
        return clean, None, inferred

    @staticmethod
    def _find_header_value(
        header_sources: Sequence[tuple[str, Mapping[str, Any]]],
        keys: Sequence[Optional[str]],
    ) -> tuple[Any, Optional[str]]:
        """Find the first non-empty value for a prioritized header-key list."""
        normalized_keys: list[str] = []
        for key in keys:
            clean = _clean_text(key)
            if clean is not None and clean.upper() not in normalized_keys:
                normalized_keys.append(clean.upper())

        for source, header in header_sources:
            for key in normalized_keys:
                if key in header and _clean_text(header[key]) is not None:
                    return header[key], f"{source}.{key}"
        return None, None

    @staticmethod
    def _find_raw_card_value(
        header_sources: Sequence[tuple[str, Mapping[str, Any]]],
        keys: Sequence[str],
    ) -> Optional[str]:
        """Return the original FITS numeric lexeme when a Header retained it."""
        for _source, header in header_sources:
            for key in keys:
                marker = f"{RAW_CARD_PREFIX}{key.upper()}"
                if marker in header:
                    return str(header[marker]).strip()
        return None

    @classmethod
    def _find_high_precision_header_value(
        cls,
        header_sources: Sequence[tuple[str, Mapping[str, Any]]],
        key: str,
    ) -> tuple[Any, Optional[str], Optional[str]]:
        """Read a direct or public-Stingray-style split FITS keyword.

        Stingray's ``high_precision_keyword_read`` first reads ``KEY`` and
        otherwise sums ``KEYI`` + ``KEYF`` (truncating an eight-character key
        to seven characters before adding the suffix).  This equivalent
        mapping-level preflight retains the original card lexemes for display
        while still letting the service validate malformed components before
        calling mission calibration code.
        """
        normalized_key = key.upper()
        for source, header in header_sources:
            if (
                normalized_key in header
                and _clean_text(header[normalized_key]) is not None
            ):
                return (
                    header[normalized_key],
                    f"{source}.{normalized_key}",
                    cls._find_raw_card_value([(source, header)], [normalized_key]),
                )

            split_base = (
                normalized_key[:7] if len(normalized_key) == 8 else normalized_key
            )
            key_i = f"{split_base}I"
            key_f = f"{split_base}F"
            has_i = key_i in header and _clean_text(header[key_i]) is not None
            has_f = key_f in header and _clean_text(header[key_f]) is not None
            if not has_i and not has_f:
                continue
            split_source = f"{source}.{key_i} + {source}.{key_f}"
            if not has_i or not has_f:
                return float("nan"), split_source, None
            parsed_i = _safe_float(header[key_i])
            parsed_f = _safe_float(header[key_f])
            if parsed_i is None or parsed_f is None:
                return float("nan"), split_source, None
            exact_i = cls._find_raw_card_value([(source, header)], [key_i]) or str(
                header[key_i]
            )
            exact_f = cls._find_raw_card_value([(source, header)], [key_f]) or str(
                header[key_f]
            )
            try:
                exact = format(
                    Decimal(exact_i.replace("D", "E").replace("d", "e"))
                    + Decimal(exact_f.replace("D", "E").replace("d", "e")),
                    "f",
                )
            except (InvalidOperation, ValueError):
                exact = None
            with np.errstate(over="ignore", invalid="ignore"):
                combined = parsed_i + parsed_f
            if not math.isfinite(combined):
                return float("nan"), split_source, exact
            return combined, split_source, exact
        return None, None, None

    @staticmethod
    def _apply_missing_only_override(
        entry: dict[str, Any],
        override_value: Any,
        *,
        field_name: str,
    ) -> dict[str, Any]:
        """Apply an override only when source metadata did not identify a value."""
        override = _clean_text(override_value)
        if override is None:
            return entry
        existing = _clean_text(entry.get("value"))
        if existing is not None:
            if existing.casefold() != override.casefold():
                raise ValueError(
                    f"{field_name.capitalize()} metadata already identifies '{existing}'. "
                    "Overrides are accepted only when that metadata is missing."
                )
            return entry
        return _field(
            override,
            raw_value=override,
            source=f"request.{field_name}_override",
            source_type="override",
            override=True,
        )

    def _mapping_for(
        self,
        mission_info: Optional[dict[str, Any]],
        instrument: Optional[str],
        mode: Optional[str],
    ) -> Optional[dict[str, Any]]:
        if mission_info is None:
            return None
        mapping: dict[str, Any] = {}
        for output_key, database_key in MAPPING_KEYS.items():
            value = get_key_from_mission_info(
                mission_info,
                database_key,
                None,
                inst=instrument,
                mode=mode,
            )
            mapping[output_key] = _normalise_mapping_value(value)
        return mapping

    @staticmethod
    def _runtime_modes_for_instrument(
        mission_info: Mapping[str, Any], instrument: Optional[str]
    ) -> Any:
        """Return every runtime-declared or nested mode for an instrument."""
        declared = _normalise_mapping_value(
            get_key_from_mission_info(
                mission_info,
                "modes",
                None,
                inst=instrument,
            )
        )
        modes = _runtime_choices(declared)
        selected_instrument = _canonical_runtime_choice(
            instrument, mission_info.get("instruments")
        )
        scoped = (
            mission_info.get(selected_instrument)
            if selected_instrument is not None
            else None
        )
        if isinstance(scoped, Mapping):
            for key, value in scoped.items():
                clean = _clean_text(key)
                if clean is not None and isinstance(value, Mapping):
                    if all(clean.casefold() != item.casefold() for item in modes):
                        modes.append(clean)
        if not modes:
            return declared
        if len(modes) == 1 and not isinstance(declared, list):
            return modes[0]
        return modes

    def _identify_parts(
        self,
        *,
        source: dict[str, Any],
        header_sources: Sequence[tuple[str, Mapping[str, Any]]],
        mission_attribute: Any = None,
        instrument_attribute: Any = None,
        mode_attribute: Any = None,
        mission_override: Any = None,
        instrument_override: Any = None,
        mode_override: Any = None,
    ) -> tuple[dict[str, Any], list[str]]:
        """Identify mission fields and retain a source for every value."""
        warnings: list[str] = []
        database = self._runtime_database()

        mission_raw = _clean_text(mission_attribute)
        mission_source = "EventList.mission" if mission_raw is not None else None
        mission_source_type = "event_list_attribute"
        if mission_raw is None:
            mission_raw, mission_source = self._find_header_value(
                header_sources, ["MISSION", "TELESCOP"]
            )
            mission_source_type = "fits_header"

        canonical, mission_info, alias_inferred = self._resolve_mission(
            mission_raw, database
        )
        mission_entry = _field(
            canonical,
            raw_value=mission_raw,
            source=mission_source,
            source_type=mission_source_type,
            inferred=alias_inferred,
        )
        mission_entry = self._apply_missing_only_override(
            mission_entry, mission_override, field_name="mission"
        )
        canonical, mission_info, override_alias = self._resolve_mission(
            mission_entry["value"], database
        )
        mission_entry["value"] = canonical
        mission_entry["inferred"] = bool(mission_entry["inferred"] or override_alias)
        mission_entry["database_supported"] = mission_info is not None

        instrument_key = (
            get_key_from_mission_info(mission_info, "instkey", None)
            if mission_info is not None
            else None
        )
        instrument_raw = _clean_text(instrument_attribute)
        instrument_source = "EventList.instr" if instrument_raw is not None else None
        instrument_source_type = "event_list_attribute"
        if instrument_raw is None:
            instrument_raw, instrument_source = self._find_header_value(
                header_sources, [instrument_key, "INSTRUME", "DETNAM"]
            )
            instrument_source_type = "fits_header"
        instrument_entry = _field(
            instrument_raw,
            source=instrument_source,
            source_type=instrument_source_type,
        )
        instrument_entry = self._apply_missing_only_override(
            instrument_entry, instrument_override, field_name="instrument"
        )

        instrument = instrument_entry["value"]
        mode_key = (
            get_key_from_mission_info(mission_info, "dmodekey", None, inst=instrument)
            if mission_info is not None
            else None
        )
        mode_raw = _clean_text(mode_attribute)
        mode_source = "EventList.mode" if mode_raw is not None else None
        mode_source_type = "event_list_attribute"
        if mode_raw is None:
            mode_raw, mode_source = self._find_header_value(
                header_sources, [mode_key, "DATAMODE", "OBS_MODE"]
            )
            mode_source_type = "fits_header"
        mode_entry = _field(mode_raw, source=mode_source, source_type=mode_source_type)
        mode_entry = self._apply_missing_only_override(
            mode_entry, mode_override, field_name="mode"
        )

        mapping_validation_error = None
        if mission_info is not None:
            available_instruments = _normalise_mapping_value(
                mission_info.get("instruments")
            )
            instrument_choices = _runtime_choices(available_instruments)
            selected_instrument = instrument_entry["value"]
            if selected_instrument is not None and instrument_choices:
                canonical_instrument = _canonical_runtime_choice(
                    selected_instrument, available_instruments
                )
                if canonical_instrument is None:
                    mapping_validation_error = (
                        f"Instrument '{selected_instrument}' is not defined for "
                        f"{mission_entry['value']}"
                    )
                else:
                    instrument_entry["value"] = canonical_instrument

            selected_mode = mode_entry["value"]
            if selected_mode is not None and mapping_validation_error is None:
                available_modes = self._runtime_modes_for_instrument(
                    mission_info, instrument_entry["value"]
                )
                mode_choices = _runtime_choices(available_modes)
                if (
                    instrument_entry["value"] is None
                    and instrument_choices
                    and not mode_choices
                ):
                    mapping_validation_error = (
                        f"Mode '{selected_mode}' requires an instrument selection for "
                        f"{mission_entry['value']}"
                    )
                elif mode_choices:
                    canonical_mode = _canonical_runtime_choice(
                        selected_mode, available_modes
                    )
                    if canonical_mode is None:
                        mapping_validation_error = (
                            f"Mode '{selected_mode}' is not defined for "
                            f"{mission_entry['value']}"
                            + (
                                f"/{instrument_entry['value']}"
                                if instrument_entry["value"] is not None
                                else ""
                            )
                        )
                    else:
                        mode_entry["value"] = canonical_mode

        if mapping_validation_error is not None:
            warnings.append(
                f"{mapping_validation_error}; no generic fallback mapping was applied."
            )

        if mission_entry["value"] is None:
            warnings.append(
                "Mission metadata is missing. Supply a mission override to use mission mappings "
                "or approximate conversion."
            )
        elif mission_info is None:
            warnings.append(
                f"Mission '{mission_entry['value']}' is not present in Stingray's runtime "
                "xselect mission database."
            )
        if instrument_entry["value"] is None:
            warnings.append("Instrument metadata is missing.")
        if mode_entry["value"] is None:
            warnings.append("Observing-mode metadata is missing.")

        identified = {
            "source": source,
            "mission": mission_entry,
            "instrument": instrument_entry,
            "mode": mode_entry,
            "mapping": self._mapping_for(
                mission_info,
                instrument_entry["value"],
                mode_entry["value"],
            )
            if mapping_validation_error is None
            else None,
            "mapping_validation_error": mapping_validation_error,
        }
        return identified, warnings

    @staticmethod
    def _fits_header_sources(
        stream: BinaryIO,
    ) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, Any]]]:
        """Read FITS headers without materializing event-table data."""
        header_sources: list[tuple[str, dict[str, Any]]] = []
        hdu_summary: list[dict[str, Any]] = []
        with duplicate_binary_stream(stream) as fits_stream:
            with fits.open(
                fits_stream, mode="readonly", memmap=True, lazy_load_hdus=True
            ) as hdulist:
                if len(hdulist) > MAX_FITS_HDUS:
                    raise ValueError(
                        f"FITS file has {len(hdulist):,} HDUs; the inspection cap is "
                        f"{MAX_FITS_HDUS:,}"
                    )
                for index, hdu in enumerate(hdulist):
                    header = _header_to_mapping(hdu.header)
                    name = _clean_text(hdu.name) or str(index)
                    label = f"HDU[{index}:{name}]"
                    header_sources.append((label, header))
                    hdu_summary.append(
                        {
                            "index": index,
                            "name": name,
                            "type": type(hdu).__name__,
                            "rows": int(hdu.header.get("NAXIS2", 0))
                            if "NAXIS2" in hdu.header
                            else None,
                        }
                    )
        return header_sources, hdu_summary

    def _identify_event_list(
        self,
        name: str,
        *,
        max_events: int,
        mission_override: Any = None,
        instrument_override: Any = None,
        mode_override: Any = None,
    ) -> tuple[Optional[Any], Optional[dict[str, Any]], list[str], Optional[str]]:
        try:
            event_list = self.state.copy_event_data(
                name,
                max_events=max_events,
                max_cells=MAX_STATE_SNAPSHOT_CELLS,
                max_bytes=MAX_STATE_SNAPSHOT_BYTES,
            )
        except ValueError as exc:
            return None, None, [], str(exc)
        if event_list is None:
            return None, None, [], f"EventList '{name}' was not found"
        header = _header_to_mapping(getattr(event_list, "header", None))
        header_sources = [("EventList.header", header)] if header else []
        try:
            identified, warnings = self._identify_parts(
                source={
                    "type": "loaded_event_list",
                    "name": name,
                    "event_count": int(len(event_list.time)),
                },
                header_sources=header_sources,
                mission_attribute=getattr(event_list, "mission", None),
                instrument_attribute=getattr(event_list, "instr", None),
                mode_attribute=getattr(event_list, "mode", None),
                mission_override=mission_override,
                instrument_override=instrument_override,
                mode_override=mode_override,
            )
        except ValueError as exc:
            return event_list, None, [], str(exc)
        if getattr(event_list, "header", None) is not None and not header:
            warnings.append(
                "The EventList header could not be parsed; explicit attributes were used."
            )
        identified["timing_metadata"] = self._timing_metadata(
            event_list, header_sources, warnings
        )
        return event_list, identified, warnings, None

    def _identify_fits(
        self,
        stream: BinaryIO,
        *,
        display_path: str,
        size_bytes: int,
        mission_override: Any = None,
        instrument_override: Any = None,
        mode_override: Any = None,
    ) -> tuple[Optional[dict[str, Any]], list[str], Optional[str]]:
        try:
            headers, hdu_summary = self._fits_header_sources(stream)
            identified, warnings = self._identify_parts(
                source={
                    "type": "selected_fits_file",
                    "path": display_path,
                    "size_bytes": size_bytes,
                    "hdu_count": len(hdu_summary),
                },
                header_sources=headers,
                mission_override=mission_override,
                instrument_override=instrument_override,
                mode_override=mode_override,
            )
            identified["hdus"] = hdu_summary
            identified["timing_metadata"] = self._timing_metadata(
                None, headers, warnings
            )
            return identified, warnings, None
        except Exception as exc:
            return None, [], f"Could not inspect the selected FITS headers: {exc}"

    @classmethod
    def _timing_metadata(
        cls,
        event_list: Any,
        header_sources: Sequence[tuple[str, Mapping[str, Any]]],
        warnings: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Return concise timing metadata with source labels."""
        output: dict[str, Any] = {}
        warning_list = warnings if warnings is not None else []
        for output_name, keys in {
            "mjd_observation": ["MJD-OBS", "MJD_OBS", "MJDOBS"],
            "tstart": ["TSTART"],
            "tstop": ["TSTOP"],
            "timezero": ["TIMEZERO"],
            "timedel": ["TIMEDEL"],
            "timepixr": ["TIMEPIXR"],
        }.items():
            if len(keys) == 1:
                value, source, exact_value = cls._find_high_precision_header_value(
                    header_sources, keys[0]
                )
            else:
                value, source = cls._find_header_value(header_sources, keys)
                exact_value = None
            if value is None:
                continue
            parsed = _safe_float(value)
            if parsed is None:
                warning_list.append(
                    f"Ignored malformed or non-finite {keys[0]} value from {source}."
                )
                continue
            if output_name == "timedel" and parsed < 0:
                warning_list.append(
                    f"Ignored invalid TIMEDEL value from {source}; TIMEDEL must be "
                    "non-negative."
                )
                continue
            if output_name == "timepixr" and not 0.0 <= parsed <= 1.0:
                warning_list.append(
                    f"Ignored invalid TIMEPIXR value from {source}; TIMEPIXR must be "
                    "between 0 and 1."
                )
                continue
            output[output_name] = {
                "value": parsed,
                "source": source,
                **({"decimal": exact_value} if exact_value is not None else {}),
            }

        for output_name, keys in {
            "timeunit": ["TIMEUNIT"],
            "timesys": ["TIMESYS"],
            "timeref": ["TIMEREF"],
            "date_observation": ["DATE-OBS"],
            "observation_id": ["OBS_ID", "OBSID"],
            "object": ["OBJECT"],
        }.items():
            value, source = cls._find_header_value(header_sources, keys)
            if value is not None:
                output[output_name] = {"value": value, "source": source}

        raw_mjdref, mjdref_source = cls._find_header_value(header_sources, ["MJDREF"])
        raw_mjdref_card = cls._find_raw_card_value(header_sources, ["MJDREF"])
        mjdref = _safe_float(raw_mjdref)
        mjdref_decimal = (
            raw_mjdref_card
            if raw_mjdref_card is not None and mjdref is not None
            else str(raw_mjdref)
            if mjdref is not None
            else None
        )
        mjdref_components = None
        if raw_mjdref is not None and mjdref is None:
            warning_list.append(
                f"Ignored malformed non-finite MJDREF value from {mjdref_source}."
            )
        if mjdref is None:
            mjdrefi, source_i = cls._find_header_value(header_sources, ["MJDREFI"])
            mjdreff, source_f = cls._find_header_value(header_sources, ["MJDREFF"])
            raw_mjdrefi_card = cls._find_raw_card_value(header_sources, ["MJDREFI"])
            raw_mjdreff_card = cls._find_raw_card_value(header_sources, ["MJDREFF"])
            exact_i = raw_mjdrefi_card or (
                str(mjdrefi) if mjdrefi is not None else None
            )
            exact_f = raw_mjdreff_card or (
                str(mjdreff) if mjdreff is not None else None
            )
            base_i = _safe_float(mjdrefi)
            base_f = _safe_float(mjdreff)
            if (mjdrefi is None) != (mjdreff is None):
                warning_list.append(
                    "Ignored incomplete split MJDREF metadata; both MJDREFI and "
                    "MJDREFF are required by Stingray's high-precision reader."
                )
            if mjdrefi is not None and base_i is None:
                warning_list.append(
                    f"Ignored malformed non-finite MJDREFI value from {source_i}."
                )
            if mjdreff is not None and base_f is None:
                warning_list.append(
                    f"Ignored malformed non-finite MJDREFF value from {source_f}; "
                    "it was not substituted with zero."
                )
            if (
                mjdrefi is not None
                and mjdreff is not None
                and base_i is not None
                and base_f is not None
            ):
                with np.errstate(over="ignore", invalid="ignore"):
                    combined_mjdref = base_i + base_f
                if not math.isfinite(combined_mjdref):
                    warning_list.append(
                        "Ignored split MJDREF metadata because MJDREFI + MJDREFF "
                        "is not representable as a finite value."
                    )
                else:
                    mjdref = combined_mjdref
                    mjdref_source = f"{source_i} + {source_f}"
                    mjdref_components = {
                        "integer": {"value": exact_i, "source": source_i},
                        "fraction": {
                            "value": exact_f,
                            "source": source_f,
                        },
                    }
                    try:
                        mjdref_decimal = format(
                            Decimal(str(exact_i).replace("D", "E").replace("d", "e"))
                            + Decimal(str(exact_f).replace("D", "E").replace("d", "e")),
                            "f",
                        )
                    except (InvalidOperation, ValueError):
                        mjdref_decimal = str(mjdref)
        if mjdref is None and event_list is not None:
            candidate = _safe_float(getattr(event_list, "mjdref", None))
            if candidate is not None and candidate > 0:
                mjdref = candidate
                mjdref_source = "EventList.mjdref"
                mjdref_decimal = str(getattr(event_list, "mjdref"))
        if mjdref is not None:
            output["mjdref"] = {
                "value": mjdref,
                "decimal": mjdref_decimal,
                "source": mjdref_source,
                "components": mjdref_components,
            }
        return output

    def list_capabilities(self) -> dict[str, Any]:
        """List runtime mission mappings and operation-specific support."""
        try:
            raw_count = len(read_mission_info())
            database = self._runtime_database()
            missions: list[dict[str, Any]] = []
            warnings: list[str] = []
            for key in sorted(database):
                name, info = database[key]
                interpreter = mission_specific_event_interpretation(name)
                if key == "xte":
                    rough = {
                        "status": "conditional",
                        "approximate": True,
                        "dependencies": [
                            "mission",
                            "instrument=PCA",
                            "epoch_mjd",
                            "detector_id",
                        ],
                        "message": (
                            "Approximate RXTE PCA conversion requires an observation MJD and "
                            "a detector ID (PCU 0-4) for every PI/PHA channel."
                        ),
                        "epoch_mjd_domain": {
                            "minimum_exclusive": XTE_PCA_EPOCH_MJD_MIN_EXCLUSIVE,
                            "maximum_inclusive": XTE_PCA_EPOCH_MJD_MAX_INCLUSIVE,
                        },
                    }
                else:
                    try:
                        get_rough_conversion_function(name)
                    except (ValueError, TypeError, AttributeError, KeyError):
                        rough = {
                            "status": "unsupported",
                            "approximate": False,
                            "dependencies": [],
                            "message": "No public rough PI-to-energy conversion is available.",
                        }
                    else:
                        rough = {
                            "status": "supported",
                            "approximate": True,
                            "dependencies": ["mission"],
                            "message": "A public approximate PI-to-energy conversion is available.",
                        }

                instruments = _normalise_mapping_value(info.get("instruments"))
                modes = _normalise_mapping_value(info.get("modes"))
                instrument_choices = _runtime_choices(instruments)
                if instrument_choices:
                    instrument_modes = {
                        str(instrument): selected_modes
                        for instrument in instrument_choices
                        if (
                            selected_modes := self._runtime_modes_for_instrument(
                                info, str(instrument)
                            )
                        )
                        is not None
                    }
                    if instrument_modes:
                        modes = instrument_modes

                missions.append(
                    {
                        "mission": name,
                        "mapping": self._mapping_for(info, None, None),
                        "instruments": instruments,
                        "modes": modes,
                        "rough_pi_to_energy": rough,
                        "specialized_interpretation": {
                            "supported": interpreter is not None,
                            "scope": (
                                "XTE PCA science-event FITS (XTE_SE, TEVTB2 and PHA)"
                                if key == "xte" and interpreter is not None
                                else None
                            ),
                        },
                    }
                )

            data = {
                "missions": missions,
                "mission_count": len(missions),
                "raw_database_entry_count": raw_count,
                "database_source": "runtime stingray.mission_support.read_mission_info",
                "support_note": (
                    "Mission database mappings describe FITS layout only; they do not imply "
                    "rough-conversion or specialized-interpretation support."
                ),
                "precise_calibration": {
                    "method": "RMF-based PI-to-energy conversion",
                    "location": "General I/O",
                },
                "provenance": operation_provenance(
                    "mission_io.list_capabilities",
                    input_source={
                        "type": "runtime_mission_database",
                        "provider": "stingray.mission_support.read_mission_info",
                    },
                    parameters={},
                    read_only=True,
                    source_modified=False,
                ),
            }
            safe_data = json_safe(data, warnings)
            safe_data["warnings"] = list(warnings)
            return self.create_result(
                success=True,
                data=safe_data,
                message=f"Found {len(missions)} runtime mission mappings",
                error=None,
                warnings=warnings,
            )
        except Exception as exc:
            return self.handle_error(exc, "Listing runtime mission capabilities")

    def get_mission_info(
        self,
        mission: str,
        *,
        instrument: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return the selected runtime mapping and capability details."""
        try:
            database = self._runtime_database()
            canonical, info, inferred = self._resolve_mission(mission, database)
            if canonical is None:
                return self._failure("Mission is required")
            if info is None:
                return self._failure(
                    f"Mission '{canonical}' is not present in Stingray's runtime mission database"
                )

            warnings: list[str] = []
            if inferred:
                warnings.append(
                    f"Mission name '{mission}' was mapped to xselect database name '{canonical}'."
                )
            key = canonical.casefold()
            interpreter = mission_specific_event_interpretation(canonical)
            selected_instrument = _clean_text(instrument)
            available_instruments = _normalise_mapping_value(info.get("instruments"))
            instrument_choices = _runtime_choices(available_instruments)
            if selected_instrument is not None and instrument_choices:
                canonical_instrument = _canonical_runtime_choice(
                    selected_instrument, available_instruments
                )
                if canonical_instrument is None:
                    return self._failure(
                        f"Instrument '{selected_instrument}' is not defined for {canonical}; "
                        f"available instruments: {', '.join(instrument_choices)}"
                    )
                selected_instrument = canonical_instrument

            selected_mode = _clean_text(mode)
            available_modes = self._runtime_modes_for_instrument(
                info,
                selected_instrument,
            )
            mode_choices = _runtime_choices(available_modes)
            if (
                selected_mode is not None
                and selected_instrument is None
                and instrument_choices
                and not mode_choices
            ):
                return self._failure(
                    f"Mode '{selected_mode}' requires an instrument selection for "
                    f"{canonical}; available instruments: {', '.join(instrument_choices)}"
                )
            if selected_mode is not None and mode_choices:
                canonical_mode = _canonical_runtime_choice(
                    selected_mode, available_modes
                )
                if canonical_mode is None:
                    preview = ", ".join(mode_choices[:8])
                    suffix = " ..." if len(mode_choices) > 8 else ""
                    return self._failure(
                        f"Mode '{selected_mode}' is not defined for {canonical}"
                        + (
                            f"/{selected_instrument}"
                            if selected_instrument is not None
                            else ""
                        )
                        + f"; available modes include: {preview}{suffix}"
                    )
                selected_mode = canonical_mode
            specialized_supported = interpreter is not None and not (
                key == "xte"
                and selected_instrument is not None
                and selected_instrument.casefold() != "pca"
            )
            if (
                key == "xte"
                and selected_instrument is not None
                and selected_instrument.casefold() != "pca"
            ):
                warnings.append(
                    "Specialized XTE interpretation is limited to PCA science-event FITS; "
                    f"instrument '{selected_instrument}' is not supported."
                )
            if (
                key == "xte"
                and selected_instrument is not None
                and selected_instrument.casefold() != "pca"
            ):
                rough_status = "unsupported"
                dependencies = []
                warnings.append(
                    "Approximate XTE PI-to-energy conversion is limited to the PCA; "
                    f"instrument '{selected_instrument}' is not supported."
                )
            elif key == "xte":
                rough_status = "conditional"
                dependencies = ["instrument=PCA", "epoch_mjd", "detector_id"]
            else:
                try:
                    get_rough_conversion_function(canonical)
                except (ValueError, TypeError, AttributeError, KeyError):
                    rough_status = "unsupported"
                    dependencies = []
                else:
                    rough_status = "supported"
                    dependencies = ["mission"]

            data = {
                "mission": canonical,
                "requested_mission": mission,
                "mission_name_inferred": inferred,
                "instrument": selected_instrument,
                "mode": selected_mode,
                "mapping": self._mapping_for(info, selected_instrument, selected_mode),
                "available_instruments": available_instruments,
                "available_modes": available_modes,
                "capabilities": {
                    "rough_pi_to_energy": {
                        "status": rough_status,
                        "approximate": rough_status != "unsupported",
                        "dependencies": dependencies,
                        "epoch_mjd_domain": (
                            {
                                "minimum_exclusive": XTE_PCA_EPOCH_MJD_MIN_EXCLUSIVE,
                                "maximum_inclusive": XTE_PCA_EPOCH_MJD_MAX_INCLUSIVE,
                            }
                            if key == "xte" and rough_status != "unsupported"
                            else None
                        ),
                    },
                    "specialized_interpretation": {
                        "supported": specialized_supported,
                        "scope": (
                            "XTE PCA science-event FITS (XTE_SE, TEVTB2 and PHA)"
                            if key == "xte" and interpreter is not None
                            else None
                        ),
                    },
                },
                "precise_calibration": {
                    "method": "RMF-based PI-to-energy conversion",
                    "location": "General I/O",
                },
                "provenance": operation_provenance(
                    "mission_io.get_mission_info",
                    input_source={
                        "type": "runtime_mission_database",
                        "provider": "stingray.mission_support.read_mission_info",
                    },
                    parameters={
                        "requested_mission": mission,
                        "resolved_mission": canonical,
                        "instrument": selected_instrument,
                        "mode": selected_mode,
                    },
                    read_only=True,
                    source_modified=False,
                ),
            }
            safe_data = json_safe(data, warnings)
            safe_data["warnings"] = list(warnings)
            return self.create_result(
                success=True,
                data=safe_data,
                message=f"Runtime mapping for {canonical}",
                error=None,
                warnings=warnings,
            )
        except Exception as exc:
            return self.handle_error(exc, "Reading mission mapping", mission=mission)

    def identify_source(
        self,
        *,
        event_list_name: Optional[str] = None,
        file_path: Optional[str] = None,
        file_grant: Optional[str] = None,
        mission_override: Optional[str] = None,
        instrument_override: Optional[str] = None,
        mode_override: Optional[str] = None,
    ) -> dict[str, Any]:
        """Identify mission fields in one loaded EventList or selected FITS file."""
        if bool(event_list_name) == bool(file_path):
            return self._failure(
                "Select exactly one source: a loaded EventList or an explicitly selected FITS file"
            )
        try:
            if event_list_name:
                _, identified, warnings, error = self._identify_event_list(
                    event_list_name,
                    max_events=MAX_EXPORT_ROWS,
                    mission_override=mission_override,
                    instrument_override=instrument_override,
                    mode_override=mode_override,
                )
                if error:
                    return self._failure(error)
            else:
                if not file_grant:
                    return self._failure(
                        "A native file-selection grant is required for the selected FITS path"
                    )
                with open_verified_read_grant(file_path or "", file_grant) as granted:
                    size = validate_file_size(
                        granted.stream,
                        MAX_FITS_INSPECT_BYTES,
                        "Selected FITS file",
                    )
                    identified, warnings, error = self._identify_fits(
                        granted.stream,
                        display_path=str(granted.path),
                        size_bytes=size,
                        mission_override=mission_override,
                        instrument_override=instrument_override,
                        mode_override=mode_override,
                    )
                if error:
                    return self._failure(error)

            assert identified is not None
            identified["provenance"] = operation_provenance(
                "mission_io.identify_source",
                input_source=identified["source"],
                parameters={
                    "mission_override": _clean_text(mission_override),
                    "instrument_override": _clean_text(instrument_override),
                    "mode_override": _clean_text(mode_override),
                },
                read_only=True,
                source_modified=False,
            )
            safe_data = json_safe(identified, warnings)
            safe_data["warnings"] = list(warnings)
            return self.create_result(
                success=True,
                data=safe_data,
                message="Mission metadata inspected",
                error=None,
                warnings=warnings,
            )
        except (PermissionError, FileNotFoundError, ValueError, OSError) as exc:
            return self._failure(str(exc))
        except Exception as exc:
            return self.handle_error(exc, "Identifying mission metadata")

    @staticmethod
    def _validate_pi(values: Any) -> tuple[Optional[np.ndarray], Optional[str]]:
        array, error = validate_finite_array(
            values,
            label="PI values",
            min_size=1,
            max_size=MAX_ARRAY_INPUT,
        )
        if error:
            return None, error
        assert array is not None
        negative = np.flatnonzero(array < 0)
        if negative.size:
            return None, f"PI values[{int(negative[0])}] must be non-negative"
        fractional = np.flatnonzero(array != np.floor(array))
        if fractional.size:
            return None, f"PI values[{int(fractional[0])}] must be an integer channel"
        too_large = np.flatnonzero(array > np.iinfo(np.int32).max)
        if too_large.size:
            return (
                None,
                f"PI values[{int(too_large[0])}] exceeds the supported channel range",
            )
        return array.astype(np.int64), None

    @staticmethod
    def _validate_detector_ids(
        values: Any,
        *,
        expected_size: int,
    ) -> tuple[Optional[np.ndarray], Optional[str]]:
        array, error = validate_finite_array(
            values,
            label="Detector IDs",
            min_size=1,
            max_size=MAX_ARRAY_INPUT,
        )
        if error:
            return None, error
        assert array is not None
        fractional = np.flatnonzero(array != np.floor(array))
        if fractional.size:
            return None, f"Detector IDs[{int(fractional[0])}] must be an integer"
        invalid = np.flatnonzero((array < 0) | (array > 4))
        if invalid.size:
            return (
                None,
                f"Detector IDs[{int(invalid[0])}] must be in the RXTE PCU range 0-4",
            )
        if array.size == 1 and expected_size > 1:
            array = np.full(expected_size, array[0])
        elif array.size != expected_size:
            return None, (
                f"Detector IDs contains {array.size} value(s), but {expected_size} PI values "
                "were supplied; provide one ID to broadcast or one per channel"
            )
        return array.astype(np.int64), None

    @classmethod
    def _derive_event_epoch(
        cls,
        event_list: Any,
        warnings: Optional[list[str]] = None,
    ) -> tuple[Optional[float], Optional[str]]:
        """Derive an observation MJD from explicit numeric timing metadata."""
        warning_list = warnings if warnings is not None else []
        header = _header_to_mapping(getattr(event_list, "header", None))
        header_sources = [("EventList.header", header)] if header else []
        mjd_observation = None
        mjd_observation_source = None
        for key in ["MJD-OBS", "MJD_OBS", "MJDOBS"]:
            value, source = cls._find_header_value(header_sources, [key])
            parsed = _safe_float(value)
            if parsed is not None:
                mjd_observation = parsed
                mjd_observation_source = source
                break

        mjdref_value, mjdref_source = cls._find_header_value(header_sources, ["MJDREF"])
        mjdref = _safe_float(mjdref_value)
        if mjdref_value is not None and mjdref is None:
            return None, None
        if mjdref_value is None:
            part_i, source_i = cls._find_header_value(header_sources, ["MJDREFI"])
            part_f, source_f = cls._find_header_value(header_sources, ["MJDREFF"])
            parsed_i = _safe_float(part_i)
            parsed_f = _safe_float(part_f)
            if (part_i is None) != (part_f is None):
                return None, None
            if part_i is not None and (parsed_i is None or parsed_f is None):
                return None, None
            if parsed_i is not None and parsed_f is not None:
                with np.errstate(over="ignore", invalid="ignore"):
                    combined_mjdref = parsed_i + parsed_f
                if not math.isfinite(combined_mjdref):
                    return None, None
                mjdref = combined_mjdref
                mjdref_source = f"{source_i} + {source_f}"
        if mjdref is None:
            mjdref = _safe_float(getattr(event_list, "mjdref", None))
            if mjdref is not None and mjdref > 0:
                mjdref_source = "EventList.mjdref"
            else:
                mjdref = None

        tstart_value, tstart_source, _ = cls._find_high_precision_header_value(
            header_sources, "TSTART"
        )
        tstart = _safe_float(tstart_value)
        if tstart_value is not None and tstart is None:
            return None, None
        offset_days: Optional[float] = None
        if tstart is not None:
            timezero_value, timezero_source, _ = cls._find_high_precision_header_value(
                header_sources, "TIMEZERO"
            )
            timezero = 0.0 if timezero_value is None else _safe_float(timezero_value)
            if timezero is None:
                return None, None

            timedel_value, timedel_source, _ = cls._find_high_precision_header_value(
                header_sources, "TIMEDEL"
            )
            timedel = 0.0 if timedel_value is None else _safe_float(timedel_value)
            if timedel is None or timedel < 0:
                return None, None

            timepixr_value, timepixr_source, _ = cls._find_high_precision_header_value(
                header_sources, "TIMEPIXR"
            )
            timepixr = None if timepixr_value is None else _safe_float(timepixr_value)
            if timepixr_value is not None and (
                timepixr is None or not 0.0 <= timepixr <= 1.0
            ):
                return None, None
            if (
                timepixr is not None
                and not math.isclose(timepixr, 0.5, rel_tol=0.0, abs_tol=0.0)
                and (timedel_value is None or timedel <= 0)
            ):
                # A non-central reference requires a real bin width.  Treat a
                # missing/zero TIMEDEL as malformed rather than inventing a
                # zero correction that can select the wrong gain epoch.
                return None, None

            # Match the installed public FITSTimeseriesReader timing transform:
            # event times and t_start receive TIMEZERO plus the TIMEPIXR bin
            # reference correction.  Deriving the calibration epoch from raw
            # TSTART alone can otherwise be wrong by whole days.
            adjusted_tstart = tstart + timezero
            timing_sources = [str(tstart_source)]
            if timezero_value is not None:
                timing_sources.append(str(timezero_source))
            if timepixr is not None:
                adjusted_tstart += (0.5 - timepixr) * timedel
                timing_sources.extend(
                    [str(timepixr_source), str(timedel_source or "TIMEDEL default 0")]
                )
            if not math.isfinite(adjusted_tstart):
                return None, None

            time_unit_value, time_unit_source = cls._find_header_value(
                header_sources, ["TIMEUNIT"]
            )
            time_unit = (_clean_text(time_unit_value) or "s").casefold()
            seconds_per_unit = TIME_UNIT_SECONDS.get(time_unit)
            if seconds_per_unit is None:
                return None, None
            offset_days = adjusted_tstart * seconds_per_unit / 86400.0
            if not math.isfinite(offset_days):
                return None, None
            tstart_source = " + ".join(timing_sources)
            if time_unit_source is not None:
                tstart_source = (
                    f"{tstart_source} ({time_unit_source}={time_unit_value})"
                )
        else:
            explicit_t_start = _safe_float(getattr(event_list, "t_start", None))
            explicit_gti = getattr(event_list, "_gti", None)
            gti_start: Optional[float] = None
            if explicit_gti is not None:
                with np.errstate(over="ignore", invalid="ignore"):
                    gti_array = np.asarray(explicit_gti, dtype=float)
                if (
                    gti_array.ndim == 2
                    and gti_array.shape[0] > 0
                    and gti_array.shape[1] == 2
                ):
                    gti_start = _safe_float(gti_array[0, 0])
            times = np.asarray(getattr(event_list, "time", []), dtype=float)
            if explicit_t_start is not None:
                tstart = explicit_t_start
                tstart_source = "EventList.t_start"
            elif gti_start is not None:
                tstart = gti_start
                tstart_source = "EventList._gti start"
            elif times.size and np.isfinite(times).all():
                tstart = float(np.min(times))
                tstart_source = "minimum EventList.time"
            if tstart is not None:
                time_unit_value, time_unit_source = cls._find_header_value(
                    header_sources, ["TIMEUNIT"]
                )
                time_unit = (_clean_text(time_unit_value) or "s").casefold()
                seconds_per_unit = TIME_UNIT_SECONDS.get(time_unit)
                if seconds_per_unit is None:
                    return None, None
                offset_days = tstart * seconds_per_unit / 86400.0
                if time_unit_source is not None:
                    tstart_source = (
                        f"{tstart_source} ({time_unit_source}={time_unit_value})"
                    )
        if mjdref is not None and offset_days is not None:
            epoch = mjdref + offset_days
            if math.isfinite(epoch):
                if mjd_observation is not None:
                    comparison_tolerance = 8.0 * max(
                        abs(float(np.spacing(epoch))),
                        abs(float(np.spacing(mjd_observation))),
                    )
                    if abs(epoch - mjd_observation) > comparison_tolerance:
                        warning_list.append(
                            f"MJD-OBS ({mjd_observation:g} from "
                            f"{mjd_observation_source}) conflicts with the event-time "
                            f"reference epoch ({epoch:g}); calibration used MJDREF plus "
                            "the timing applied to EventList events."
                        )
                return epoch, f"{mjdref_source} + {tstart_source} in days"
        if mjd_observation is not None:
            return mjd_observation, mjd_observation_source
        return None, None

    def convert_pi_to_energy(
        self,
        *,
        pi_values: Optional[Sequence[float]] = None,
        event_list_name: Optional[str] = None,
        mission_override: Optional[str] = None,
        instrument_override: Optional[str] = None,
        mode_override: Optional[str] = None,
        epoch_mjd: Optional[float] = None,
        detector_ids: Optional[Sequence[int]] = None,
        save_as: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run a public Stingray rough PI-to-energy conversion.

        This method never mutates a loaded source.  ``save_as`` atomically adds
        a detached EventList with the original PI channels and new energy array.
        """
        if (pi_values is None) == (event_list_name is None):
            return self._failure(
                "Provide exactly one PI source: pasted PI values or a loaded EventList"
            )
        if save_as is not None and event_list_name is None:
            return self._failure(
                "Save as is available only for a loaded EventList source"
            )

        warnings = [
            "APPROXIMATE conversion: rough mission relations are not a substitute for "
            "RMF-calibrated energy conversion. Use RMF calibration in General I/O for "
            "precise energies."
        ]
        source_event = None
        identified: dict[str, Any]
        if event_list_name is not None:
            source_event, identified, identify_warnings, error = (
                self._identify_event_list(
                    event_list_name,
                    max_events=MAX_ARRAY_INPUT,
                    mission_override=mission_override,
                    instrument_override=instrument_override,
                    mode_override=mode_override,
                )
            )
            if error:
                return self._failure(error, warnings=warnings)
            assert source_event is not None and identified is not None
            warnings.extend(identify_warnings)
            raw_pi = getattr(source_event, "pi", None)
            if raw_pi is None:
                return self._failure(
                    f"EventList '{event_list_name}' has no PI/channel data to convert",
                    warnings=warnings,
                )
            input_source = {"type": "loaded_event_list", "name": event_list_name}
        else:
            try:
                identified, identify_warnings = self._identify_parts(
                    source={"type": "pasted_pi_values"},
                    header_sources=[],
                    mission_override=mission_override,
                    instrument_override=instrument_override,
                    mode_override=mode_override,
                )
            except ValueError as exc:
                return self._failure(str(exc), warnings=warnings)
            warnings.extend(identify_warnings)
            raw_pi = pi_values
            input_source = {"type": "pasted_pi_values"}

        mapping_validation_error = identified.get("mapping_validation_error")
        if mapping_validation_error is not None:
            return self._failure(mapping_validation_error, warnings=warnings)

        pi_array, error = self._validate_pi(raw_pi)
        if error:
            return self._failure(error, warnings=warnings)
        assert pi_array is not None
        if source_event is not None:
            time_array = np.asarray(getattr(source_event, "time", []))
            if time_array.ndim != 1:
                return self._failure(
                    f"EventList '{event_list_name}' time data must be one-dimensional",
                    warnings=warnings,
                )
            if time_array.size != pi_array.size:
                return self._failure(
                    f"EventList '{event_list_name}' has {time_array.size:,} time value(s) "
                    f"but {pi_array.size:,} PI/channel value(s); conversion requires "
                    "one channel per event",
                    warnings=warnings,
                )

        mission = identified["mission"]["value"]
        instrument = identified["instrument"]["value"]
        if mission is None:
            return self._failure(
                "Mission metadata is missing; supply a clearly labelled mission override",
                warnings=warnings,
            )
        mission_key = mission.casefold()

        parsed_epoch = None
        requested_epoch = None
        epoch_source = None
        if epoch_mjd is not None:
            requested_epoch = _safe_float(epoch_mjd)
            if requested_epoch is None or requested_epoch <= 0:
                return self._failure(
                    "Epoch MJD must be a positive finite value", warnings=warnings
                )
            if mission_key == "xte":
                parsed_epoch = requested_epoch
                epoch_source = "request.epoch_mjd"
            else:
                warnings.append(
                    f"Epoch MJD was supplied but is not used by the {mission} rough "
                    "conversion."
                )
        elif mission_key == "xte" and source_event is not None:
            parsed_epoch, epoch_source = self._derive_event_epoch(
                source_event, warnings
            )

        detector_array = None
        detector_source = None
        if mission_key == "xte":
            if instrument is None:
                return self._failure(
                    "RXTE rough conversion requires instrument metadata; only PCA is supported",
                    warnings=warnings,
                )
            if instrument.casefold() != "pca":
                return self._failure(
                    f"RXTE instrument '{instrument}' is unsupported for rough conversion; "
                    "Stingray 2.2.10 supports PCA only",
                    warnings=warnings,
                )
            if parsed_epoch is None:
                return self._failure(
                    "RXTE PCA rough conversion requires the observation epoch in MJD",
                    warnings=warnings,
                )
            if not (
                XTE_PCA_EPOCH_MJD_MIN_EXCLUSIVE
                < parsed_epoch
                <= XTE_PCA_EPOCH_MJD_MAX_INCLUSIVE
            ):
                return self._failure(
                    "RXTE PCA rough conversion supports epochs only in the calibrated "
                    f"range {XTE_PCA_EPOCH_MJD_MIN_EXCLUSIVE:g} < MJD <= "
                    f"{XTE_PCA_EPOCH_MJD_MAX_INCLUSIVE:g}; supply an epoch within "
                    "that range",
                    warnings=warnings,
                )
            if np.any(pi_array > 255):
                index = int(np.flatnonzero(pi_array > 255)[0])
                return self._failure(
                    f"PI values[{index}] must be in the RXTE PCA channel range 0-255",
                    warnings=warnings,
                )

            source_detector = (
                getattr(source_event, "detector_id", None)
                if source_event is not None
                else None
            )
            if source_detector is not None and detector_ids is not None:
                source_checked, source_error = self._validate_detector_ids(
                    source_detector, expected_size=pi_array.size
                )
                requested_checked, requested_error = self._validate_detector_ids(
                    detector_ids, expected_size=pi_array.size
                )
                if source_error:
                    return self._failure(source_error, warnings=warnings)
                if requested_error:
                    return self._failure(requested_error, warnings=warnings)
                if not np.array_equal(source_checked, requested_checked):
                    return self._failure(
                        "Detector IDs are already present on the EventList; a conflicting "
                        "request override is not allowed",
                        warnings=warnings,
                    )
                detector_array = source_checked
                detector_source = "EventList.detector_id"
            else:
                detector_input = (
                    source_detector if source_detector is not None else detector_ids
                )
                if detector_input is None:
                    return self._failure(
                        "RXTE PCA rough conversion requires detector IDs (PCU 0-4), one to "
                        "broadcast or one per PI value",
                        warnings=warnings,
                    )
                detector_array, detector_error = self._validate_detector_ids(
                    detector_input, expected_size=pi_array.size
                )
                if detector_error:
                    return self._failure(detector_error, warnings=warnings)
                detector_source = (
                    "EventList.detector_id"
                    if source_detector is not None
                    else "request.detector_ids"
                )
        elif detector_ids is not None:
            warnings.append(
                f"Detector IDs were supplied but are not used by the {mission} rough conversion."
            )

        if mission_key == "axaf" and np.any(pi_array < 1):
            index = int(np.flatnonzero(pi_array < 1)[0])
            return self._failure(
                f"PI values[{index}] must be at least 1 for the AXAF/Chandra rough "
                "conversion so the approximate photon energy remains non-negative",
                warnings=warnings,
            )

        try:
            conversion = get_rough_conversion_function(
                mission,
                instrument=instrument,
                epoch=parsed_epoch,
            )
            if mission_key == "xte":
                assert detector_array is not None
                energies = conversion(pi_array, detector_id=detector_array)
            else:
                energies = conversion(pi_array)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            if mission_key == "xte":
                message = f"RXTE PCA rough conversion is unavailable for the supplied instrument/epoch: {exc}"
            else:
                message = (
                    f"No public rough PI-to-energy conversion is available for mission "
                    f"'{mission}': {exc}"
                )
            return self._failure(message, warnings=warnings)

        energy_array = np.asarray(energies, dtype=float)
        if energy_array.shape != pi_array.shape:
            return self._failure(
                "Stingray returned an unexpected energy-array shape", warnings=warnings
            )
        bad_energy = np.flatnonzero(~np.isfinite(energy_array))
        if bad_energy.size:
            warnings.append(
                f"Stingray returned {bad_energy.size:,} non-finite approximate energy "
                "value(s); JSON previews represent those values as null."
            )
        negative_energy = np.flatnonzero(energy_array < 0)
        if negative_energy.size:
            index = int(negative_energy[0])
            return self._failure(
                "Stingray returned a negative approximate photon energy at PI value "
                f"index {index}; the result was withheld",
                warnings=warnings,
            )

        detector_parameters = None
        if detector_array is not None:
            canonical_detector_bytes = np.asarray(detector_array, dtype="<i8").tobytes(
                order="C"
            )
            detector_parameters = {
                "source": detector_source,
                "count": int(detector_array.size),
                "sha256_int64_le": hashlib.sha256(canonical_detector_bytes).hexdigest(),
                "values": (
                    detector_array.tolist()
                    if detector_array.size <= PREVIEW_ROWS
                    else None
                ),
                "preview": detector_array[:PREVIEW_ROWS].tolist(),
                "preview_truncated": bool(detector_array.size > PREVIEW_ROWS),
            }

        provenance = operation_provenance(
            "mission_io.approximate_pi_to_energy",
            input_source=input_source,
            parameters={
                "mission": mission,
                "instrument": instrument,
                "mode": identified["mode"]["value"],
                "epoch_mjd": parsed_epoch,
                "requested_epoch_mjd": requested_epoch,
                "detector_ids": detector_parameters,
            },
            conversion_type="rough_approximate",
            approximate=True,
            energy_unit="keV",
            precise_calibration_path="RMF-based conversion in General I/O",
        )

        saved_name = None
        if save_as is not None:
            name_error = validate_derived_name(save_as)
            if name_error:
                return self._failure(name_error, warnings=warnings)
            assert source_event is not None and event_list_name is not None
            source_event.energy = energy_array.copy()
            source_event.pi = np.asarray(source_event.pi).copy()
            if detector_array is not None:
                source_event.detector_id = detector_array.copy()
            if not _clean_text(getattr(source_event, "mission", None)):
                source_event.mission = mission
            if instrument is not None and not _clean_text(
                getattr(source_event, "instr", None)
            ):
                source_event.instr = instrument
            provenance_json = json.dumps(
                json_safe(provenance, warnings), allow_nan=False, sort_keys=True
            )
            source_event.mission_io_conversion_type = "rough_approximate"
            source_event.mission_io_source_name = event_list_name
            source_event.mission_io_mission = mission
            source_event.mission_io_instrument = instrument or ""
            source_event.mission_io_epoch_mjd = parsed_epoch
            source_event.mission_io_provenance_json = provenance_json
            note = (
                f"Mission I/O: APPROXIMATE rough PI-to-energy conversion from "
                f"'{event_list_name}' ({mission}; precise path: RMF in General I/O)."
            )
            old_notes = _clean_text(getattr(source_event, "notes", None))
            source_event.notes = f"{old_notes}\n{note}" if old_notes else note
            if not self.state.add_event_data_if_absent(save_as, source_event):
                return self._failure(
                    f"Destination EventList name '{save_as}' already exists; choose a unique name",
                    warnings=warnings,
                )
            saved_name = save_as

        preview_count = min(pi_array.size, PREVIEW_ROWS)
        rows = []
        for index in range(preview_count):
            row: dict[str, Any] = {
                "index": index,
                "pi": int(pi_array[index]),
                "energy_kev": (
                    float(energy_array[index])
                    if math.isfinite(float(energy_array[index]))
                    else None
                ),
            }
            if detector_array is not None:
                row["detector_id"] = int(detector_array[index])
            rows.append(row)

        data = {
            "label": "APPROXIMATE rough PI-to-energy conversion",
            "conversion_type": "rough_approximate",
            "approximate": True,
            "energy_unit": "keV",
            "mission": identified["mission"],
            "instrument": identified["instrument"],
            "mode": identified["mode"],
            "dependencies": {
                "mission": {"required": True, "value": mission},
                "instrument": {
                    "required": mission_key == "xte",
                    "used": mission_key == "xte",
                    "value": instrument,
                },
                "epoch_mjd": {
                    "required": mission_key == "xte",
                    "used": mission_key == "xte",
                    "value": parsed_epoch,
                    "requested_value": requested_epoch,
                    "source": epoch_source,
                },
                "detector_id": {
                    "required": mission_key == "xte",
                    "used": mission_key == "xte",
                    "source": detector_source,
                },
            },
            "count": int(pi_array.size),
            "rows": rows,
            "preview_count": preview_count,
            "preview_truncated": preview_count < pi_array.size,
            "saved_event_list": saved_name,
            "precise_calibration": {
                "method": "RMF-based PI-to-energy conversion",
                "location": "General I/O",
            },
            "provenance": provenance,
        }
        safe_data = json_safe(data, warnings)
        safe_data["warnings"] = list(warnings)
        return self.create_result(
            success=True,
            data=safe_data,
            message=(
                f"Approximately converted {pi_array.size} PI channel(s) to keV"
                + (f" and saved EventList '{saved_name}'" if saved_name else "")
            ),
            error=None,
            warnings=warnings,
        )

    def interpret_selected_fits(
        self,
        *,
        file_path: str,
        file_grant: str,
        mission_override: Optional[str] = None,
        instrument_override: Optional[str] = None,
        mode_override: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run supported mission-specific FITS interpretation on a bounded copy."""
        try:
            with open_verified_read_grant(file_path, file_grant) as granted:
                size = validate_file_size(
                    granted.stream,
                    MAX_INTERPRET_FITS_BYTES,
                    "Mission-specific interpretation input",
                )
                identified, warnings, error = self._identify_fits(
                    granted.stream,
                    display_path=str(granted.path),
                    size_bytes=size,
                    mission_override=mission_override,
                    instrument_override=instrument_override,
                    mode_override=mode_override,
                )
                if error:
                    return self._failure(error)
                assert identified is not None
                mission = identified["mission"]["value"]
                if mission is None:
                    return self._failure(
                        "Mission metadata is missing; supply a mission override before interpretation",
                        warnings=warnings,
                    )
                interpreter = mission_specific_event_interpretation(mission)
                if interpreter is None:
                    return self._failure(
                        f"Stingray 2.2.10 has no specialized event interpretation for mission "
                        f"'{mission}'. Only XTE is currently supported.",
                        warnings=warnings,
                    )
                instrument = _clean_text(identified["instrument"]["value"])
                if mission.casefold() == "xte":
                    if instrument is None:
                        return self._failure(
                            "XTE specialized interpretation requires instrument metadata; only "
                            "PCA science-event FITS is supported.",
                            warnings=warnings,
                        )
                    if instrument.casefold() != "pca":
                        return self._failure(
                            f"XTE instrument '{instrument}' is unsupported for specialized "
                            "interpretation; only PCA science-event FITS is supported.",
                            warnings=warnings,
                        )

                with duplicate_binary_stream(granted.stream) as fits_stream:
                    hdulist_context = fits.open(
                        fits_stream,
                        mode="readonly",
                        memmap=True,
                        lazy_load_hdus=True,
                    )
                    with hdulist_context as hdulist:
                        if len(hdulist) > MAX_FITS_HDUS:
                            return self._failure(
                                f"FITS file has {len(hdulist):,} HDUs; the interpretation cap is "
                                f"{MAX_FITS_HDUS:,}",
                                warnings=warnings,
                            )
                        if "XTE_SE" not in hdulist:
                            return self._failure(
                                "The selected XTE file has no XTE_SE extension. Stingray's public "
                                "interpreter currently supports science-event files only.",
                                warnings=warnings,
                            )
                        source_hdu = hdulist["XTE_SE"]
                        row_count = int(source_hdu.header.get("NAXIS2", 0))
                        if row_count > MAX_ARRAY_INPUT:
                            return self._failure(
                                f"XTE_SE contains {row_count:,} rows; the read-only interpretation "
                                f"cap is {MAX_ARRAY_INPUT:,}",
                                warnings=warnings,
                            )
                        if (
                            source_hdu.data is None
                            or "PHA" not in source_hdu.columns.names
                        ):
                            return self._failure(
                                "The XTE_SE extension has no PHA column to interpret",
                                warnings=warnings,
                            )
                        copied_hdu = source_hdu.copy()
                        original_pha = np.asarray(copied_hdu.data["PHA"]).copy()

            interpreted_hdu = interpreter(copied_hdu)
            interpreted_pha = np.asarray(interpreted_hdu.data["PHA"])
            if interpreted_pha.shape != original_pha.shape:
                return self._failure(
                    "Stingray returned an unexpected interpreted PHA shape",
                    warnings=warnings,
                )
            changed = original_pha != interpreted_pha
            preview_count = min(original_pha.size, PREVIEW_ROWS)
            rows = [
                {
                    "index": index,
                    "original_pha": int(original_pha[index]),
                    "interpreted_pha": int(interpreted_pha[index]),
                    "changed": bool(changed[index]),
                }
                for index in range(preview_count)
            ]
            warnings.append(
                "Read-only interpretation changes local RXTE PHA channel encoding on an "
                "in-memory copy; it does not calibrate channels to energy."
            )
            provenance = operation_provenance(
                "mission_io.mission_specific_event_interpretation",
                input_source=identified["source"],
                parameters={
                    "mission": mission,
                    "instrument": identified["instrument"]["value"],
                    "mode": identified["mode"]["value"],
                },
                read_only=True,
                source_modified=False,
            )
            data = {
                "label": "Read-only mission-specific event interpretation",
                "mission": identified["mission"],
                "instrument": identified["instrument"],
                "mode": identified["mode"],
                "supported_scope": "XTE PCA science-event FITS (XTE_SE, TEVTB2 and PHA)",
                "read_only": True,
                "source_modified": False,
                "hdu": "XTE_SE",
                "event_count": int(original_pha.size),
                "changed_count": int(np.count_nonzero(changed)),
                "original_pha_range": (
                    [int(np.min(original_pha)), int(np.max(original_pha))]
                    if original_pha.size
                    else None
                ),
                "interpreted_pha_range": (
                    [int(np.min(interpreted_pha)), int(np.max(interpreted_pha))]
                    if interpreted_pha.size
                    else None
                ),
                "rows": rows,
                "preview_count": preview_count,
                "preview_truncated": preview_count < original_pha.size,
                "provenance": provenance,
            }
            safe_data = json_safe(data, warnings)
            safe_data["warnings"] = list(warnings)
            return self.create_result(
                success=True,
                data=safe_data,
                message="Mission-specific FITS interpretation summarized without changing the file",
                error=None,
                warnings=warnings,
            )
        except (
            PermissionError,
            FileNotFoundError,
            ValueError,
            OSError,
            KeyError,
        ) as exc:
            return self._failure(str(exc))
        except Exception as exc:
            return self.handle_error(exc, "Interpreting selected mission FITS file")
