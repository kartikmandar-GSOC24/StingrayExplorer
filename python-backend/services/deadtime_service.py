"""
Dead-time service for dead-time model and FAD corrections.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.
"""

from typing import Any, Dict, List, Optional

import numpy as np
from stingray import AveragedPowerspectrum, EventList
from stingray.deadtime.fad import FAD

from .analysis_helpers import (
    collect_warnings,
    finite_list,
    overlap_error,
    segment_size_error,
)
from .base_service import BaseService

# Below this many averaged segments the FAD correction is unreliable
# (Bachetti & Huppenkothen 2018 / stingray docstring recommendation).
MIN_FAD_SEGMENTS = 30


def _gti_exposure(event_list) -> float:
    """Total good time in seconds (sum of GTI durations, not last - first).

    EventList.gti is auto-derived from the event times when it was never set,
    so this is always defined for a non-empty list.
    """
    gti = np.atleast_2d(np.asarray(event_list.gti, dtype=float))
    return float(np.sum(gti[:, 1] - gti[:, 0]))


def _finite_or_none(value) -> Optional[float]:
    """Coerce a stingray-meta scalar to a JSON-safe float, or None.

    Every array column in this service is sanitized with `finite_list`, but
    scalars pulled straight out of `results.meta` are not. FAD's smoothed
    Fourier difference (`smooth_real`) can be exactly zero -- e.g. when the
    two inputs are byte-identical -- which turns `fad_delta` (and, in
    principle, any other meta scalar derived from that same division) into
    NaN. An unguarded `float(nan)` would pass success=True all the way to
    `json.dumps(..., allow_nan=False)` and blow up the response. This is the
    scalar equivalent of `finite_list`.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _detached_copy(event_list) -> EventList:
    """A throwaway EventList sharing the stored arrays but owning its own GTI.

    stingray's FAD() does `data1.gti = data2.gti = cross_two_gtis(...)`, which
    would otherwise permanently overwrite the GTIs of the EventLists held in
    StateManager (and race with concurrent requests). Attribute assignment on
    this wrapper cannot reach the stored object, and `time` is shared by
    reference so large event lists are not duplicated.
    """
    return EventList(time=event_list.time, gti=np.array(event_list.gti, copy=True))


class DeadtimeService(BaseService):
    """Service for dead-time correction operations."""

    def calculate_pds_correction(
        self,
        event_list_name: str,
        dt: float,
        segment_size: float,
        dead_time: float,
        background_rate: float = 0.0,
        limit_k: int = 200,
    ) -> Dict[str, Any]:
        """
        Model-based (Zhang+95, non-paralyzable) dead-time correction of a PDS.

        Args:
            event_list_name: Name of the EventList in state
            dt: Time binning in seconds
            segment_size: Segment length in seconds for the averaged PDS
            dead_time: Detector dead time per event in seconds
            background_rate: Background count rate in counts/s
            limit_k: Number of terms in the Zhang+95 series expansion

        Returns:
            Result dictionary with uncorrected and corrected power spectra
        """
        try:
            if not self.state.has_event_data(event_list_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_name}' not found",
                    error=None,
                )

            if dead_time <= 0:
                return self.create_result(
                    success=False,
                    data=None,
                    message=(
                        f"dead_time must be positive (got {dead_time}s); "
                        "there is nothing to correct for a zero dead time"
                    ),
                    error=None,
                )

            seg_error = segment_size_error(segment_size, dt)
            if seg_error:
                return self.create_result(
                    success=False, data=None, message=seg_error, error=None
                )

            event_list = self.state.get_event_data(event_list_name)
            n_events = int(len(event_list.time))
            if n_events == 0:
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_name}' contains no events",
                    error=None,
                )

            exposure = _gti_exposure(event_list)
            if exposure <= 0:
                return self.create_result(
                    success=False,
                    data=None,
                    message=(
                        f"EventList '{event_list_name}' has no good-time exposure; "
                        "cannot derive a count rate"
                    ),
                    error=None,
                )
            if segment_size > exposure:
                return self.create_result(
                    success=False,
                    data=None,
                    message=(
                        f"segment_size ({segment_size}s) is longer than the total "
                        f"good-time exposure ({exposure:.1f}s)"
                    ),
                    error=None,
                )

            # `rate` for the Zhang model is the DETECTED rate, i.e. the events
            # that survived dead time divided by the live exposure.
            rate = n_events / exposure

            # stingray raises a bare ValueError from inside the numba model for
            # this; pre-empt it with a message naming the actual numbers.
            occupancy = (rate + background_rate) * dead_time
            if occupancy >= 1:
                return self.create_result(
                    success=False,
                    data=None,
                    message=(
                        "(rate + background_rate) x dead_time must be less than 1 "
                        "for a physical correction: detected rate "
                        f"{rate:.2f} c/s + background {background_rate:.2f} c/s "
                        f"over dead time {dead_time}s gives {occupancy:.2f}. "
                        "Lower the dead time or check the event list."
                    ),
                    error=None,
                )

            warning_messages: List[str] = []
            with collect_warnings(warning_messages):
                # norm is hard-locked to "leahy": deadtime_correct() applies
                # `2 / model` without ever checking self.norm, i.e. it assumes
                # the Leahy white-noise level of 2. Any other norm would be
                # silently mis-corrected.
                pds = AveragedPowerspectrum.from_events(
                    event_list, dt=dt, segment_size=segment_size, norm="leahy"
                )
                corrected = pds.deadtime_correct(
                    dead_time=dead_time,
                    rate=rate,
                    background_rate=background_rate,
                    limit_k=limit_k,
                )

            result_data = {
                "freq": finite_list(pds.freq),
                "power_uncorrected": finite_list(pds.power),
                "power_corrected": finite_list(corrected.power),
                "rate": float(rate),
                "n_events": n_events,
                "exposure": exposure,
                "n_segments": int(pds.m),
                "dt": float(dt),
                "segment_size": float(segment_size),
                "dead_time": float(dead_time),
                "background_rate": float(background_rate),
                "limit_k": int(limit_k),
                "norm": "leahy",
                "warnings": warning_messages,
            }

            return self.create_result(
                success=True,
                data=result_data,
                message=(
                    f"Dead-time corrected PDS ({int(pds.m)} segments, "
                    f"detected rate {rate:.1f} c/s)"
                ),
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Applying model dead-time correction",
                event_list=event_list_name,
                dt=dt,
                segment_size=segment_size,
                dead_time=dead_time,
            )

    def calculate_fad_correction(
        self,
        event_list_1_name: str,
        event_list_2_name: str,
        dt: float,
        segment_size: float,
        norm: str = "frac",
        smoothing_length: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Frequency Amplitude Difference correction from two independent detectors.

        Args:
            event_list_1_name: Name of the first detector's EventList
            event_list_2_name: Name of the second detector's EventList
            dt: Time binning in seconds
            segment_size: Segment length in seconds
            norm: Power spectrum normalization (frac/leahy/abs/none)
            smoothing_length: Sigma (standard deviation) of the Gaussian
                filter stingray uses to smooth the FAD diagnostic in
                frequency space, in units of frequency BINS (array samples)
                -- NOT seconds, despite the field name. stingray passes this
                value straight to `scipy.ndimage.gaussian_filter1d` on the
                per-segment power spectrum, whose bin spacing is
                df = 1/segment_size, so the physical smoothing width in Hz
                is smoothing_length / segment_size: the same numeric value
                smooths a different physical frequency range depending on
                segment_size. When left as None, stingray defaults to
                `3 * segment_size` (segment_size in seconds, reused verbatim
                as a bin count), which happens to give a
                segment_size-independent physical width of 3 Hz -- unlike
                any value supplied explicitly here.

        Returns:
            Result dictionary with FAD-corrected periodograms
        """
        try:
            for name in (event_list_1_name, event_list_2_name):
                if not self.state.has_event_data(name):
                    return self.create_result(
                        success=False,
                        data=None,
                        message=f"EventList '{name}' not found",
                        error=None,
                    )

            seg_error = segment_size_error(segment_size, dt)
            if seg_error:
                return self.create_result(
                    success=False, data=None, message=seg_error, error=None
                )

            events1 = self.state.get_event_data(event_list_1_name)
            events2 = self.state.get_event_data(event_list_2_name)

            # Preflight the degenerate inputs stingray fails on cryptically
            # deep inside FAD (a bare IndexError/AssertionError/ZeroDivision
            # with no mention of which event list or GTI caused it):
            #   - an event list with no events at all -- note `EventList.time`
            #     is `None`, not an empty array, when the list is genuinely
            #     empty, so `len(events.time)` cannot be used directly here.
            #   - an event list with events but zero good-time exposure (e.g.
            #     a fully-screened observation with `gti` reduced to zero
            #     rows).
            for name, events in (
                (event_list_1_name, events1),
                (event_list_2_name, events2),
            ):
                n_events = 0 if events.time is None else len(events.time)
                if n_events == 0:
                    return self.create_result(
                        success=False,
                        data=None,
                        message=f"EventList '{name}' contains no events",
                        error=None,
                    )
                if _gti_exposure(events) <= 0:
                    return self.create_result(
                        success=False,
                        data=None,
                        message=(
                            f"EventList '{name}' has no good-time exposure "
                            "(its GTI is empty); cannot compute the FAD "
                            "diagnostic"
                        ),
                        error=None,
                    )

            ovl_error = overlap_error(events1, events2, segment_size)
            if ovl_error:
                return self.create_result(
                    success=False, data=None, message=ovl_error, error=None
                )

            warning_messages: List[str] = []
            with collect_warnings(warning_messages):
                # strict=False (stingray's default): a non-compliant FAD
                # diagnostic must degrade to a warning, never a RuntimeError.
                results = FAD(
                    _detached_copy(events1),
                    _detached_copy(events2),
                    segment_size,
                    dt=dt,
                    norm=norm,
                    smoothing_length=smoothing_length,
                    strict=False,
                )

            n_segments = int(results.meta["M"])
            # `fad_delta` is `(std - stdtheor) / stdtheor`, where `std` comes
            # from dividing by the smoothed Fourier difference; that smoothed
            # value can be exactly zero (e.g. the two inputs are
            # byte-identical), producing a NaN that must never reach the
            # response unguarded (json.dumps(..., allow_nan=False) would
            # raise and take the whole request down with an unhandled 500).
            fad_delta = _finite_or_none(results.meta["fad_delta"])
            if n_segments < MIN_FAD_SEGMENTS:
                warning_messages.append(
                    f"Only {n_segments} segments were averaged (fewer than "
                    f"{MIN_FAD_SEGMENTS}); the FAD correction is unreliable below "
                    "that. Shorten segment_size or use a longer observation."
                )
            if fad_delta is None:
                warning_messages.append(
                    "The FAD compliance diagnostic (fad_delta) could not be "
                    "computed: the smoothed Fourier difference between the "
                    "two inputs was zero, which happens when the two event "
                    "lists are identical or otherwise fully correlated. Use "
                    "two independent, simultaneous detectors; fad_delta and "
                    "the compliance check are unavailable for this run."
                )
            elif not bool(results.meta["is_compliant"]):
                warning_messages.append(
                    "FAD diagnostic failed: the scatter of the smoothed Fourier "
                    "difference deviates from theory by "
                    f"{fad_delta * 100:.1f}%. The two event "
                    "lists may not be independent simultaneous detectors."
                )

            # `cs` is complex (the corrected cross spectrum); serialize its
            # magnitude for the headline trace and keep the real part (the
            # signed cospectrum) alongside it.
            cs = np.asarray(results["cs"])

            result_data = {
                "freq": finite_list(results["freq"]),
                "pds1": finite_list(results["pds1"]),
                "pds2": finite_list(results["pds2"]),
                "ptot": finite_list(results["ptot"]),
                "cs": finite_list(np.abs(cs)),
                "cs_real": finite_list(cs.real),
                "n_segments": n_segments,
                "dt": _finite_or_none(results.meta["dt"]),
                "segment_size": float(segment_size),
                "norm": str(results.meta["norm"]),
                "smoothing_length": _finite_or_none(results.meta["smoothing_length"]),
                "is_compliant": bool(results.meta["is_compliant"]),
                "fad_delta": fad_delta,
                "warnings": warning_messages,
            }

            return self.create_result(
                success=True,
                data=result_data,
                message=(
                    f"FAD correction computed ({n_segments} segments, norm={norm})"
                ),
            )

        except Exception as e:
            return self.handle_error(
                e,
                "Applying FAD dead-time correction",
                event_list_1=event_list_1_name,
                event_list_2=event_list_2_name,
                dt=dt,
                segment_size=segment_size,
            )
