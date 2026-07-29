"""Tests for CorrelationService (auto/cross correlation).

Every stingray behaviour pinned here was verified against stingray 2.2.10; the
comments record the measured values so a regression is obvious.
"""

import json

import httpx
import numpy as np
import pytest
from stingray import EventList
from stingray.crosscorrelation import CrossCorrelation

from services.correlation_service import (
    MAX_BINS,
    CorrelationService,
    _shared_grid_lightcurves,
)
from services.state_manager import StateManager
from utils.performance_monitor import PerformanceMonitor

DT = 0.05
LENGTH = 64.0
# A realistic mission-elapsed time: float64 spacing here is 1.49e-8 s, enough
# to visibly quantise a grid built by np.arange over absolute times.
MET = 8e7


def pulse_times(
    seed: int,
    n_events: int = 30000,
    length: float = LENGTH,
    center: float = 30.0,
    width: float = 2.0,
    amp: float = 6.0,
) -> np.ndarray:
    """Event times drawn from a rate with a single Gaussian pulse.

    A non-periodic modulation is used on purpose: a sinusoid makes the
    correlation peak ambiguous modulo its period, which would make the
    sign-convention and shared-grid assertions below unfalsifiable.
    """
    rng = np.random.default_rng(seed)
    out: list = []
    while len(out) < n_events:
        candidates = rng.uniform(0.0, length, n_events)
        rate = 1.0 + amp * np.exp(-((candidates - center) ** 2) / (2 * width**2))
        keep = candidates[rng.uniform(0.0, 1.0 + amp, n_events) < rate]
        out.extend(keep.tolist())
    return np.sort(np.asarray(out[:n_events]))


@pytest.fixture()
def pulse_state(state_manager: StateManager) -> StateManager:
    """A pulsed list, the same list delayed by 0.5 s, and a truncated copy."""
    times = pulse_times(7)
    state_manager.add_event_data("ev_pulse", EventList(time=times, gti=[[0.0, LENGTH]]))
    state_manager.add_event_data(
        "ev_delayed",
        EventList(time=times + 0.5, gti=[[0.5, LENGTH + 0.5]]),
    )
    # Same photons, but the list only starts at t=16 s: identical signal on a
    # different absolute-time footing.
    truncated = times[times >= 16.0]
    state_manager.add_event_data(
        "ev_truncated", EventList(time=truncated, gti=[[16.0, LENGTH]])
    )
    return state_manager


# --------------------------------------------------------------------------
# auto-correlation
# --------------------------------------------------------------------------


def test_auto_correlation_serializes_with_zero_time_shift(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.auto_correlation("ev1", dt=DT)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["time_shift"] == 0.0
    assert data["mode"] == "same"
    assert data["norm"] == "none"
    assert data["dt"] == DT
    assert data["n"] == len(data["corr"]) == len(data["time_lags"])
    assert isinstance(data["warnings"], list)
    # 64 s / 0.05 s, minus the partial first/last bin the GTI trims.
    assert 1275 <= data["n"] <= 1280


def test_auto_correlation_full_mode_doubles_the_lag_axis(loaded_state):
    svc = CorrelationService(loaded_state)
    same = svc.auto_correlation("ev1", dt=DT, mode="same")
    full = svc.auto_correlation("ev1", dt=DT, mode="full")
    assert full["success"], full
    assert full["data"]["mode"] == "full"
    assert full["data"]["n"] == 2 * same["data"]["n"] - 1
    assert len(full["data"]["time_lags"]) == full["data"]["n"]


def test_auto_correlation_variance_norm_is_bounded(pulse_state):
    # AutoCorrelation() drops `norm`, so the variance path must route through
    # CrossCorrelation(lc, lc, norm='variance'). Measured peaks for this
    # fixture: norm='none' -> 6.06e5 counts^2, norm='variance' -> 1.057.
    svc = CorrelationService(pulse_state)
    raw = svc.auto_correlation("ev_pulse", dt=DT, norm="none")
    normed = svc.auto_correlation("ev_pulse", dt=DT, norm="variance")
    assert normed["success"], normed
    json.dumps(normed, allow_nan=False)
    assert normed["data"]["norm"] == "variance"
    assert normed["data"]["time_shift"] == 0.0
    peak_raw = max(v for v in raw["data"]["corr"] if v is not None)
    peak_normed = max(v for v in normed["data"]["corr"] if v is not None)
    assert peak_raw > 1000.0
    assert peak_normed < 2.0


def test_auto_correlation_rejects_unknown_mode(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.auto_correlation("ev1", dt=DT, mode="valid")
    assert not result["success"]
    assert "mode" in result["message"]
    assert "same" in result["message"] and "full" in result["message"]


def test_auto_correlation_rejects_unknown_norm(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.auto_correlation("ev1", dt=DT, norm="leahy")
    assert not result["success"]
    assert "norm" in result["message"]


def test_auto_correlation_rejects_unknown_event_list(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.auto_correlation("nope", dt=DT)
    assert not result["success"]
    assert "not found" in result["message"]
    assert result["data"] is None


def test_auto_correlation_rejects_non_positive_dt(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.auto_correlation("ev1", dt=0.0)
    assert not result["success"]
    assert "dt" in result["message"]


def test_auto_correlation_rejects_dt_larger_than_the_data(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.auto_correlation("ev1", dt=40.0)
    assert not result["success"]
    assert "at least 3" in result["message"]


# --------------------------------------------------------------------------
# cross-correlation
# --------------------------------------------------------------------------


def test_cross_correlation_sign_convention_for_delayed_second_list(pulse_state):
    # ev_delayed = ev_pulse + 0.5 s, so the FIRST list leads and time_shift < 0.
    # Documented for the UI as: positive time_shift means the first list lags
    # the second.
    svc = CorrelationService(pulse_state)
    result = svc.cross_correlation("ev_pulse", "ev_delayed", dt=DT)
    assert result["success"], result
    assert result["data"]["time_shift"] == pytest.approx(-0.5, abs=2 * DT)
    # ...and the reversed pair flips the sign.
    reversed_result = svc.cross_correlation("ev_delayed", "ev_pulse", dt=DT)
    assert reversed_result["data"]["time_shift"] == pytest.approx(0.5, abs=2 * DT)


def test_cross_correlation_bins_both_lists_on_one_shared_grid(pulse_state):
    # ev_truncated holds the same photons as ev_pulse but only from t=16 s on.
    # Binning each list independently (EventList.to_lc) puts identical features
    # 320 bins apart, and stingray correlates by POSITION, so the naive answer
    # is time_shift = +16.0 s. A shared bin-edge grid gives the true 0.0 s.
    ev_pulse = pulse_state.get_event_data("ev_pulse")
    ev_truncated = pulse_state.get_event_data("ev_truncated")
    naive = CrossCorrelation(
        ev_pulse.to_lc(dt=DT), ev_truncated.to_lc(dt=DT), mode="same"
    )
    assert abs(float(naive.time_shift)) > 10.0  # measured 16.0

    svc = CorrelationService(pulse_state)
    result = svc.cross_correlation("ev_pulse", "ev_truncated", dt=DT)
    assert result["success"], result
    assert result["data"]["time_shift"] == pytest.approx(0.0, abs=2 * DT)
    # The shared grid spans only the common range (~48 s), not ev_pulse's 64 s.
    common = float(ev_truncated.time[-1]) - float(ev_truncated.time[0])
    assert result["data"]["n"] * DT == pytest.approx(common, abs=2 * DT)
    assert result["data"]["n"] < 0.8 * (LENGTH / DT)


def test_cross_correlation_warns_when_the_common_range_crops_the_data(pulse_state):
    svc = CorrelationService(pulse_state)
    result = svc.cross_correlation("ev_pulse", "ev_truncated", dt=DT)
    assert result["success"], result
    assert any("common time range" in w for w in result["data"]["warnings"])


def test_cross_correlation_serializes_for_independent_lists(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.cross_correlation("ev1", "ev2", dt=DT)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["dt"] == DT
    assert data["mode"] == "same"
    assert data["norm"] == "none"
    assert data["n"] == len(data["corr"]) == len(data["time_lags"])
    assert isinstance(data["warnings"], list)


def test_cross_correlation_variance_nan_nulls_the_time_shift(pulse_state):
    # A flat 200-event list has a negative noise-subtracted variance
    # (measured -0.89) while the pulsed list is strongly positive (+454), so
    # sqrt(var1*var2) is NaN and stingray silently returns an all-NaN corr
    # with a bogus time_shift (measured -0.5).
    rng = np.random.default_rng(42)
    flat = np.sort(rng.uniform(0.0, LENGTH, 200))
    pulse_state.add_event_data("ev_flat", EventList(time=flat, gti=[[0.0, LENGTH]]))
    svc = CorrelationService(pulse_state)
    result = svc.cross_correlation("ev_flat", "ev_pulse", dt=DT, norm="variance")
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["time_shift"] is None
    assert all(v is None for v in data["corr"])
    assert any("NaN" in w for w in data["warnings"])
    assert any("negative" in w.lower() for w in data["warnings"])


def test_cross_correlation_rejects_disjoint_event_lists(loaded_state):
    rng = np.random.default_rng(8)
    far = np.sort(rng.uniform(1000.0, 1064.0, 5000))
    loaded_state.add_event_data("ev_far", EventList(time=far, gti=[[1000.0, 1064.0]]))
    svc = CorrelationService(loaded_state)
    result = svc.cross_correlation("ev1", "ev_far", dt=DT)
    assert not result["success"]
    assert "no overlapping time range" in result["message"]


def test_cross_correlation_rejects_unknown_event_lists(loaded_state):
    svc = CorrelationService(loaded_state)
    first = svc.cross_correlation("nope", "ev2", dt=DT)
    assert not first["success"]
    assert "nope" in first["message"] and "not found" in first["message"]
    second = svc.cross_correlation("ev1", "nope", dt=DT)
    assert not second["success"]
    assert "nope" in second["message"] and "not found" in second["message"]


def test_cross_correlation_rejects_unknown_mode(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.cross_correlation("ev1", "ev2", dt=DT, mode="valid")
    assert not result["success"]
    assert "mode" in result["message"]


def test_cross_correlation_rejects_unknown_norm(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.cross_correlation("ev1", "ev2", dt=DT, norm="frac")
    assert not result["success"]
    assert "norm" in result["message"]


def test_cross_correlation_rejects_dt_larger_than_the_overlap(loaded_state):
    svc = CorrelationService(loaded_state)
    result = svc.cross_correlation("ev1", "ev2", dt=30.0)
    assert not result["success"]
    assert "at least 3" in result["message"]


def test_cross_correlation_full_mode_lengths_agree(pulse_state):
    svc = CorrelationService(pulse_state)
    result = svc.cross_correlation("ev_pulse", "ev_delayed", dt=DT, mode="full")
    assert result["success"], result
    data = result["data"]
    # stingray's cross= construction path desyncs corr/time_lags in 'full'
    # mode; the two-Lightcurve path used here must not.
    assert data["n"] == len(data["corr"]) == len(data["time_lags"])
    assert data["time_shift"] == pytest.approx(-0.5, abs=2 * DT)


def test_variance_norm_warns_when_noise_subtracted_variance_is_negative(loaded_state):
    # Both conftest lists are Poisson-flat (measured noise-subtracted variance
    # -3.72 at dt=0.05), so the product stays positive and no NaN appears --
    # but the normalisation is physically meaningless and must be flagged.
    svc = CorrelationService(loaded_state)
    result = svc.cross_correlation("ev1", "ev2", dt=DT, norm="variance")
    assert result["success"], result
    assert result["data"]["time_shift"] is not None
    assert any("negative" in w.lower() for w in result["data"]["warnings"])


# --------------------------------------------------------------------------
# grid robustness (unsorted input, bin cap, dt fidelity, float precision)
# --------------------------------------------------------------------------


def test_cross_correlation_uses_the_full_span_of_an_unsorted_event_list(pulse_state):
    # EventList.read() does not forward skip_checks in stingray 2.2.10, so real
    # unsorted event files reach the service with time[0]/time[-1] pointing at
    # interior photons. Deriving the grid from them correlated a sliver of the
    # data (measured 26 lags instead of ~1280) or inverted start/stop and faked
    # a "no overlapping time range" rejection.
    shuffled = np.random.default_rng(99).permutation(pulse_times(7))
    events = EventList(time=shuffled, gti=[[0.0, LENGTH]], skip_checks=True)
    assert float(events.time[0]) > float(np.min(events.time))
    assert float(events.time[-1]) < float(np.max(events.time))
    pulse_state.add_event_data("ev_shuffled", events)

    svc = CorrelationService(pulse_state)
    ordered = svc.cross_correlation("ev_pulse", "ev_delayed", dt=DT)
    unordered = svc.cross_correlation("ev_shuffled", "ev_delayed", dt=DT)
    assert unordered["success"], unordered
    # np.histogram is order-independent, so the results must be identical.
    assert unordered["data"]["n"] == ordered["data"]["n"]
    assert unordered["data"]["corr"] == ordered["data"]["corr"]
    assert unordered["data"]["time_shift"] == ordered["data"]["time_shift"]
    # The grid spans the whole overlap (~63.5 s), not an interior sliver.
    assert unordered["data"]["n"] * DT == pytest.approx(LENGTH - 0.5, abs=0.5)

    # The auto path used to derive its span the same way.
    assert (
        svc.auto_correlation("ev_shuffled", dt=DT)["data"]["n"]
        == svc.auto_correlation("ev_pulse", dt=DT)["data"]["n"]
    )


def test_correlation_rejects_a_dt_that_would_blow_up_the_bin_count(loaded_state):
    # Nothing else bounds the grid: two 3 ks lists at dt=1e-3 already serialise
    # ~93 MB of JSON and add ~750 MB of RSS, and a finer dt OOMs the backend.
    svc = CorrelationService(loaded_state)
    cases = (
        (svc.auto_correlation("ev1", dt=1e-5), "the span of 'ev1'"),
        (svc.cross_correlation("ev1", "ev2", dt=1e-5), "the overlapping time range"),
    )
    for result, what in cases:
        assert not result["success"], result
        assert result["data"] is None
        message = result["message"]
        assert message.startswith(f"dt (1e-05s) over {what} (63.")
        assert "bins;" in message
        assert (
            f"increase dt or shorten the range (the cap is {MAX_BINS:,} bins)"
            in message
        )
        # The reported count is the real one: ~64 s / 1e-5 s.
        assert "6,39" in message

    # A large-but-workable grid is still accepted.
    ok = svc.cross_correlation("ev1", "ev2", dt=1e-3)
    assert ok["success"], ok
    assert ok["data"]["n"] < MAX_BINS


def test_requested_dt_is_the_dt_used_by_both_endpoints(state_manager):
    # EventList.dt is the instrument time resolution (TIMEDEL for real HEASARC
    # files) and EventList.to_lc snaps dt to a multiple of it, so the auto page
    # rendered half as many lags as the cross page for identical input while
    # its message quoted the requested dt (640 lags "at dt=0.05s" over 64 s).
    times = pulse_times(7)
    for name in ("ev_res", "ev_res_copy"):
        state_manager.add_event_data(
            name, EventList(time=times, gti=[[0.0, LENGTH]], dt=0.1)
        )
    # Pins the upstream behaviour being routed around.
    assert float(state_manager.get_event_data("ev_res").to_lc(dt=DT).dt) == 0.1

    svc = CorrelationService(state_manager)
    auto = svc.auto_correlation("ev_res", dt=DT)
    cross = svc.cross_correlation("ev_res", "ev_res_copy", dt=DT)
    assert auto["success"], auto
    assert cross["success"], cross
    assert auto["data"]["dt"] == DT
    assert cross["data"]["dt"] == DT
    assert auto["data"]["n"] == cross["data"]["n"]
    # The success message must describe the run that actually happened.
    assert f"({auto['data']['n']} lags, dt={DT}s)" in auto["message"]
    assert f"({cross['data']['n']} lags, dt={DT}s)" in cross["message"]
    # Binning on our own grid bypasses stingray's beat-artefact guard, so the
    # mismatch is surfaced instead of silently rewriting the user's dt.
    for result in (auto, cross):
        assert any("time resolution" in w for w in result["data"]["warnings"])


def test_large_absolute_times_do_not_stretch_the_lag_axis(state_manager):
    # np.arange over absolute MET quantises its step to the local float64
    # spacing: at MET 8e7 a requested dt of 0.01 s really stepped 0.010000005 s
    # (measured), while stingray kept deriving time_lags from the declared dt.
    times = pulse_times(7)
    state_manager.add_event_data(
        "ev_met", EventList(time=times + MET, gti=[[MET, MET + LENGTH]])
    )
    state_manager.add_event_data(
        "ev_met_delayed",
        EventList(time=times + MET + 0.5, gti=[[MET + 0.5, MET + LENGTH + 0.5]]),
    )
    lc1, lc2, grid_start, grid_stop = _shared_grid_lightcurves(
        state_manager.get_event_data("ev_met"),
        state_manager.get_event_data("ev_met_delayed"),
        0.01,
    )
    assert lc1.n == lc2.n
    assert (grid_stop - grid_start) / lc1.n == pytest.approx(0.01, abs=1e-9)

    svc = CorrelationService(state_manager)
    result = svc.cross_correlation("ev_met", "ev_met_delayed", dt=DT)
    assert result["success"], result
    assert result["data"]["time_shift"] == pytest.approx(-0.5, abs=2 * DT)


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correlation_routes_are_wired(loaded_state):
    from main import create_app

    app = create_app()
    app.state.state_manager = loaded_state
    app.state.performance_monitor = PerformanceMonitor()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        auto = await client.post(
            "/api/correlation/auto-correlation",
            json={"event_list_name": "ev1", "dt": DT},
        )
        cross = await client.post(
            "/api/correlation/cross-correlation",
            json={
                "event_list_1_name": "ev1",
                "event_list_2_name": "ev2",
                "dt": DT,
                "mode": "same",
                "norm": "none",
            },
        )

    assert auto.status_code == 200
    assert auto.json()["success"], auto.json()
    assert auto.json()["data"]["time_shift"] == 0.0
    assert cross.status_code == 200
    assert cross.json()["success"], cross.json()
    assert "warnings" in cross.json()["data"]


@pytest.mark.asyncio
async def test_correlation_routes_soft_fail_with_http_200(loaded_state):
    from main import create_app

    app = create_app()
    app.state.state_manager = loaded_state
    app.state.performance_monitor = PerformanceMonitor()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/correlation/auto-correlation",
            json={"event_list_name": "missing", "dt": DT},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
