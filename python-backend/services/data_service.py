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

    def load_event_list(
        self,
        file_path: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Load an EventList from a file.

        Args:
            file_path: Path to the event file
            name: Name to assign to the loaded event list
            fmt: File format (ogip, hdf5, hea, etc.)
            rmf_file: Optional path to RMF file
            additional_columns: Optional list of additional columns to read

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
            )

            # Add to state manager
            self.state.add_event_data(name, event_list)

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
            }

            return self.create_result(
                success=True,
                data=summary,
                message=f"EventList '{name}' loaded successfully ({len(event_list.time)} events)",
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
    ) -> Dict[str, Any]:
        """
        Load an EventList from a URL.

        Args:
            url: URL to download the event file from
            name: Name to assign to the loaded event list
            fmt: File format

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

            # Load the event list
            event_list = EventList.read(temp_filename, fmt)

            # Clean up temporary file
            os.remove(temp_filename)

            # Add to state manager
            self.state.add_event_data(name, event_list)

            summary = {
                "name": name,
                "n_events": len(event_list.time),
                "time_range": [
                    _to_python_float(event_list.time.min()),
                    _to_python_float(event_list.time.max())
                ],
            }

            return self.create_result(
                success=True,
                data=summary,
                message=f"EventList '{name}' loaded successfully from URL",
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

            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            # Save based on format
            if fmt == "hdf5":
                event_list.to_astropy_table().write(
                    file_path, format=fmt, path="data"
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

    def load_event_list_lazy(
        self,
        file_path: str,
        name: str,
        fmt: str = "ogip",
        rmf_file: Optional[str] = None,
        additional_columns: Optional[List[str]] = None,
        safety_margin: float = 0.5,
    ) -> Dict[str, Any]:
        """
        Load EventList using lazy loading for large files.

        This method intelligently decides whether to use lazy loading
        or standard loading based on file size and available memory.

        Args:
            file_path: Path to the event file
            name: Name to assign to the loaded event list
            fmt: File format (ogip, hdf5, hea, etc.)
            rmf_file: Optional path to RMF file
            additional_columns: Optional list of additional columns to read
            safety_margin: Fraction of available RAM to use (0.0-1.0)

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

            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024**2)
            file_size_gb = file_size / (1024**3)

            # Check if we can load safely
            can_load_safe = self._can_load_safely(file_path, safety_margin, fmt)
            memory_info = self._get_memory_info()
            estimated_memory_mb = self._estimate_memory_usage(file_size, fmt) / (1024**2)

            # Load the event list
            event_list = EventList.read(
                file_path,
                fmt=fmt,
                rmf_file=rmf_file,
                additional_columns=additional_columns,
            )

            # Add to state manager
            self.state.add_event_data(name, event_list)

            # Determine loading method used
            method = "standard" if can_load_safe else "standard_risky"

            # Prepare summary (use helper for numpy type conversion)
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
                "loading_info": {
                    "method": method,
                    "file_size_mb": file_size_mb,
                    "file_size_gb": file_size_gb,
                    "estimated_memory_mb": estimated_memory_mb,
                    "memory_safe": can_load_safe,
                    "available_memory_mb": memory_info["available_mb"],
                },
            }

            warning = ""
            if not can_load_safe:
                warning = " (Warning: Large file loaded despite memory risk)"

            return self.create_result(
                success=True,
                data=summary,
                message=f"EventList '{name}' loaded via lazy loading ({len(event_list.time)} events){warning}",
            )

        except MemoryError as e:
            return self.create_result(
                success=False,
                data=None,
                message="Out of memory loading file. File is too large for available RAM.",
                error=str(e),
            )
        except Exception as e:
            return self.handle_error(
                e, "Loading event list with lazy loading", file_path=file_path, name=name
            )

    def load_event_list_preview(
        self,
        file_path: str,
        name: str,
        preview_duration: float = 100.0,
        fmt: str = "ogip",
    ) -> Dict[str, Any]:
        """
        Load only the first segment of a file as a preview.

        For FITS files, uses FITSTimeseriesReader for efficient lazy access:
        1. Reads only the time column first (memory efficient)
        2. Sorts times to handle unsorted event files
        3. Filters to preview window using sorted indices
        4. Reads full data only for events in the preview window

        For other formats, falls back to full EventList.read() with filtering.

        Args:
            file_path: Path to the event file
            name: Name to assign to the loaded event list
            preview_duration: Duration in seconds to preview (default: 100s)
            fmt: File format

        Returns:
            Result dictionary with preview EventList
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

            file_size = os.path.getsize(file_path)
            file_size_mb = file_size / (1024**2)

            # Check if this is a FITS file format
            is_fits = fmt.lower() in ['ogip', 'hea', 'fits', 'evt']

            if is_fits:
                # Use FITSTimeseriesReader for efficient lazy access
                return self._load_preview_fits(
                    file_path, name, preview_duration, file_size_mb
                )
            else:
                # For non-FITS formats, use full EventList.read() with filtering
                return self._load_preview_generic(
                    file_path, name, preview_duration, fmt, file_size_mb
                )

        except StopIteration:
            return self.create_result(
                success=False,
                data=None,
                message="File has no data in the specified preview duration",
                error="No segments available",
            )
        except Exception as e:
            return self.handle_error(
                e, "Loading event list preview", file_path=file_path, name=name
            )

    def _load_preview_fits(
        self,
        file_path: str,
        name: str,
        preview_duration: float,
        file_size_mb: float,
    ) -> Dict[str, Any]:
        """
        Load preview from FITS file using FITSTimeseriesReader.

        This method:
        1. Uses FITSTimeseriesReader to get metadata (GTI, mjdref) without loading all data
        2. Reads only the TIME column first (much smaller than full EventList)
        3. Sorts times to handle unsorted files (FITSTimeseriesReader assumes sorted)
        4. Finds events within the preview window
        5. Reads full data (time, energy, PI) only for preview events
        """
        # Step 1: Initialize reader for metadata access
        reader = FITSTimeseriesReader(file_path, output_class=EventList, data_kind="events")
        original_gti = reader.gti
        mjdref = getattr(reader, 'mjdref', 0.0)
        mission = getattr(reader, 'mission', None)
        instr = getattr(reader, 'instr', None)

        if original_gti is None or len(original_gti) == 0:
            return self.create_result(
                success=False,
                data=None,
                message="File has no GTI information",
                error="No GTI found",
            )

        # Step 2: Read only the time column (memory efficient)
        # data_kind="times" returns just the time array
        times_reader = FITSTimeseriesReader(file_path, data_kind="times")
        all_times = times_reader[:]  # Returns just the time array

        total_events = len(all_times)

        # Step 3: Sort times to handle unsorted event files
        # FITSTimeseriesReader.filter_at_time_intervals uses searchsorted which
        # requires sorted data. Many FITS files have unsorted events.
        sort_indices = np.argsort(all_times)
        sorted_times = all_times[sort_indices]

        # Step 4: Calculate preview window
        preview_start = float(original_gti[0, 0])
        preview_end = min(preview_start + preview_duration, float(original_gti[0, 1]))

        # Step 5: Find events within preview window (using sorted times for efficiency)
        # Use searchsorted on the now-sorted array
        start_idx = np.searchsorted(sorted_times, preview_start, side='left')
        end_idx = np.searchsorted(sorted_times, preview_end, side='right')

        # Get the original file indices for events in preview window
        preview_sorted_indices = slice(start_idx, end_idx)
        original_indices = sort_indices[preview_sorted_indices]

        if len(original_indices) == 0:
            return self.create_result(
                success=False,
                data=None,
                message=f"No events found in the first {preview_duration}s of the file",
                error="Empty preview segment",
            )

        # Step 6: Read full event data only for preview events
        # We need to read the FITS file directly to get energy/PI for specific indices
        preview_times = sorted_times[start_idx:end_idx]
        preview_energy = None
        preview_pi = None

        # Read energy and PI columns for the preview events
        with fits.open(file_path) as hdulist:
            # Find the events HDU
            events_hdu = None
            for hdu in hdulist:
                if hdu.name.upper() in ['EVENTS', 'EVT']:
                    events_hdu = hdu
                    break

            if events_hdu is not None and events_hdu.data is not None:
                # Get column names
                col_names = [col.name.upper() for col in events_hdu.columns]

                # Read energy if available
                if 'ENERGY' in col_names:
                    all_energy = events_hdu.data['ENERGY']
                    preview_energy = all_energy[original_indices]
                    # Sort to match sorted times
                    preview_energy = preview_energy[np.argsort(original_indices.argsort())]

                # Read PI if available
                if 'PI' in col_names:
                    all_pi = events_hdu.data['PI']
                    preview_pi = all_pi[original_indices]
                    # Sort to match sorted times
                    preview_pi = preview_pi[np.argsort(original_indices.argsort())]
                elif 'PHA' in col_names:
                    all_pi = events_hdu.data['PHA']
                    preview_pi = all_pi[original_indices]
                    preview_pi = preview_pi[np.argsort(original_indices.argsort())]

        # Step 7: Create preview EventList
        preview_gti = np.array([[preview_start, preview_end]])
        mjdref_float = _to_python_float(mjdref) or 0.0

        event_list = EventList(
            time=preview_times,
            energy=preview_energy,
            pi=preview_pi,
            gti=preview_gti,
            mjdref=mjdref_float,
            mission=mission,
            instr=instr,
        )

        # Add to state manager
        self.state.add_event_data(name, event_list)

        # Calculate durations for info
        total_duration = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))
        preview_actual_duration = float(preview_times.max() - preview_times.min()) if len(preview_times) > 1 else 0.0

        summary = {
            "name": name,
            "n_events": len(preview_times),
            "time_range": [
                _to_python_float(preview_times.min()),
                _to_python_float(preview_times.max())
            ],
            "has_energy": preview_energy is not None,
            "has_pi": preview_pi is not None,
            "gti_count": 1,
            "preview_info": {
                "preview_duration": preview_duration,
                "actual_duration": preview_actual_duration,
                "total_file_duration": total_duration,
                "total_gti_count": len(original_gti),
                "file_size_mb": file_size_mb,
                "is_preview": True,
                "full_event_count": total_events,
                "loading_method": "FITSTimeseriesReader",
            },
        }

        return self.create_result(
            success=True,
            data=summary,
            message=f"Preview loaded: '{name}' - First {preview_duration}s ({len(preview_times)} events of {total_events} total)",
        )

    def _load_preview_generic(
        self,
        file_path: str,
        name: str,
        preview_duration: float,
        fmt: str,
        file_size_mb: float,
    ) -> Dict[str, Any]:
        """
        Load preview from non-FITS file formats using full EventList.read().

        For HDF5, ECSV, and other formats, we load the full EventList
        and filter it using numpy masking.
        """
        # Load the full EventList
        full_event_list = EventList.read(file_path, fmt=fmt)

        # Get the original GTI
        original_gti = full_event_list.gti
        if original_gti is None or len(original_gti) == 0:
            original_gti = np.array([[full_event_list.time.min(), full_event_list.time.max()]])

        # Calculate the preview interval
        preview_start = float(original_gti[0, 0])
        preview_end = min(preview_start + preview_duration, float(original_gti[0, 1]))
        preview_gti = np.array([[preview_start, preview_end]])

        # Filter times using numpy masking
        mask = (full_event_list.time >= preview_start) & (full_event_list.time <= preview_end)
        preview_times = full_event_list.time[mask]

        if len(preview_times) == 0:
            return self.create_result(
                success=False,
                data=None,
                message=f"No events found in the first {preview_duration}s of the file",
                error="Empty preview segment",
            )

        # Filter energy and PI
        preview_energy = full_event_list.energy[mask] if full_event_list.energy is not None else None
        preview_pi = full_event_list.pi[mask] if full_event_list.pi is not None else None

        # Create preview EventList
        mjdref_float = _to_python_float(full_event_list.mjdref) or 0.0
        event_list = EventList(
            time=preview_times,
            energy=preview_energy,
            pi=preview_pi,
            gti=preview_gti,
            mjdref=mjdref_float,
            mission=getattr(full_event_list, 'mission', None),
            instr=getattr(full_event_list, 'instr', None),
        )

        # Add to state manager
        self.state.add_event_data(name, event_list)

        # Calculate durations
        total_duration = float(np.sum(original_gti[:, 1] - original_gti[:, 0]))
        preview_actual_duration = float(preview_times.max() - preview_times.min()) if len(preview_times) > 1 else 0.0

        summary = {
            "name": name,
            "n_events": len(preview_times),
            "time_range": [
                _to_python_float(preview_times.min()),
                _to_python_float(preview_times.max())
            ],
            "has_energy": preview_energy is not None,
            "has_pi": preview_pi is not None,
            "gti_count": 1,
            "preview_info": {
                "preview_duration": preview_duration,
                "actual_duration": preview_actual_duration,
                "total_file_duration": total_duration,
                "total_gti_count": len(original_gti),
                "file_size_mb": file_size_mb,
                "is_preview": True,
                "full_event_count": len(full_event_list.time),
                "loading_method": "EventList.read",
            },
        }

        return self.create_result(
            success=True,
            data=summary,
            message=f"Preview loaded: '{name}' - First {preview_duration}s ({len(preview_times)} events of {len(full_event_list.time)} total)",
        )


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
