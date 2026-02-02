"""
Data service for EventList operations.

Handles loading, saving, and managing event lists.
Includes lazy loading support for large files.
"""

import os
import tempfile
from typing import Any, Dict, List, Optional

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

            # Load the event list using Stingray
            event_list = EventList.read(
                file_path,
                fmt=fmt,
                rmf_file=rmf_file,
                additional_columns=additional_columns,
                high_precision=high_precision,
                skip_checks=skip_checks,
            )

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
            }

            # Build message with warnings if present
            message = f"EventList '{name}' loaded successfully ({len(event_list.time)} events)"
            if gti_warnings:
                message += f" [GTI warnings: {len(gti_warnings)}]"

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
        """Check file size and provide loading recommendations."""
        try:
            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024**2)
            file_size_gb = file_size / (1024**3)

            # Determine risk level
            if file_size_gb > 10:
                risk_level = "critical"
            elif file_size_gb > 5:
                risk_level = "risky"
            elif file_size_gb > 1:
                risk_level = "caution"
            else:
                risk_level = "safe"

            recommend_lazy = file_size_gb > 1.0 or risk_level in ["caution", "risky", "critical"]

            # Get memory info
            memory_info = self._get_memory_info()
            estimated_memory_mb = self._estimate_memory_usage(file_size, "fits") / (1024**2)

            return self.create_result(
                success=True,
                data={
                    "file_size_bytes": file_size,
                    "file_size_mb": file_size_mb,
                    "file_size_gb": file_size_gb,
                    "risk_level": risk_level,
                    "recommend_lazy": recommend_lazy,
                    "estimated_memory_mb": estimated_memory_mb,
                    "memory_info": memory_info,
                },
                message=f"File size: {file_size_mb:.2f} MB, Risk: {risk_level}",
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

            # Create reader for metadata access
            reader = FITSTimeseriesReader(
                file_path, output_class=EventList, data_kind="events"
            )

            # Get GTI and other metadata
            original_gti = reader.gti
            mjdref = getattr(reader, 'mjdref', 0.0)
            mission = getattr(reader, 'mission', None)
            instr = getattr(reader, 'instr', None)

            # Get time data efficiently
            times_reader = FITSTimeseriesReader(file_path, data_kind="times")
            all_times = times_reader[:]
            total_events = len(all_times)

            # Calculate time statistics
            time_min = _to_python_float(all_times.min()) if total_events > 0 else None
            time_max = _to_python_float(all_times.max()) if total_events > 0 else None
            duration = _to_python_float(all_times.max() - all_times.min()) if total_events > 1 else 0.0

            # GTI info
            gti_count = len(original_gti) if original_gti is not None else 0
            total_gti_time = None
            if original_gti is not None and len(original_gti) > 0:
                total_gti_time = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))

            # Get available columns from FITS file
            available_columns = []
            with fits.open(file_path) as hdulist:
                for hdu in hdulist:
                    if hdu.name.upper() in ['EVENTS', 'EVT']:
                        available_columns = [col.name for col in hdu.columns]
                        break

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
        """
        recommendations = {
            "can_load_full": risk_level in ["safe", "caution"],
            "recommend_lazy": risk_level in ["caution", "risky", "critical"],
            "suggested_chunk_size": None,
            "suggested_time_chunk": None,
            "strategy": "full",
        }

        if risk_level == "critical":
            recommendations["strategy"] = "chunked"
            recommendations["suggested_chunk_size"] = min(100000, total_events // 10)
            recommendations["suggested_time_chunk"] = 100.0  # seconds
        elif risk_level == "risky":
            recommendations["strategy"] = "time_range"
            recommendations["suggested_chunk_size"] = min(500000, total_events // 5)
            recommendations["suggested_time_chunk"] = 500.0
        elif risk_level == "caution":
            recommendations["strategy"] = "preview_first"
            recommendations["suggested_chunk_size"] = min(1000000, total_events // 2)
            recommendations["suggested_time_chunk"] = 1000.0
        else:
            recommendations["strategy"] = "full"

        return recommendations
