import json

import numpy as np

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
    assert _finite_list(np.array([1.0, np.nan, np.inf, -np.inf])) == [1.0, None, None, None]


def test_cross_spectrum_power_is_magnitude(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_cross_spectrum("ev1", "ev2", dt=0.0625, output_name="cs_mag")
    assert result["success"], result
    cs = loaded_state.get_spectrum_data("cs_mag")
    expected_mag = np.abs(np.asarray(cs.power))
    expected_phase = np.angle(np.asarray(cs.power))
    assert np.allclose(result["data"]["power"], expected_mag)
    assert np.allclose(result["data"]["power_phase"], expected_phase)


def test_dynamical_power_spectrum_serializes(loaded_state):
    svc = SpectrumService(loaded_state)
    result = svc.create_dynamical_power_spectrum("ev1", dt=0.0625, segment_size=8.0)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
