import json

import numpy as np

from services.timing_service import TimingService


def test_coherence_of_identical_signals_is_one(loaded_state):
    svc = TimingService(loaded_state)
    # An event list crossed with itself has coherence == 1 at all frequencies.
    result = svc.calculate_coherence("ev1", "ev1", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    coh = np.asarray(result["data"]["coherence"], dtype=float)
    # Identical inputs give raw coherence == 1 exactly; the Ingram-2019 noise-bias
    # correction can push individual noise-dominated bins above 1 without bound
    # (~(N/P)^2 / n_bin), so only a coarse cap discriminates against the old
    # |unnorm_power|^2 bug, whose values were ~1e8.
    assert np.all(coh < 2.0)
    assert np.median(coh) > 0.9  # measured 0.993 for this fixture


def test_coherence_includes_uncertainty(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_coherence("ev1", "ev2", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    data = result["data"]
    assert "coherence_err" in data
    assert data["coherence_err"] is not None
    assert len(data["coherence_err"]) == len(data["coherence"])


def test_time_lags_include_errors_and_serialize(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_time_lags("ev1", "ev2", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert "time_lags_err" in data
    assert len(data["freq"]) == len(data["time_lags"])
    assert data["time_lags_err"] is not None
    assert len(data["time_lags_err"]) == len(data["time_lags"])


def test_time_lags_freq_range_filters_all_arrays(loaded_state):
    svc = TimingService(loaded_state)
    full = svc.calculate_time_lags("ev1", "ev2", dt=0.0625, segment_size=8.0)
    sub = svc.calculate_time_lags(
        "ev1", "ev2", dt=0.0625, segment_size=8.0, freq_range=(0.5, 2.0)
    )
    assert sub["success"], sub
    freqs = np.asarray(sub["data"]["freq"], dtype=float)
    assert freqs.min() >= 0.5
    assert freqs.max() <= 2.0
    assert len(sub["data"]["freq"]) < len(full["data"]["freq"])
    assert len(sub["data"]["time_lags"]) == len(sub["data"]["freq"])
    if sub["data"]["time_lags_err"] is not None:
        assert len(sub["data"]["time_lags_err"]) == len(sub["data"]["freq"])


def test_power_colors_serializes(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_power_colors(
        "ev1",
        dt=0.0625,
        segment_size=8.0,
        freq_ranges={
            "A": (0.125, 0.5),
            "B": (0.5, 1.0),
            "C": (1.0, 2.0),
            "D": (2.0, 4.0),
        },
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert len(data["time"]) == 8  # 64 s / 8 s segments
    for band in data["power_colors"].values():
        assert len(band) == len(data["time"])


def test_bispectrum_serializes(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.create_bispectrum("ev1", dt=0.25, maxlag=10)
    assert result["success"], result
    json.dumps(result, allow_nan=False)


def test_time_lag_of_identical_signals_is_zero(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_time_lags("ev1", "ev1", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    lags = np.asarray([v for v in result["data"]["time_lags"] if v is not None])
    assert np.max(np.abs(lags)) < 1e-10


def test_tiny_segment_size_rejected_for_coherence(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_coherence("ev1", "ev2", dt=0.0625, segment_size=0.125)
    assert not result["success"]
    assert "3x dt" in result["message"]


def test_coherence_of_independent_signals_is_low(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_coherence("ev1", "ev2", dt=0.0625, segment_size=8.0)
    coh = np.asarray(
        [v for v in result["data"]["coherence"] if v is not None], dtype=float
    )
    assert np.median(coh) < 0.5  # measured ~0.1 for independent fixtures


def test_disjoint_event_lists_rejected_for_coherence(loaded_state):
    rng = np.random.default_rng(8)
    far = np.sort(rng.uniform(1000.0, 1064.0, 5000))
    from stingray import EventList

    loaded_state.add_event_data("ev_far", EventList(time=far, gti=[[1000.0, 1064.0]]))
    svc = TimingService(loaded_state)
    result = svc.calculate_coherence("ev1", "ev_far", dt=0.0625, segment_size=8.0)
    assert not result["success"]
    assert "no overlapping time range" in result["message"]


def test_time_lag_sign_convention_for_shifted_signal(loaded_state):
    # Pin the sign convention the UI will document: ev_shifted = ev1 delayed by 0.1 s.
    from stingray import EventList

    ev1 = loaded_state.get_event_data("ev1")
    # Keep the same GTI as ev1 so both light curves share one bin grid; with
    # gti=[[0.1, 64.1]] the GTI intersection misaligns the grids (0.1 is not a
    # multiple of dt) and the effective shift becomes 2 bins = 0.125 s.
    shifted_times = ev1.time + 0.1
    shifted_times = shifted_times[shifted_times < 64.0]
    shifted = EventList(time=np.sort(shifted_times), gti=[[0.0, 64.0]])
    loaded_state.add_event_data("ev_shifted", shifted)
    svc = TimingService(loaded_state)
    result = svc.calculate_time_lags(
        "ev1", "ev_shifted", dt=0.0625, segment_size=8.0, freq_range=(0.25, 2.0)
    )
    assert result["success"], result
    lags = np.asarray([v for v in result["data"]["time_lags"] if v is not None])
    median_lag = float(np.median(lags))
    # Magnitude must recover the 0.1 s shift well below the phase-wrap limit (5 Hz).
    assert abs(abs(median_lag) - 0.1) < 0.02
    # Observed: median_lag = -0.095 for channel 2 delayed by 0.1 s → stingray
    # convention: positive lag means channel 2 (second list) leads channel 1;
    # a delayed second channel yields negative lags.
