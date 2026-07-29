import json

import httpx
import numpy as np
import pytest
from stingray import EventList

from services.deadtime_service import DeadtimeService
from utils.performance_monitor import PerformanceMonitor


@pytest.fixture()
def deadtime_state(loaded_state):
    """loaded_state plus a dead-time-affected event list built like report (b).

    300 c/s incident over 200 s, non-paralyzable dead time 2.5 ms -> ~171 c/s
    detected. The uncorrected Leahy power sits well below 2; the model
    correction must bring it back to 2.
    """
    rng = np.random.default_rng(42)
    length = 200.0
    times = np.sort(rng.uniform(0.0, length, 60000))
    ev = EventList(time=times, gti=[[0.0, length]]).apply_deadtime(0.0025)
    loaded_state.add_event_data("ev_dead", ev)
    return loaded_state


def test_pds_correction_recovers_leahy_white_noise(deadtime_state):
    svc = DeadtimeService(deadtime_state)
    result = svc.calculate_pds_correction(
        "ev_dead", dt=0.001, segment_size=20.0, dead_time=0.0025, limit_k=250
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]

    uncorrected = np.asarray(data["power_uncorrected"], dtype=float)
    corrected = np.asarray(data["power_corrected"], dtype=float)
    assert len(data["freq"]) == len(uncorrected) == len(corrected)
    # Dead time suppresses the Leahy white-noise level (measured 1.657)...
    assert uncorrected.mean() < 1.9
    # ...and the model correction restores it to 2 (measured 1.9982).
    assert abs(corrected.mean() - 2.0) < 0.05
    assert data["n_segments"] == 10  # 200 s / 20 s segments
    assert data["rate"] == pytest.approx(171.5, abs=1.0)
    assert data["norm"] == "leahy"
    assert data["warnings"] == []


def test_pds_correction_missing_event_list_soft_fails(deadtime_state):
    svc = DeadtimeService(deadtime_state)
    result = svc.calculate_pds_correction(
        "nope", dt=0.001, segment_size=20.0, dead_time=0.0025
    )
    assert not result["success"]
    assert result["data"] is None
    assert "not found" in result["message"]


def test_pds_correction_rejects_unphysical_rate_times_dead_time(deadtime_state):
    # ev1 is 20000 events over 64 s = 312.5 c/s; 312.5 * 0.01 s = 3.12 >= 1.
    svc = DeadtimeService(deadtime_state)
    result = svc.calculate_pds_correction(
        "ev1", dt=0.01, segment_size=8.0, dead_time=0.01
    )
    assert not result["success"]
    assert "must be less than 1" in result["message"]
    # The message names the actual numbers so the user can act on it.
    assert "312.50" in result["message"]
    assert "0.01" in result["message"]
    assert "3.12" in result["message"]


def test_pds_correction_rejects_tiny_segment_size(deadtime_state):
    svc = DeadtimeService(deadtime_state)
    result = svc.calculate_pds_correction(
        "ev1", dt=0.0625, segment_size=0.125, dead_time=0.0001
    )
    assert not result["success"]
    assert "3x dt" in result["message"]


def test_pds_correction_rejects_segment_longer_than_exposure(deadtime_state):
    svc = DeadtimeService(deadtime_state)
    result = svc.calculate_pds_correction(
        "ev1", dt=0.01, segment_size=100.0, dead_time=0.0001
    )
    assert not result["success"]
    assert "longer than the total good-time exposure" in result["message"]


def test_pds_correction_rejects_non_positive_dead_time(deadtime_state):
    svc = DeadtimeService(deadtime_state)
    result = svc.calculate_pds_correction(
        "ev1", dt=0.01, segment_size=8.0, dead_time=0.0
    )
    assert not result["success"]
    assert "dead_time must be positive" in result["message"]


def test_pds_correction_background_rate_counts_towards_the_physical_limit(
    deadtime_state,
):
    # 312.5 c/s source is fine at td=1 ms (0.31), but +800 c/s background is not.
    svc = DeadtimeService(deadtime_state)
    ok = svc.calculate_pds_correction(
        "ev1", dt=0.01, segment_size=8.0, dead_time=0.001
    )
    assert ok["success"], ok
    bad = svc.calculate_pds_correction(
        "ev1", dt=0.01, segment_size=8.0, dead_time=0.001, background_rate=800.0
    )
    assert not bad["success"]
    assert "must be less than 1" in bad["message"]
    assert "800.00" in bad["message"]


def _register_deadtime_pair(state, seed_a=11, seed_b=12, length=64.0, n=20000):
    """Two independent simultaneous streams, each dead-time filtered (report (c))."""
    for name, seed in (("det_a", seed_a), ("det_b", seed_b)):
        rng = np.random.default_rng(seed)
        times = np.sort(rng.uniform(0.0, length, n))
        ev = EventList(time=times, gti=[[0.0, length]]).apply_deadtime(0.0025)
        state.add_event_data(name, ev)


def test_fad_correction_returns_finite_serializable_columns(loaded_state):
    _register_deadtime_pair(loaded_state)
    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction(
        "det_a", "det_b", dt=1.0 / 512, segment_size=2.0
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]

    assert data["n_segments"] == 32  # 64 s / 2 s segments
    assert data["norm"] == "frac"
    n_freq = len(data["freq"])
    assert n_freq > 0
    for column in ("pds1", "pds2", "ptot", "cs"):
        values = data[column]
        assert len(values) == n_freq
        assert all(v is not None for v in values)
        assert np.isfinite(np.asarray(values, dtype=float)).all()
    # cs is the magnitude of a complex column; the signed cospectrum comes too.
    assert len(data["cs_real"]) == n_freq
    assert all(v >= 0 for v in data["cs"])
    assert not any("fewer than 30" in w for w in data["warnings"])


def test_fad_correction_warns_below_thirty_segments_but_still_computes(loaded_state):
    _register_deadtime_pair(loaded_state)
    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction(
        "det_a", "det_b", dt=1.0 / 512, segment_size=8.0
    )
    assert result["success"], result
    assert result["data"]["n_segments"] == 8
    assert any("fewer than 30" in w for w in result["data"]["warnings"])
    assert len(result["data"]["freq"]) > 0


def test_fad_correction_does_not_mutate_stored_event_lists(loaded_state):
    # FAD assigns the GTI intersection onto BOTH inputs; the service must shield
    # the objects held in StateManager from that side effect.
    rng = np.random.default_rng(21)
    a = EventList(time=np.sort(rng.uniform(0.0, 64.0, 20000)), gti=[[0.0, 64.0]])
    b = EventList(time=np.sort(rng.uniform(8.0, 72.0, 20000)), gti=[[8.0, 72.0]])
    loaded_state.add_event_data("gti_a", a)
    loaded_state.add_event_data("gti_b", b)

    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction(
        "gti_a", "gti_b", dt=1.0 / 512, segment_size=1.0
    )
    assert result["success"], result
    assert np.allclose(loaded_state.get_event_data("gti_a").gti, [[0.0, 64.0]])
    assert np.allclose(loaded_state.get_event_data("gti_b").gti, [[8.0, 72.0]])


def test_fad_correction_missing_event_list_soft_fails(loaded_state):
    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction("ev1", "nope", dt=0.01, segment_size=8.0)
    assert not result["success"]
    assert "not found" in result["message"]


def test_fad_correction_rejects_disjoint_event_lists(loaded_state):
    rng = np.random.default_rng(8)
    far = np.sort(rng.uniform(1000.0, 1064.0, 5000))
    loaded_state.add_event_data(
        "ev_far", EventList(time=far, gti=[[1000.0, 1064.0]])
    )
    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction("ev1", "ev_far", dt=0.01, segment_size=8.0)
    assert not result["success"]
    assert "no overlapping time range" in result["message"]


def test_fad_correction_rejects_tiny_segment_size(loaded_state):
    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction("ev1", "ev2", dt=0.0625, segment_size=0.125)
    assert not result["success"]
    assert "3x dt" in result["message"]


def test_fad_correction_rejects_empty_event_list(loaded_state):
    # `EventList(time=np.array([]))` normalizes `.time` to None, not an empty
    # array, so the preflight must not call `len()` on it directly (that
    # would raise a raw TypeError instead of a readable rejection).
    loaded_state.add_event_data(
        "ev_empty", EventList(time=np.array([]), gti=[[0.0, 64.0]])
    )
    svc = DeadtimeService(loaded_state)

    result = svc.calculate_fad_correction("ev1", "ev_empty", dt=0.01, segment_size=8.0)
    assert not result["success"]
    assert result["data"] is None
    assert "contains no events" in result["message"]

    # Same rejection regardless of which argument position is empty.
    result_swapped = svc.calculate_fad_correction(
        "ev_empty", "ev1", dt=0.01, segment_size=8.0
    )
    assert not result_swapped["success"]
    assert "contains no events" in result_swapped["message"]


def test_fad_correction_rejects_zero_exposure_event_list(loaded_state):
    # A fully-screened observation: real event times, but a GTI array with
    # zero rows (all good time removed by screening). Before the preflight
    # this reached stingray's FAD() unguarded and raised a bare
    # `IndexError: list index out of range`.
    rng = np.random.default_rng(9)
    times = np.sort(rng.uniform(0.0, 64.0, 500))
    loaded_state.add_event_data(
        "ev_no_gti", EventList(time=times, gti=np.zeros((0, 2)))
    )
    svc = DeadtimeService(loaded_state)

    result = svc.calculate_fad_correction(
        "ev1", "ev_no_gti", dt=0.01, segment_size=8.0
    )
    assert not result["success"]
    assert result["data"] is None
    assert "no good-time exposure" in result["message"]
    assert "ev_no_gti" in result["message"]


def test_fad_correction_handles_nan_fad_delta_without_crashing(loaded_state):
    # Force fad_delta to NaN the same way a real user would trigger it: pick
    # the same event list for both "detectors" (e.g. testing with one loaded
    # file, or accidentally selecting the same detector twice). The smoothed
    # Fourier difference between two byte-identical inputs is exactly zero,
    # so `average_diff / smooth_real**0.5` is 0/0 -> NaN -> fad_delta is NaN.
    # Without a finite-or-None guard, that NaN reaches `json.dumps(...,
    # allow_nan=False)` unguarded and turns a success:true result into an
    # unhandled 500 at the JSON-encoding layer.
    svc = DeadtimeService(loaded_state)
    result = svc.calculate_fad_correction(
        "ev1", "ev1", dt=1.0 / 512, segment_size=2.0
    )

    assert result["success"], result
    json.dumps(result, allow_nan=False)  # must not raise
    data = result["data"]

    assert data["fad_delta"] is None
    assert data["n_segments"] == 32  # 64 s / 2 s segments, above MIN_FAD_SEGMENTS
    assert any(
        "fad_delta" in w and "could not be computed" in w
        for w in data["warnings"]
    )


def _client(state):
    """httpx client over the real app, wired to a pre-populated StateManager."""
    from main import create_app

    app = create_app()
    # ASGITransport does not run the lifespan; provide state manually.
    app.state.state_manager = state
    app.state.performance_monitor = PerformanceMonitor()
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.mark.asyncio
async def test_pds_correction_route_matches_the_request_contract(loaded_state):
    async with _client(loaded_state) as client:
        response = await client.post(
            "/api/deadtime/pds-correction",
            json={
                "event_list_name": "ev1",
                "dt": 0.05,
                "segment_size": 8.0,
                "dead_time": 0.0001,
                "background_rate": 0.0,
                "limit_k": 200,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"], body
    data = body["data"]
    assert set(
        ["freq", "power_uncorrected", "power_corrected", "rate", "n_segments",
         "warnings"]
    ) <= set(data)
    assert data["n_segments"] == 8  # 64 s / 8 s segments


@pytest.mark.asyncio
async def test_fad_correction_route_matches_the_request_contract(loaded_state):
    async with _client(loaded_state) as client:
        response = await client.post(
            "/api/deadtime/fad-correction",
            json={
                "event_list_1_name": "ev1",
                "event_list_2_name": "ev2",
                "dt": 1.0 / 512,
                "segment_size": 2.0,
                "norm": "frac",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["success"], body
    data = body["data"]
    assert set(
        ["freq", "pds1", "pds2", "ptot", "cs", "n_segments", "warnings"]
    ) <= set(data)
    assert data["n_segments"] == 32
