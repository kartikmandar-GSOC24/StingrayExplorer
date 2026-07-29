"""Tests for the var-energy spectrum service and routes.

Covariance/rms spectra are all-NaN on pure Poisson data (no excess variance in
the reference band), so every "should produce numbers" test uses an event list
whose arrival times are drawn from a sinusoidally modulated rate. Energies are
assigned independently of time, so every energy band shares the same
variability — exactly the correlated-variability case these spectra measure.
"""

import json

import numpy as np
import pytest
from stingray import EventList

from services.varenergy_service import VarEnergyService

ESPEC = dict(energy_min=0.5, energy_max=10.0, n_bands=5)
FREQ = dict(freq_min=0.1, freq_max=1.0)


def modulated_event_list(
    seed: int = 17,
    n_events: int = 120000,
    length: float = 64.0,
    mod_freq: float = 0.5,
    amplitude: float = 0.6,
) -> EventList:
    """Event list with a shared sinusoidal rate modulation across all energies."""
    rng = np.random.default_rng(seed)
    kept = []
    total = 0
    while total < n_events:
        candidates = rng.uniform(0.0, length, n_events)
        accept = rng.uniform(0.0, 1.0, n_events) < (
            1 + amplitude * np.sin(2 * np.pi * mod_freq * candidates)
        ) / (1 + amplitude)
        kept.append(candidates[accept])
        total += int(accept.sum())
    times = np.sort(np.concatenate(kept)[:n_events])
    energy = rng.uniform(0.5, 10.0, n_events)
    return EventList(time=times, energy=energy, gti=[[0.0, length]])


def sparse_event_list(seed: int = 3, n_events: int = 400, length: float = 64.0) -> EventList:
    """Pure-Poisson, low-count list: the legitimate all-NaN / low-count path."""
    rng = np.random.default_rng(seed)
    times = np.sort(rng.uniform(0.0, length, n_events))
    energy = rng.uniform(0.5, 10.0, n_events)
    return EventList(time=times, energy=energy, gti=[[0.0, length]])


def two_gti_constant_event_list(
    seed: int = 11, n_per_gti: int = 20000, gti=((0.0, 100.0), (900.0, 1000.0))
) -> EventList:
    """Constant-rate Poisson source seen in two GTIs across a long slew gap.

    There is no intrinsic variability whatsoever; the only structure a light
    curve spanning gti[0][0]..gti[-1][-1] can show is the 800 s of dead time
    between the two intervals.
    """
    rng = np.random.default_rng(seed)
    times = np.concatenate(
        [np.sort(rng.uniform(start, stop, n_per_gti)) for start, stop in gti]
    )
    energy = rng.uniform(0.5, 10.0, times.size)
    return EventList(time=times, energy=energy, gti=[list(g) for g in gti])


def gappy_modulated_event_list(gti=((0.0, 28.0), (36.0, 64.0)), **kwargs) -> EventList:
    """`modulated_event_list` with the events outside `gti` screened out."""
    events = modulated_event_list(**kwargs)
    inside = np.zeros(events.time.size, dtype=bool)
    for start, stop in gti:
        inside |= (events.time >= start) & (events.time < stop)
    return EventList(
        time=events.time[inside],
        energy=events.energy[inside],
        gti=[list(g) for g in gti],
    )


@pytest.fixture()
def modulated_state(state_manager):
    state_manager.add_event_data("ev_mod", modulated_event_list())
    return state_manager


def finite_values(values):
    return np.asarray([v for v in values if v is not None], dtype=float)


# --------------------------------------------------------------------------
# rms-spectrum
# --------------------------------------------------------------------------


def test_rms_spectrum_returns_finite_spectrum_and_serializes(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, norm="frac", **FREQ, **ESPEC
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert len(data["energy"]) == 5
    assert len(data["spectrum"]) == 5
    assert len(data["spectrum_error"]) == 5
    assert all(v is not None for v in data["spectrum"])
    # 60% sinusoidal modulation -> fractional rms of order 0.4 in every band.
    rms = finite_values(data["spectrum"])
    assert np.all(rms > 0.2) and np.all(rms < 0.8)
    assert data["freq_range"] == [0.1, 1.0]
    assert data["norm"] == "frac"
    assert data["n_segments_hint"] == 8  # 64 s of GTI / 8 s segments
    assert data["warnings"] == [] or isinstance(data["warnings"], list)


def test_rms_spectrum_abs_norm_differs_from_frac(modulated_state):
    svc = VarEnergyService(modulated_state)
    frac = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, norm="frac", **FREQ, **ESPEC
    )
    absolute = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, norm="abs", **FREQ, **ESPEC
    )
    assert absolute["success"], absolute
    assert finite_values(absolute["data"]["spectrum"])[0] > 10 * finite_values(
        frac["data"]["spectrum"]
    )[0]
    assert absolute["data"]["norm"] == "abs"


def test_rms_spectrum_rejects_unknown_norm(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, norm="leahy", **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "norm" in result["message"]


def test_rms_spectrum_missing_event_list(state_manager):
    svc = VarEnergyService(state_manager)
    result = svc.rms_spectrum(
        "nope", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "not found" in result["message"]


def test_rms_spectrum_rejects_tiny_segment_size(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=0.125, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "3x dt" in result["message"]


def test_rms_spectrum_rejects_segment_longer_than_gti(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=200.0, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "good-time interval" in result["message"]
    assert "64" in result["message"]


def test_rms_spectrum_rejects_freq_max_above_nyquist(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        freq_min=0.1,
        freq_max=20.0,
        **ESPEC,
    )
    assert not result["success"]
    assert "Nyquist" in result["message"]


def test_rms_spectrum_rejects_inverted_freq_range(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, freq_min=1.0, freq_max=0.1, **ESPEC
    )
    assert not result["success"]
    assert "freq_min" in result["message"]


def test_rms_spectrum_rejects_bad_energy_range(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        energy_min=10.0,
        energy_max=0.5,
        n_bands=5,
        **FREQ,
    )
    assert not result["success"]
    assert "energy_min" in result["message"]


def test_rms_spectrum_rejects_single_band(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        energy_min=0.5,
        energy_max=10.0,
        n_bands=1,
        **FREQ,
    )
    assert not result["success"]
    assert "n_bands" in result["message"]


def test_log_bands_rejected_for_zero_energy_min(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        energy_min=0.0,
        energy_max=10.0,
        n_bands=5,
        log_bands=True,
        **FREQ,
    )
    assert not result["success"]
    assert "log" in result["message"]


def test_log_bands_produce_log_spaced_energies(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        log_bands=True,
        **FREQ,
        **ESPEC,
    )
    assert result["success"], result
    energies = np.asarray(result["data"]["energy"], dtype=float)
    # Log-spaced edges give increasing bin widths -> increasing centre spacing.
    spacing = np.diff(energies)
    assert np.all(np.diff(spacing) > 0)


def test_event_list_without_energy_is_rejected(state_manager):
    rng = np.random.default_rng(4)
    times = np.sort(rng.uniform(0.0, 64.0, 5000))
    state_manager.add_event_data("ev_noe", EventList(time=times, gti=[[0.0, 64.0]]))
    svc = VarEnergyService(state_manager)
    result = svc.rms_spectrum(
        "ev_noe", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "energy" in result["message"]


def test_low_count_data_yields_nulls_and_warnings(state_manager):
    state_manager.add_event_data("ev_few", sparse_event_list())
    svc = VarEnergyService(state_manager)
    result = svc.rms_spectrum(
        "ev_few", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert any(v is None for v in data["spectrum"])
    assert data["warnings"], "stingray's low-count advisory must reach the payload"
    assert any("Low count rate" in w for w in data["warnings"])


# --------------------------------------------------------------------------
# lag-spectrum
# --------------------------------------------------------------------------


def test_lag_spectrum_returns_seconds_and_serializes(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.lag_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert len(data["energy"]) == 5
    assert all(v is not None for v in data["spectrum"])
    # No injected energy-dependent delay -> lags consistent with zero (<0.1 s).
    assert np.all(np.abs(finite_values(data["spectrum"])) < 0.1)
    assert data["ref_band"] is None
    assert data["freq_range"] == [0.1, 1.0]
    assert data["n_segments_hint"] == 8


def test_lag_spectrum_with_reference_band(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.lag_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        ref_min=8.0,
        ref_max=10.0,
        **FREQ,
        **ESPEC,
    )
    assert result["success"], result
    assert result["data"]["ref_band"] == [8.0, 10.0]
    full = svc.lag_spectrum("ev_mod", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC)
    assert result["data"]["spectrum"] != full["data"]["spectrum"]
    # A narrow reference band makes stingray's error formula take the sqrt of a
    # negative number; the bare numpy text must not reach the UI unexplained.
    for warning in result["data"]["warnings"]:
        assert not warning.startswith("invalid value encountered"), warning


def test_bare_numpy_warnings_are_wrapped_in_an_explanation():
    from services.varenergy_service import _humanize_warnings

    readable = _humanize_warnings(
        [
            "invalid value encountered in sqrt",
            "invalid value encountered in sqrt",
            "Low count rate in the 0.5-2.4 subject band: 6 ct/segment (<10). Skipping.",
        ]
    )
    assert len(readable) == 2, "duplicates must collapse"
    assert readable[0].startswith("undefined maths")
    assert "invalid value encountered in sqrt" in readable[0]
    assert readable[1].startswith("Low count rate")


@pytest.mark.parametrize(
    "ref_min,ref_max", [(8.0, None), (None, 10.0)]
)
def test_lag_spectrum_rejects_half_a_reference_band(modulated_state, ref_min, ref_max):
    svc = VarEnergyService(modulated_state)
    result = svc.lag_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        ref_min=ref_min,
        ref_max=ref_max,
        **FREQ,
        **ESPEC,
    )
    assert not result["success"]
    assert "ref_min" in result["message"] and "ref_max" in result["message"]


def test_lag_spectrum_rejects_inverted_reference_band(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.lag_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        ref_min=10.0,
        ref_max=8.0,
        **FREQ,
        **ESPEC,
    )
    assert not result["success"]
    assert "ref_min" in result["message"]


# --------------------------------------------------------------------------
# excess-variance
# --------------------------------------------------------------------------


def test_excess_variance_workaround_returns_finite_values(modulated_state):
    # Pins the stingray 2.2.10 bug workaround: the constructed object's
    # .spectrum is always all-NaN, so the service must use the arrays returned
    # by _spectrum_function().
    from stingray.varenergyspectrum import ExcessVarianceSpectrum

    raw = ExcessVarianceSpectrum(
        events=modulated_state.get_event_data("ev_mod"),
        freq_interval=[0.1, 1.0],
        energy_spec=(0.5, 10.0, 5, "lin"),
        bin_time=0.0625,
    )
    assert np.all(np.isnan(raw.spectrum)), "upstream bug disappeared; drop the workaround"

    svc = VarEnergyService(modulated_state)
    result = svc.excess_variance_spectrum("ev_mod", bin_time=0.0625, **ESPEC)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert len(data["energy"]) == 5
    assert all(v is not None for v in data["spectrum"])
    assert all(v is not None for v in data["spectrum_error"])
    fvar = finite_values(data["spectrum"])
    # F_var recovers the injected ~0.42 fractional variability in every band.
    assert np.all(fvar > 0.2) and np.all(fvar < 0.8)
    assert data["normalization"] == "fvar"


def test_excess_variance_normalization_none_is_unnormalized(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.excess_variance_spectrum(
        "ev_mod", bin_time=0.0625, normalization="none", **ESPEC
    )
    assert result["success"], result
    assert result["data"]["normalization"] == "none"
    # Unnormalized excess variance is in counts^2, orders of magnitude above F_var.
    assert np.all(finite_values(result["data"]["spectrum"]) > 1.0)


def test_excess_variance_rejects_unknown_normalization(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.excess_variance_spectrum(
        "ev_mod", bin_time=0.0625, normalization="norm_xs", **ESPEC
    )
    assert not result["success"]
    assert "normalization" in result["message"]


def test_excess_variance_is_not_invented_by_inter_gti_gaps(state_manager):
    # stingray's ExcessVarianceSpectrum builds ONE light curve from gti[0, 0]
    # to gti[-1, -1], so every bin in the 800 s gap is a real 0-count bin and
    # np.var(lc.counts) measures the gap, not the source. The service must
    # restrict the statistic to bins that are actually inside a GTI.
    from stingray.varenergyspectrum import ExcessVarianceSpectrum

    events = two_gti_constant_event_list()
    state_manager.add_event_data("ev_gappy", events)

    raw, _ = ExcessVarianceSpectrum(
        events=events,
        freq_interval=[0.0, 0.5],
        energy_spec=(0.5, 10.0, 4, "lin"),
        bin_time=1.0,
    )._spectrum_function()
    assert np.all(raw > 1.5), (
        "upstream stopped counting gap bins as data; revisit the workaround",
        raw,
    )

    svc = VarEnergyService(state_manager)
    result = svc.excess_variance_spectrum(
        "ev_gappy", bin_time=1.0, energy_min=0.5, energy_max=10.0, n_bands=4
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    measured = [
        (value, error)
        for value, error in zip(data["spectrum"], data["spectrum_error"])
        if value is not None
    ]
    # A constant Poisson source has no excess variance: every band that comes
    # out finite must sit within a few sigma of zero, nowhere near F_var ~ 2.
    for value, error in measured:
        assert value < 0.2, measured
        assert value < 5 * error, measured


def test_excess_variance_still_measures_real_variability_across_gtis(state_manager):
    # Masking the gaps must not cost sensitivity: the same 60% modulation is
    # recovered whether or not the observation is interrupted.
    state_manager.add_event_data("ev_mod", modulated_event_list())
    state_manager.add_event_data("ev_mod_gaps", gappy_modulated_event_list())
    svc = VarEnergyService(state_manager)

    whole = svc.excess_variance_spectrum("ev_mod", bin_time=0.0625, **ESPEC)
    gappy = svc.excess_variance_spectrum("ev_mod_gaps", bin_time=0.0625, **ESPEC)
    assert whole["success"] and gappy["success"], (whole, gappy)
    whole_fvar = finite_values(whole["data"]["spectrum"])
    gappy_fvar = finite_values(gappy["data"]["spectrum"])
    assert len(gappy_fvar) == 5
    assert np.all(gappy_fvar > 0.2) and np.all(gappy_fvar < 0.8)
    assert np.all(np.abs(gappy_fvar - whole_fvar) < 0.1)


def test_excess_variance_builds_each_light_curve_once(modulated_state, monkeypatch):
    # VarEnergySpectrum.__init__ runs _spectrum_function() and discards the
    # result; the service used to run it a second time to recover the numbers,
    # doubling the heaviest allocation in this module.
    from stingray import Lightcurve

    original = Lightcurve.make_lightcurve
    calls = []

    def counting_make_lightcurve(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(
        Lightcurve, "make_lightcurve", staticmethod(counting_make_lightcurve)
    )
    svc = VarEnergyService(modulated_state)
    result = svc.excess_variance_spectrum(
        "ev_mod", bin_time=0.0625, energy_min=0.5, energy_max=10.0, n_bands=3
    )
    assert result["success"], result
    assert len(calls) == 3, "one light curve per energy band, not two"


def test_nan_advice_on_the_excess_variance_page_names_only_its_own_controls(
    state_manager,
):
    # ExcessVarianceSpectrum has no reference band and the endpoint exposes no
    # segment_size, so the shared advisory sent users hunting for controls that
    # do not exist on that page.
    state_manager.add_event_data("ev_few", sparse_event_list())
    svc = VarEnergyService(state_manager)
    result = svc.excess_variance_spectrum("ev_few", bin_time=0.0625, **ESPEC)
    assert result["success"], result
    assert all(v is None for v in result["data"]["spectrum"])
    advice = [w for w in result["data"]["warnings"] if "could not be computed" in w]
    assert advice, result["data"]["warnings"]
    assert "segment_size" not in advice[0]
    assert "reference band" not in advice[0]
    assert "bin_time" in advice[0] and "energy bands" in advice[0]

    # The segmented spectra do have both controls, and keep naming them.
    covariance = svc.avg_covariance_spectrum(
        "ev_few", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    segmented_advice = [
        w for w in covariance["data"]["warnings"] if "could not be computed" in w
    ]
    assert segmented_advice, covariance["data"]["warnings"]
    assert "segment_size" in segmented_advice[0]
    assert "reference band" in segmented_advice[0]


# --------------------------------------------------------------------------
# variable-energy-spectrum
# --------------------------------------------------------------------------


def test_variable_energy_spectrum_returns_three_panels(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.variable_energy_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert len(data["energy"]) == 5
    for key in ("counts", "rms", "lag"):
        assert set(data[key]) == {"spectrum", "error"}
        assert len(data[key]["spectrum"]) == 5
        assert len(data[key]["error"]) == 5
    assert np.all(finite_values(data["counts"]["spectrum"]) > 0)
    assert np.all(finite_values(data["rms"]["spectrum"]) > 0.2)
    assert np.all(np.abs(finite_values(data["lag"]["spectrum"])) < 0.1)
    assert data["freq_range"] == [0.1, 1.0]
    assert data["ref_band"] is None
    assert data["n_segments_hint"] == 8


def test_variable_energy_spectrum_honours_reference_band(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.variable_energy_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        ref_min=8.0,
        ref_max=10.0,
        **FREQ,
        **ESPEC,
    )
    assert result["success"], result
    assert result["data"]["ref_band"] == [8.0, 10.0]


def test_variable_energy_spectrum_rejects_half_a_reference_band(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.variable_energy_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, ref_min=8.0, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "ref_min" in result["message"]


# --------------------------------------------------------------------------
# covariance-spectrum / avg-covariance-spectrum
# --------------------------------------------------------------------------


def test_covariance_spectrum_uses_the_whole_gti_as_one_segment(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.covariance_spectrum("ev_mod", bin_time=0.0625, **FREQ, **ESPEC)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["segment_size"] == 64.0
    assert data["n_segments_hint"] == 1
    assert data["norm"] == "abs"
    assert data["ref_band"] is None
    assert all(v is not None for v in data["spectrum"])
    assert np.all(finite_values(data["spectrum"]) > 0)


def test_covariance_spectrum_frac_norm(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.covariance_spectrum(
        "ev_mod", bin_time=0.0625, norm="frac", **FREQ, **ESPEC
    )
    assert result["success"], result
    assert result["data"]["norm"] == "frac"
    assert np.all(finite_values(result["data"]["spectrum"]) < 1.0)


def test_avg_covariance_spectrum_averages_segments(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.avg_covariance_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["segment_size"] == 8.0
    assert data["n_segments_hint"] == 8
    assert all(v is not None for v in data["spectrum"])
    assert np.all(finite_values(data["spectrum"]) > 0)
    # Averaging 8 segments must not change the covariance level materially.
    single = svc.covariance_spectrum("ev_mod", bin_time=0.0625, **FREQ, **ESPEC)
    ratio = finite_values(data["spectrum"]) / finite_values(single["data"]["spectrum"])
    assert np.all(np.abs(ratio - 1.0) < 0.2)


def test_avg_covariance_spectrum_rejects_segment_longer_than_gti(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.avg_covariance_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=100.0, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "good-time interval" in result["message"]


def test_avg_covariance_spectrum_with_reference_band(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.avg_covariance_spectrum(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        ref_min=8.0,
        ref_max=10.0,
        **FREQ,
        **ESPEC,
    )
    assert result["success"], result
    assert result["data"]["ref_band"] == [8.0, 10.0]


def test_covariance_spectrum_reports_the_gtis_it_dropped(state_manager):
    # segment_size is derived as the longest GTI, and stingray's
    # time_intervals_from_gtis skips every shorter one outright, so "1 segment
    # (full GTI)" is only true for a single-GTI observation. The payload has to
    # say how much exposure actually contributed.
    state_manager.add_event_data(
        "ev_gaps", gappy_modulated_event_list(gti=((0.0, 24.0), (28.0, 64.0)))
    )
    svc = VarEnergyService(state_manager)
    result = svc.covariance_spectrum("ev_gaps", bin_time=0.0625, **FREQ, **ESPEC)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["segment_size"] == 36.0
    assert data["n_segments_hint"] == 1
    assert data["n_gtis_total"] == 2
    assert data["n_gtis_used"] == 1
    assert data["exposure_total"] == 60.0
    assert data["exposure_used"] == 36.0
    dropped = [w for w in data["warnings"] if "skipped entirely" in w]
    assert dropped, data["warnings"]
    assert "36s of the 60s" in dropped[0]
    assert "60%" in dropped[0]
    assert "1 of 2 good-time intervals" in result["message"]


def test_single_gti_covariance_says_nothing_about_dropped_exposure(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.covariance_spectrum("ev_mod", bin_time=0.0625, **FREQ, **ESPEC)
    assert result["success"], result
    data = result["data"]
    assert data["n_gtis_total"] == data["n_gtis_used"] == 1
    assert data["exposure_used"] == data["exposure_total"] == 64.0
    assert not [w for w in data["warnings"] if "skipped entirely" in w]
    assert result["message"] == "Computed covariance spectrum in 5 energy bands"


def test_segmented_endpoints_warn_when_a_gti_is_too_short_for_the_segment(
    state_manager,
):
    state_manager.add_event_data(
        "ev_gaps", gappy_modulated_event_list(gti=((0.0, 6.0), (8.0, 64.0)))
    )
    svc = VarEnergyService(state_manager)
    result = svc.rms_spectrum(
        "ev_gaps", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    skipped = [w for w in result["data"]["warnings"] if "skips entirely" in w]
    assert skipped, result["data"]["warnings"]
    assert "1 of the 2 good-time intervals" in skipped[0]


def test_covariance_on_sparse_poisson_data_is_null_with_warnings(state_manager):
    # Pure Poisson noise has no excess variance in the reference band, so the
    # covariance is the sqrt of a negative number: legitimately all-NaN.
    state_manager.add_event_data("ev_few", sparse_event_list())
    svc = VarEnergyService(state_manager)
    result = svc.avg_covariance_spectrum(
        "ev_few", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert all(v is None for v in data["spectrum"])
    assert data["warnings"], "the all-NaN result must come with an explanation"
    assert any("could not be computed" in w for w in data["warnings"])


# --------------------------------------------------------------------------
# segment_size / bin_time compatibility
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bin_time,segment_size,expected",
    [(0.03, 8.0, 8.01), (0.07, 10.0, 10.01), (0.05, 8.03, 8.05), (0.09, 32.0, 32.04)],
)
def test_segment_size_is_snapped_to_a_whole_number_of_bins(
    modulated_state, bin_time, segment_size, expected
):
    # stingray masks frequencies on rint(segment_size/bin_time) bins but sizes
    # the FFT with floor(); when they disagree sub_power[good] raised
    # "IndexError: boolean index did not match indexed array", and when they
    # happened to match in length the mask was applied to the wrong grid.
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=bin_time, segment_size=segment_size, **FREQ, **ESPEC
    )
    assert result["success"], result
    assert "IndexError" not in (result["message"] or "")
    note = [w for w in result["data"]["warnings"] if "segment_size was adjusted" in w]
    assert note, result["data"]["warnings"]
    assert f"to {expected:g}s" in note[0], note


@pytest.mark.parametrize(
    "bin_time,segment_size", [(0.03, 8.0), (0.07, 10.0), (0.05, 8.03), (0.09, 32.0)]
)
def test_adjusted_segment_puts_stingrays_two_grids_on_one_bin_count(
    modulated_state, bin_time, segment_size
):
    from stingray.utils import fix_segment_size_to_integer_samples

    svc = VarEnergyService(modulated_state)
    adjusted, note = svc._fit_segment_to_bins(segment_size, bin_time, None)
    assert note
    _, fft_bins = fix_segment_size_to_integer_samples(adjusted, bin_time)
    assert fft_bins == int(np.rint(adjusted / bin_time))


def test_variable_energy_spectrum_survives_a_non_integer_segment_ratio(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.variable_energy_spectrum(
        "ev_mod", bin_time=0.03, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    assert all(v is not None for v in result["data"]["rms"]["spectrum"])


def test_segment_size_that_already_fits_is_left_alone(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.0625, segment_size=8.0, **FREQ, **ESPEC
    )
    assert result["success"], result
    assert not [
        w for w in result["data"]["warnings"] if "segment_size was adjusted" in w
    ]


# --------------------------------------------------------------------------
# frequency window vs frequency resolution
# --------------------------------------------------------------------------


def test_frequency_window_with_no_fourier_bin_is_rejected(modulated_state):
    # segment_size 8 s -> the lowest sampled frequency is 1/8 = 0.125 Hz, so
    # 0.001-0.05 Hz selects nothing and every band used to come back null
    # behind a bare "Mean of empty slice." warning.
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod",
        bin_time=0.05,
        segment_size=8.0,
        freq_min=0.001,
        freq_max=0.05,
        **ESPEC,
    )
    assert not result["success"]
    assert "1/segment_size" in result["message"]
    assert "0.125 Hz" in result["message"]


def test_frequency_window_floor_applies_to_the_covariance_endpoints(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.avg_covariance_spectrum(
        "ev_mod",
        bin_time=0.05,
        segment_size=8.0,
        freq_min=0.001,
        freq_max=0.05,
        **ESPEC,
    )
    assert not result["success"]
    assert "1/segment_size" in result["message"]


def test_frequency_window_wider_than_one_bin_is_accepted(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.rms_spectrum(
        "ev_mod", bin_time=0.05, segment_size=8.0, freq_min=0.001, freq_max=0.5, **ESPEC
    )
    assert result["success"], result


# --------------------------------------------------------------------------
# reference bands with no events
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method", ["lag_spectrum", "variable_energy_spectrum", "avg_covariance_spectrum"]
)
def test_empty_reference_band_is_rejected_readably(modulated_state, method):
    svc = VarEnergyService(modulated_state)
    result = getattr(svc, method)(
        "ev_mod",
        bin_time=0.0625,
        segment_size=8.0,
        ref_min=50.0,
        ref_max=100.0,
        **FREQ,
        **ESPEC,
    )
    assert not result["success"]
    assert "reference band" in result["message"]
    assert "no events" in result["message"]
    assert "NoneType" not in result["message"]


def test_empty_reference_band_is_rejected_by_covariance_spectrum(modulated_state):
    svc = VarEnergyService(modulated_state)
    result = svc.covariance_spectrum(
        "ev_mod", bin_time=0.0625, ref_min=50.0, ref_max=100.0, **FREQ, **ESPEC
    )
    assert not result["success"]
    assert "reference band" in result["message"]
    assert "NoneType" not in result["message"]


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


def test_all_six_routes_are_registered():
    from routes import varenergy_routes

    paths = {route.path for route in varenergy_routes.router.routes}
    assert paths == {
        "/rms-spectrum",
        "/lag-spectrum",
        "/excess-variance",
        "/variable-energy-spectrum",
        "/covariance-spectrum",
        "/avg-covariance-spectrum",
    }


def test_rms_request_model_has_no_reference_band_field():
    # ref_band is silently inert for RmsSpectrum in stingray 2.2.10, so the
    # endpoint must not offer a control that does nothing.
    from routes.varenergy_routes import RmsSpectrumRequest

    fields = set(RmsSpectrumRequest.model_fields)
    assert not fields & {"ref_band", "ref_min", "ref_max"}


def test_route_bodies_offload_to_a_thread():
    import inspect

    from routes import varenergy_routes

    for route in varenergy_routes.router.routes:
        source = inspect.getsource(route.endpoint)
        assert "asyncio.to_thread" in source, route.path


@pytest.mark.asyncio
async def test_rms_spectrum_endpoint_end_to_end():
    import httpx

    from main import create_app
    from services.state_manager import StateManager
    from utils.performance_monitor import PerformanceMonitor

    app = create_app()
    app.state.state_manager = StateManager()
    app.state.performance_monitor = PerformanceMonitor()
    app.state.state_manager.add_event_data("ev_mod", modulated_event_list())

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/varenergy/rms-spectrum",
            json={
                "event_list_name": "ev_mod",
                "bin_time": 0.0625,
                "segment_size": 8.0,
                "freq_min": 0.1,
                "freq_max": 1.0,
                "energy_min": 0.5,
                "energy_max": 10.0,
                "n_bands": 5,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"], body
    assert len(body["data"]["energy"]) == 5
    assert body["data"]["norm"] == "frac"
