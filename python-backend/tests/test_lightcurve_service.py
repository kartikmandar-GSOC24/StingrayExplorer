import json

from services.lightcurve_service import LightcurveService


def test_decimation_caps_returned_points(loaded_state):
    svc = LightcurveService(loaded_state)
    # 64 s span at dt=0.001 -> 64000 bins; cap at 5000 plot points.
    result = svc.create_lightcurve_from_event_list(
        "ev1", dt=0.001, output_name="lc_fine", max_points=5000
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["n_bins"] == 64000  # true resolution is reported
    assert len(data["time"]) <= 5000  # transferred arrays are capped
    assert data["plot_stride"] == 13  # ceil(64000 / 5000)
    assert len(data["time"]) == len(data["counts"])


def test_no_decimation_below_cap(loaded_state):
    svc = LightcurveService(loaded_state)
    result = svc.create_lightcurve_from_event_list(
        "ev1", dt=1.0, output_name="lc_coarse"
    )
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    data = result["data"]
    assert data["plot_stride"] == 1
    assert len(data["time"]) == data["n_bins"]


def test_get_lightcurve_data_decimates(loaded_state):
    svc = LightcurveService(loaded_state)
    svc.create_lightcurve_from_event_list("ev1", dt=0.001, output_name="lc_fine2")
    result = svc.get_lightcurve_data("lc_fine2", max_points=1000)
    assert result["success"], result
    json.dumps(result, allow_nan=False)
    assert len(result["data"]["time"]) <= 1000
    assert result["data"]["plot_stride"] == 64
