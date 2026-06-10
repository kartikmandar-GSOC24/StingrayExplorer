"""
Lightcurve service for lightcurve operations.

Handles creation and manipulation of lightcurves.
"""

from typing import Any, Dict, List, Optional

import numpy as np
from stingray import Lightcurve

from .base_service import BaseService

# Cap on points transferred for plotting. The full-resolution Lightcurve stays
# in StateManager; only the JSON payload is strided.
DEFAULT_MAX_PLOT_POINTS = 200_000


def _decimate_for_plot(time, counts, max_points):
    """Stride-decimate arrays for display. Returns (time, counts, stride).

    max_points: Cap on points in the JSON payload; None or 0 sends full resolution.
    """
    n = len(time)
    if not max_points or max_points < 0 or n <= max_points:
        return time, counts, 1
    stride = int(np.ceil(n / max_points))
    return time[::stride], counts[::stride], stride


class LightcurveService(BaseService):
    """
    Service for Lightcurve operations.

    Handles creation and manipulation of lightcurves without any UI dependencies.
    """

    def create_lightcurve_from_event_list(
        self,
        event_list_name: str,
        dt: float,
        output_name: str,
        gti: Optional[List[List[float]]] = None,
        max_points: Optional[int] = DEFAULT_MAX_PLOT_POINTS,
    ) -> Dict[str, Any]:
        """
        Create a Lightcurve from an EventList.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            output_name: Name to save the lightcurve as
            gti: Optional Good Time Intervals
            max_points: Cap on points in the JSON payload; None or 0 sends full resolution.

        Returns:
            Result dictionary with lightcurve data
        """
        try:
            if not self.state.has_event_data(event_list_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_name}' not found",
                    error=None,
                )

            event_list = self.state.get_event_data(event_list_name)

            # Create lightcurve from event list
            lc = event_list.to_lc(dt=dt)

            # Apply GTIs if provided
            if gti is not None:
                gti_array = np.array(gti)
                lc = lc.apply_gtis(gti_array)

            # Save to state
            self.state.add_lightcurve_data(output_name, lc)

            # Prepare response data
            plot_time, plot_counts, stride = _decimate_for_plot(
                lc.time, lc.counts, max_points
            )
            lc_data = {
                "name": output_name,
                "time": plot_time.astype(float).tolist(),
                "counts": plot_counts.astype(float).tolist(),
                "dt": float(lc.dt),
                "n_bins": len(lc.time),
                "plot_stride": stride,
                "time_range": [float(lc.time.min()), float(lc.time.max())],
                "count_rate_mean": float(np.mean(lc.counts / lc.dt)),
            }

            return self.create_result(
                success=True,
                data=lc_data,
                message=f"Lightcurve '{output_name}' created (dt={dt}s, {len(lc.time)} bins)",
            )

        except Exception as e:
            return self.handle_error(
                e, "Creating lightcurve", event_list=event_list_name, dt=dt
            )

    def create_lightcurve_from_arrays(
        self,
        times: List[float],
        counts: List[float],
        dt: float,
        output_name: str,
    ) -> Dict[str, Any]:
        """
        Create a Lightcurve from time and count arrays.

        Args:
            times: Array of time values
            counts: Array of count values
            dt: Time binning in seconds
            output_name: Name to save the lightcurve as

        Returns:
            Result dictionary with lightcurve data
        """
        try:
            times_arr = np.array(times)
            counts_arr = np.array(counts)

            lc = Lightcurve(times_arr, counts_arr, dt=dt, skip_checks=True)

            # Save to state
            self.state.add_lightcurve_data(output_name, lc)

            lc_data = {
                "name": output_name,
                "time": lc.time.astype(float).tolist(),
                "counts": lc.counts.astype(float).tolist(),
                "dt": float(lc.dt),
                "n_bins": len(lc.time),
            }

            return self.create_result(
                success=True,
                data=lc_data,
                message=f"Lightcurve '{output_name}' created from arrays",
            )

        except Exception as e:
            return self.handle_error(e, "Creating lightcurve from arrays", dt=dt)

    def rebin_lightcurve(
        self,
        name: str,
        rebin_factor: float,
        output_name: str,
        max_points: Optional[int] = DEFAULT_MAX_PLOT_POINTS,
    ) -> Dict[str, Any]:
        """
        Rebin a lightcurve.

        Args:
            name: Name of the lightcurve to rebin
            rebin_factor: Rebinning factor
            output_name: Name for the rebinned lightcurve
            max_points: Cap on points in the JSON payload; None or 0 sends full resolution.

        Returns:
            Result dictionary with rebinned lightcurve data
        """
        try:
            if not self.state.has_lightcurve_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Lightcurve '{name}' not found",
                    error=None,
                )

            lightcurve = self.state.get_lightcurve_data(name)
            rebinned_lc = lightcurve.rebin(rebin_factor)

            # Save to state
            self.state.add_lightcurve_data(output_name, rebinned_lc)

            plot_time, plot_counts, stride = _decimate_for_plot(
                rebinned_lc.time, rebinned_lc.counts, max_points
            )
            lc_data = {
                "name": output_name,
                "time": plot_time.astype(float).tolist(),
                "counts": plot_counts.astype(float).tolist(),
                "dt": float(rebinned_lc.dt),
                "n_bins": len(rebinned_lc.time),
                "plot_stride": stride,
            }

            return self.create_result(
                success=True,
                data=lc_data,
                message=f"Lightcurve rebinned (factor={rebin_factor})",
            )

        except Exception as e:
            return self.handle_error(
                e, "Rebinning lightcurve", name=name, rebin_factor=rebin_factor
            )

    def get_lightcurve_data(
        self, name: str, max_points: Optional[int] = DEFAULT_MAX_PLOT_POINTS
    ) -> Dict[str, Any]:
        """
        Get lightcurve data for plotting.

        Args:
            name: Name of the lightcurve
            max_points: Cap on points in the JSON payload; None or 0 sends full resolution.

        Returns:
            Result dictionary with lightcurve data
        """
        try:
            if not self.state.has_lightcurve_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Lightcurve '{name}' not found",
                    error=None,
                )

            lc = self.state.get_lightcurve_data(name)

            plot_time, plot_counts, stride = _decimate_for_plot(
                lc.time, lc.counts, max_points
            )
            lc_data = {
                "name": name,
                "time": plot_time.astype(float).tolist(),
                "counts": plot_counts.astype(float).tolist(),
                "dt": float(lc.dt),
                "n_bins": len(lc.time),
                "plot_stride": stride,
                "time_range": [float(lc.time.min()), float(lc.time.max())],
                "count_stats": {
                    "mean": float(np.mean(lc.counts)),
                    "std": float(np.std(lc.counts)),
                    "min": float(np.min(lc.counts)),
                    "max": float(np.max(lc.counts)),
                },
            }

            return self.create_result(
                success=True,
                data=lc_data,
                message=f"Lightcurve '{name}' data retrieved",
            )

        except Exception as e:
            return self.handle_error(e, "Getting lightcurve data", name=name)

    def list_lightcurves(self) -> Dict[str, Any]:
        """List all loaded lightcurves."""
        try:
            lc_data = self.state.get_lightcurve_data()

            summaries = []
            for name, lc in lc_data:
                summaries.append(
                    {
                        "name": name,
                        "n_bins": len(lc.time),
                        "dt": float(lc.dt),
                        "time_range": [float(lc.time.min()), float(lc.time.max())],
                    }
                )

            return self.create_result(
                success=True,
                data=summaries,
                message=f"Found {len(summaries)} lightcurve(s)",
            )

        except Exception as e:
            return self.handle_error(e, "Listing lightcurves")

    def delete_lightcurve(self, name: str) -> Dict[str, Any]:
        """Delete a lightcurve from state."""
        try:
            if not self.state.has_lightcurve_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Lightcurve '{name}' not found",
                    error=None,
                )

            self.state.remove_lightcurve_data(name)

            return self.create_result(
                success=True,
                data={"name": name},
                message=f"Lightcurve '{name}' deleted",
            )

        except Exception as e:
            return self.handle_error(e, "Deleting lightcurve", name=name)
