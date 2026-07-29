"""
Correlation service for auto/cross-correlation analysis.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.

Sign convention (verified against stingray 2.2.10 by aligning a Gaussian pulse):
**a positive ``time_shift`` means the first event list lags behind the second**;
a negative ``time_shift`` means the first list leads. Surface this verbatim in
the UI -- it is easy to get backwards.

stingray's ``CrossCorrelation`` correlates the two ``counts`` arrays purely by
position and never looks at ``Lightcurve.time``, so two lists covering different
absolute time ranges would be silently mis-aligned. This service therefore bins
both event lists onto ONE shared bin-edge grid spanning their common time range
before handing them to stingray.
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from stingray import Lightcurve
from stingray.crosscorrelation import AutoCorrelation, CrossCorrelation

from .analysis_helpers import collect_warnings, finite_list, overlap_error
from .base_service import BaseService

# 'valid' is deliberately excluded: with equal-length inputs (which the shared
# grid always produces) it degenerates to a single point.
VALID_MODES = ("same", "full")
VALID_NORMS = ("none", "variance")

# Minimum number of shared bins before a correlation is worth computing.
MIN_BINS = 3


def _mode_error(mode: str) -> Optional[str]:
    """Readable rejection for correlation modes this endpoint does not expose."""
    if mode not in VALID_MODES:
        return (
            f"mode '{mode}' is not supported; use one of "
            f"{', '.join(repr(m) for m in VALID_MODES)}"
        )
    return None


def _norm_error(norm: str) -> Optional[str]:
    """Readable rejection for normalisations stingray's correlation cannot do."""
    if norm not in VALID_NORMS:
        return (
            f"norm '{norm}' is not supported; use one of "
            f"{', '.join(repr(n) for n in VALID_NORMS)}"
        )
    return None


def _dt_error(dt: float) -> Optional[str]:
    """Readable rejection for bin sizes that cannot produce a light curve."""
    if not np.isfinite(dt) or dt <= 0:
        return f"dt ({dt}) must be a positive number of seconds"
    return None


def _span_error(span: float, dt: float, what: str) -> Optional[str]:
    """Readable rejection when the time span cannot hold MIN_BINS bins."""
    if span / dt < MIN_BINS:
        return (
            f"dt ({dt}s) is too coarse for {what} ({span:.3f}s): "
            f"at least {MIN_BINS} bins are needed to correlate"
        )
    return None


def _empty_error(event_list, name: str) -> Optional[str]:
    """Readable rejection for event lists with no photons."""
    times = getattr(event_list, "time", None)
    if times is None or len(times) == 0:
        return f"EventList '{name}' contains no events"
    return None


def _noise_subtracted_variance(lc: Lightcurve) -> float:
    """Reproduce stingray's norm='variance' denominator term for one curve.

    stingray computes ``var(counts) - mean(counts_err)**2`` and then takes
    ``sqrt(var1 * var2)``. A negative term is what makes the normalisation
    either meaningless (both negative) or NaN (exactly one negative).
    """
    counts = np.asarray(lc.counts, dtype=float)
    counts_err = np.asarray(lc.counts_err, dtype=float)
    return float(np.var(counts) - np.mean(counts_err) ** 2)


def _variance_warning(lc: Lightcurve, label: str) -> Optional[str]:
    """Advisory when a light curve is too flat/faint for norm='variance'."""
    variance = _noise_subtracted_variance(lc)
    if variance > 0:
        return None
    return (
        f"{label} has a negative noise-subtracted variance "
        f"(var - mean(err)^2 = {variance:.3g}), which happens for flat or "
        "low-count data; the 'variance' normalisation is not physically "
        "meaningful here. Try a larger dt or norm='none'."
    )


def _nan_corr_warning(corr) -> Optional[str]:
    """Advisory when stingray silently produced an all/partly-NaN correlation.

    Must be evaluated on the RAW stingray array, before finite_list() turns the
    NaNs into JSON nulls. stingray still reports an argmax-derived time_shift
    for an all-NaN corr, which is meaningless, so the caller nulls it out.
    """
    values = np.asarray(corr, dtype=float)
    if not np.isnan(values).any():
        return None
    return (
        "The correlation contains NaN values (stingray's 'variance' "
        "normalisation takes the square root of a negative variance product "
        "for flat or low-count light curves). The time shift is unreliable "
        "and has been omitted."
    )


def _shared_grid_lightcurves(
    events1, events2, dt: float
) -> Tuple[Lightcurve, Lightcurve, float, float]:
    """Bin two event lists onto one identical grid over their common range.

    stingray performs no time alignment whatsoever, so this is the only thing
    that makes a cross-correlation of two independently-loaded event lists
    physically meaningful.
    """
    start = max(float(events1.time[0]), float(events2.time[0]))
    stop = min(float(events1.time[-1]), float(events2.time[-1]))

    edges = np.arange(start, stop + dt, dt)
    # arange's exclusive stop can leave one edge past the common range; that
    # final bin would only be partially covered, so drop it.
    edges = edges[edges <= stop + 1e-9]

    counts1, _ = np.histogram(events1.time, bins=edges)
    counts2, _ = np.histogram(events2.time, bins=edges)
    centers = edges[:-1] + dt / 2.0
    gti = [[float(edges[0]), float(edges[-1])]]

    lc1 = Lightcurve(time=centers, counts=counts1, dt=dt, gti=gti, skip_checks=True)
    lc2 = Lightcurve(time=centers, counts=counts2, dt=dt, gti=gti, skip_checks=True)
    return lc1, lc2, float(edges[0]), float(edges[-1])


class CorrelationService(BaseService):
    """Service for auto/cross-correlation operations."""

    def auto_correlation(
        self,
        event_list_name: str,
        dt: float,
        mode: str = "same",
        norm: str = "none",
    ) -> Dict[str, Any]:
        """Auto-correlate one event list's light curve with itself.

        ``norm='none'`` uses ``AutoCorrelation``; ``norm='variance'`` must go
        through ``CrossCorrelation(lc, lc, norm='variance')`` because
        ``AutoCorrelation.__init__`` does not forward ``norm`` (it is hardcoded
        to ``'none'`` upstream). ``time_shift`` is always 0 for an
        auto-correlation.
        """
        try:
            for message in (_mode_error(mode), _norm_error(norm), _dt_error(dt)):
                if message:
                    return self.create_result(
                        success=False, data=None, message=message, error=None
                    )

            if not self.state.has_event_data(event_list_name):
                return self.create_result(
                    success=False,
                    data=None,
                    message=f"EventList '{event_list_name}' not found",
                    error=None,
                )

            event_list = self.state.get_event_data(event_list_name)
            empty = _empty_error(event_list, event_list_name)
            if empty:
                return self.create_result(
                    success=False, data=None, message=empty, error=None
                )

            span = float(event_list.time[-1]) - float(event_list.time[0])
            span_message = _span_error(span, dt, f"the span of '{event_list_name}'")
            if span_message:
                return self.create_result(
                    success=False, data=None, message=span_message, error=None
                )

            warnings_out: List[str] = []
            with collect_warnings(warnings_out):
                lc = event_list.to_lc(dt=dt)
                if norm == "variance":
                    variance_warning = _variance_warning(lc, "The light curve")
                    if variance_warning:
                        warnings_out.append(variance_warning)
                    correlation = CrossCorrelation(lc, lc, mode=mode, norm="variance")
                else:
                    correlation = AutoCorrelation(lc, mode=mode)

            data = self._build_payload(correlation, mode, norm, warnings_out)
            return self.create_result(
                success=True,
                data=data,
                message=(
                    f"Auto-correlation computed for '{event_list_name}' "
                    f"({data['n']} lags, dt={dt}s)"
                ),
            )

        except Exception as exception:  # pragma: no cover - defensive
            return self.handle_error(
                exception,
                "Auto-correlation",
                event_list=event_list_name,
                dt=dt,
                mode=mode,
                norm=norm,
            )

    def cross_correlation(
        self,
        event_list_1_name: str,
        event_list_2_name: str,
        dt: float,
        mode: str = "same",
        norm: str = "none",
    ) -> Dict[str, Any]:
        """Cross-correlate two event lists binned onto one shared grid.

        A positive ``time_shift`` means the FIRST list lags behind the second.
        """
        try:
            for message in (_mode_error(mode), _norm_error(norm), _dt_error(dt)):
                if message:
                    return self.create_result(
                        success=False, data=None, message=message, error=None
                    )

            for name in (event_list_1_name, event_list_2_name):
                if not self.state.has_event_data(name):
                    return self.create_result(
                        success=False,
                        data=None,
                        message=f"EventList '{name}' not found",
                        error=None,
                    )

            events1 = self.state.get_event_data(event_list_1_name)
            events2 = self.state.get_event_data(event_list_2_name)
            for event_list, name in (
                (events1, event_list_1_name),
                (events2, event_list_2_name),
            ):
                empty = _empty_error(event_list, name)
                if empty:
                    return self.create_result(
                        success=False, data=None, message=empty, error=None
                    )

            # Runs on the RAW event lists, before any binning.
            overlap = overlap_error(events1, events2)
            if overlap:
                return self.create_result(
                    success=False, data=None, message=overlap, error=None
                )

            start = max(float(events1.time[0]), float(events2.time[0]))
            stop = min(float(events1.time[-1]), float(events2.time[-1]))
            span_message = _span_error(stop - start, dt, "the overlapping time range")
            if span_message:
                return self.create_result(
                    success=False, data=None, message=span_message, error=None
                )

            warnings_out: List[str] = []
            with collect_warnings(warnings_out):
                lc1, lc2, grid_start, grid_stop = _shared_grid_lightcurves(
                    events1, events2, dt
                )

                cropped = any(
                    float(events.time[0]) < grid_start - dt
                    or float(events.time[-1]) > grid_stop + dt
                    for events in (events1, events2)
                )
                if cropped:
                    warnings_out.append(
                        "Both event lists were binned onto a shared "
                        f"{dt}s grid over their common time range "
                        f"{grid_start:.3f}-{grid_stop:.3f}s ({lc1.n} bins); "
                        "events outside that range were excluded."
                    )

                if norm == "variance":
                    for lc, label in (
                        (lc1, f"'{event_list_1_name}'"),
                        (lc2, f"'{event_list_2_name}'"),
                    ):
                        variance_warning = _variance_warning(lc, label)
                        if variance_warning:
                            warnings_out.append(variance_warning)

                correlation = CrossCorrelation(lc1, lc2, mode=mode, norm=norm)

            data = self._build_payload(correlation, mode, norm, warnings_out)
            return self.create_result(
                success=True,
                data=data,
                message=(
                    f"Cross-correlation computed for '{event_list_1_name}' x "
                    f"'{event_list_2_name}' ({data['n']} lags, dt={dt}s)"
                ),
            )

        except Exception as exception:  # pragma: no cover - defensive
            return self.handle_error(
                exception,
                "Cross-correlation",
                event_list_1=event_list_1_name,
                event_list_2=event_list_2_name,
                dt=dt,
                mode=mode,
                norm=norm,
            )

    def _build_payload(
        self,
        correlation: CrossCorrelation,
        mode: str,
        norm: str,
        warnings_out: List[str],
    ) -> Dict[str, Any]:
        """Serialise a stingray correlation object into the API payload."""
        # Evaluated on the raw array: finite_list() replaces NaN with None.
        nan_warning = _nan_corr_warning(correlation.corr)
        if nan_warning and nan_warning not in warnings_out:
            warnings_out.append(nan_warning)

        time_shift: Optional[float] = None
        if nan_warning is None:
            shift = float(correlation.time_shift)
            if np.isfinite(shift):
                time_shift = shift

        return {
            "time_lags": finite_list(correlation.time_lags),
            "corr": finite_list(correlation.corr),
            "time_shift": time_shift,
            "dt": float(correlation.dt),
            "n": int(correlation.n),
            "mode": mode,
            "norm": norm,
            "warnings": warnings_out,
        }
