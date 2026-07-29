"""
Var-energy service for energy-dependent variability spectra.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.

Covers rms, lag, excess-variance, a combined counts/rms/lag overview and the
covariance spectrum (unsegmented and segment-averaged), all built on
``stingray.varenergyspectrum``.

Two stingray 2.2.10 quirks are worked around here and documented at their call
sites: ``ExcessVarianceSpectrum`` discards its own results, and the legacy
``stingray.covariancespectrum`` module corrupts its light curves (see
``covariance_spectrum``).
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from stingray.varenergyspectrum import (
    CountSpectrum,
    CovarianceSpectrum,
    ExcessVarianceSpectrum,
    LagSpectrum,
    RmsSpectrum,
)

from .analysis_helpers import collect_warnings, finite_list, segment_size_error
from .base_service import BaseService

VALID_NORMS = ("frac", "abs")
VALID_EXCESS_VARIANCE_NORMALIZATIONS = ("fvar", "none")

NAN_ADVICE = (
    "the {kind} spectrum could not be computed for any energy band "
    "(stingray returns NaN when the reference band shows no variability above "
    "the Poisson noise floor). Try a longer segment_size, a coarser bin_time, "
    "fewer energy bands, or a source with real variability."
)

# numpy's floating-point warnings surface verbatim through catch_warnings and
# read as gibberish in the UI ("invalid value encountered in sqrt"), so wrap
# them in a sentence that says what it means for the plot.
_NUMPY_WARNING_PREFIXES = (
    "invalid value encountered",
    "divide by zero encountered",
    "overflow encountered",
    "underflow encountered",
)


def _humanize_warnings(messages: List[str]) -> List[str]:
    """Wrap bare numpy float warnings in something a user can act on."""
    readable: List[str] = []
    for text in messages:
        if text.startswith(_NUMPY_WARNING_PREFIXES):
            text = (
                "undefined maths while computing this spectrum "
                f"(numpy: {text}); any affected energy bands are returned as null"
            )
        if text not in readable:
            readable.append(text)
    return readable


def _longest_gti(event_list) -> Optional[float]:
    """Duration of the longest single good-time interval, in seconds.

    stingray asserts ``No GTIs are equal to or longer than segment_size``, so
    the longest *single* interval (not the summed exposure) is the limit.
    """
    gti = getattr(event_list, "gti", None)
    if gti is not None and len(gti) > 0:
        spans = np.asarray(gti, dtype=float)
        return float(np.max(spans[:, 1] - spans[:, 0]))
    times = getattr(event_list, "time", None)
    if times is None or len(times) == 0:
        return None
    return float(times[-1] - times[0])


def _n_segments_hint(event_list, segment_size: float) -> int:
    """How many whole segments fit in the GTIs (stingray's own m may differ)."""
    gti = getattr(event_list, "gti", None)
    if gti is None or len(gti) == 0:
        span = _longest_gti(event_list) or 0.0
        return int(span // segment_size)
    spans = np.asarray(gti, dtype=float)
    return int(np.sum(np.floor((spans[:, 1] - spans[:, 0]) / segment_size)))


class VarEnergyService(BaseService):
    """Service for rms/lag/excess-variance/covariance energy spectra."""

    # ------------------------------------------------------------------
    # shared validation
    # ------------------------------------------------------------------

    def _resolve_event_list(self, event_list_name: str):
        """Return (event_list, error_message). Exactly one is not None."""
        if not self.state.has_event_data(event_list_name):
            return None, f"EventList '{event_list_name}' not found"
        event_list = self.state.get_event_data(event_list_name)
        if event_list.time is None or len(event_list.time) == 0:
            return None, f"EventList '{event_list_name}' contains no events"
        if getattr(event_list, "energy", None) is None:
            return None, (
                f"EventList '{event_list_name}' has no energy column; "
                "energy-resolved spectra need per-event energies"
            )
        return event_list, None

    def _energy_spec_error(
        self, energy_min: float, energy_max: float, n_bands: int, log_bands: bool
    ) -> Optional[str]:
        if energy_min >= energy_max:
            return (
                f"energy_min ({energy_min} keV) must be below "
                f"energy_max ({energy_max} keV)"
            )
        if n_bands < 2:
            return f"n_bands ({n_bands}) must be at least 2 to make a spectrum"
        if log_bands and energy_min <= 0:
            return (
                f"energy_min ({energy_min} keV) must be above zero for "
                "log-spaced energy bands"
            )
        return None

    def _freq_interval_error(
        self, freq_min: float, freq_max: float, bin_time: float
    ) -> Optional[str]:
        if bin_time <= 0:
            return f"bin_time ({bin_time}s) must be positive"
        if freq_min < 0:
            return f"freq_min ({freq_min} Hz) must not be negative"
        if freq_min >= freq_max:
            return f"freq_min ({freq_min} Hz) must be below freq_max ({freq_max} Hz)"
        nyquist = 1.0 / (2.0 * bin_time)
        if freq_max > nyquist:
            return (
                f"freq_max ({freq_max} Hz) is above the Nyquist frequency "
                f"({nyquist:g} Hz) for bin_time {bin_time}s; lower freq_max or "
                "use a smaller bin_time"
            )
        return None

    def _segment_error(
        self, event_list, segment_size: float, bin_time: float
    ) -> Optional[str]:
        if segment_size <= 0:
            return f"segment_size ({segment_size}s) must be positive"
        error = segment_size_error(segment_size, bin_time)
        if error:
            return error
        span = _longest_gti(event_list)
        if span is not None and segment_size > span:
            return (
                f"segment_size ({segment_size}s) is longer than the longest "
                f"good-time interval ({span:g}s); use a smaller segment_size"
            )
        return None

    def _norm_error(self, norm: str) -> Optional[str]:
        if norm not in VALID_NORMS:
            return (
                f"norm '{norm}' is not supported; use one of "
                f"{', '.join(VALID_NORMS)}"
            )
        return None

    def _ref_band(
        self, ref_min: Optional[float], ref_max: Optional[float]
    ) -> Tuple[Optional[List[float]], Optional[str]]:
        """Validate the optional reference band. Returns (band, error)."""
        if ref_min is None and ref_max is None:
            return None, None
        if ref_min is None or ref_max is None:
            return None, (
                "ref_min and ref_max must be given together (or both left "
                "empty to use the full band as reference)"
            )
        if ref_min >= ref_max:
            return None, (
                f"ref_min ({ref_min} keV) must be below ref_max ({ref_max} keV)"
            )
        return [float(ref_min), float(ref_max)], None

    def _energy_spec(
        self, energy_min: float, energy_max: float, n_bands: int, log_bands: bool
    ) -> Tuple[float, float, int, str]:
        return (
            float(energy_min),
            float(energy_max),
            int(n_bands),
            "log" if log_bands else "lin",
        )

    def _add_nan_advice(self, values, warnings: List[str], kind: str) -> None:
        """Explain an entirely non-finite spectrum instead of showing bare gaps."""
        array = np.asarray(values, dtype=float)
        if array.size and not np.isfinite(array).any():
            advice = NAN_ADVICE.format(kind=kind)
            if advice not in warnings:
                warnings.append(advice)

    # ------------------------------------------------------------------
    # rms-spectrum
    # ------------------------------------------------------------------

    def rms_spectrum(
        self,
        event_list_name: str,
        bin_time: float,
        segment_size: float,
        freq_min: float,
        freq_max: float,
        energy_min: float,
        energy_max: float,
        n_bands: int = 5,
        log_bands: bool = False,
        norm: str = "frac",
    ) -> Dict[str, Any]:
        """Fractional (or absolute) rms as a function of energy.

        No reference band: stingray's ``ref_band`` is silently ignored by
        ``RmsSpectrum`` for a single event list, so the endpoint does not
        expose a control that would do nothing.
        """
        try:
            event_list, error = self._resolve_event_list(event_list_name)
            if error:
                return self.create_result(False, None, error, None)

            for check in (
                self._norm_error(norm),
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                self._freq_interval_error(freq_min, freq_max, bin_time),
                self._segment_error(event_list, segment_size, bin_time),
            ):
                if check:
                    return self.create_result(False, None, check, None)

            warnings: List[str] = []
            with collect_warnings(warnings):
                spectrum = RmsSpectrum(
                    event_list,
                    energy_spec=self._energy_spec(
                        energy_min, energy_max, n_bands, log_bands
                    ),
                    freq_interval=[float(freq_min), float(freq_max)],
                    bin_time=float(bin_time),
                    segment_size=float(segment_size),
                    norm=norm,
                )
            self._add_nan_advice(spectrum.spectrum, warnings, "rms")

            data = {
                "energy": finite_list(spectrum.energy),
                "spectrum": finite_list(spectrum.spectrum),
                "spectrum_error": finite_list(spectrum.spectrum_error),
                "freq_range": [float(freq_min), float(freq_max)],
                "norm": norm,
                "n_segments_hint": _n_segments_hint(event_list, float(segment_size)),
                "warnings": _humanize_warnings(warnings),
            }
            return self.create_result(
                True, data, f"Computed rms spectrum in {n_bands} energy bands"
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating rms spectrum", event_list=event_list_name
            )

    # ------------------------------------------------------------------
    # lag-spectrum
    # ------------------------------------------------------------------

    def lag_spectrum(
        self,
        event_list_name: str,
        bin_time: float,
        segment_size: float,
        freq_min: float,
        freq_max: float,
        energy_min: float,
        energy_max: float,
        n_bands: int = 5,
        log_bands: bool = False,
        ref_min: Optional[float] = None,
        ref_max: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Time lag (seconds) as a function of energy."""
        try:
            event_list, error = self._resolve_event_list(event_list_name)
            if error:
                return self.create_result(False, None, error, None)

            ref_band, ref_error = self._ref_band(ref_min, ref_max)
            for check in (
                ref_error,
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                self._freq_interval_error(freq_min, freq_max, bin_time),
                self._segment_error(event_list, segment_size, bin_time),
            ):
                if check:
                    return self.create_result(False, None, check, None)

            warnings: List[str] = []
            with collect_warnings(warnings):
                spectrum = LagSpectrum(
                    event_list,
                    freq_interval=[float(freq_min), float(freq_max)],
                    energy_spec=self._energy_spec(
                        energy_min, energy_max, n_bands, log_bands
                    ),
                    ref_band=ref_band,
                    bin_time=float(bin_time),
                    segment_size=float(segment_size),
                )
            self._add_nan_advice(spectrum.spectrum, warnings, "lag")

            data = {
                "energy": finite_list(spectrum.energy),
                "spectrum": finite_list(spectrum.spectrum),
                "spectrum_error": finite_list(spectrum.spectrum_error),
                "freq_range": [float(freq_min), float(freq_max)],
                "ref_band": ref_band,
                "n_segments_hint": _n_segments_hint(event_list, float(segment_size)),
                "warnings": _humanize_warnings(warnings),
            }
            return self.create_result(
                True, data, f"Computed lag spectrum in {n_bands} energy bands"
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating lag spectrum", event_list=event_list_name
            )

    # ------------------------------------------------------------------
    # excess-variance
    # ------------------------------------------------------------------

    def excess_variance_spectrum(
        self,
        event_list_name: str,
        bin_time: float,
        energy_min: float,
        energy_max: float,
        n_bands: int = 5,
        log_bands: bool = False,
        normalization: str = "fvar",
    ) -> Dict[str, Any]:
        """Excess variance (F_var or unnormalized) as a function of energy.

        No frequency range and no segment size: ``ExcessVarianceSpectrum``
        stores ``freq_interval`` but never reads it, and ignores
        ``segment_size`` entirely — it always builds one light curve spanning
        the whole GTI at ``bin_time`` resolution.
        """
        try:
            event_list, error = self._resolve_event_list(event_list_name)
            if error:
                return self.create_result(False, None, error, None)

            if normalization not in VALID_EXCESS_VARIANCE_NORMALIZATIONS:
                return self.create_result(
                    False,
                    None,
                    f"normalization '{normalization}' is not supported; use one "
                    f"of {', '.join(VALID_EXCESS_VARIANCE_NORMALIZATIONS)}",
                    None,
                )
            if bin_time <= 0:
                return self.create_result(
                    False, None, f"bin_time ({bin_time}s) must be positive", None
                )
            energy_error = self._energy_spec_error(
                energy_min, energy_max, n_bands, log_bands
            )
            if energy_error:
                return self.create_result(False, None, energy_error, None)

            warnings: List[str] = []
            with collect_warnings(warnings):
                spectrum = ExcessVarianceSpectrum(
                    events=event_list,
                    # Required positionally by stingray but never read by
                    # _spectrum_function(); the sampled frequency range is set
                    # by bin_time and the GTI length instead.
                    freq_interval=[0.0, 1.0 / (2.0 * float(bin_time))],
                    energy_spec=self._energy_spec(
                        energy_min, energy_max, n_bands, log_bands
                    ),
                    bin_time=float(bin_time),
                    normalization=normalization,
                )
                # stingray 2.2.10 bug: VarEnergySpectrum.__init__ calls
                # self._spectrum_function() but throws the return value away.
                # Every sibling class assigns self.spectrum[i] in place;
                # ExcessVarianceSpectrum instead returns (spec, spec_err), so
                # the object's .spectrum stays at its all-NaN initial value.
                # Recover the real arrays by calling the method ourselves.
                values, errors = spectrum._spectrum_function()
            self._add_nan_advice(values, warnings, "excess variance")

            data = {
                "energy": finite_list(spectrum.energy),
                "spectrum": finite_list(values),
                "spectrum_error": finite_list(errors),
                "normalization": normalization,
                "warnings": _humanize_warnings(warnings),
            }
            return self.create_result(
                True,
                data,
                f"Computed excess-variance spectrum in {n_bands} energy bands",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating excess-variance spectrum", event_list=event_list_name
            )

    # ------------------------------------------------------------------
    # variable-energy-spectrum (counts + rms + lag overview)
    # ------------------------------------------------------------------

    def variable_energy_spectrum(
        self,
        event_list_name: str,
        bin_time: float,
        segment_size: float,
        freq_min: float,
        freq_max: float,
        energy_min: float,
        energy_max: float,
        n_bands: int = 5,
        log_bands: bool = False,
        ref_min: Optional[float] = None,
        ref_max: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Counts, fractional rms and lag versus energy from one set of params."""
        try:
            event_list, error = self._resolve_event_list(event_list_name)
            if error:
                return self.create_result(False, None, error, None)

            ref_band, ref_error = self._ref_band(ref_min, ref_max)
            for check in (
                ref_error,
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                self._freq_interval_error(freq_min, freq_max, bin_time),
                self._segment_error(event_list, segment_size, bin_time),
            ):
                if check:
                    return self.create_result(False, None, check, None)

            energy_spec = self._energy_spec(energy_min, energy_max, n_bands, log_bands)
            freq_interval = [float(freq_min), float(freq_max)]
            warnings: List[str] = []
            with collect_warnings(warnings):
                counts = CountSpectrum(event_list, energy_spec)
                # RmsSpectrum ignores ref_band for a single event list, so the
                # reference band only reaches the lag panel.
                rms = RmsSpectrum(
                    event_list,
                    energy_spec=energy_spec,
                    freq_interval=freq_interval,
                    bin_time=float(bin_time),
                    segment_size=float(segment_size),
                    norm="frac",
                )
                lag = LagSpectrum(
                    event_list,
                    freq_interval=freq_interval,
                    energy_spec=energy_spec,
                    ref_band=ref_band,
                    bin_time=float(bin_time),
                    segment_size=float(segment_size),
                )
            self._add_nan_advice(rms.spectrum, warnings, "rms")
            self._add_nan_advice(lag.spectrum, warnings, "lag")

            data = {
                "energy": finite_list(counts.energy),
                "counts": {
                    "spectrum": finite_list(counts.spectrum),
                    "error": finite_list(counts.spectrum_error),
                },
                "rms": {
                    "spectrum": finite_list(rms.spectrum),
                    "error": finite_list(rms.spectrum_error),
                },
                "lag": {
                    "spectrum": finite_list(lag.spectrum),
                    "error": finite_list(lag.spectrum_error),
                },
                "freq_range": freq_interval,
                "ref_band": ref_band,
                "norm": "frac",
                "n_segments_hint": _n_segments_hint(event_list, float(segment_size)),
                "warnings": _humanize_warnings(warnings),
            }
            return self.create_result(
                True,
                data,
                f"Computed counts, rms and lag spectra in {n_bands} energy bands",
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating variable-energy spectrum", event_list=event_list_name
            )

    # ------------------------------------------------------------------
    # covariance spectra
    # ------------------------------------------------------------------

    def covariance_spectrum(
        self,
        event_list_name: str,
        bin_time: float,
        freq_min: float,
        freq_max: float,
        energy_min: float,
        energy_max: float,
        n_bands: int = 5,
        log_bands: bool = False,
        ref_min: Optional[float] = None,
        ref_max: Optional[float] = None,
        norm: str = "abs",
    ) -> Dict[str, Any]:
        """Covariance spectrum over the whole observation (a single segment).

        Deliberately NOT built on the legacy ``stingray.covariancespectrum``
        module: its ``Covariancespectrum``/``AveragedCovariancespectrum`` pass
        the full ``(time, energy)`` array to ``Lightcurve.make_lightcurve``,
        which flattens it and histograms the *energy* column as arrival times
        (verified: the bins covering 0.3-12 s carry ~10x the true rate), and
        ``AveragedCovariancespectrum`` additionally always computes
        ``nbins = int(segment_size / segment_size) = 1``, so it only ever looks
        at the first segment. Both are unusable, so this endpoint uses
        ``varenergyspectrum.CovarianceSpectrum`` with a single segment
        spanning the longest good-time interval.
        """
        try:
            event_list, error = self._resolve_event_list(event_list_name)
            if error:
                return self.create_result(False, None, error, None)
            segment_size = _longest_gti(event_list)
            if not segment_size or segment_size <= 0:
                return self.create_result(
                    False,
                    None,
                    f"EventList '{event_list_name}' has no usable good-time interval",
                    None,
                )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating covariance spectrum", event_list=event_list_name
            )
        return self._covariance(
            event_list_name=event_list_name,
            event_list=event_list,
            bin_time=bin_time,
            segment_size=float(segment_size),
            freq_min=freq_min,
            freq_max=freq_max,
            energy_min=energy_min,
            energy_max=energy_max,
            n_bands=n_bands,
            log_bands=log_bands,
            ref_min=ref_min,
            ref_max=ref_max,
            norm=norm,
        )

    def avg_covariance_spectrum(
        self,
        event_list_name: str,
        bin_time: float,
        segment_size: float,
        freq_min: float,
        freq_max: float,
        energy_min: float,
        energy_max: float,
        n_bands: int = 5,
        log_bands: bool = False,
        ref_min: Optional[float] = None,
        ref_max: Optional[float] = None,
        norm: str = "abs",
    ) -> Dict[str, Any]:
        """Covariance spectrum averaged over segments of ``segment_size``."""
        try:
            event_list, error = self._resolve_event_list(event_list_name)
            if error:
                return self.create_result(False, None, error, None)
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating covariance spectrum", event_list=event_list_name
            )
        return self._covariance(
            event_list_name=event_list_name,
            event_list=event_list,
            bin_time=bin_time,
            segment_size=segment_size,
            freq_min=freq_min,
            freq_max=freq_max,
            energy_min=energy_min,
            energy_max=energy_max,
            n_bands=n_bands,
            log_bands=log_bands,
            ref_min=ref_min,
            ref_max=ref_max,
            norm=norm,
        )

    def _covariance(
        self,
        event_list_name: str,
        event_list,
        bin_time: float,
        segment_size: float,
        freq_min: float,
        freq_max: float,
        energy_min: float,
        energy_max: float,
        n_bands: int,
        log_bands: bool,
        ref_min: Optional[float],
        ref_max: Optional[float],
        norm: str,
    ) -> Dict[str, Any]:
        try:
            ref_band, ref_error = self._ref_band(ref_min, ref_max)
            for check in (
                ref_error,
                self._norm_error(norm),
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                self._freq_interval_error(freq_min, freq_max, bin_time),
                self._segment_error(event_list, segment_size, bin_time),
            ):
                if check:
                    return self.create_result(False, None, check, None)

            warnings: List[str] = []
            with collect_warnings(warnings):
                spectrum = CovarianceSpectrum(
                    event_list,
                    energy_spec=self._energy_spec(
                        energy_min, energy_max, n_bands, log_bands
                    ),
                    ref_band=ref_band,
                    freq_interval=[float(freq_min), float(freq_max)],
                    bin_time=float(bin_time),
                    segment_size=float(segment_size),
                    norm=norm,
                )
            self._add_nan_advice(spectrum.spectrum, warnings, "covariance")

            data = {
                "energy": finite_list(spectrum.energy),
                "spectrum": finite_list(spectrum.spectrum),
                "spectrum_error": finite_list(spectrum.spectrum_error),
                "freq_range": [float(freq_min), float(freq_max)],
                "ref_band": ref_band,
                "norm": norm,
                "segment_size": float(segment_size),
                "n_segments_hint": _n_segments_hint(event_list, float(segment_size)),
                "warnings": _humanize_warnings(warnings),
            }
            return self.create_result(
                True, data, f"Computed covariance spectrum in {n_bands} energy bands"
            )
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating covariance spectrum", event_list=event_list_name
            )
