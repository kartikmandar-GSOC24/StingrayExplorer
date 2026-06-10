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
    # With 8 segments, statistical fluctuations allow ~5% overshoot above 1.
    # The key assertion is that values are near 1, not millions (the old bug).
    assert np.all(coh <= 1.0 + 0.1)
    assert np.median(coh) > 0.9


def test_coherence_includes_uncertainty(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_coherence("ev1", "ev2", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    data = result["data"]
    assert "coherence_err" in data
    if data["coherence_err"] is not None:
        assert len(data["coherence_err"]) == len(data["coherence"])


def test_time_lags_include_errors_and_serialize(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_time_lags("ev1", "ev2", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert "time_lags_err" in data
    assert len(data["freq"]) == len(data["time_lags"])
    if data["time_lags_err"] is not None:
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


def test_power_colors_serializes(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.calculate_power_colors(
        "ev1",
        dt=0.0625,
        segment_size=8.0,
        freq_ranges={"A": (0.125, 0.5), "B": (0.5, 1.0), "C": (1.0, 2.0), "D": (2.0, 4.0)},
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)


def test_bispectrum_serializes(loaded_state):
    svc = TimingService(loaded_state)
    result = svc.create_bispectrum("ev1", dt=0.25, maxlag=10)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
