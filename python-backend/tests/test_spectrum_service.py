import json

import numpy as np
import pytest

from services.spectrum_service import SpectrumService, _finite_list


def test_cross_spectrum_is_strict_json_serializable(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_cross_spectrum("ev1", "ev2", dt=0.0625)
    assert result["success"], result
    json.dumps(result, allow_nan=False)  # complex or NaN values raise here
    data = result["data"]
    assert all(isinstance(p, float) for p in data["power"][:10])
    assert data["power_phase"] is not None
    assert len(data["power_phase"]) == len(data["power"])


def test_averaged_cross_spectrum_is_strict_json_serializable(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_averaged_cross_spectrum(
        "ev1", "ev2", dt=0.0625, segment_size=8.0
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    assert result["data"]["power_phase"] is not None


def test_power_spectrum_has_null_phase(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_power_spectrum("ev1", dt=0.0625)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    assert result["data"]["power_phase"] is None


def test_rebin_of_stored_cross_spectrum_serializes(loaded_state):
    svc = SpectrumService(loaded_state)
    created = svc.create_cross_spectrum("ev1", "ev2", dt=0.0625, output_name="cs1")
    assert created["success"], created
    rebinned = svc.rebin_spectrum("cs1", rebin_factor=0.1, log=True)
    assert rebinned["success"], rebinned
    json.dumps(rebinned, allow_nan=False)


def test_finite_list_maps_nonfinite_to_none():
    assert _finite_list(np.array([1.0, np.nan, np.inf, -np.inf])) == [
        1.0,
        None,
        None,
        None,
    ]


def test_cross_spectrum_power_is_magnitude(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_cross_spectrum("ev1", "ev2", dt=0.0625, output_name="cs_mag")
    assert result["success"], result
    cs = loaded_state.get_spectrum_data("cs_mag")
    expected_mag = np.abs(np.asarray(cs.power))
    expected_phase = np.angle(np.asarray(cs.power))
    assert np.allclose(result["data"]["power"], expected_mag)
    assert np.allclose(result["data"]["power_phase"], expected_phase)


def test_linear_rebin_scales_df_by_factor(loaded_state):
    svc = SpectrumService(loaded_state)
    created = svc.create_power_spectrum("ev1", dt=0.0625, output_name="ps_lin")
    assert created["success"], created
    base_df = created["data"]["df"]
    result = svc.rebin_spectrum("ps_lin", rebin_factor=2.0, log=False)
    assert result["success"], result
    freq = result["data"]["freq"]
    new_df = freq[1] - freq[0]
    assert new_df == pytest.approx(2.0 * base_df, rel=1e-6)
    assert result["data"]["norm"] == created["data"]["norm"]


def test_dynamical_power_spectrum_serializes(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_dynamical_power_spectrum("ev1", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)


def test_averaged_power_spectrum_serializes_with_n_segments(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_averaged_power_spectrum("ev1", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    assert result["data"]["n_segments"] == 8


def test_tiny_segment_size_rejected_with_readable_message(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_averaged_power_spectrum("ev1", dt=0.0625, segment_size=0.125)
    assert not result["success"]
    assert "3x dt" in result["message"]


def test_disjoint_event_lists_rejected_readably(loaded_state):
    import numpy as np
    from stingray import EventList

    rng = np.random.default_rng(7)
    far = np.sort(rng.uniform(1000.0, 1064.0, 5000))
    loaded_state.add_event_data("ev_far", EventList(time=far, gti=[[1000.0, 1064.0]]))
    svc = SpectrumService(loaded_state)
    result = svc.create_cross_spectrum("ev1", "ev_far", dt=0.0625)
    assert not result["success"]
    assert "no overlapping time range" in result["message"]
