"""
Var-energy service for energy-dependent variability spectra.

Implemented per docs/superpowers/plans/2026-07-29-quicklook-remaining-pages.md.

Covers rms, lag, excess-variance, a combined counts/rms/lag overview and the
covariance spectrum (unsegmented and segment-averaged), all built on
``stingray.varenergyspectrum``.

Several stingray 2.2.10 quirks are worked around here and documented at their
call sites: ``ExcessVarianceSpectrum`` discards its own results and counts
inter-GTI gaps as real zero-count bins (see
``_GtiAwareExcessVarianceSpectrum``), the FFT length and the frequency mask are
derived from different roundings of ``segment_size / bin_time`` (see
``_fit_segment_to_bins``), and the legacy ``stingray.covariancespectrum``
module corrupts its light curves (see ``covariance_spectrum``).
"""

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from stingray.gti import create_gti_mask
from stingray.utils import excess_variance
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

# stingray's own tolerance in gti.time_intervals_from_gtis.
_GTI_EPSILON = 1e-5

# The all-NaN advisory has to be per spectrum kind: rms/lag/covariance are
# computed against a reference band over segments of segment_size, but
# ExcessVarianceSpectrum builds no reference band at all (its
# _spectrum_function passes only_base=True) and neither the endpoint nor the
# page exposes a segment_size, so the shared wording named three controls that
# do not exist there.
NAN_ADVICE = {
    "default": (
        "the {kind} spectrum could not be computed for any energy band "
        "(stingray returns NaN when the reference band shows no variability "
        "above the Poisson noise floor). Try a longer segment_size, a coarser "
        "bin_time, fewer energy bands, or a source with real variability."
    ),
    "excess variance": (
        "the excess variance spectrum could not be computed for any energy "
        "band (stingray returns NaN when a band's measured variance sits at "
        "or below its own Poisson noise level, so the excess variance comes "
        "out negative). Try a coarser bin_time or fewer energy bands to put "
        "more counts in each light-curve bin, or a source with real "
        "variability."
    ),
}


def _nan_advice(kind: str) -> str:
    return NAN_ADVICE.get(kind, NAN_ADVICE["default"]).format(kind=kind)


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


def _excess_variance_in_gtis(lightcurve, normalization: str) -> Tuple[float, float]:
    """``stingray.utils.excess_variance`` over the in-GTI bins only.

    ``VarEnergySpectrum._construct_lightcurves`` builds ONE light curve running
    from ``gti[0, 0]`` to ``gti[-1, -1]`` (``Lightcurve.make_lightcurve`` with
    ``tseg=tstop - tstart``) and never masks the inter-GTI gaps, so every bin
    that falls in a slew/occultation/SAA gap is a genuine 0-count bin in
    ``lc.counts``.  ``excess_variance`` then takes ``np.var(lc.counts)`` over
    that raw array, so the gaps - not the source - set the variance: a constant
    Poisson source observed in two 100 s GTIs 800 s apart reports
    ``F_var ~ 2.0 +/- 0.011`` instead of a value consistent with zero.

    Masking is the correct fix rather than averaging per-GTI results: F_var
    (Vaughan et al. 2003) is a sample variance over the *observed* bins, so the
    estimator only wants the bins that were actually exposed, and pooling them
    keeps a single well-determined mean count rate.  ``create_gti_mask`` is the
    same helper ``Lightcurve.apply_gtis`` uses; besides the gaps it also drops
    the partially-exposed bins straddling a GTI edge, which would otherwise
    read as low outliers.
    """
    gti = getattr(lightcurve, "gti", None)
    if gti is None or len(gti) == 0 or len(lightcurve.time) == 0:
        return excess_variance(lightcurve, normalization)

    inside = create_gti_mask(lightcurve.time, gti, dt=lightcurve.dt)
    if inside.all():
        return excess_variance(lightcurve, normalization)
    if np.count_nonzero(inside) < 2:
        # A variance over fewer than two exposed bins is meaningless; NaN lets
        # finite_list()/_add_nan_advice explain it like any other empty band.
        return float("nan"), float("nan")
    return excess_variance(lightcurve.apply_mask(inside, inplace=False), normalization)


class _GtiAwareExcessVarianceSpectrum(ExcessVarianceSpectrum):
    """``ExcessVarianceSpectrum`` that skips gap bins and computes only once.

    Two stingray 2.2.10 problems are fixed by this single override:

    * gap contamination - see ``_excess_variance_in_gtis``;
    * duplicated work - ``VarEnergySpectrum.__init__`` calls
      ``self._spectrum_function()`` and throws the return value away.  Every
      sibling class assigns ``self.spectrum[i]`` in place, but
      ``ExcessVarianceSpectrum`` returns ``(spec, spec_err)`` instead, so the
      constructed object's ``.spectrum`` stays at its all-NaN initial value and
      the service used to recover the numbers by running the whole
      one-light-curve-per-energy-band computation a second time.  Storing the
      arrays here makes the constructor's own call the only one: identical
      numbers, half the light curves and half the peak allocation.
    """

    def _spectrum_function(self):
        spectrum = np.zeros(len(self.energy_intervals), dtype=float)
        spectrum_error = np.zeros_like(spectrum)
        for index, energy_interval in enumerate(self.energy_intervals):
            lightcurve = self._construct_lightcurves(
                energy_interval, exclude=False, only_base=True
            )
            spectrum[index], spectrum_error[index] = _excess_variance_in_gtis(
                lightcurve, self.normalization
            )
        self.spectrum = spectrum
        self.spectrum_error = spectrum_error
        return spectrum, spectrum_error


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


def _gti_usage(event_list, segment_size: float) -> Dict[str, Any]:
    """How much of the exposure a given ``segment_size`` actually reaches.

    ``gti.time_intervals_from_gtis`` skips every good-time interval shorter
    than ``segment_size`` outright (``if g[1] - g[0] + epsilon < segment_size:
    continue``) and only uses whole segments inside the ones it keeps, without
    warning.  A multi-orbit observation segmented at the length of its longest
    GTI therefore contributes a small fraction of its exposure.
    """
    gti = getattr(event_list, "gti", None)
    if gti is None or len(gti) == 0 or segment_size <= 0:
        return {
            "n_gtis_total": 0,
            "n_gtis_used": 0,
            "exposure_total": 0.0,
            "exposure_used": 0.0,
        }
    spans = np.asarray(gti, dtype=float)
    durations = spans[:, 1] - spans[:, 0]
    kept = durations + _GTI_EPSILON >= segment_size
    segments = np.floor((durations[kept] + _GTI_EPSILON) / segment_size)
    return {
        "n_gtis_total": int(durations.size),
        "n_gtis_used": int(np.count_nonzero(kept)),
        "exposure_total": float(np.sum(durations)),
        "exposure_used": float(np.sum(segments) * segment_size),
    }


def _gti_usage_warning(
    usage: Dict[str, Any], segment_size: float, derived_from_longest_gti: bool
) -> Optional[str]:
    """Say out loud which whole good-time intervals a ``segment_size`` drops.

    Only whole dropped GTIs are reported; the sub-segment remainder at the end
    of a kept GTI is normal segmenting and would be noise in the UI (the exact
    numbers are in ``exposure_used``/``exposure_total`` either way).
    """
    total = usage["exposure_total"]
    used = usage["exposure_used"]
    dropped_gtis = usage["n_gtis_total"] - usage["n_gtis_used"]
    if total <= 0 or dropped_gtis <= 0:
        return None
    fraction = used / total
    if derived_from_longest_gti:
        lead = (
            f"this single segment is the longest good-time interval "
            f"({segment_size:g}s), so the {dropped_gtis} shorter "
            f"{'GTI was' if dropped_gtis == 1 else 'GTIs were'} skipped "
            "entirely"
        )
    else:
        lead = (
            f"segment_size ({segment_size:g}s) is longer than {dropped_gtis} "
            f"of the {usage['n_gtis_total']} good-time intervals, which "
            "stingray skips entirely"
        )
    return (
        f"{lead}: {used:g}s of the {total:g}s of exposure "
        f"({fraction:.0%}) contributed to this spectrum, not the whole "
        "observation"
    )


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

    def _ref_band_events_error(self, event_list, ref_band) -> Optional[str]:
        """Reject a reference band that holds no events.

        stingray computes the reference PDS once, up front:
        ``LagSpectrum._spectrum_function`` and
        ``ComplexCovarianceSpectrum._spectrum_function`` call
        ``avg_pds_from_timeseries(ref_events, ...)`` and immediately read
        ``results.meta["m"]``/``results["power"]``.  Unlike the per-subject-band
        loop a few lines below (which guards with ``if results_cross is None or
        results_ps is None: continue``) that dereference is unguarded, and
        ``avg_pds_from_timeseries`` returns ``None`` when the band is empty, so
        an out-of-range reference band surfaces as ``'NoneType' object has no
        attribute 'meta'`` / ``'NoneType' object is not subscriptable``.
        """
        if ref_band is None:
            return None
        energies = getattr(event_list, "energy", None)
        if energies is None:
            return None
        values = np.asarray(energies, dtype=float)
        if values.size == 0:
            return None
        in_band = (values >= ref_band[0]) & (values < ref_band[1])
        if np.any(in_band):
            return None
        return (
            f"the reference band ({ref_band[0]:g}-{ref_band[1]:g} keV) contains "
            f"no events; this event list covers {np.nanmin(values):g}-"
            f"{np.nanmax(values):g} keV. Choose a reference band inside that "
            "range, or leave ref_min/ref_max empty to use the full band"
        )

    def _fit_segment_to_bins(
        self, segment_size: float, bin_time: float, span: Optional[float]
    ) -> Tuple[float, Optional[str]]:
        """Snap ``segment_size`` to a whole number of ``bin_time`` bins.

        stingray sizes the FFT with ``utils.fix_segment_size_to_integer_samples``
        (the floor of ``segment_size / bin_time``, unless it is within 1% of the
        ceiling) but builds the frequency mask in
        ``VarEnergySpectrum._get_good_frequency_bins`` from
        ``np.rint(segment_size / bin_time)``.  When those two roundings disagree
        the mask is one element longer than the power array and
        ``sub_power[good]`` raises ``IndexError: boolean index did not match
        indexed array`` (e.g. bin_time=0.03s with the page's default
        segment_size=8s); when they happen to have equal length the mask is
        silently applied to the wrong frequency grid, integrating power above
        the requested freq_max and normalising with the wrong delta_nu.

        Making segment_size an exact multiple of bin_time makes floor(), rint()
        and the 1%-tolerance branch all land on the same bin count, so both
        failure modes disappear.  The adjustment is reported to the caller so it
        can be surfaced instead of applied behind the user's back.
        """
        if bin_time <= 0 or segment_size <= 0:
            return segment_size, None
        n_bins = int(np.rint(segment_size / bin_time))
        # Rounding up must not push the segment past the longest GTI, which
        # stingray asserts on.
        while n_bins > 1 and span is not None and n_bins * bin_time > span:
            n_bins -= 1
        adjusted = float(n_bins * bin_time)
        if abs(adjusted - segment_size) <= 1e-9 * max(1.0, abs(segment_size)):
            return segment_size, None
        return adjusted, (
            f"segment_size was adjusted from {segment_size:g}s to {adjusted:g}s "
            f"({n_bins} x bin_time {bin_time:g}s) so that it spans a whole "
            "number of time bins; stingray's FFT length and its frequency grid "
            "disagree otherwise"
        )

    def _freq_resolution_error(
        self, freq_min: float, freq_max: float, segment_size: float, bin_time: float
    ) -> Optional[str]:
        """Reject a frequency window that contains no Fourier bin.

        ``_get_good_frequency_bins`` selects ``freq >= freq_min & freq <
        freq_max`` from ``fftfreq(segment_size / bin_time, bin_time)``, whose
        positive entries are the multiples of ``1 / segment_size``.  If no
        multiple lands in the window the mask is all-False, ``np.mean`` runs on
        an empty slice, and every band comes back null behind a bare "Mean of
        empty slice." warning.
        """
        if bin_time <= 0 or segment_size <= 0:
            return None
        n_bins = int(np.rint(segment_size / bin_time))
        if n_bins < 3:
            return None  # already rejected by segment_size_error
        delta_nu = 1.0 / (n_bins * bin_time)
        highest = ((n_bins - 1) // 2) * delta_nu
        lowest = max(1, int(np.ceil(freq_min / delta_nu - 1e-9))) * delta_nu
        if lowest <= highest and lowest < freq_max:
            return None
        return (
            f"no Fourier frequency bin falls inside {freq_min:g}-{freq_max:g} Hz: "
            f"the frequency resolution is 1/segment_size = {delta_nu:g} Hz, so "
            f"the sampled frequencies are the multiples of {delta_nu:g} Hz from "
            f"{delta_nu:g} Hz to {highest:g} Hz. Widen the frequency range or "
            "use a longer segment_size"
        )

    def _validate_timing(
        self,
        event_list,
        bin_time: float,
        segment_size: float,
        freq_min: float,
        freq_max: float,
    ) -> Tuple[float, List[str], Optional[str]]:
        """Validate bin_time, segment_size and the frequency window together.

        Returns ``(segment_size, notes, error)``: ``segment_size`` snapped to a
        whole number of bins, ``notes`` recording that adjustment for the
        payload's ``warnings``, and ``error`` the first readable rejection.
        """
        error = self._freq_interval_error(freq_min, freq_max, bin_time)
        if error:
            return segment_size, [], error
        error = self._segment_error(event_list, segment_size, bin_time)
        if error:
            return segment_size, [], error

        segment_size, note = self._fit_segment_to_bins(
            segment_size, bin_time, _longest_gti(event_list)
        )
        notes = [note] if note else []
        error = self._freq_resolution_error(
            freq_min, freq_max, segment_size, bin_time
        )
        return segment_size, notes, error

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
            advice = _nan_advice(kind)
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

            segment_size, notes, timing_error = self._validate_timing(
                event_list, bin_time, segment_size, freq_min, freq_max
            )
            for check in (
                self._norm_error(norm),
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                timing_error,
            ):
                if check:
                    return self.create_result(False, None, check, None)

            usage = _gti_usage(event_list, float(segment_size))
            warnings: List[str] = list(notes)
            gti_note = _gti_usage_warning(usage, float(segment_size), False)
            if gti_note:
                warnings.append(gti_note)
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
            segment_size, notes, timing_error = self._validate_timing(
                event_list, bin_time, segment_size, freq_min, freq_max
            )
            for check in (
                ref_error,
                self._ref_band_events_error(event_list, ref_band),
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                timing_error,
            ):
                if check:
                    return self.create_result(False, None, check, None)

            usage = _gti_usage(event_list, float(segment_size))
            warnings: List[str] = list(notes)
            gti_note = _gti_usage_warning(usage, float(segment_size), False)
            if gti_note:
                warnings.append(gti_note)
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
        the whole GTI at ``bin_time`` resolution. That light curve also runs
        straight through the inter-GTI gaps, which is why this endpoint uses
        ``_GtiAwareExcessVarianceSpectrum`` rather than stingray's class.
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
                # _GtiAwareExcessVarianceSpectrum masks the inter-GTI gap bins
                # (which stingray counts as real zero-count bins) and stores its
                # results on the object, so the constructor's own call to
                # _spectrum_function() is the only one that runs — see the class
                # docstring for both stingray 2.2.10 bugs it stands in for.
                spectrum = _GtiAwareExcessVarianceSpectrum(
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
            self._add_nan_advice(spectrum.spectrum, warnings, "excess variance")

            data = {
                "energy": finite_list(spectrum.energy),
                "spectrum": finite_list(spectrum.spectrum),
                "spectrum_error": finite_list(spectrum.spectrum_error),
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
            segment_size, notes, timing_error = self._validate_timing(
                event_list, bin_time, segment_size, freq_min, freq_max
            )
            for check in (
                ref_error,
                self._ref_band_events_error(event_list, ref_band),
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                timing_error,
            ):
                if check:
                    return self.create_result(False, None, check, None)

            energy_spec = self._energy_spec(energy_min, energy_max, n_bands, log_bands)
            freq_interval = [float(freq_min), float(freq_max)]
            usage = _gti_usage(event_list, float(segment_size))
            warnings: List[str] = list(notes)
            gti_note = _gti_usage_warning(usage, float(segment_size), False)
            if gti_note:
                warnings.append(gti_note)
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

        "Whole observation" means the longest *single* GTI, not the summed
        exposure: ``gti.time_intervals_from_gtis`` starts every segment at a GTI
        boundary and skips any GTI shorter than the segment, so no single-segment
        choice can span a gap. The longest GTI is the largest such segment, but
        on a multi-GTI observation it drops the shorter ones, so the payload
        reports ``n_gtis_used``/``n_gtis_total`` and
        ``exposure_used``/``exposure_total`` and adds a warning naming the lost
        exposure rather than letting the result read as the full observation.
        (Picking a shorter segment would keep more exposure but silently change
        the frequency resolution the user's freq_min/freq_max are measured
        against, so the choice is surfaced instead of second-guessed;
        ``avg_covariance_spectrum`` is the endpoint for choosing it explicitly.)
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
            segment_derived_from_longest_gti=True,
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
        segment_derived_from_longest_gti: bool = False,
    ) -> Dict[str, Any]:
        try:
            ref_band, ref_error = self._ref_band(ref_min, ref_max)
            segment_size, notes, timing_error = self._validate_timing(
                event_list, bin_time, segment_size, freq_min, freq_max
            )
            for check in (
                ref_error,
                self._ref_band_events_error(event_list, ref_band),
                self._norm_error(norm),
                self._energy_spec_error(energy_min, energy_max, n_bands, log_bands),
                timing_error,
            ):
                if check:
                    return self.create_result(False, None, check, None)

            usage = _gti_usage(event_list, float(segment_size))
            warnings: List[str] = list(notes)
            gti_note = _gti_usage_warning(
                usage, float(segment_size), segment_derived_from_longest_gti
            )
            if gti_note:
                warnings.append(gti_note)
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
                # Honesty about how much of the observation this segmenting
                # actually used; the UI chip reads "(full GTI)" otherwise.
                **usage,
                "warnings": _humanize_warnings(warnings),
            }
            dropped = usage["n_gtis_total"] - usage["n_gtis_used"]
            message = f"Computed covariance spectrum in {n_bands} energy bands"
            if dropped > 0:
                message += (
                    f" from {usage['n_gtis_used']} of "
                    f"{usage['n_gtis_total']} good-time intervals"
                )
            return self.create_result(True, data, message)
        except Exception as exc:
            return self.handle_error(
                exc, "Calculating covariance spectrum", event_list=event_list_name
            )
