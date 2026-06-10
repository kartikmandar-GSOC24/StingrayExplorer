"""
Spectrum service for spectral analysis operations.

Handles power spectrum, cross spectrum, and dynamical power spectrum operations.
"""

from typing import Any, Dict, Optional

import numpy as np
from stingray import (
    AveragedCrossspectrum,
    AveragedPowerspectrum,
    Crossspectrum,
    DynamicalPowerspectrum,
    Powerspectrum,
)

from .base_service import BaseService


def _power_to_lists(power) -> tuple:
    """Split a (possibly complex) power array into JSON-safe magnitude and phase lists.

    Returns (power_list, phase_list_or_None). Non-finite values become None so
    strict JSON (and JS JSON.parse) never sees NaN/Infinity.
    """
    arr = np.asarray(power)
    if np.iscomplexobj(arr):
        mag = np.abs(arr)
        phase = np.angle(arr)
        return _finite_list(mag), _finite_list(phase)
    return _finite_list(arr), None


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


def _overlap_error(events1, events2) -> Optional[str]:
    """Readable rejection when two event lists share no time overlap."""
    start = max(float(events1.time[0]), float(events2.time[0]))
    stop = min(float(events1.time[-1]), float(events2.time[-1]))
    if stop <= start:
        return (
            "the two event lists have no overlapping time range "
            f"({events1.time[0]:.1f}-{events1.time[-1]:.1f}s vs "
            f"{events2.time[0]:.1f}-{events2.time[-1]:.1f}s)"
        )
    return None


class SpectrumService(BaseService):
    """
    Service for spectral analysis operations.

    Handles power spectrum, cross spectrum, and dynamical power spectrum.
    """

    def create_power_spectrum(
        self,
        event_list_name: str,
        dt: float,
        norm: str = "leahy",
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a power spectrum from an EventList.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            norm: Normalization type ("leahy", "frac", "abs", "none")
            output_name: Optional name to save the spectrum

        Returns:
            Result dictionary with power spectrum data
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
            ps = Powerspectrum(lc, norm=norm)

            # Save if name provided
            if output_name:
                self.state.add_spectrum_data(output_name, ps)

            power_list, phase_list = _power_to_lists(ps.power)
            ps_data = {
                "name": output_name,
                "freq": ps.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(ps.freq),
                "df": float(ps.df),
                "freq_range": [float(ps.freq[0]), float(ps.freq[-1])],
            }

            return self.create_result(
                success=True,
                data=ps_data,
                message=f"Power spectrum created (dt={dt}s, norm={norm})",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Creating power spectrum",
                event_list=event_list_name,
                dt=dt,
                norm=norm,
            )

    def create_averaged_power_spectrum(
        self,
        event_list_name: str,
        dt: float,
        segment_size: float,
        norm: str = "leahy",
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an averaged power spectrum from an EventList.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            segment_size: Segment size in seconds for averaging
            norm: Normalization type
            output_name: Optional name to save the spectrum

        Returns:
            Result dictionary with averaged power spectrum data
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
            ps = AveragedPowerspectrum.from_lightcurve(lc, segment_size, norm=norm)

            if output_name:
                self.state.add_spectrum_data(output_name, ps)

            power_list, phase_list = _power_to_lists(ps.power)
            ps_data = {
                "name": output_name,
                "freq": ps.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(ps.freq),
                "df": float(ps.df),
                "segment_size": segment_size,
                "n_segments": int(ps.m) if hasattr(ps, "m") else None,
            }

            return self.create_result(
                success=True,
                data=ps_data,
                message=f"Averaged power spectrum created (segment={segment_size}s)",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Creating averaged power spectrum",
                event_list=event_list_name,
                dt=dt,
                segment_size=segment_size,
                norm=norm,
            )

    def create_cross_spectrum(
        self,
        event_list_1_name: str,
        event_list_2_name: str,
        dt: float,
        norm: str = "leahy",
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a cross spectrum from two EventLists.

        Args:
            event_list_1_name: Name of first EventList
            event_list_2_name: Name of second EventList
            dt: Time binning in seconds
            norm: Normalization type
            output_name: Optional name to save the spectrum

        Returns:
            Result dictionary with cross spectrum data
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

            event_list_1 = self.state.get_event_data(event_list_1_name)
            event_list_2 = self.state.get_event_data(event_list_2_name)

            overlap_error = _overlap_error(event_list_1, event_list_2)
            if overlap_error:
                return self.create_result(
                    success=False, data=None, message=overlap_error, error=None
                )

            cs = Crossspectrum.from_events(
                events1=event_list_1,
                events2=event_list_2,
                dt=dt,
                norm=norm,
            )

            if output_name:
                self.state.add_spectrum_data(output_name, cs)

            power_list, phase_list = _power_to_lists(cs.power)
            cs_data = {
                "name": output_name,
                "freq": cs.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(cs.freq),
                "df": float(cs.df),
            }

            return self.create_result(
                success=True,
                data=cs_data,
                message=f"Cross spectrum created (dt={dt}s)",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Creating cross spectrum",
                event_list_1=event_list_1_name,
                event_list_2=event_list_2_name,
                dt=dt,
                norm=norm,
            )

    def create_averaged_cross_spectrum(
        self,
        event_list_1_name: str,
        event_list_2_name: str,
        dt: float,
        segment_size: float,
        norm: str = "leahy",
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an averaged cross spectrum from two EventLists.

        Args:
            event_list_1_name: Name of first EventList
            event_list_2_name: Name of second EventList
            dt: Time binning in seconds
            segment_size: Segment size in seconds
            norm: Normalization type
            output_name: Optional name to save the spectrum

        Returns:
            Result dictionary with averaged cross spectrum data
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

            event_list_1 = self.state.get_event_data(event_list_1_name)
            event_list_2 = self.state.get_event_data(event_list_2_name)

            overlap_error = _overlap_error(event_list_1, event_list_2)
            if overlap_error:
                return self.create_result(
                    success=False, data=None, message=overlap_error, error=None
                )

            lc1 = event_list_1.to_lc(dt=dt)
            lc2 = event_list_2.to_lc(dt=dt)

            cs = AveragedCrossspectrum.from_lightcurve(
                lc1=lc1,
                lc2=lc2,
                segment_size=segment_size,
                norm=norm,
            )

            if output_name:
                self.state.add_spectrum_data(output_name, cs)

            power_list, phase_list = _power_to_lists(cs.power)
            cs_data = {
                "name": output_name,
                "freq": cs.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": norm,
                "n_freq": len(cs.freq),
                "df": float(cs.df),
                "segment_size": segment_size,
            }

            return self.create_result(
                success=True,
                data=cs_data,
                message=f"Averaged cross spectrum created (segment={segment_size}s)",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Creating averaged cross spectrum",
                event_list_1=event_list_1_name,
                event_list_2=event_list_2_name,
                dt=dt,
                segment_size=segment_size,
                norm=norm,
            )

    def create_dynamical_power_spectrum(
        self,
        event_list_name: str,
        dt: float,
        segment_size: float,
        norm: str = "leahy",
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a dynamical power spectrum from an EventList.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            segment_size: Segment size in seconds
            norm: Normalization type
            output_name: Optional name to save the spectrum

        Returns:
            Result dictionary with dynamical power spectrum data
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
            dps = DynamicalPowerspectrum(lc, segment_size=segment_size, norm=norm)

            if output_name:
                self.state.add_spectrum_data(output_name, dps)

            dps_data = {
                "name": output_name,
                "freq": dps.freq.tolist(),
                "time": dps.time.astype(float).tolist(),
                "dyn_ps": [_finite_list(row) for row in dps.dyn_ps],
                "norm": norm,
                "segment_size": segment_size,
                "shape": list(dps.dyn_ps.shape),
            }

            return self.create_result(
                success=True,
                data=dps_data,
                message=f"Dynamical power spectrum created (segment={segment_size}s)",
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Creating dynamical power spectrum",
                event_list=event_list_name,
                dt=dt,
                segment_size=segment_size,
                norm=norm,
            )

    def rebin_spectrum(
        self,
        name: str,
        rebin_factor: float,
        log: bool = False,
        output_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Rebin a spectrum.

        Args:
            name: Name of the spectrum to rebin
            rebin_factor: Rebinning factor
            log: If True, use logarithmic rebinning
            output_name: Optional name for rebinned spectrum

        Returns:
            Result dictionary with rebinned spectrum data
        """
        try:
            if not self.state.has_spectrum_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Spectrum '{name}' not found",
                    error=None,
                )

            spectrum = self.state.get_spectrum_data(name)

            if log:
                rebinned = spectrum.rebin_log(rebin_factor)
            else:
                # stingray rebin()'s positional arg is df (Hz), not a factor; use f=
                rebinned = spectrum.rebin(f=rebin_factor)

            if output_name:
                self.state.add_spectrum_data(output_name, rebinned)

            power_list, phase_list = _power_to_lists(rebinned.power)
            data = {
                "name": output_name,
                "freq": rebinned.freq.tolist(),
                "power": power_list,
                "power_phase": phase_list,
                "norm": getattr(rebinned, "norm", None),
                "n_freq": len(rebinned.freq),
            }

            return self.create_result(
                success=True,
                data=data,
                message=f"Spectrum rebinned ({'log' if log else 'linear'}, factor={rebin_factor})",
            )

        except Exception as e:
            return self.handle_error(
                e, "Rebinning spectrum", name=name, rebin_factor=rebin_factor, log=log
            )

    def list_spectra(self) -> Dict[str, Any]:
        """List all loaded spectra."""
        try:
            spec_data = self.state.get_spectrum_data()

            summaries = []
            for name, spec in spec_data:
                spec_type = type(spec).__name__
                summaries.append(
                    {
                        "name": name,
                        "type": spec_type,
                        "n_freq": len(spec.freq) if hasattr(spec, "freq") else None,
                    }
                )

            return self.create_result(
                success=True,
                data=summaries,
                message=f"Found {len(summaries)} spectrum/spectra",
            )

        except Exception as e:
            return self.handle_error(e, "Listing spectra")

    def delete_spectrum(self, name: str) -> Dict[str, Any]:
        """Delete a spectrum from state."""
        try:
            if not self.state.has_spectrum_data(name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"Spectrum '{name}' not found",
                    error=None,
                )

            self.state.remove_spectrum_data(name)

            return self.create_result(
                success=True,
                data={"name": name},
                message=f"Spectrum '{name}' deleted",
            )

        except Exception as e:
            return self.handle_error(e, "Deleting spectrum", name=name)
