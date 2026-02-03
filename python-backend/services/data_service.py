"""
Data service for EventList operations.

Handles loading, saving, and managing event lists.
Includes lazy loading support for large files.
"""

import asyncio
import os
import tempfile
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, AsyncGenerator, Dict, List, Optional

import numpy as np
import psutil
import requests
from astropy.io import fits
from stingray import EventList
from stingray.io import FITSTimeseriesReader

from .base_service import BaseService


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
        return arr.tolist() if hasattr(arr, 'tolist') else list(arr)


class DataService(BaseService):
    """
    Service for EventList data operations.

    Handles loading, saving, and managing event lists without any UI dependencies.
    """

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
            warnings.append("GTI is empty or missing - no valid observation intervals defined")
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

    def load_event_list(
        self,
        file_path: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
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

            # Capture Stingray/library warnings during loading
            stingray_warnings: List[str] = []
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter("always")  # Catch all warnings

                # Load the event list using Stingray
                event_list = EventList.read(
                    file_path,
                    fmt=fmt,
                    rmf_file=rmf_file,
                    additional_columns=additional_columns,
                    high_precision=high_precision,
                    skip_checks=skip_checks,
                )

                # Collect warning messages
                for w in caught_warnings:
                    stingray_warnings.append(str(w.message))

            # Add to state manager
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)

            # Prepare serializable summary (use helper for numpy type conversion)
            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max())
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
                "stingray_warnings": stingray_warnings if stingray_warnings else None,
            }

            # Build message with warnings if present
            message = f"EventList '{name}' loaded successfully ({len(event_list.time)} events)"
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"
            if stingray_warnings:
                message += f" [Stingray warnings: {len(stingray_warnings)}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except Exception as e:
            return self.handle_error(
                e, "Loading event list", file_path=file_path, name=name, fmt=fmt
            )

    def load_event_list_from_url(
        self,
        url: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        high_precision: bool = False,
        skip_checks: bool = False,
    ) -> Dict[str, Any]:
        """
        Load an EventList from a URL.

        Args:
            url: URL to download the event file from
            name: Name to assign to the loaded event list
            fmt: File format
            rmf_file: Optional path to local RMF file for energy calibration
            additional_columns: Optional list of additional columns to read
            high_precision: Use numpy.float128 for time array (pulsar timing)
            skip_checks: Skip time ordering and GTI validation (performance)

        Returns:
            Result dictionary
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

            # Download file to temporary location
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()

            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=f".{fmt}") as tmp_file:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        tmp_file.write(chunk)
                temp_filename = tmp_file.name

            # Load the event list with guaranteed temp file cleanup
            try:
                event_list = EventList.read(
                    temp_filename,
                    fmt=fmt,
                    rmf_file=rmf_file,
                    additional_columns=additional_columns,
                    high_precision=high_precision,
                    skip_checks=skip_checks,
                )
            finally:
                # Clean up temporary file even if loading fails
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)

            # Add to state manager
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)

            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max())
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
            }

            # Build message with warnings if present
            message = f"EventList '{name}' loaded successfully from URL"
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except requests.RequestException as e:
            return self.create_result(
                success=False,
                data=None,
                message=f"Failed to download file from URL: {str(e)}",
                error=str(e),
            )
        except Exception as e:
            return self.handle_error(
                e, "Loading event list from URL", url=url, name=name, fmt=fmt
            )

    def save_event_list(
        self,
        name: str,
        file_path: str,
        fmt: str = "ogip",
    ) -> Dict[str, Any]:
        """
        Save an EventList to disk.

        Args:
            name: Name of the event list in state
            file_path: Path where to save the file
            fmt: File format to save as

        Returns:
            Result dictionary
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

            # Ensure directory exists (handle case where file_path has no directory)
            dirname = os.path.dirname(file_path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

            # Save based on format
            # For FITS formats, use to_astropy_table() for better OGIP compliance
            # Stingray's direct write() may not preserve all metadata correctly
            if fmt in ["fits", "ogip", "hea"]:
                table = event_list.to_astropy_table()
                table.write(file_path, format="fits", overwrite=True)
            elif fmt == "hdf5":
                event_list.to_astropy_table().write(
                    file_path, format="hdf5", path="data", overwrite=True
                )
            else:
                event_list.write(file_path, fmt)

            return self.create_result(
                success=True,
                data={"file_path": file_path},
                message=f"EventList '{name}' saved to '{file_path}'",
            )

        except Exception as e:
            return self.handle_error(
                e, "Saving event list", name=name, file_path=file_path, fmt=fmt
            )

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
                    _to_python_float(event_list.time.max())
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
                info["total_gti_time"] = _to_python_float(sum(g[1] - g[0] for g in event_list.gti))

            # Energy/PI range
            if event_list.energy is not None:
                info["energy_range"] = [
                    _to_python_float(event_list.energy.min()),
                    _to_python_float(event_list.energy.max())
                ]
            if event_list.pi is not None:
                info["pi_range"] = [int(event_list.pi.min()), int(event_list.pi.max())]

            # Mission metadata (if available)
            if hasattr(event_list, 'mission') and event_list.mission:
                info["mission"] = str(event_list.mission)
            if hasattr(event_list, 'instr') and event_list.instr:
                info["instrument"] = str(event_list.instr)

            # Time statistics
            if len(event_list.time) > 1:
                # Sort times to get accurate time differences
                sorted_times = np.sort(event_list.time)
                time_diffs = sorted_times[1:] - sorted_times[:-1]
                info["mean_count_rate"] = _to_python_float(len(event_list.time) / duration) if duration and duration > 0 else 0
                info["min_time_diff"] = _to_python_float(time_diffs.min())
                info["max_time_diff"] = _to_python_float(time_diffs.max())

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
                summaries.append({
                    "name": name,
                    "n_events": len(event_list.time),
                    "time_range": [
                        _to_python_float(event_list.time.min()),
                        _to_python_float(event_list.time.max())
                    ],
                    "has_energy": event_list.energy is not None,
                    "has_pi": event_list.pi is not None,
                    "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                })

            return self.create_result(
                success=True,
                data=summaries,
                message=f"Found {len(summaries)} event list(s)",
            )

        except Exception as e:
            return self.handle_error(e, "Listing event lists")

    def check_file_size(self, file_path: str) -> Dict[str, Any]:
        """Check file size and provide loading recommendations based on available RAM."""
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024**2)
            file_size_gb = file_size / (1024**3)

            # Get memory info first - we need this for smart recommendations
            memory_info = self._get_memory_info()
            available_ram_mb = memory_info["available_mb"]

            # Estimate memory needed to load the EventList
            # FITS files typically expand to ~3x file size in memory
            estimated_memory_mb = self._estimate_memory_usage(file_size, "fits") / (1024**2)

            # Calculate what percentage of available RAM this would use
            ram_usage_percent = (estimated_memory_mb / available_ram_mb) * 100 if available_ram_mb > 0 else 100

            # Determine risk level based on RAM usage percentage
            # This is smarter than just file size - adapts to user's system
            if ram_usage_percent > 80:
                risk_level = "critical"  # Would use >80% of available RAM
            elif ram_usage_percent > 50:
                risk_level = "risky"     # Would use >50% of available RAM
            elif ram_usage_percent > 30:
                risk_level = "caution"   # Would use >30% of available RAM
            else:
                risk_level = "safe"      # Would use <30% of available RAM

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

        except Exception as e:
            return self.handle_error(e, "Checking file size", file_path=file_path)

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
        multipliers = {
            "fits": 3,
            "evt": 3,
            "ogip": 3,
            "hea": 3,
            "hdf5": 2,
        }
        multiplier = multipliers.get(fmt, 3)
        return int(file_size * multiplier)

    def _can_load_safely(
        self,
        file_path: str,
        safety_margin: float = 0.5,
        fmt: str = "fits",
    ) -> bool:
        """Check if file can be safely loaded into memory."""
        file_size = os.path.getsize(file_path)
        available_ram = psutil.virtual_memory().available
        needed_ram = self._estimate_memory_usage(file_size, fmt)
        safe_limit = available_ram * safety_margin
        return needed_ram < safe_limit

    def get_event_list_full_preview(self, name: str, time_limit: int = 10) -> Dict[str, Any]:
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
                    _to_python_float(event_list.time.max())
                ],
                "duration": _to_python_float(event_list.time.max() - event_list.time.min()),

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
                        _to_python_float(event_list.energy.max())
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

                # GTI data
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_list": (
                    [[_to_python_float(g[0]), _to_python_float(g[1])] for g in event_list.gti]
                    if event_list.gti is not None
                    else None
                ),
                "total_gti_time": (
                    _to_python_float(sum(g[1] - g[0] for g in event_list.gti))
                    if event_list.gti is not None and len(event_list.gti) > 0
                    else None
                ),

                # Reference time - mjdref is often numpy.longdouble
                "mjdref": _to_python_float(event_list.mjdref),

                # Metadata (if available) - convert to string to be safe
                "mission": str(getattr(event_list, "mission", None)) if getattr(event_list, "mission", None) else None,
                "instrument": str(getattr(event_list, "instr", None)) if getattr(event_list, "instr", None) else None,
                "detector_id": (
                    getattr(event_list, "detector_id", None)
                    if hasattr(event_list, "detector_id") and event_list.detector_id is not None
                    else None
                ),
                "ephem": str(getattr(event_list, "ephem", None)) if getattr(event_list, "ephem", None) else None,
                "timeref": str(getattr(event_list, "timeref", None)) if getattr(event_list, "timeref", None) else None,
                "timesys": str(getattr(event_list, "timesys", None)) if getattr(event_list, "timesys", None) else None,

                # Statistics
                "mean_count_rate": None,
                "min_time_diff": None,
                "max_time_diff": None,
            }

            # Calculate time statistics
            duration = preview["duration"]
            if duration and duration > 0:
                preview["mean_count_rate"] = _to_python_float(len(event_list.time) / duration)

            if len(event_list.time) > 1:
                sorted_times = np.sort(event_list.time)
                time_diffs = sorted_times[1:] - sorted_times[:-1]
                preview["min_time_diff"] = _to_python_float(time_diffs.min())
                preview["max_time_diff"] = _to_python_float(time_diffs.max())
                preview["mean_time_diff"] = _to_python_float(time_diffs.mean())

            # Check for additional columns
            additional_cols = []
            for attr in dir(event_list):
                if not attr.startswith("_") and attr not in [
                    "time", "energy", "pi", "gti", "mjdref", "mission", "instr",
                    "detector_id", "ephem", "timeref", "timesys", "header",
                    "notes", "ncounts", "dt", "n"
                ]:
                    val = getattr(event_list, attr, None)
                    if isinstance(val, np.ndarray) and len(val) == len(event_list.time):
                        additional_cols.append(attr)
            preview["additional_columns"] = additional_cols

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
            is_fits = fmt.lower() in ['ogip', 'hea', 'fits', 'evt']
            if not is_fits:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"True lazy loading only supports FITS formats. Got: {fmt}",
                    error="Unsupported format for lazy loading",
                )

            # Create the reader
            reader = FITSTimeseriesReader(
                file_path, output_class=EventList, data_kind="events"
            )

            # Get file metadata
            original_gti = reader.gti
            mjdref = getattr(reader, 'mjdref', 0.0)
            mission = getattr(reader, 'mission', None)
            instr = getattr(reader, 'instr', None)

            # Get total event count for reporting
            times_reader = FITSTimeseriesReader(file_path, data_kind="times")
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

            # Add to state manager
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)

            # Calculate loaded duration
            loaded_duration = abs_end - abs_start

            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max())
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
                "lazy_loading_info": {
                    "method": "time_range",
                    "requested_range": [start_time, end_time],
                    "actual_range": [abs_start, abs_end],
                    "loaded_duration": loaded_duration,
                    "total_file_duration": total_duration,
                    "total_file_events": total_events,
                    "events_loaded_percent": (len(event_list.time) / total_events * 100) if total_events > 0 else 0,
                },
            }

            message = (
                f"Lazy loaded '{name}': {len(event_list.time)} events "
                f"({summary['lazy_loading_info']['events_loaded_percent']:.1f}% of file) "
                f"from time range [{start_time:.1f}s - {end_time:.1f}s]"
            )
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except Exception as e:
            return self.handle_error(
                e, "Loading event list by time range",
                file_path=file_path, name=name, start_time=start_time, end_time=end_time
            )

    def load_event_list_by_event_count(
        self,
        file_path: str,
        name: str,
        start_index: int = 0,
        count: int = 10000,
        fmt: str = "ogip",
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
            is_fits = fmt.lower() in ['ogip', 'hea', 'fits', 'evt']
            if not is_fits:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"True lazy loading only supports FITS formats. Got: {fmt}",
                    error="Unsupported format for lazy loading",
                )

            # Create the reader
            reader = FITSTimeseriesReader(
                file_path, output_class=EventList, data_kind="events"
            )

            # Get file metadata
            original_gti = reader.gti
            mjdref = getattr(reader, 'mjdref', 0.0)
            mission = getattr(reader, 'mission', None)
            instr = getattr(reader, 'instr', None)

            # Get total event count
            times_reader = FITSTimeseriesReader(file_path, data_kind="times")
            all_times = times_reader[:]
            total_events = len(all_times)

            if original_gti is not None and len(original_gti) > 0:
                total_duration = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))
            else:
                total_duration = float(all_times.max() - all_times.min()) if total_events > 0 else 0.0

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

            # Add to state manager
            self.state.add_event_data(name, event_list)

            # Validate GTI and collect warnings
            gti_warnings = self._validate_gti(event_list)

            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max())
                ],
                "has_energy": event_list.energy is not None,
                "has_pi": event_list.pi is not None,
                "gti_count": len(event_list.gti) if event_list.gti is not None else 0,
                "gti_warnings": gti_warnings if gti_warnings else None,
                "lazy_loading_info": {
                    "method": "event_count",
                    "start_index": start_index,
                    "end_index": end_index,
                    "events_requested": count,
                    "events_loaded": actual_count,
                    "total_file_events": total_events,
                    "total_file_duration": total_duration,
                    "events_loaded_percent": (actual_count / total_events * 100) if total_events > 0 else 0,
                },
            }

            message = (
                f"Lazy loaded '{name}': {actual_count} events "
                f"({summary['lazy_loading_info']['events_loaded_percent']:.1f}% of file) "
                f"from indices [{start_index}:{end_index}]"
            )
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"

            return self.create_result(
                success=True,
                data=summary,
                message=message,
            )

        except Exception as e:
            return self.handle_error(
                e, "Loading event list by event count",
                file_path=file_path, name=name, start_index=start_index, count=count
            )

    def get_file_metadata(self, file_path: str, fmt: str = "ogip") -> Dict[str, Any]:
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
            is_fits = fmt.lower() in ['ogip', 'hea', 'fits', 'evt']
            if not is_fits:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Metadata preview only supports FITS formats. Got: {fmt}",
                    error="Unsupported format",
                )

            file_size = os.path.getsize(file_path)
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

            with fits.open(file_path) as hdulist:
                # Find the EVENTS or EVT extension
                events_hdu = None
                for hdu in hdulist:
                    if hdu.name.upper() in ['EVENTS', 'EVT']:
                        events_hdu = hdu
                        break

                if events_hdu is not None:
                    # Get row count from header (NAXIS2) - no data loading!
                    total_events = events_hdu.header.get('NAXIS2', 0)
                    available_columns = [col.name for col in events_hdu.columns]

                    # Get MJDREF from header
                    mjdref = events_hdu.header.get('MJDREF', 0.0)
                    if mjdref == 0.0:
                        # Some files split MJDREF into integer and fractional parts
                        mjdrefi = events_hdu.header.get('MJDREFI', 0)
                        mjdreff = events_hdu.header.get('MJDREFF', 0.0)
                        mjdref = mjdrefi + mjdreff

                    # Get mission/instrument from header
                    mission = events_hdu.header.get('TELESCOP', None) or events_hdu.header.get('MISSION', None)
                    instr = events_hdu.header.get('INSTRUME', None)

                    # Get time range from header keywords if available (fast!)
                    tstart = events_hdu.header.get('TSTART', None)
                    tstop = events_hdu.header.get('TSTOP', None)

                    if tstart is not None and tstop is not None:
                        time_min = float(tstart)
                        time_max = float(tstop)
                    elif total_events > 0:
                        # Fallback: read only first and last few rows (much faster than full load)
                        time_col = events_hdu.data['TIME']
                        time_min = float(time_col[0])
                        time_max = float(time_col[-1])

                # Read GTI extension (usually small, OK to load fully)
                gti_hdu = None
                for hdu in hdulist:
                    if hdu.name.upper() in ['GTI', 'STDGTI']:
                        gti_hdu = hdu
                        break

                if gti_hdu is not None and gti_hdu.data is not None:
                    start_col = gti_hdu.data['START'] if 'START' in gti_hdu.columns.names else None
                    stop_col = gti_hdu.data['STOP'] if 'STOP' in gti_hdu.columns.names else None
                    if start_col is not None and stop_col is not None:
                        original_gti = np.column_stack([start_col, stop_col])

            # Calculate duration
            duration = (time_max - time_min) if (time_min is not None and time_max is not None) else 0.0

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
                "file_path": file_path,
                "file_size_mb": file_size_mb,
                "file_size_gb": file_size_gb,
                "risk_level": risk_level,
                "total_events": total_events,
                "time_range": [time_min, time_max],
                "duration": duration,
                "gti_count": gti_count,
                "total_gti_time": total_gti_time,
                "gti_list": (
                    [[_to_python_float(g[0]), _to_python_float(g[1])] for g in original_gti]
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

        except Exception as e:
            return self.handle_error(
                e, "Getting file metadata", file_path=file_path
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
            recommendations["suggested_chunk_size"] = min(100000, max(1000, total_events // 10))
            recommendations["suggested_time_chunk"] = 100.0  # seconds
        elif risk_level == "risky":
            # Large file (5-10GB) - strongly recommend partial loading
            recommendations["strategy"] = "time_range"
            recommendations["suggested_chunk_size"] = min(500000, max(10000, total_events // 5))
            recommendations["suggested_time_chunk"] = 500.0
        elif risk_level == "caution":
            # Medium file (1-5GB) - partial loading recommended
            recommendations["strategy"] = "time_range"
            recommendations["suggested_chunk_size"] = min(1000000, max(50000, total_events // 2))
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

    def check_batch_file_size(self, file_paths: List[str]) -> Dict[str, Any]:
        """
        Check sizes of multiple files and estimate total memory usage.

        Args:
            file_paths: List of file paths to check

        Returns:
            Result dictionary with per-file and total memory estimates
        """
        try:
            memory_info = self._get_memory_info()
            available_ram_mb = memory_info["available_mb"]

            files_info = []
            total_size_mb = 0.0
            total_estimated_ram_mb = 0.0

            for path in file_paths:
                if not os.path.exists(path):
                    files_info.append({
                        "file_path": path,
                        "file_name": os.path.basename(path),
                        "error": "File not found",
                        "size_mb": 0,
                        "estimated_ram_mb": 0,
                        "ram_percent": 0,
                        "risk_level": "critical",
                    })
                    continue

                size_bytes = os.path.getsize(path)
                size_mb = size_bytes / (1024**2)

                # Determine format from extension
                ext = os.path.splitext(path)[1].lower()
                fmt = "fits" if ext in ['.fits', '.fit', '.fts', '.evt'] else "hdf5" if ext in ['.hdf5', '.h5'] else "fits"

                estimated_ram_mb = self._estimate_memory_usage(size_bytes, fmt) / (1024**2)
                ram_percent = (estimated_ram_mb / available_ram_mb) * 100 if available_ram_mb > 0 else 100

                files_info.append({
                    "file_path": path,
                    "file_name": os.path.basename(path),
                    "size_mb": round(size_mb, 1),
                    "estimated_ram_mb": round(estimated_ram_mb, 1),
                    "ram_percent": round(ram_percent, 1),
                    "risk_level": self._get_risk_level(ram_percent),
                })

                total_size_mb += size_mb
                total_estimated_ram_mb += estimated_ram_mb

            total_ram_percent = (total_estimated_ram_mb / available_ram_mb) * 100 if available_ram_mb > 0 else 100

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
                    "file_count": len(file_paths),
                    "recommend_partial_loading": total_ram_percent > 30,
                },
                message=f"Checked {len(file_paths)} files: {total_size_mb:.1f} MB total, ~{total_ram_percent:.0f}% of available RAM",
            )

        except Exception as e:
            return self.handle_error(e, "Checking batch file sizes")

    def load_batch_event_lists(
        self,
        files: List[Dict[str, Any]],
        use_same_settings: bool = True,
        # Shared settings (used when use_same_settings=True)
        shared_fmt: str = "ogip",
        shared_rmf_file: Optional[str] = None,
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
    ) -> Dict[str, Any]:
        """
        Load multiple EventLists in parallel using threads.

        Args:
            files: List of dicts with file configurations. Each dict should have:
                - file_path: str (required)
                - name: str (required)
                - fmt: str (optional, used if use_same_settings=False)
                - rmf_file: Optional[str]
                - additional_columns: Optional[List[str]]
                - high_precision: bool
                - skip_checks: bool
                - use_partial_loading: bool
                - partial_mode: str ('time_range' or 'event_count')
                - time_range_start/end: Optional[float]
                - event_start_index/count: Optional[int]
            use_same_settings: If True, use shared_* settings for all files
            shared_*: Settings applied to all files when use_same_settings=True
            max_workers: Max parallel threads (default: min(cpu_count, len(files), 8))

        Returns:
            Result with successful[], failed[], and summary statistics
        """
        start_time = time.time()

        if not files:
            return self.create_result(
                success=False,
                message="No files provided for batch loading",
            )

        # Pre-validate: check for duplicate names in the request
        names = [f.get("name", "") for f in files]
        duplicate_names = [name for name in set(names) if names.count(name) > 1]
        if duplicate_names:
            return self.create_result(
                success=False,
                message=f"Duplicate names in request: {duplicate_names}",
            )

        # Pre-validate: check no names already exist in state
        existing_names = []
        for f in files:
            name = f.get("name", "")
            if name and self.state.has_event_data(name):
                existing_names.append(name)
        if existing_names:
            return self.create_result(
                success=False,
                message=f"Names already exist in state: {existing_names}",
            )

        # Determine worker count
        if max_workers is None:
            max_workers = min(os.cpu_count() or 4, len(files), 8)

        successful: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        def load_single_file(file_config: Dict[str, Any]) -> Dict[str, Any]:
            """Load a single file with the appropriate settings."""
            file_path = file_config.get("file_path", "")
            name = file_config.get("name", "")

            if not file_path or not name:
                return {
                    "success": False,
                    "name": name,
                    "file_path": file_path,
                    "error": "Missing file_path or name",
                }

            # Determine settings to use
            if use_same_settings:
                fmt = shared_fmt
                rmf_file = shared_rmf_file
                additional_columns = shared_additional_columns
                high_precision = shared_high_precision
                skip_checks = shared_skip_checks
                use_partial = shared_use_partial_loading
                partial_mode = shared_partial_mode
                time_start = shared_time_range_start
                time_end = shared_time_range_end
                event_start = shared_event_start_index
                event_cnt = shared_event_count
            else:
                # Use per-file settings
                fmt = file_config.get("fmt", "ogip")
                rmf_file = file_config.get("rmf_file")
                additional_columns = file_config.get("additional_columns")
                high_precision = file_config.get("high_precision", False)
                skip_checks = file_config.get("skip_checks", False)
                use_partial = file_config.get("use_partial_loading", False)
                partial_mode = file_config.get("partial_mode", "time_range")
                time_start = file_config.get("time_range_start")
                time_end = file_config.get("time_range_end")
                event_start = file_config.get("event_start_index")
                event_cnt = file_config.get("event_count")

            try:
                if use_partial:
                    if partial_mode == "time_range":
                        if time_start is None or time_end is None:
                            return {
                                "success": False,
                                "name": name,
                                "file_path": file_path,
                                "error": "Partial loading (time_range) requires time_range_start and time_range_end",
                            }
                        result = self.load_event_list_by_time_range(
                            file_path, name, time_start, time_end, fmt
                        )
                    else:  # event_count
                        result = self.load_event_list_by_event_count(
                            file_path, name,
                            event_start or 0,
                            event_cnt or 10000,
                            fmt
                        )
                else:
                    result = self.load_event_list(
                        file_path, name, fmt,
                        rmf_file, additional_columns,
                        high_precision, skip_checks
                    )

                return {
                    "success": result.get("success", False),
                    "name": name,
                    "file_path": file_path,
                    "data": result.get("data"),
                    "message": result.get("message"),
                    "error": result.get("error") if not result.get("success") else None,
                }
            except Exception as e:
                return {
                    "success": False,
                    "name": name,
                    "file_path": file_path,
                    "error": str(e),
                }

        # Execute loading in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_file = {
                executor.submit(load_single_file, f): f
                for f in files
            }

            # Collect results as they complete
            for future in as_completed(future_to_file):
                file_info = future_to_file[future]
                try:
                    result = future.result()
                    if result.get("success"):
                        successful.append({
                            "name": result["name"],
                            "file_path": result["file_path"],
                            "data": result.get("data"),
                            "message": result.get("message"),
                        })
                    else:
                        failed.append({
                            "name": result.get("name", file_info.get("name", "")),
                            "file_path": result.get("file_path", file_info.get("file_path", "")),
                            "error": result.get("error", "Unknown error"),
                        })
                except Exception as e:
                    failed.append({
                        "name": file_info.get("name", ""),
                        "file_path": file_info.get("file_path", ""),
                        "error": str(e),
                    })

        total_time_ms = (time.time() - start_time) * 1000
        total_events = sum(
            s.get("data", {}).get("n_events", 0) if s.get("data") else 0
            for s in successful
        )

        return self.create_result(
            success=len(failed) == 0,
            data={
                "successful": successful,
                "failed": failed,
                "summary": {
                    "total_files": len(files),
                    "success_count": len(successful),
                    "failure_count": len(failed),
                    "total_events_loaded": total_events,
                    "total_time_ms": round(total_time_ms, 1),
                    "workers_used": max_workers,
                },
            },
            message=f"Loaded {len(successful)}/{len(files)} files ({total_events:,} total events) in {total_time_ms:.0f}ms",
        )

    async def load_batch_event_lists_stream(
        self,
        files: List[Dict[str, Any]],
        use_same_settings: bool = True,
        shared_fmt: str = "ogip",
        shared_rmf_file: Optional[str] = None,
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
        """
        Stream batch loading results as they complete via SSE.

        Yields events for each file completion and a final summary event.
        This allows the frontend to update progress incrementally instead of
        waiting for all files to complete.

        Args:
            files: List of file configurations (same as load_batch_event_lists)
            use_same_settings: If True, use shared_* settings for all files
            shared_*: Shared settings applied when use_same_settings=True
            max_workers: Max parallel threads

        Yields:
            Dict events with type 'file_complete' or 'complete'
        """
        start_time = time.time()

        if not files:
            yield {
                "type": "error",
                "error": "No files provided for batch loading",
            }
            return

        # Pre-validate: check for duplicate names in the request
        names = [f.get("name", "") for f in files]
        duplicate_names = [name for name in set(names) if names.count(name) > 1]
        if duplicate_names:
            yield {
                "type": "error",
                "error": f"Duplicate names in request: {duplicate_names}",
            }
            return

        # Pre-validate: check no names already exist in state
        existing_names = []
        for f in files:
            name = f.get("name", "")
            if name and self.state.has_event_data(name):
                existing_names.append(name)
        if existing_names:
            yield {
                "type": "error",
                "error": f"Names already exist in state: {existing_names}",
            }
            return

        # Determine worker count
        if max_workers is None:
            max_workers = min(os.cpu_count() or 4, len(files), 8)

        successful: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        def load_single_file(file_config: Dict[str, Any]) -> Dict[str, Any]:
            """Load a single file with the appropriate settings."""
            file_path = file_config.get("file_path", "")
            name = file_config.get("name", "")

            if not file_path or not name:
                return {
                    "success": False,
                    "name": name,
                    "file_path": file_path,
                    "error": "Missing file_path or name",
                }

            # Determine settings to use
            if use_same_settings:
                fmt = shared_fmt
                rmf_file = shared_rmf_file
                additional_columns = shared_additional_columns
                high_precision = shared_high_precision
                skip_checks = shared_skip_checks
                use_partial = shared_use_partial_loading
                partial_mode = shared_partial_mode
                time_start = shared_time_range_start
                time_end = shared_time_range_end
                event_start = shared_event_start_index
                event_cnt = shared_event_count
            else:
                # Use per-file settings
                fmt = file_config.get("fmt", "ogip")
                rmf_file = file_config.get("rmf_file")
                additional_columns = file_config.get("additional_columns")
                high_precision = file_config.get("high_precision", False)
                skip_checks = file_config.get("skip_checks", False)
                use_partial = file_config.get("use_partial_loading", False)
                partial_mode = file_config.get("partial_mode", "time_range")
                time_start = file_config.get("time_range_start")
                time_end = file_config.get("time_range_end")
                event_start = file_config.get("event_start_index")
                event_cnt = file_config.get("event_count")

            try:
                if use_partial:
                    if partial_mode == "time_range":
                        if time_start is None or time_end is None:
                            return {
                                "success": False,
                                "name": name,
                                "file_path": file_path,
                                "error": "Partial loading (time_range) requires time_range_start and time_range_end",
                            }
                        result = self.load_event_list_by_time_range(
                            file_path, name, time_start, time_end, fmt
                        )
                    else:  # event_count
                        result = self.load_event_list_by_event_count(
                            file_path, name,
                            event_start or 0,
                            event_cnt or 10000,
                            fmt
                        )
                else:
                    result = self.load_event_list(
                        file_path, name, fmt,
                        rmf_file, additional_columns,
                        high_precision, skip_checks
                    )

                return {
                    "success": result.get("success", False),
                    "name": name,
                    "file_path": file_path,
                    "data": result.get("data"),
                    "message": result.get("message"),
                    "error": result.get("error") if not result.get("success") else None,
                }
            except Exception as e:
                return {
                    "success": False,
                    "name": name,
                    "file_path": file_path,
                    "error": str(e),
                }

        # Execute loading in parallel, yielding results as they complete
        # Use asyncio to wrap thread pool futures for proper async handling
        loop = asyncio.get_event_loop()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks and wrap them as asyncio futures
            future_to_file = {
                executor.submit(load_single_file, f): f
                for f in files
            }

            # Convert to asyncio futures for proper async iteration
            pending = {
                asyncio.wrap_future(future): (future, file_info)
                for future, file_info in future_to_file.items()
            }

            completed = 0
            while pending:
                # Wait for the next future to complete (non-blocking)
                done, _ = await asyncio.wait(
                    pending.keys(),
                    return_when=asyncio.FIRST_COMPLETED
                )

                for async_future in done:
                    original_future, file_info = pending.pop(async_future)
                    completed += 1

                    try:
                        result = async_future.result()
                        if result.get("success"):
                            successful.append({
                                "name": result["name"],
                                "file_path": result["file_path"],
                                "data": result.get("data"),
                                "message": result.get("message"),
                            })
                            yield {
                                "type": "file_complete",
                                "name": result["name"],
                                "file_path": result["file_path"],
                                "success": True,
                                "completed": completed,
                                "total": len(files),
                                "data": result.get("data"),
                            }
                        else:
                            error_msg = result.get("error", "Unknown error")
                            failed.append({
                                "name": result.get("name", file_info.get("name", "")),
                                "file_path": result.get("file_path", file_info.get("file_path", "")),
                                "error": error_msg,
                            })
                            yield {
                                "type": "file_complete",
                                "name": result.get("name", file_info.get("name", "")),
                                "file_path": result.get("file_path", file_info.get("file_path", "")),
                                "success": False,
                                "completed": completed,
                                "total": len(files),
                                "error": error_msg,
                            }
                    except Exception as e:
                        failed.append({
                            "name": file_info.get("name", ""),
                            "file_path": file_info.get("file_path", ""),
                            "error": str(e),
                        })
                        yield {
                            "type": "file_complete",
                            "name": file_info.get("name", ""),
                            "file_path": file_info.get("file_path", ""),
                            "success": False,
                            "completed": completed,
                            "total": len(files),
                            "error": str(e),
                        }

                    # Allow event loop to flush the SSE response
                    await asyncio.sleep(0)

        # Final completion event with summary
        total_time_ms = (time.time() - start_time) * 1000
        total_events = sum(
            s.get("data", {}).get("n_events", 0) if s.get("data") else 0
            for s in successful
        )

        yield {
            "type": "complete",
            "total_time_ms": round(total_time_ms, 1),
            "success_count": len(successful),
            "failure_count": len(failed),
            "total_events": total_events,
            "workers_used": max_workers,
        }
