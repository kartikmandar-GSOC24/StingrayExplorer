"""
Timing service for timing analysis operations.

Handles bispectrum, power colors, and other timing analysis.
"""

from typing import Any, Dict, Optional

import numpy as np
from stingray import Bispectrum, DynamicalPowerspectrum

from .base_service import BaseService


def _finite_list(arr) -> list:
    """Convert a float array to a list, replacing non-finite values with None."""
    values = np.asarray(arr, dtype=float)
    if np.isfinite(values).all():
        return values.tolist()
    return [float(v) if np.isfinite(v) else None for v in values]


def _segment_size_error(segment_size: float, dt: float) -> Optional[str]:
    """Human-readable rejection for segment sizes that stingray fails on cryptically.

    Needs at least 3 time bins per segment to produce a non-empty spectrum.
    """
    if segment_size / dt < 3:
        return (
            f"segment_size ({segment_size}s) must be at least 3x dt ({dt}s) "
            "to produce a non-empty spectrum"
        )
    return None


class TimingService(BaseService):
    """
    Service for timing analysis operations.

    Handles bispectrum, power colors, and higher-order timing analysis.
    """

    def create_bispectrum(
        self,
        event_list_name: str,
        dt: float,
        maxlag: int = 25,
        scale: str = "unbiased",
        window: str = "uniform",
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a bispectrum from an EventList.

        The bispectrum is used to detect non-linear interactions and
        non-Gaussian features in the data.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            maxlag: Maximum lag for bispectrum calculation
            scale: Scaling type ("biased" or "unbiased")
            window: Window function type
            output_name: Optional name to save the result

        Returns:
            Result dictionary with bispectrum data
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
            lc = event_list.to_lc(dt=dt)
            bs = Bispectrum(lc, maxlag=maxlag, scale=scale, window=window)

            if output_name:
                self.state.add_analysis_result(output_name, bs)

            bs_data = {
                "name": output_name,
                "freq": bs.freq.tolist(),
                "lags": bs.lags.tolist(),
                "bispec_mag": bs.bispec_mag.tolist(),
                "bispec_phase": bs.bispec_phase.tolist(),
                "cum3": bs.cum3.tolist(),
                "maxlag": maxlag,
                "scale": scale,
                "window": window,
            }

            return self.create_result(
                success=True,
                data=bs_data,
                message=f"Bispectrum created (maxlag={maxlag})",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Creating bispectrum",
                event_list=event_list_name,
                dt=dt,
                maxlag=maxlag,
            )

    def calculate_power_colors(
        self,
        event_list_name: str,
        dt: float,
        segment_size: float,
        freq_ranges: Dict[str, tuple],
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate power colors from frequency bands.

        Power colors are ratios of integrated power in different frequency bands,
        useful for source classification and state analysis.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            segment_size: Segment size in seconds
            freq_ranges: Dictionary of frequency ranges
            output_name: Optional name to save the result

        Returns:
            Result dictionary with power colors
        """
        try:
            if not self.state.has_event_data(event_list_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_name}' not found",
                    error=None,
                )

            seg_error = _segment_size_error(segment_size, dt)
            if seg_error:
                return self.create_result(
                    success=False, data=None, message=seg_error, error=None
                )

            event_list = self.state.get_event_data(event_list_name)
            lc = event_list.to_lc(dt=dt)
            dps = DynamicalPowerspectrum(lc, segment_size=segment_size, norm="leahy")

            # Mean power in each frequency band per time segment.
            # dps.dyn_ps has shape (n_freq, n_time); mask along axis 0 (freq).
            power_colors = {}
            for band_name, (f_min, f_max) in freq_ranges.items():
                mask = (dps.freq >= f_min) & (dps.freq < f_max)
                band_mean_power = dps.dyn_ps[mask, :].mean(axis=0)
                power_colors[band_name] = _finite_list(band_mean_power)

            result_data = {
                "name": output_name,
                "power_colors": power_colors,
                "time": dps.time.astype(float).tolist(),
                "freq_ranges": freq_ranges,
            }

            if output_name:
                self.state.add_analysis_result(output_name, result_data)

            return self.create_result(
                success=True,
                data=result_data,
                message=f"Power colors calculated for {len(freq_ranges)} bands",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Calculating power colors",
                event_list=event_list_name,
                dt=dt,
                segment_size=segment_size,
            )

    def calculate_time_lags(
        self,
        event_list_1_name: str,
        event_list_2_name: str,
        dt: float,
        segment_size: float,
        freq_range: Optional[tuple] = None,
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate time lags between two event lists.

        Args:
            event_list_1_name: Name of first EventList
            event_list_2_name: Name of second EventList
            dt: Time binning in seconds
            segment_size: Segment size in seconds
            freq_range: Optional frequency range to calculate lags for
            output_name: Optional name to save the result

        Returns:
            Result dictionary with time lags
        """
        try:
            if not self.state.has_event_data(event_list_1_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_1_name}' not found",
                    error=None,
                )

            if not self.state.has_event_data(event_list_2_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_2_name}' not found",
                    error=None,
                )

            seg_error = _segment_size_error(segment_size, dt)
            if seg_error:
                return self.create_result(
                    success=False, data=None, message=seg_error, error=None
                )

            from stingray import AveragedCrossspectrum

            event_list_1 = self.state.get_event_data(event_list_1_name)
            event_list_2 = self.state.get_event_data(event_list_2_name)

            lc1 = event_list_1.to_lc(dt=dt)
            lc2 = event_list_2.to_lc(dt=dt)

            cs = AveragedCrossspectrum.from_lightcurve(
                lc1=lc1,
                lc2=lc2,
                segment_size=segment_size,
                norm="leahy",
            )

            # Stingray's time_lag() returns (lag, lag_err) for averaged spectra.
            lag_result = cs.time_lag()
            if isinstance(lag_result, tuple):
                time_lags, time_lags_err = lag_result
            else:
                time_lags, time_lags_err = lag_result, None

            freq = np.asarray(cs.freq, dtype=float)
            time_lags = np.real(np.asarray(time_lags))
            if time_lags_err is not None:
                time_lags_err = np.real(np.asarray(time_lags_err))

            if time_lags.shape != freq.shape:
                raise ValueError(
                    f"Unexpected time_lag() result shape {time_lags.shape}"
                )

            if freq_range:
                mask = (freq >= freq_range[0]) & (freq <= freq_range[1])
                freq = freq[mask]
                time_lags = time_lags[mask]
                if time_lags_err is not None:
                    time_lags_err = time_lags_err[mask]

            result_data = {
                "name": output_name,
                "freq": freq.tolist(),
                "time_lags": _finite_list(time_lags),
                "time_lags_err": (
                    _finite_list(time_lags_err) if time_lags_err is not None else None
                ),
                "freq_range": freq_range,
            }

            if output_name:
                self.state.add_analysis_result(output_name, result_data)

            return self.create_result(
                success=True,
                data=result_data,
                message="Time lags calculated",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Calculating time lags",
                event_list_1=event_list_1_name,
                event_list_2=event_list_2_name,
                dt=dt,
                segment_size=segment_size,
            )

    def calculate_coherence(
        self,
        event_list_1_name: str,
        event_list_2_name: str,
        dt: float,
        segment_size: float,
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Calculate coherence between two event lists.

        Args:
            event_list_1_name: Name of first EventList
            event_list_2_name: Name of second EventList
            dt: Time binning in seconds
            segment_size: Segment size in seconds
            output_name: Optional name to save the result

        Returns:
            Result dictionary with coherence data
        """
        try:
            if not self.state.has_event_data(event_list_1_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_1_name}' not found",
                    error=None,
                )

            if not self.state.has_event_data(event_list_2_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_2_name}' not found",
                    error=None,
                )

            seg_error = _segment_size_error(segment_size, dt)
            if seg_error:
                return self.create_result(
                    success=False, data=None, message=seg_error, error=None
                )

            from stingray import AveragedCrossspectrum

            event_list_1 = self.state.get_event_data(event_list_1_name)
            event_list_2 = self.state.get_event_data(event_list_2_name)

            lc1 = event_list_1.to_lc(dt=dt)
            lc2 = event_list_2.to_lc(dt=dt)

            cs = AveragedCrossspectrum.from_lightcurve(
                lc1=lc1,
                lc2=lc2,
                segment_size=segment_size,
                norm="leahy",
            )

            # Stingray's coherence() returns (coherence, uncertainty) for
            # averaged cross spectra (Vaughan & Nowak 1997).
            coh_result = cs.coherence()
            if isinstance(coh_result, tuple):
                coherence_vals, coherence_err = coh_result
            else:
                coherence_vals, coherence_err = coh_result, None

            coherence_vals = np.real(np.asarray(coherence_vals))
            if coherence_vals.shape != np.asarray(cs.freq).shape:
                raise ValueError(
                    f"Unexpected coherence() result shape {coherence_vals.shape}"
                )

            # Uncertainty formula goes negative where coh > 1; report magnitude as the half-width.
            result_data = {
                "name": output_name,
                "freq": cs.freq.tolist(),
                "coherence": _finite_list(coherence_vals),
                "coherence_err": (
                    _finite_list(np.abs(np.real(np.asarray(coherence_err))))
                    if coherence_err is not None
                    else None
                ),
                "segment_size": segment_size,
                "n_segments": int(cs.m) if hasattr(cs, "m") else None,
            }

            if output_name:
                self.state.add_analysis_result(output_name, result_data)

            return self.create_result(
                success=True,
                data=result_data,
                message="Coherence calculated",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Calculating coherence",
                event_list_1=event_list_1_name,
                event_list_2=event_list_2_name,
                dt=dt,
                segment_size=segment_size,
            )
