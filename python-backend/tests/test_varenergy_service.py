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
