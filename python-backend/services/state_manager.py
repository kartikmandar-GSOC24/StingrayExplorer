"""
State management for Stingray Explorer backend.

Manages loaded data including EventLists, Lightcurves, and analysis results.
"""

import copy
import gc
import logging
import sys
import threading
from itertools import chain
from typing import Any, Dict, List, Optional

import numpy as np
from astropy import units as u
from astropy.table import Column
from astropy.utils.masked import Masked

logger = logging.getLogger(__name__)


def _bounded_utf8_size(value: str, limit: Optional[int]) -> int:
    """Count UTF-8 bytes without allocating an encoded copy of the full string."""
    if limit is not None and len(value) > limit:
        # Every Unicode code point occupies at least one UTF-8 byte.
        return limit + 1

    total = 0
    for offset in range(0, len(value), 4096):
        total += len(value[offset : offset + 4096].encode("utf-8"))
        if limit is not None and total > limit:
            return limit + 1
    return total


def _bounded_key_size(value: Any, limit: Optional[int]) -> int:
    """Estimate a mapping key without constructing an unbounded string form."""
    if isinstance(value, str):
        return _bounded_utf8_size(value, limit)
    if isinstance(value, (bytes, bytearray)):
        size = len(value)
        return min(size, limit + 1) if limit is not None else size
    size = max(32, int(sys.getsizeof(value)))
    return min(size, limit + 1) if limit is not None else size


def _object_payload_items(value: np.ndarray) -> Any:
    """Return referenced object values or reject opaque structured references."""
    if not value.dtype.hasobject:
        return ()
    if value.dtype.kind != "O":
        raise ValueError(
            "Stored state contains a structured dtype with object references and "
            "cannot be copied safely"
        )
    return enumerate(np.asarray(value).flat)


def _precopy_metrics(
    value: Any,
    *,
    max_rows: Optional[int],
    max_cells: Optional[int],
    max_bytes: Optional[int],
    active: Optional[set[int]] = None,
) -> tuple[int, int, int]:
    """Estimate rows, scalar cells, and bytes without copying nested state."""
    if active is None:
        active = set()
    if value is None or isinstance(value, (bool, float, np.number)):
        return 0, 1, 32
    if type(value) is int:
        bit_length = abs(value).bit_length()
        decimal_bytes = 1 + (bit_length * 30_103) // 100_000
        if value < 0:
            decimal_bytes += 1
        return 0, 1, max(32, int(sys.getsizeof(value)), decimal_bytes)
    if isinstance(value, str):
        return 0, 1, _bounded_utf8_size(value, max_bytes)
    if isinstance(value, (bytes, bytearray)):
        return 0, 1, len(value)
    if type(value) is np.ndarray and not value.dtype.hasobject:
        rows = int(value.shape[0]) if value.ndim else 0
        return rows, int(value.size), int(value.nbytes)

    identity = id(value)
    if identity in active:
        raise ValueError(
            "Stored state contains a cyclic value and cannot be copied safely"
        )
    active.add(identity)
    try:
        if isinstance(value, Masked):
            own_rows = int(value.shape[0]) if value.ndim else 0
            own_cells = int(value.size)
            own_bytes = int(value.nbytes) + int(np.asarray(value.mask).nbytes)
            unit = getattr(value, "unit", None)
            data_items = _object_payload_items(value)
            items = chain(
                data_items,
                (("unit", unit.to_string() if unit is not None else None),),
            )
        elif isinstance(value, u.Quantity):
            own_rows = int(value.shape[0]) if value.ndim else 0
            own_cells = int(value.size)
            own_bytes = int(value.nbytes)
            data_items = _object_payload_items(value)
            items = chain(data_items, (("unit", value.unit.to_string()),))
        elif isinstance(value, Column):
            own_rows = int(value.shape[0]) if value.ndim else 0
            own_cells = int(value.size)
            own_bytes = int(value.nbytes)
            column_items: list[tuple[Any, Any]] = [
                ("metadata", value.meta),
                ("description", value.description),
                ("format", value.format),
                (
                    "unit",
                    value.unit.to_string() if value.unit is not None else None,
                ),
            ]
            if isinstance(value, np.ma.MaskedArray):
                mask = np.ma.getmask(value)
                if mask is not np.ma.nomask:
                    own_bytes += int(np.asarray(mask).nbytes)
                column_items.append(("fill_value", value.fill_value))
            data_items = _object_payload_items(value)
            items = chain(data_items, column_items)
        elif type(value) is np.ndarray:
            own_rows = int(value.shape[0]) if value.ndim else 0
            own_cells = int(value.size)
            own_bytes = int(value.nbytes)
            if max_rows is not None and own_rows > max_rows:
                return own_rows, own_cells, own_bytes
            items = _object_payload_items(value)
        elif isinstance(value, np.ndarray):
            own_rows = int(value.shape[0]) if value.ndim else 0
            own_cells = int(value.size)
            own_bytes = int(value.nbytes)
            if max_rows is not None and own_rows > max_rows:
                return own_rows, own_cells, own_bytes
            data_items = _object_payload_items(value)
            items = chain(data_items, vars(value).items())
        elif isinstance(value, dict):
            items = value.items()
            own_rows = 0
            own_cells = 0
            own_bytes = 0
        elif isinstance(value, (list, tuple)):
            own_rows = len(value)
            own_cells = 0
            own_bytes = 0
            if max_rows is not None and own_rows > max_rows:
                return own_rows, own_cells, own_bytes
            items = enumerate(value)
        elif hasattr(value, "colnames") and hasattr(value, "meta"):
            own_rows = len(value)
            own_cells = 0
            own_bytes = 0
            if max_rows is not None and own_rows > max_rows:
                return own_rows, own_cells, own_bytes
            items = chain(
                ((name, value[name]) for name in value.colnames),
                (("metadata", value.meta),),
            )
        elif hasattr(value, "__dict__"):
            items = vars(value).items()
            own_rows = 0
            own_cells = 0
            own_bytes = 0
        else:
            # Avoid invoking an arbitrary, potentially huge ``__str__`` only to
            # estimate a value that will be rejected before deepcopy.
            return 0, 1, max(32, int(sys.getsizeof(value)))

        observed_rows = own_rows
        cells = own_cells
        estimated_bytes = own_bytes
        if max_rows is not None and observed_rows > max_rows:
            return observed_rows, cells, estimated_bytes
        if max_cells is not None and cells > max_cells:
            return observed_rows, cells, estimated_bytes
        if max_bytes is not None and estimated_bytes > max_bytes:
            return observed_rows, cells, estimated_bytes
        for key, item in items:
            remaining_bytes = (
                None if max_bytes is None else max(0, max_bytes - estimated_bytes)
            )
            key_bytes = _bounded_key_size(key, remaining_bytes)
            estimated_bytes += key_bytes
            if max_bytes is not None and estimated_bytes > max_bytes:
                return observed_rows, cells, estimated_bytes
            child_rows, child_cells, child_bytes = _precopy_metrics(
                item,
                max_rows=max_rows,
                max_cells=(None if max_cells is None else max(0, max_cells - cells)),
                max_bytes=(
                    None if max_bytes is None else max(0, max_bytes - estimated_bytes)
                ),
                active=active,
            )
            observed_rows = max(observed_rows, child_rows)
            cells += child_cells
            estimated_bytes += child_bytes
            if max_rows is not None and observed_rows > max_rows:
                return observed_rows, cells, estimated_bytes
            if max_cells is not None and cells > max_cells:
                return observed_rows, cells, estimated_bytes
            if max_bytes is not None and estimated_bytes > max_bytes:
                return observed_rows, cells, estimated_bytes
        return observed_rows, cells, estimated_bytes
    finally:
        active.remove(identity)


def _precopy_column_count(value: Any) -> int:
    """Count top-level tabular columns without constructing a Table."""
    if hasattr(value, "colnames"):
        return len(value.colnames)
    if isinstance(value, dict):
        reserved = {"warnings", "provenance", "parameters", "metadata"}
        metadata = value.get("metadata")
        if isinstance(metadata, dict):
            declared = metadata.get("non_column_fields", [])
            if isinstance(declared, (list, tuple)):
                reserved.update(name for name in declared if isinstance(name, str))
        count = 0
        for key, item in value.items():
            if key in reserved or isinstance(item, dict):
                continue
            # Do not call np.asarray here: a large Python sequence would be
            # duplicated before the row/cell cap has run.  One top-level
            # sequence is conservatively one candidate column; detailed shape
            # validation remains in the I/O service after the cap.
            if isinstance(item, (list, tuple)):
                count += 1
            elif isinstance(item, np.ndarray) and item.ndim == 1:
                count += 1
            elif getattr(item, "ndim", 0) == 1:
                count += 1
        return count
    if hasattr(value, "array_attrs") and hasattr(value, "main_array_attr"):
        main_name = str(value.main_array_attr)
        main_value = getattr(value, main_name, None)
        try:
            main_rows = len(main_value)
        except TypeError:
            main_rows = None
        names = {main_name} if main_rows is not None else set()
        # Stingray's array_attrs() calls np.asanyarray on every attribute.  A
        # user-supplied Python list could therefore be materialized before the
        # allocation cap.  Inspect stored values and lengths only here.
        for name, item in vars(value).items():
            if isinstance(item, (str, bytes, bytearray, dict)) or item is None:
                continue
            if isinstance(item, np.ndarray):
                aligned = item.ndim >= 1 and len(item) == main_rows
            elif isinstance(item, (list, tuple)):
                aligned = len(item) == main_rows
            else:
                aligned = getattr(item, "ndim", 0) == 1 and len(item) == main_rows
            if aligned:
                names.add(str(name))
        return len(names)
    return 0


def _enforce_precopy_caps(
    value: Any,
    label: str,
    *,
    max_rows: Optional[int],
    max_cells: Optional[int],
    max_bytes: Optional[int],
    max_columns: Optional[int] = None,
) -> None:
    if max_columns is not None:
        columns = _precopy_column_count(value)
        if columns > max_columns:
            raise ValueError(
                f"{label} has {columns:,} columns; the operation column cap is "
                f"{max_columns:,}"
            )
    rows, cells, estimated_bytes = _precopy_metrics(
        value,
        max_rows=max_rows,
        max_cells=max_cells,
        max_bytes=max_bytes,
    )
    if max_rows is not None and rows > max_rows:
        raise ValueError(
            f"{label} has {rows:,} rows; the operation cap is {max_rows:,}"
        )
    if max_cells is not None and cells > max_cells:
        raise ValueError(
            f"{label} has at least {cells:,} cells; the operation cell cap is "
            f"{max_cells:,}"
        )
    if max_bytes is not None and estimated_bytes > max_bytes:
        raise ValueError(
            f"{label} is estimated at least {estimated_bytes / 1024**2:.1f} MiB; "
            f"the operation size cap is {max_bytes / 1024**2:.1f} MiB"
        )


def _force_garbage_collection() -> int:
    """
    Force garbage collection across all generations.

    This is more thorough than a single gc.collect() call.
    See: https://docs.python.org/3/library/gc.html

    Returns:
        Total number of unreachable objects collected
    """
    collected = 0
    # Collect all generations (0, 1, 2) for thorough cleanup
    for generation in range(3):
        collected += gc.collect(generation)
    return collected


class StateManager:
    """
    Thread-safe state manager for Stingray Explorer.

    Manages the application state including loaded event lists,
    lightcurves, and analysis results.
    """

    def __init__(self):
        """Initialize the state manager."""
        self._event_data: Dict[str, Any] = {}
        self._lightcurve_data: Dict[str, Any] = {}
        self._spectrum_data: Dict[str, Any] = {}
        self._analysis_results: Dict[str, Any] = {}
        self._lock = threading.RLock()

    # Event data methods
    def add_event_data(self, name: str, event_list: Any) -> None:
        """
        Add an event list to state.

        Args:
            name: Unique name for the event list
            event_list: Stingray EventList object
        """
        with self._lock:
            self._event_data[name] = event_list

    def add_event_data_if_absent(self, name: str, event_list: Any) -> bool:
        """Atomically add an EventList without replacing an existing name."""
        with self._lock:
            if name in self._event_data:
                return False
            self._event_data[name] = event_list
            return True

    def get_event_data(self, name: Optional[str] = None) -> Any:
        """
        Get event list(s) from state.

        Args:
            name: Name of specific event list, or None for all

        Returns:
            Single EventList if name provided, otherwise list of (name, event_list) tuples
        """
        with self._lock:
            if name is not None:
                return self._event_data.get(name)
            return list(self._event_data.items())

    def copy_event_data(
        self,
        name: str,
        max_events: Optional[int] = None,
        max_columns: Optional[int] = None,
        max_cells: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> Any:
        """Return a detached snapshot of an EventList, or ``None`` if absent.

        The copy is made while holding the state lock so a concurrent delete or
        clear cannot null the stored arrays halfway through the snapshot.  When
        ``max_events`` is supplied, the stored time-array length is checked
        before deepcopy allocates another full EventList.
        """
        with self._lock:
            event_list = self._event_data.get(name)
            if event_list is not None and any(
                limit is not None
                for limit in (max_events, max_columns, max_cells, max_bytes)
            ):
                _enforce_precopy_caps(
                    event_list,
                    f"EventList '{name}'",
                    max_rows=max_events,
                    max_columns=max_columns,
                    max_cells=max_cells,
                    max_bytes=max_bytes,
                )
            return copy.deepcopy(event_list) if event_list is not None else None

    def has_event_data(self, name: str) -> bool:
        """Check if an event list with given name exists."""
        with self._lock:
            return name in self._event_data

    def remove_event_data(self, name: str) -> bool:
        """
        Remove an event list from state and free memory.

        Args:
            name: Name of the event list to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if name in self._event_data:
                # Pop the object from dict (removes reference from dict)
                event_list = self._event_data.pop(name)
                # Explicitly set internal arrays to None to help GC
                # This breaks any internal references
                if hasattr(event_list, "time"):
                    event_list.time = None
                if hasattr(event_list, "energy"):
                    event_list.energy = None
                if hasattr(event_list, "pi"):
                    event_list.pi = None
                if hasattr(event_list, "gti"):
                    event_list.gti = None
                # Delete the local reference
                del event_list
                # Force garbage collection
                collected = _force_garbage_collection()
                logger.debug(
                    f"Removed event list '{name}', collected {collected} objects"
                )
                return True
            return False

    def list_event_names(self) -> List[str]:
        """Get list of all event list names."""
        with self._lock:
            return list(self._event_data.keys())

    def clear_event_data(self) -> int:
        """
        Clear all event lists from state and free memory.

        Returns:
            Number of event lists cleared
        """
        with self._lock:
            count = len(self._event_data)
            # Clear internal arrays for each event list to help GC
            for event_list in self._event_data.values():
                if hasattr(event_list, "time"):
                    event_list.time = None
                if hasattr(event_list, "energy"):
                    event_list.energy = None
                if hasattr(event_list, "pi"):
                    event_list.pi = None
                if hasattr(event_list, "gti"):
                    event_list.gti = None
            # Clear the dictionary
            self._event_data.clear()
            # Force garbage collection
            collected = _force_garbage_collection()
            logger.debug(f"Cleared {count} event lists, collected {collected} objects")
            return count

    # Lightcurve data methods
    def add_lightcurve_data(self, name: str, lightcurve: Any) -> None:
        """
        Add a lightcurve to state.

        Args:
            name: Unique name for the lightcurve
            lightcurve: Stingray Lightcurve object
        """
        with self._lock:
            self._lightcurve_data[name] = lightcurve

    def add_lightcurve_data_if_absent(self, name: str, lightcurve: Any) -> bool:
        """Atomically add a Lightcurve without replacing an existing name."""
        with self._lock:
            if name in self._lightcurve_data:
                return False
            self._lightcurve_data[name] = lightcurve
            return True

    def get_lightcurve_data(self, name: Optional[str] = None) -> Any:
        """
        Get lightcurve(s) from state.

        Args:
            name: Name of specific lightcurve, or None for all

        Returns:
            Single Lightcurve if name provided, otherwise list of (name, lightcurve) tuples
        """
        with self._lock:
            if name is not None:
                return self._lightcurve_data.get(name)
            return list(self._lightcurve_data.items())

    def copy_lightcurve_data(
        self,
        name: str,
        max_points: Optional[int] = None,
        max_columns: Optional[int] = None,
        max_cells: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> Any:
        """Return a detached Lightcurve snapshot after an optional pre-copy cap."""
        with self._lock:
            lightcurve = self._lightcurve_data.get(name)
            if lightcurve is not None and any(
                limit is not None
                for limit in (max_points, max_columns, max_cells, max_bytes)
            ):
                _enforce_precopy_caps(
                    lightcurve,
                    f"Lightcurve '{name}'",
                    max_rows=max_points,
                    max_columns=max_columns,
                    max_cells=max_cells,
                    max_bytes=max_bytes,
                )
            return copy.deepcopy(lightcurve) if lightcurve is not None else None

    def has_lightcurve_data(self, name: str) -> bool:
        """Check if a lightcurve with given name exists."""
        with self._lock:
            return name in self._lightcurve_data

    def remove_lightcurve_data(self, name: str) -> bool:
        """Remove a lightcurve from state and free memory."""
        with self._lock:
            if name in self._lightcurve_data:
                lc = self._lightcurve_data.pop(name)
                # Clear numpy arrays
                if hasattr(lc, "time"):
                    lc.time = None
                if hasattr(lc, "counts"):
                    lc.counts = None
                if hasattr(lc, "count_err"):
                    lc.count_err = None
                del lc
                _force_garbage_collection()
                return True
            return False

    def list_lightcurve_names(self) -> List[str]:
        """Get list of all lightcurve names."""
        with self._lock:
            return list(self._lightcurve_data.keys())

    # Spectrum data methods
    def add_spectrum_data(self, name: str, spectrum: Any) -> None:
        """Add a spectrum to state."""
        with self._lock:
            self._spectrum_data[name] = spectrum

    def add_spectrum_data_if_absent(self, name: str, spectrum: Any) -> bool:
        """Atomically add a spectrum without replacing an existing name."""
        with self._lock:
            if name in self._spectrum_data:
                return False
            self._spectrum_data[name] = spectrum
            return True

    def get_spectrum_data(self, name: Optional[str] = None) -> Any:
        """Get spectrum(s) from state."""
        with self._lock:
            if name is not None:
                return self._spectrum_data.get(name)
            return list(self._spectrum_data.items())

    def copy_spectrum_data(self, name: str) -> Any:
        """Return a detached spectrum snapshot, or ``None`` if absent."""
        with self._lock:
            spectrum = self._spectrum_data.get(name)
            return copy.deepcopy(spectrum) if spectrum is not None else None

    def has_spectrum_data(self, name: str) -> bool:
        """Check if a spectrum with given name exists."""
        with self._lock:
            return name in self._spectrum_data

    def remove_spectrum_data(self, name: str) -> bool:
        """Remove a spectrum from state and free memory."""
        with self._lock:
            if name in self._spectrum_data:
                spectrum = self._spectrum_data.pop(name)
                # Clear numpy arrays (Powerspectrum/Crossspectrum have freq, power, etc.)
                if hasattr(spectrum, "freq"):
                    spectrum.freq = None
                if hasattr(spectrum, "power"):
                    spectrum.power = None
                if hasattr(spectrum, "power_err"):
                    spectrum.power_err = None
                del spectrum
                _force_garbage_collection()
                return True
            return False

    def list_spectrum_names(self) -> List[str]:
        """Get list of all spectrum names."""
        with self._lock:
            return list(self._spectrum_data.keys())

    # Analysis results methods
    def add_analysis_result(self, name: str, result: Any) -> None:
        """Add an analysis result to state."""
        with self._lock:
            self._analysis_results[name] = result

    def add_analysis_result_if_absent(self, name: str, result: Any) -> bool:
        """Atomically add an analysis result without replacing a name."""
        with self._lock:
            if name in self._analysis_results:
                return False
            self._analysis_results[name] = result
            return True

    def get_analysis_result(self, name: Optional[str] = None) -> Any:
        """Get analysis result(s) from state."""
        with self._lock:
            if name is not None:
                return self._analysis_results.get(name)
            return list(self._analysis_results.items())

    def copy_analysis_result(
        self,
        name: str,
        max_rows: Optional[int] = None,
        max_columns: Optional[int] = None,
        max_cells: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> Any:
        """Return a detached analysis-result snapshot after an optional row cap."""
        with self._lock:
            result = self._analysis_results.get(name)
            if result is not None and any(
                limit is not None
                for limit in (max_rows, max_columns, max_cells, max_bytes)
            ):
                _enforce_precopy_caps(
                    result,
                    f"Analysis result '{name}'",
                    max_rows=max_rows,
                    max_columns=max_columns,
                    max_cells=max_cells,
                    max_bytes=max_bytes,
                )
            return copy.deepcopy(result) if result is not None else None

    def has_analysis_result(self, name: str) -> bool:
        """Check whether an analysis result name exists."""
        with self._lock:
            return name in self._analysis_results

    def list_analysis_result_names(self) -> List[str]:
        """Return all stored analysis-result names."""
        with self._lock:
            return list(self._analysis_results.keys())

    def remove_analysis_result(self, name: str) -> bool:
        """Remove an analysis result from state."""
        with self._lock:
            if name in self._analysis_results:
                del self._analysis_results[name]
                return True
            return False

    # Utility methods
    def clear_all(self) -> None:
        """Clear all state data and free memory."""
        with self._lock:
            # Clear internal arrays for all objects to help GC
            for event_list in self._event_data.values():
                for attr in ["time", "energy", "pi", "gti"]:
                    if hasattr(event_list, attr):
                        setattr(event_list, attr, None)

            for lc in self._lightcurve_data.values():
                for attr in ["time", "counts", "count_err"]:
                    if hasattr(lc, attr):
                        setattr(lc, attr, None)

            for spectrum in self._spectrum_data.values():
                for attr in ["freq", "power", "power_err"]:
                    if hasattr(spectrum, attr):
                        setattr(spectrum, attr, None)

            # Clear all dictionaries
            self._event_data.clear()
            self._lightcurve_data.clear()
            self._spectrum_data.clear()
            self._analysis_results.clear()

            # Force garbage collection
            collected = _force_garbage_collection()
            logger.debug(f"Cleared all state data, collected {collected} objects")

    def get_summary(self) -> Dict[str, int]:
        """Get a summary of stored data counts."""
        with self._lock:
            return {
                "event_lists": len(self._event_data),
                "lightcurves": len(self._lightcurve_data),
                "spectra": len(self._spectrum_data),
                "analysis_results": len(self._analysis_results),
            }
